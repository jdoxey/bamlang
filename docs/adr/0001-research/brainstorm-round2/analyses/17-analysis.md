# Analysis 17 — Underworld (ghosts, haunting, death certificates, probate)

## 1. The idea in three sentences

Every object is owned by whatever it was *first* stored into (or by its creating scope if never stored), and it dies, freeing its memory immediately, when that owner dies or when anyone runs `kill x`. Every other reference survives as a "ghost" behind a soul-table entry with a generation check: identity, equality and a death certificate (who, where, why) still work, but any field or method access "haunts". That is a catchable unwind to the nearest `otherwise`/`on haunt`, and the event dispatcher unregisters callbacks that haunt. A dead object can name an `heir`, and then every outstanding reference forwards to it.

## 2. Prior art

Almost every component is known. The new part is the *combination*: dynamic first-store adoption, catchable use-after-free and certificates as a language-level value.

| Piece | Known as | Source |
|---|---|---|
| Soul table, ghosts | **Tombstones** (Lomet 1975). Every object is reached through an indirection cell that is marked dead on free. Generations on recycled slots are the "locks and keys" / generational-index refinement. | https://en.wikipedia.org/wiki/Tombstone_(programming), https://researcher.ibm.com/publications/making-pointers-safe-in-system-programming-languages |
| Ghost that reports class and death | **NSZombie** (Cocoa debug mode). A deallocated object becomes a zombie that logs "message sent to deallocated instance". | https://mikeash.com/pyblog/friday-qa-2011-05-20-the-inner-life-of-zombies.html |
| Heir / probate | **Smalltalk `become:` / `becomeForward:`**. The inventor names it. With an object table, as in Smalltalk-80, it is O(1), which is the same trick the soul table uses. | https://gbracha.blogspot.de/2009/07/miracle-of-become.html, https://lists.squeakfoundation.org/pipermail/vm-dev/2022-January/037586.html |
| Death certificate, kill cascade | **Erlang monitors/links**. Holders get `'DOWN'` with an exit reason, and linked processes die together. Here that is applied to every object instead of every process. | https://erlang.org/docs/23/reference_manual/processes |
| Single owner, unchecked aliases, dynamic check | **Gel / "Ownership You Can Count On"** and Nim's owned refs. There, destroying an owner while aliases exist is a runtime error at *free* time. Underworld moves the error to *use* time and makes it catchable. | https://digitalmars.com/d/archives/digitalmars/D/Ownership_You_Can_Count_On_355291.html |

Also: haunting is close to a catchable `NullPointerException` (Java), and "skip the op" resembles Objective-C's message-to-nil. Body moving through the soul is classic Mac OS handles. **Verdict on novelty:** the components are a rename of known machinery. Two things are new: first-store adoption with no static check, and making the ghost a recoverable, explanatory value.

## 3. Soundness: counterexamples

Pseudo-code is illustrative only, not a syntax decision.

**C1. The idea's own scenario (b) leaks through a grave cycle.** Rule 2 buries a *loose* object in the first living holder it is stored into. Nothing forbids grave cycles.
```
root = Node()            // loose in scope
c = Node()
root.add(c)              // children.append(c): c buried in root.children (buried in root)
                         // c.parent = self: root is still LOOSE, so root is buried in c
// graves: root -> c -> root.children -> root. Nothing is loose, so scope end kills nothing.
return root              // root is not loose, so this just returns a reference. The whole tree leaks forever.
```
The claim that "leaks from unreachable objects are impossible by construction" is false. A fix needs an unstated rule: at burial time, walk the grave chain and refuse or redirect the burial if the holder descends from the object. That is O(depth) on every first store, plus a new rule to learn.

**C2. The same thing happens in (c): Editor ↔ window.** `e = Editor(); e.window = Window(); e.window.add(Button(onTap: { e.save() }))`. Is closure capture a store? The rules don't say.
- If capture buries, `e` ends up buried in the closure, which is buried in the button, which is buried in the window, which is buried in `e`. That is a cycle, so it leaks.
- If capture doesn't bury, then `counter = Counter(); timer.every(1s, { counter.tick() })` kills `counter` at function return. On the first tick the callback haunts and is **silently exorcised**; the certificate is logged only in debug builds. The timer just stops.

Either answer breaks one common callback pattern.

