# 17 — The Underworld: death is a state, not an ending

## 1. Name

**Underworld** (with séances, death certificates and probate).

## 2. The crazy premise

**Broken assumption: "a dangling reference is a bug."** Every sensible design, whether ARC, ownership, generational refs or regions, is built to *prevent* use-after-free. If it can't prevent it, it detects it and crashes. Underworld makes use-after-death **legal, routine, well-defined and informative**. Freeing an object frees its memory immediately. Its *identity* goes on as a ghost. You can address the ghost, compare it, hash it and print it, and it will tell you who killed it, where, and why. Code that tries to *use* a ghost doesn't get undefined behaviour. It gets a "haunting", which is a defined, catchable control-flow event.

Dangling is now safe. So the lifetime rule can be dumb, dynamic and never checked at compile time: **the compiler never rejects a program for a lifetime reason.** There's no borrow checker, no `weak`, no move syntax and no cycle problem.

Gates and assumptions touched:
- G2 passes. No tracing ever happens, and frees are immediate.
- G3 passes. `kill`, `heir`, `rebury`, `vault` and `ferry` are statements or kinds, not annotations.
- I deliberately break the assumption that "memory safety means no dangling refs". Here memory safety means "no dangling *access*".
- Control flow stays deterministic on a single thread. Across threads, *which* stale refs haunt can depend on timing (see weaknesses).

## 3. Pitch

Objects live in a grave tree. Each object is buried with the first thing that adopted it: its creating scope, or the first live object or collection it was stored into. It dies when that grave closes, or when anyone says `kill x`. It dies *now*, deterministically, and its memory is reused immediately. Every other reference to it, from caches, callbacks, parent pointers or other components, is left addressing a **ghost**. A ghost keeps its identity (`==` and hashing still work) and carries a **death certificate**: the cause, the kill site, the killer, and the chain of graves it went down with. Touching a ghost's fields or methods **haunts**. The operation is skipped, and control unwinds to the nearest `otherwise`. If the haunting comes from a UI or event callback, the dispatcher *exorcises* that callback, which means it unregisters and kills it. A death can also name an **heir**: `kill doc heir newDoc`. Every surviving reference then transparently forwards to the heir. One line handles reload, reconnect and hot-swap for all holders at once. Non-nesting lifetimes stop being a type-system problem. You kill the session when the user logs out, and everyone holding it finds out safely, with a reason attached.

## 4. The rules (everything a programmer learns)

1. **References are free.** Copy them, alias them, store them anywhere, capture them in closures. There are no reference kinds and no `weak`. Plain values (numbers, strings, small structs) are copied and have no lifetime.
2. **Every object has one grave.** A new object is *loose* in the scope that created it. The first time a loose object is stored into a field or collection of a living object, it is **buried** there. Storing an already-buried object somewhere else only creates another reference. Returning a loose object makes it loose in the caller's scope.
3. **Graves close.** When a scope ends, its still-loose objects die. When an object dies, everything buried in it dies too, children before parents.
4. **Unburying.** Overwriting a field, or removing an element from a collection, makes the old buried object loose in the current scope. If you don't store it somewhere again, it dies at scope end. `rebury x in y` moves a grave explicitly, for example when reparenting a tree node.
5. **`kill x [because "..."] [heir y]`** kills x and everything buried in it, right now.
6. **Ghosts.** After death, every reference to x addresses x's ghost. `alive x`, `x == y`, hashing, printing and `x.death` (the certificate) all work on ghosts and never haunt.
7. **Haunting.** Reading or writing a field of a ghost, or calling one of its methods, *haunts*. The operation does not happen, and control unwinds to the nearest `otherwise` (statement-level) or `on haunt` (function-level) handler. If nothing handles it, the thread stops and prints the full certificate chain. Effects that happened before the haunting are not rolled back.
8. **Probate.** If the dead object had an heir, using the ghost uses the heir instead, with no haunting. Chains of heirs are followed.
9. **Exorcism.** A closure invoked by the runtime (event, timer, callback list) that haunts without handling it is killed and unregistered. The certificate is logged in debug builds.
10. **Realms (threads).** Objects belong to the thread whose grave tree holds them. `ferry x to t` moves x and its buried subtree to thread t. While x is away, the sender's references haunt with "in another realm". A `vault` is a shared object. Its contents can be touched only inside `with v { ... }`, which takes v's lock. A reference to vault contents that is used outside the `with` block haunts.

