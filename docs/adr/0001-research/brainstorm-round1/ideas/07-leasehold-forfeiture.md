# 07 — Leasehold: Deeds, Leases and Forfeiture

## 1. Name

**Leasehold** (deeds, leases, forfeiture, wills, escrow).

## 2. Inspiration — how the lens maps onto memory

| Law concept | Memory concept |
|---|---|
| **Deed** (title to property) | The one owning reference to an object. Exactly one per object. |
| **Lease** | A non-owning reference. You can use the property; you don't own it and you can't keep it alive. |
| **Term of a lease** | A lease ends when the property is destroyed. No date, no annotation: the term is "as long as the property stands". |
| **Forfeiture** | A tenant whose lease is voided, and who has no clause saying what happens then, loses their own standing. In memory: **the holder of a voided lease is destroyed too**. |
| **Registry of deeds** | Each object keeps a register of every heap slot that leases it, so voiding is eager and exact. |
| **Notice period** | An object in use by a running function can't be destroyed mid-call. Its death is scheduled for when that call returns. |
| **Will / bequest** | When an owner dies, its property dies with it, unless its `will` gives some of it to a living owner. |
| **Trust** | A named owner that lives as long as the program. Its job is to hold property for other people. |
| **Escrow** | A neutral, locked holder for property that several threads deal with. One party draws on it at a time. |
| **Power of attorney** | A lease passed as a parameter. It gives full authority to act, including mutation, without ownership. |

In law, a tenant has no rights once the property is gone. The usual memory answers are the strong ref (the tenant keeps the building standing), the weak ref (the tenant finds a hole in the ground and has to check every time) and the generational check (the tenant is arrested on the next visit). Leasehold adds a fourth: **the tenancy, and anything built on it, ends with the property, automatically, at the moment it happens.**

## 3. Pitch

Every object has one owner, and ownership forms a tree rooted in locals and trusts. Every other reference is a lease, and leases are completely free to use. You can copy them, store them in fields, capture them in closures, and form any cycle you like, because they never keep anything alive. The new idea is what happens when leased property dies. The runtime looks up the dead object's lease register. A lease in an *optional* place (a `maybe` field, a collection element) is simply emptied. A lease in a *required* place forfeits its holder: the holder is destroyed as well, and that can cascade. This gives the language's central guarantee: **a live object's required leases are always valid**, with no null checks, no `[weak self]`, no lifetime parameters and no GC. A UI callback that captures `self` cannot outlive the editor. When the editor goes, the callback is forfeited and drops out of whatever list was holding it. Non-nesting lifetimes are expressed by *where* you put a lease (required vs optional), not by annotating *how long* it lives.

## 4. The rules

1. **One deed.** Every heap object has exactly one owner: a local variable, a field, a collection slot, or a trust. A local or field initialised from a constructor call or from `give` holds the deed.
2. **Owners take their property with them.** When an owner dies or goes out of scope, everything it holds the deed to dies too, recursively (unless rule 8 applies).
3. **`give` transfers a deed.** `give x` moves ownership. After a `give`, the giver can't use `x` again (a compile error, checked by local flow analysis). You can only `give` out of a field if the field is `maybe` (it becomes empty) or you `swap` something in.
4. **Everything else is a lease.** This covers parameters, closure captures, fields declared `lease`, and locals initialised from anything that is not a constructor call or `give`. Leases can be copied freely, never keep anything alive, may mutate the property (power of attorney), and may form cycles.
5. **Destruction voids leases.** When an object dies, every lease on it is voided at once:
   - a lease in a **vacatable** place (a `maybe` field or a `List`/`Map` element) is emptied or removed;
   - a lease in a **required** place (a plain `lease` field or a closure capture) **forfeits** its holder, which dies (and so triggers rules 2 and 5 itself).
6. **Forfeited objects leave their owner the same way.** If a forfeited object's deed is in a vacatable place, it is removed. If its deed is in a required field, the owning object is forfeited too, and the cascade continues upward.
7. **Notice period.** An object currently in use by a running function (a local owns it, or a local or parameter leases it) is *pinned*. If it dies while pinned, its death is deferred until the last pinning call returns. If one of its required leases is voided during that time, touching that lease traps with a report (not undefined behaviour).
8. **Wills.** A type may declare a `will` block. It runs just before the object's property is destroyed and may `give` that property to any living owner.
9. **Trusts.** `trust Name` declares a program-lifetime owner (an object with fields). Use one for app-wide state, registries and caches.
10. **Threads use escrow.** You can only pass three things to `spawn`: values given with `give`, leases to an `Escrow`, or leases to `seal`ed (frozen, immutable) objects owned outside the enclosing `together { }` block. `escrow.draw { x -> … }` gives exclusive access under a lock. The lease `x` may not be stored anywhere outside the escrowed property.