**C3. Overwriting a field silently deletes document data (rule 4).**
```
item = Item(); selection.current = item    // item buried in selection
doc.items.append(item)                     // already buried, so this is only a reference
...
on click { selection.current = other }     // old item is unburied, loose in the handler, dies at handler end
save: for i in doc.items { write(i) otherwise continue }   // item silently missing from the saved file
```
ARC's failure direction is "too alive" (leaks). Underworld's is "too dead", and when handlers are written in the recommended `otherwise continue` style, the death is silent data loss. The proposed lint (warn when an object is buried in a short-lived grave and also stored somewhere longer-lived) can't see across functions or into callbacks.

**C4. Partial mutation on haunting (rule 7: no rollback).**
```
fun transfer(a, b, amt) { a.balance -= amt; b.balance += amt }   // b is a ghost: money destroyed
```
Every `x.f` is now a potential non-local exit. That is C++ exception-safety burden on every line, and the unwinding is invisible in source.

**C5. Exorcism has collateral damage.** The save button's closure updates `statusBar.label` after `self.save()`. Someone killed the status bar during a toolbar rebuild. The next tap saves and then haunts on the label, so the dispatcher unregisters the **save** closure. From then on Save does nothing. The cause sits in an unrelated component.

**C6. The heir is loose and dies at scope end.**
```
fun reload() { kill doc heir Document.open(doc.path) }   // the new Document is loose in reload()
```
Rules 2–3 kill the heir when `reload` returns. Every holder then haunts, which defeats the scenario-(c) example. The idea needs an unstated rule such as "the heir is reburied in the deceased's grave". Probate also conflicts with rule 6. Does `==` on the old reference compare the ghost or the heir? A `Map` keyed by the old doc no longer finds `newDoc`. And the heir can be a different class (weakness 3), so `x.f` can disappear across probate.

**C7. Unrestricted `kill` is manual `free` with safe dangling.** Any holder can `kill cache.get("logo")` and destroy state that other components share. There is no ownership capability. Double `kill`, and `kill self` followed by `self.f`, are unspecified. The second haunts inside the object's own method unless the inventor adds the extra "self is pinned" rule.

**C8. Threads.**
- `ferry job to worker`, where `job.config` points to a shared object buried elsewhere: the worker haunts with "another realm" on its first read, so you have to deep-copy or vault first.
- `with a { with b {..} }` on one thread and `with b { with a {..} }` on another is a classic **deadlock**. Nothing prevents it.
- `with v { kill v }` self-deadlocks if "kill takes the lock" isn't re-entrant.
- The mourning queue and soul table are process-global, so every kill on every thread contends on them.

Memory safety itself holds up under these rules, provided the compiler reloads `body*` after every call. A body can move on append or compaction, so hoisting interior pointers across calls is a use-after-free if implemented wrong. That is a correctness constraint on the AI-written optimiser, not a language hole.

## 4. Scenarios

- **(a) Read lines.** Works. The list is loose and its grave passes to the caller on return.
- **(b) Parent pointers.** Fails as written: C1 leaks every tree built from a fresh root. It becomes partial if a cycle-check rule is added.
- **(c) UI callback.** Partial. Exorcism of the cmd-s closure is nice, but the result depends on adoption order (C2), the heir dies (C6), and collateral exorcism can kill the wrong callback (C5).
- **(d) Shared cache.** Works, with a tax: every use by a component needs `otherwise`. Probate refresh is a real win.
- **(e) Mutating a large list.** Works. It is passed by reference with no copy.
- **(f) Threads.** Partial. It is race-free through realm checks, but vault contents only come out by copying, ferrying breaks cross-references, and deadlock is possible.

## 5. Gates and charter

- **G2: pass.** There is no tracing. Kill cascades are destructor-like and deterministic. The mourning queue and soul recycling are bookkeeping, not a collection run. A cycle check on burial (the C1 fix) is a walk up the grave chain, not tracing.
- **G3: pass.** `kill`, `heir`, `rebury`, `ferry`, `vault`, `pin`, `otherwise` and `on haunt` are statements or kinds, not annotations. Flag: it relies on built-in `List`/`Map` just like everything else (the pending question).
- **Other goals strained:**
  - **G1 / P-SWIFT.** Memory alone has about 11 keywords or operations, and lifetime depends on an *invisible, order-dependent* fact: where an object was first stored.
  - **G4.** `otherwise` gets sprinkled everywhere and becomes the new `?.`.
  - **Determinism.** Cross-thread haunting is timing-dependent.
- **Goals served.** **G8** is served strongly (certificates) and **G10** helps (you can assert hauntings in tests).

## 6. Rubric