That's ten rules. Rules 1–3 and 5–7 are the everyday core. Rules 8–10 are only needed when you use those features.

## 5. Under the hood

- **Souls and bodies.** Each object has a *body* (its fields, on a size-class heap) and a *soul* (a 24-byte entry in a per-process soul table): `word = gen:32 | realm:24 | state:8`, plus `body*`, plus `grave` (a soul index or a scope marker), plus `cert` (an index into a certificate ring, or an heir). A reference is 64 bits: `soul index:32 | gen:32`.
- **Deref fast path.** Load the soul word, compare it with `(ref.gen | current_realm | ALIVE)`, then load `body*`. That is one compare and branch on a cache line already in use. The slow path handles ghost, probate, vault realm and forgotten. Inside a function the compiler hoists the check until the next call or `kill`. Any call can kill, so hoisting across calls needs whole-program purity info. That is optional optimisation, not semantics.
- **Kill.** Free the body to the allocator immediately. Set state to GHOST and write a certificate: cause, kill-site PC, killer's soul, timestamp, heir, parent cause. Then walk the dead body's reference fields. Any child whose `grave == this soul` is killed through an explicit worklist, so deep trees don't overflow the stack. The cost is O(buried subtree), paid at the moment of death and predictable, like C++ destructors.
- **Scopes.** Each scope keeps a small list of loose objects, and leaving the scope kills the ones whose grave is still that scope. Escape analysis removes the list in the common case, purely as an optimisation.
- **Stores.** Storing a reference into a field checks `soul.grave`. If it is a scope marker (loose), the store buries the object: `grave = holder`. That is one load and branch per reference store.
- **Recycling souls (the mourning queue).** Ghost souls go into a FIFO. A soul slot is reused only after at least max(64K, live-object-count) later deaths, and reuse bumps `gen`. An old reference to a recycled slot sees a gen mismatch and becomes **forgotten**. It still haunts safely, but the certificate says only "forgotten". Ghost and forgotten are the same at the language level: both are "dead", and only the diagnostic detail differs. That keeps control flow deterministic. When `gen` reaches its 32-bit wrap, the slot is retired and leaks 24 bytes, once per 4 billion reuses.
- **Restless ghosts.** A ghost with an heir is not recycled until its heir dies without an heir. Heirs are rare (reloads, reconnects), and the count is shown in tooling. When a probate deref happens through a mutable location, it rewrites the reference to point at the heir (path compression).
- **Moving bodies.** Every access goes through the soul, so the runtime can move a body without tracing. Lists grow by `realloc` and update `body*` in one place, and the allocator can compact cold size classes. This is a free side-benefit of the indirection.
- **Haunting** is implemented as a zero-cost-table unwind to the nearest handler, the same machinery as a panic but catchable. The event dispatcher's loop has a built-in handler that performs rule 9.
- **Realms.** Ferrying rewrites the realm byte in each soul of the subtree, O(subtree). A vault is its own realm id, and its lock lives in the vault's *soul*, so the lock survives the vault's death. Deref of a vault-realm object takes the slow path: "does this thread hold that vault's lock?". Killing a vault takes its lock first, so no thread can be inside it while its body is freed.
- **FFI.** `pin x` hands C the raw `body*` for the duration of a call. A `kill` of a pinned object marks it GHOST immediately but defers freeing the body until unpin. Bodies handed out as long-lived C handles must be `pin`ned explicitly and unpinned explicitly. That is the one manual hole.
- **Tooling.** `underworld` is a debugger view that queries recent certificates ("every Session that died in the last 5 s, and who killed it"). Hauntings in tests can be asserted on. Death-cause chains read like stack traces for lifetimes.