That's ten rules. In practice most code only touches 1, 3, 4 and 5. Rules 6 and 7 are "what you'd expect", and 8–10 are for specific situations.

## 5. Under the hood

**Object header (two words).** `owner_slot*` is a back-pointer to the slot holding the deed (needed for rule 6). `register*` is a lazily allocated array of slot addresses that hold leases to this object. A third word holds `pins:u32` and `flags` (condemned, sealed).

**Lease slots on the heap are 16 bytes:** `{ptr, register_index}`. Storing a lease into a heap slot costs three things: append the slot address to the target's register, record the index, and on overwrite swap-remove the old entry in O(1). A `List` of leases fixes up its register entries when it reallocates, which is O(n), the same as the copy. Leases in locals are plain pointers plus a pin.

**Pins.** When a function is entered with lease parameters, it does a non-atomic `pins++`; when it exits, `pins--`. The compiler elides the pin when the callee provably cannot destroy anything. That's an effect bit ("may-destroy") computed bottom-up over the call graph, with calls through closures or virtual methods assumed to destroy. This is the only RC-like traffic, and it is stack-only.

**Death procedure** (deterministic, no tracing, no scan of unrelated memory):

1. If pinned, mark it condemned and return. The pin release re-enters the procedure.
2. Run its `will`.
3. Destroy the property it owns, depth first.
4. Walk its register. For each slot: if vacatable, empty it (a collection slot is tombstoned and compacted when the collection is next unpinned, so iteration indices stay stable); if required, write the `VOID` sentinel and forfeit the holder by enqueuing it.
5. Clear its own `owner_slot` (rule 6) and free its memory.

The procedure uses a worklist, not recursion, so deep cascades can't blow the stack.

**Compiler work:**
- deed vs lease classification (syntactic, rule 4);
- use-after-`give` (local flow only, no lifetimes);
- the may-destroy effect for pin elision;
- the thread rules (rule 10), which are a conservative escape check that a draw lease and anything loaded through it is stored only into slots reachable from the same escrow, or into locals.

There is no lifetime inference and no cycle detection: cycles of leases are harmless, and cycles of deeds are impossible because deeds form a tree.

**Debugger.** A *forfeiture log* records, for each cascade, the chain "X died at file:line → voided Y.field → forfeited Y → removed from Z.list". The debugger can also show any object's deed chain and its register.

## 6. Scenarios

All code is *illustrative only — not a syntax decision*.

### (a) Read a file into a growing list
```
fn readLines(path: String) -> List of String {
    let lines = List of String()          // deed, local
    for line in File(path).lines() { lines.add(give line) }
    return give lines                     // deed passes to caller
}
```
Nothing unusual happens here. The list owns its strings, and growing it is ordinary reallocation; strings are separate objects, so nothing has to move them. When the caller's variable dies, the list and its lines die.

### (b) Tree with parent pointers
```
class Node {
    children: List of Node        // deeds
    lease parent: maybe Node      // vacatable: root has none
    fn adopt(child: Node) { child.parent = self }
}
let root = Node()
let kid = Node();  root.adopt(kid);  root.children.add(give kid)
```
Parents own their children. A child's parent link is a lease, so there is no cycle. If a subtree is destroyed, its leases go with it. If you move a child to another parent with `give`, the `parent` lease gets reassigned. If you wanted a non-root node to *require* a parent, you would declare `lease parent: Node`. Then any node whose parent dies is forfeited, which matches the ownership anyway.

### (c) UI callback capturing enclosing state — the crux
```
class Editor {
    doc: Document
    saveButton: Button
    init() {
        saveButton = Button("Save")
        saveButton.onTap = { self.save(); self.dirty = false }   // captures self as a lease
        App.shortcuts.add({ self.save() })                         // closure deed given to a trust's List
        Timer.after(5.seconds, { self.autosave() })                // closure deed given to the timer trust
    }
    will { if dirty { App.pendingSaves.add(give doc) } }           // bequest: unsaved doc outlives editor
}
```
Captures are leases, so `Editor → Button → closure ⇢ Editor` is not a cycle and nobody writes `[weak self]`. Inside each closure, `self` is a *required* lease. That gives a guarantee: **if the closure is still alive, the editor is alive.** You never check for nil. Here is what happens when the editor closes:
- The button and its `onTap` die because the editor owns them.
- The shortcut closure in `App.shortcuts` loses its required lease and is forfeited, so it drops out of the trust's list (rule 6). Deregistration happens automatically.
- The pending timer callback is forfeited in the same way. A late `autosave()` cannot fire on a dead editor.
- If the closure is mid-call when the window closes (the user taps Save and `save()` closes the window), the editor is pinned and dies when `onTap` returns (rule 7).
- The `will` hands the unsaved `doc` to `App.pendingSaves`. That covers the case where you *do* want work to outlive the scope, and it is explicit and visible.