| Criterion | W | Score | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 3 | It never rejects a program, but the user must track hidden first-store adoption, unburying on overwrite, and the fact that any dereference can unwind. The C1 fix adds a rule. |
| Memory safety | 15 | 4 | It has no UAF given correct `body*` reloads, but grave cycles leak (C1), partial updates corrupt invariants (C4), and `pin` is a manual hole. |
| Expressiveness (b, c, d, OO) | 15 | 3 | Probate and certificates are genuinely expressive, but (b) leaks, (c) depends on order, and the default failure is premature death. |
| Implementation risk (AI on LLVM) | 15 | 2 | It needs a soul table, `invoke` with landing pads at every dereference, a store barrier, cascades, realms, vault lock checks, a global mourning queue, probate with path compression, pinning, and a cycle check. That is far more runtime than O1. |
| Performance & predictability | 10 | 3 | Deaths are deterministic and there is no RC traffic. But every access is two dependent loads, unwind edges inhibit optimisation, there are no hoisted interior pointers, and there is 24 B/object plus a ghost reserve. |
| Concurrency fit | 10 | 3 | Realm checks make it race-free, but vault data only comes out by copying, ferry is O(subtree) and breaks cross-references, and nothing prevents deadlock. |
| Tooling, debug & C FFI | 10 | 4 | Certificate chains are excellent for G8. FFI needs `pin` for every C call because bodies move, and long-lived C handles are manual. |

Total = 25·3/5 + 15·4/5 + 15·3/5 + 15·2/5 + 10·3/5 + 10·3/5 + 10·4/5
      = 15 + 12 + 9 + 6 + 6 + 6 + 8 = **62 / 100**

That is 21 below **O1 (83)**, 20 below **O4 (82)**, and 6 below round 1's best (**68**). The inventor's 74 doesn't account for C1, C3 or C6, or for the cost of unwinding at every dereference.

## 7. What the premise teaches, and the salvageable kernel

**Lessons from the premise:**
1. **Making use-after-free safe is cheap. Deciding what happens next is expensive.** Tombstones and gen checks cost one compare. But once a dereference can fail recoverably, every line is a potential exit, and the language inherits exception-safety and partial-mutation problems. A crash is *simpler* than recovery, which is why Vale and Gel halt.
2. **Lifetime schemes have a failure direction.** ARC fails *too alive* (leaks: diagnosable, rarely data-losing). Single-owner schemes without static checks fail *too dead* (premature death: C3 is data loss). For G11 UI code, "too alive" is the safer default. That is an argument for O1 over O4-without-checks.
3. **Dynamic ownership doesn't remove Rust's errors. It moves them to runtime and makes them order-dependent.** "The compiler never rejects" only helps if the runtime explanation is excellent. Certificates are excellent, but they arrive after the user has lost data.
4. **The missing piece in every scheme is an explanation.** O1's hard bug is "why is this still alive / why is this weak ref nil?" Nobody answers that today. Underworld's real contribution is noticing that the runtime can.

**Kernel worth stealing (into O1, optionally O4):**
- **Death certificates as a debug or test mode for O1.** Swift already keeps weak refs in a side table, and O1 can do the same. In debug builds, when the strong count reaches zero, the side table records the site of the last release, the releasing object, and an optional reason string. Then a weak load that returns nil, or a check that fails in tests, reports something like: "Editor#88 died at WindowManager.close:40 because 'user closed'; last strong ref was released by Window#12." The mirror tool, a debugger view of "who keeps this alive" (the retain path), answers the leak question. Neither needs a language rule. This is NSZombie plus Erlang exit reasons for ARC, and it hits G8 and G10.
- **Optional `retire x because "..."` as a library/runtime call** (*logical death separate from memory death*). Retiring nils all weak refs now. Strong refs that touch the object then trap with the certificate. Memory is freed when the RC reaches zero. This gives "kill the session at logout" deterministic, explainable semantics in ARC without making dereferences catchable. Keep it a trap, not a haunting (lesson 1).
- **Rejected for adoption:** probate/`heir` (spooky identity change; a library `Slot`/handle with `replace` covers reload/hot-swap). Catchable haunting (C4). First-store adoption (C1, C3). Exorcism (covered in round 1 as "callbacks become no-ops", and C5 shows the danger).

## 8. Verdict

**Kernel worth stealing.** As a memory model it is a dead end: 62, with leaks and data loss in its own scenarios. The death-certificate idea, "who killed it, where, why" attached to weak-ref nils and retired objects, is a cheap, rule-free debug and test feature that O1 should adopt.