## 6. Scenarios (illustrative only — not a syntax decision)

**(a) Read lines.** The list is loose in the function, returning it makes it loose in the caller, and growth is handled by moving the body behind the soul.
```
fun readLines(path) {
  lines = List()                    // loose in this scope
  for line in File(path).lines { lines.append(line) }   // strings are values
  return lines                      // grave passes to caller
}
```

**(b) Tree with parent pointers.** The child is buried in `children`. `parent` is just a reference, and it can never dangle unsafely.
```
class Node {
  parent; children = List()
  fun add(c) { children.append(c); c.parent = self }   // c buried in children
  fun prune() { kill self because "pruned" }            // subtree dies; parent.children holds a ghost
  fun moveTo(p) { parent.children.remove(self); rebury self in p.children; parent = p }
}
for c in root.children { c.render() otherwise continue }   // skip pruned ghosts, or root.children.exorcise()
```

**(c) UI callback capturing self: the crux.**
```
class Editor {
  doc; window
  fun build() {
    saveBtn = Button("Save", onTap: { self.save(); self.dirty = false })  // closure buried in button
    window.add(saveBtn)                                                   // button buried in window
    App.shortcuts.register("cmd-s", { self.save() })   // closure buried in App's shortcut list
  }
  fun reload() { kill doc because "reloaded" heir Document.open(doc.path) }  // every holder now sees the new doc
}
// User closes the window:  kill window because "user closed"
//  -> editor? It is buried wherever it was first stored. Say the window: then it dies with the window,
//     and so do the button and its closure. Nothing leaks, and there is no cycle problem
//     (closure -> self -> window -> button -> closure is fine, because only grave edges decide lifetime).
//  -> The cmd-s closure lives in App and still captures the dead editor. On the next cmd-s,
//     self.save() haunts and the dispatcher exorcises the closure. Debug log:
//     "closure@Editor.build:5 exorcised: Editor#88 buried with Window#12, killed at
//      WindowManager.close:40 because 'user closed'"
```

**(d) Shared cache used by two components.**
```
class Cache { entries = Map()                  // entries buried in the map
  fun get(k) { return entries[k] otherwise load(k) }
  fun evict(k) { kill entries[k] because "LRU" }
  fun refresh(k) { kill entries[k] because "stale" heir fetch(k) } }
// Components A and B keep direct references to entries:
img = cache.get("logo")                        // A holds it
draw(img) otherwise { img = cache.get("logo"); draw(img) }   // evicted -> haunt -> refetch
// After refresh(), A and B transparently use the new entry (probate). Identity maps keyed by
// entries still work with ghost keys; `seen.exorcise()` drops them.
```

**(e) Mutating a large list in a function.**
```
fun normalise(xs) { for i in 0..xs.count { xs[i] = xs[i] / max } }  // a reference, no copy
normalise(samples)        // same object; if the callee did `kill xs`, the caller's `samples` is a ghost
```

**(f) Threads.**
```
stats = vault Stats()                       // shared, lock lives in its soul
spawn { with stats { stats.hits += 1 } }    // any thread, under the lock
spawn { with stats { report(stats.copy()) } }   // values copy out; references to inside haunt outside `with`
job = Job(data); ferry job to worker        // our old `job` reference now haunts "in another realm"
```

## 7. What is new

- **Use-after-free is a first-class, defined language event.** Nothing in O1–O8 treats it that way. O6 (Vale) detects it and *halts*. Here it is catchable control flow, ghosts keep identity, and every death carries a **certificate chain**.
- **Probate (`heir`)** redirects *every* outstanding reference at once, without anyone needing to find them. Reload, reconnect, hot swap and cache refresh become one line. I don't know of a mainstream language with this as a memory-model primitive. (Smalltalk's `become:` is the closest, and it needs a heap scan.)
- **Dynamic "first store adopts" burial**, with no compile-time ownership checking. Ownership exists, but the compiler never rejects anything. That is only tolerable *because* dangling is safe. Round-1 single-owner designs had to make non-owning refs auto-null or check them statically. Here the dangling ref keeps its identity and its explanation.
- **Exorcism.** Callbacks are cleaned up *lazily, at the moment they prove they belong to the dead*, rather than by tracking captures up front.
- **Soul indirection** allows moving bodies and compaction without a GC, as a side effect.