### (d) Shared mutable cache used by two components
```
trust Caches { images: Map of String to Image }
class Gallery   { lease thumbs: Map of String to Image  ... }      // vacatable leases
class Inspector { lease current: maybe Image
                  fn show(key: String) { current = Caches.images[key] } }
```
The cache owns the images. Both components hold leases and mutate through them freely, on one thread. When the cache evicts an image, `Gallery.thumbs` loses that entry and `Inspector.current` becomes empty. Neither component is forfeited, because each put its lease in a vacatable place. If a component should be torn down when its data goes (say a detail view for one image), it declares `lease image: Image` as required, and eviction forfeits that view. The programmer chooses between "drop the reference" and "drop me" by where the lease is declared, not by writing lifetimes.

### (e) Passing a large list to a function that mutates it
```
fn normalise(xs: List of Float) { let m = xs.max(); for i in 0..xs.count { xs[i] = xs[i] / m } }
normalise(samples)        // lease: power of attorney, no copy
consume(give samples)     // only if the callee should own it
```
Parameters are leases, so there is no copy, no `inout` keyword and no borrow checker. The list is pinned for the duration of the call, so even if `normalise` triggers something that kills `samples`' owner, the memory stays valid until it returns.

### (f) Sharing data between threads
```
let stats = Escrow(give Stats())                       // locked neutral holder
let table = seal(give loadTable())                     // frozen, read-only
together {
    for chunk in chunks { spawn { stats.draw { s -> s.add(score(give chunk, table)) } } }
}   // all threads joined here; stats and table outlive them
```
Threads receive deeds (`give chunk`), leases to escrow (`stats`), or leases to sealed data (`table`). Sealed objects never die while a `together` block that leases them is running, because the owner is outside the block, so their registers never need cross-thread updates. Inside `draw`, `s` is exclusive. The compiler stops it from being stored anywhere outside the escrow, so no thread keeps a lease past the lock. Ordinary objects never have cross-thread leases, so registers stay non-atomic.

## 7. What's genuinely new vs. the covered options

- **Forfeiture as the default response to a dangling reference.** O1/O7 keep the referent alive. A weak ref nulls it and makes you check. O6 (Vale/Inko) traps on use. Leasehold **destroys the holder**, eagerly, at the referent's death. That inverts the dependency: a non-owning reference makes the *holder's* lifetime depend on the target. Required leases therefore need no checks at all, and callback, observer and registry clean-up (scenario c) falls out of the memory model instead of being a discipline.
- **One placement rule replaces lifetime annotations.** Vacatable place means "clear me". Required place means "kill me". This is the whole lifetime vocabulary, and it uses the optional type the language has anyway.
- **Eager, exact voiding through per-object lease registers**, instead of generation counters checked at every dereference (O6) or counts maintained on every copy (O1). Reads through a lease cost nothing extra. Only *storing* a lease into the heap costs anything.
- **Wills** give non-nesting handoff at death (save-on-close, pending work) without a global `promote` that leaks, which was the weakness of scope-bound regions.
- **Notice period** (pin only from the stack) makes locals safe against mid-call destruction without full RC.
- Closest prior art: Qt's QObject (parent–child ownership plus `destroyed` signals plus QPointer). Qt does this as a library convention, nulls instead of forfeiting, and has no cascade rule or thread story.

## 8. Known weaknesses

- **Action at a distance.** An object can vanish because something far away died. That is correct by the rules, but it can surprise people. The forfeiture log is mandatory tooling, not a nice-to-have.
- **Cascades are unbounded.** One death can forfeit a large graph, which causes a latency spike much like an RC release cascade. It is deterministic, but not O(1).
- **Memory overhead.** Every object carries a 2–3 word header, every heap lease is 16 bytes, and registers have to be allocated. Programs heavy with leases (big graphs) pay noticeably.
- **The trap in rule 7 still exists.** A pinned, condemned object that touches a voided required lease traps. It's rare and safe, but it is a runtime failure, not a compile error.
- **G3 pressure.** `List of lease T` versus `List of T` puts a modifier inside a container type. Is that acceptable for built-in, compiler-known containers? needs-john.
- **The thread story is restrictive.** Escrow, seal and give cover common patterns, but lock-free shared structures and long-lived cross-thread references are not expressible.
- **Pin elision depends on a whole-program may-destroy analysis.** Without it, every lease parameter costs an increment and a decrement. Separate compilation weakens the analysis.
- **The deed/lease distinction for locals is inferred from the right-hand side** (constructor or `give` means deed). It's simple, but `let x = make()` versus `let x = cache.get()` look alike and mean different things. The rule may need a visible marker.