## 8. Less crazy than it sounds, or more?

**Less crazy:**
- The deref check is essentially Vale's generational check.
- Kill-time cascade is C++ destructor order.
- The soul table resembles slot maps and old Mac OS handles.
- Haunting is a typed panic you can catch.
- Each piece is a known technique, and only the *semantics* are new.
- John-relevant: the certificate chain is the debugging story G8 wants, and it falls out of the model for free.
- Leaks from unreachable objects are impossible by construction. Every live object hangs off the grave tree, which is rooted in scopes. Only logical leaks (a long-lived list you never trim) remain, as in every language.

**More crazy:**
- Any dereference can unwind. That is the "every line can throw" problem that made checked exceptions miserable and C++ exception safety hard.
- Programs that are memory-safe can still be logically half-done (rule 7 does not roll back).
- Probate is spooky action at a distance: an object you hold can turn into a different object of a possibly different class.

## 9. Known weaknesses

1. **Graveyard-shift bug.** "First store adopts" depends on order. Put a new object into a temporary local list before putting it into the cache, and it gets buried in the temporary list. It dies at scope end, and the cache holds a ghost. Diagnostics are good (the certificate says "buried with List#5 at Foo:12"), but the bug is real. A lint can warn when an object is buried in a loose grave and also stored into a longer-lived holder in the same scope.
2. **Pervasive implicit unwinding.** Rule 7 makes every `x.f` a potential non-local exit. Partial mutation before a haunting can break invariants. One mitigation would be "a method's own `self` is pinned alive for the call's duration", but that is an extra rule. Until then the burden is on programmers.
3. **Probate type hazard.** The heir should be the same class as the dead object, or a subclass. That is a runtime check, or a compile-time check where the types are known. Restless ghosts can pile up if heirs are chained forever.
4. **Performance.** Two dependent loads per deref. 24 bytes per object plus the mourning queue, roughly 1.5–2 MB of ghosts at minimum. A burial check on every reference store. A kill cascade on large structures is an O(n) pause, deterministic but real. All of this is plausibly near O1 ARC cost, but it isn't free.
5. **Cross-thread nondeterminism.** Whether a sender's stale reference haunts depends on whether the object has been ferried back yet. That is safe but timing-dependent. Vault contents can't escape the `with` block except by copy, which is clumsy for big data.
6. **FFI pinning** is manual and is the one unsafe-ish hole. A long-lived C handle that is never unpinned leaks its body. Forgetting to pin is impossible, because raw pointers only come from `pin`.
7. **Ghost-tolerant APIs proliferate.** Collections need `exorcise()`, iteration needs `otherwise continue`, and library authors must document "may haunt". There's a risk the culture slides into sprinkling `otherwise` everywhere, which is the new `?.`.
8. **Implementation risk.** It needs a runtime soul table, unwinding through LLVM landing pads on every deref site, kill cascades and realm checks. That is more runtime than O1, but every piece is conventional and testable in isolation. AI-agent risk is moderate.

**Self-assessment (rough):**

| Criterion | Score | Weight | Points |
|---|---|---|---|
| Simplicity | 3.5 | 25 | 17.5 |
| Safety | 4.5 | 15 | 13.5 |
| Expressiveness | 4 | 15 | 12 |
| Implementation risk | 3 | 15 | 9 |
| Performance | 3 | 10 | 6 |
| Concurrency | 3.5 | 10 | 7 |
| Tooling/FFI | 4.5 | 10 | 9 |

That totals about 74. It's below O1, but probate, certificates and a compiler that never rejects programs for lifetime reasons are worth stealing even if the rest fails. Certificates and heirs could be bolted onto O1/O6 as standalone features.
