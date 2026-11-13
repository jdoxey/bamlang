# Analysis 10: Antiprogram

Analyst: independent. Source: `/home/claude/brainstorm2/ideas/10-antiprogram.md`.
All code is illustrative only — not a syntax decision.

## 1. Restatement

1. Each object lives in the first slot it is stored into (its "home"). Removing or overwriting it there destroys it and its home-subtree. Every other reference is a "visitor" that is set to `none` when the object dies, except references that point up the home tree.
2. A method declared `fun open() undo close()` runs with an undo log. Every write it makes, or its callees make, to pre-existing memory is recorded. `close` runs its own body and then replays the log backwards, which un-registers, un-sets and destroys whatever `open` installed.
3. `keep` exempts a write from the log. Tooling prints the generated inverse, tests that `open; close` leaves the heap unchanged, and runs the whole inverse at exit in debug builds so that any leftover object counts as a leak.

## 2. Prior art

Each part is known. Combining them into the main lifetime mechanism is new.

- **WAM trail (Prolog).** On backtracking, the trail undoes bindings made after a choice point. The WAM logs only bindings to variables *older* than the choice point. That is the same rule as the idea's "log writes to objects older than the span only". https://en.wikipedia.org/wiki/Warren_Abstract_Machine
- **Worlds (Warth, Ohshima, Kaehler, Kay, ECOOP 2011).** Side effects are scoped to a first-class "world" that can be committed or thrown away. This is the closest language-level ancestor of "provisional effects". https://jimmyhmiller.github.io/pdfs/2008-worlds.pdf , https://www.recurse.com/blog/55-paper-of-the-week-worlds-controlling-the-scope-of-side-effects
- **Janus and reversible languages.** Inverses are derived at the level of operations (`x += e` inverts to `x -= e`), not by restoring logged values. That difference matters in section 3. https://en.wikipedia.org/wiki/Program_Inversion,_Interpretation,_and_Injectivization , https://researchprofiles.ku.dk/en/publications/reversible-computing-from-a-programming-language-perspective/
- **Self-adjusting computation (Acar et al.).** Traces record a computation so that parts of it can be revoked and re-run. https://www.cambridge.org/core/product/441A28C813BDA23B57F1ED2BB1A7E36E
- **SolidJS owner tree.** Anything created under an owner is disposed with that owner, and `onCleanup` adds hand-written teardown. That is the "close the spans owned by the subtree" part, minus the automatic reversal of writes. https://docs.solidjs.com/v2/reference/advanced/specialized-reactivity/on-cleanup
- Also related: STM undo logs, React `useEffect` cleanup, RxJS `CompositeDisposable` and Combine `store(in:)`.

The plain home/visitor layer (rules 1–5) is round 1's "single owner plus auto-cleared non-owning refs", and the author admits as much. What is new is rules 6–8: a *deliberate, non-LIFO* undo log as the end of a lifetime, plus the antiprogram as a testable artifact.

## 3. Soundness: counterexamples

**C1. Reverting stale values clobbers later writes (lost data).** The revert writes the old value back "if the target's generation matches". Generation is tracked per object, not per slot, so the revert does not notice later permanent writes to the same slot.
```
fun open() undo close()
    self.window = make Window()       // tape: (self.window, old = none)
// later, an ordinary callback:  self.window = make Window("v2")  // permanent; un-makes v1
editor.close()                        // revert: self.window = none → un-makes v2
```
The same thing happens with counters. `open` sets `self.unsaved = 0`, callbacks increment it, and `close` restores the value from before `open`.

**C2. Spans that don't nest corrupt shared state.** An undo log is only correct when spans are LIFO (STM gets that from isolation). Non-nested lifetimes are exactly the brief's hard case.
```
A.open(): App.count += 1     // forgot keep; tape old = 0
B.open(): App.count += 1     // tape old = 1
A.close()                    // App.count = 0 while B is still open
```
Fixing this with compare-and-revert (revert only if the slot still holds the value `open` wrote) makes the result order-dependent: here the final count would be 1. Janus-style operation inverses (`-= 1`) commute, but the compiler can derive them only for a few operations. The idea's own analogy, `git revert`, has merge conflicts. Antiprogram has no conflict story.

**C3. Swapping or moving elements destroys them.** Under rule 3, overwriting a slot un-makes the object homed there, and storing an object that already has a home only creates a visitor.
```
tmp = xs[i]; xs[i] = xs[j]; xs[j] = tmp   // old xs[i] un-made (tmp pins a detached copy)
                                          // xs[i] is now a visitor to xs[j]'s object; xs[j] = tmp overwrites it…
queue.remove(job); done.add(job)          // remove = un-make: every visitor to job is already none
```
Sorting a list of objects, tree rotations, reparenting a node and moving a job between queues are all broken. A `take`/move rule is missing, and adding one is an extra rule users must learn.

**C4. An up-reference dangles through a pinned local (use-after-free).** Up-references are never cleared because "the holder always dies first". Rule 5 breaks that assumption.
```
c = root.children[0]          // local pins c ("detached but intact")
grandparent.children.clear()  // un-makes root's subtree: c is pinned, root is not
print(c.parent.name)          // c.parent is an up-ref, never cleared → root's memory freed
```
The pin would have to cover the whole home chain upward, which the rules don't say.

**C5. The visitor list grows without bound (leak with no un-make).** A visitor entry is skipped at clear time if the slot no longer matches, but nothing says entries are removed when a slot is overwritten.
```
for frame in frames  hud.icon = sharedSprite    // one (slot, gen) entry appended per frame
```
The fix is a back-index from each slot to its entry, which makes every store cost about the same as an RC update plus a list edit.

**C6. A library that forgets `keep` breaks silently.** If `Log.write` or a memo table fills inside someone's `open` without `keep`, closing an unrelated window rolls it back. The author lists this as weakness 1. It is non-local and invisible at the call site, which is the P-SWIFT and P-RUST kind of "spooky" rule.

**C7. Callbacks registered later go stale, and the program traps.**
```
b.onTap = { Timer.after(5s) { self.save() } }   // inner closure first homed in Timer's list
```
The inner closure's capture of `self` is a visitor, not an up-reference. When the editor dies, `self` becomes `none`, and the timer fires and traps. "A stale callback cannot exist by construction" holds only for registrations made inside `open`'s dynamic extent.

**C8. Reverting under locks deadlocks.** `open` runs `lock L1 { lock L2 { … } }` and the tape replays newest first, so `close` acquires L2 then L1. A thread that takes L1 then L2 deadlocks with it. Reverting writes to `shared` also brings back C2's lost updates across threads.

**C9. Smaller underspecified points.**
- A trap inside `close`'s body leaves the revert half done.
- Rule 5 says "copy", but the object's identity must be kept. Does the copy cover the subtree, and do captured variables count as locals?
- `pending.add(n); root.add(n)` makes `pending` the home, and the author admits it.
- Under (d), `a.cache = c; b.cache = c` makes A the owner, so A's death sets B's cache to `none`.

## 4. Scenarios

| | Verdict | Note |
|---|---|---|
| (a) | **works** | List slots are the homes. The file closes when its span ends at return. |
| (b) | **partial** | Building and deleting work. Reparenting, rotation and swaps destroy nodes (C3). The parent up-ref can dangle (C4). |
| (c) | **works, with caveats** | The best handling of the crux in either round: registrations are removed and the editor→window→button→closure cycle is cut at `close`. It fails for callbacks registered after `open` (C7) and for later writes to taped slots (C1). |
| (d) | **partial** | Eviction and visitors work. There is no shared ownership: the cache must be hoisted to a common ancestor (C9), and `keep` must not be forgotten (C6). |
| (e) | **works** | Passing a list is not a put, so it costs nothing. Inside a dual verb the writes are taped. For lists of objects, see C3. |
| (f) | **partial** | `send`, copy and `lock` are coarse. Reverts across threads lose updates and can deadlock (C8). |

## 5. Gates and the charter

- **G2: pass.** There is no tracing. Visitor clearing is deterministic, the shadow thread only returns memory, and heap walks happen only in tests.
- **G3: pass, flagged.** `undo` and `keep` are keywords, in the same class as `defer`. But `keep` is a statement modifier whose only job is to change compiler-generated semantics, which comes close to the spirit of an annotation. **needs-john** on that reading and on built-in `List`/`Map`. Code ejected by `--eject` is plain source, not macro output.
- **Other goals.** G1 is strained: there are nine rules, plus the new "your effects are provisional" model and the order-dependence of homes. G8 and G10 are strongly *served*: the antiprogram listing, generated identity tests, leak checking at exit and a time-travel tape. P-C is partly undermined by C4.

## 6. Score

| Criterion | W | S | Reason |
|---|---|---|---|
| Simplicity & learnability | 25 | 2 | Nine rules, plus `keep` discipline, first-put order, the up-ref exception, pins and swap hazards. Users get surprised by non-local reverts. |
| Memory safety | 15 | 3 | Traps instead of UB in most paths, but C4 is a real dangle, and C1/C2 lose data. |
| Expressiveness (b, c, d, OO) | 15 | 3 | The best (c) of any idea. (b) cannot move or swap, and (d) has no shared ownership. |
| Implementation risk (AI on LLVM) | 15 | 1 | Store barriers with home-chain walks, visitor side tables with back-indices, STM-style function cloning, runtime re-homing for `keep`, pins, a shadow thread and placement analysis. |
| Performance & predictability | 10 | 2 | A barrier on every reference store, un-make that is O(visitors), tape cost and reverts that depend on order. |
| Concurrency fit | 10 | 2 | Coarse move/copy/lock. Reverting into `shared` breaks under contention (C8). |
| Tooling, debuggability & C FFI | 10 | 3 | Exceptional debugging and testing artifacts. FFI is weak: C pointers can't be cleared, objects are pinned only per call, and long-term use needs handles. |

Total = 25·2/5 + 15·3/5 + 15·3/5 + 15·1/5 + 10·2/5 + 10·2/5 + 10·3/5
      = 10 + 9 + 9 + 3 + 4 + 4 + 6 = **45 / 100**

The author self-assessed 66. Comparison: O1 83, O4 82, round 1's best 68. Antiprogram sits at the bottom of round 1's range (47–68). The home/visitor layer brings round 1's costs, and the tape adds an undo-log design that is unsound once lifetimes stop nesting.

## 7. What the premise teaches, and the kernel

**The premise's lesson.** "Lifetime = the interval between a verb and its inverse" is a useful *specification*, even though it is a poor *mechanism*.

- The leaks that O1 and O4 actually suffer in UI code (scenario (c)) are not about memory at all. They are *registrations that were never undone*: a listener left in a bus, a window left in `App.windows`, a closure left in a timer list. Once those are removed, ARC's cycle disappears and O1's `weak self` becomes unnecessary for the common case.
- The failure analysis draws the line clearly:
  - **Undoing registrations is safe.** Inserting a span-made object into a container is inverted by removing *that identity*, and that commutes with whatever else happened in the meantime.
  - **Undoing values is unsafe.** Restoring an old scalar or field value does not commute (C1, C2).
  - Janus already knew this: invert operations, don't restore snapshots.

**The kernel, adoptable into O1 or O4.**

1. **Registration scopes.** A plain method pair `open`/`close` (or `show`/`hide`) gets a compiler-maintained *registration bag*. During `open`'s dynamic extent, every insertion of an object *made in that span* into a container or slot that existed before `open` is recorded by identity. `close` (or the receiver's destructor under O1/O4) removes exactly those identities, and clears a slot only if it still holds that object.
   - There is no scalar revert, no `keep` and no tape of values.
   - Under O1 this cuts the editor↔closure cycle deterministically.
   - Under O4 it makes `shared` handles in registries self-cleaning.
   - It is close in spirit to Solid's owner disposal, but derived automatically instead of hand-written in `onCleanup`.
2. **Generated `open; close` identity tests.** Using ARC counts, check that every object created by `open` is gone after `close`. This is cheap under both O1 and O4, and serves G10.
3. **A debug-mode exit sweep.** At exit, tear everything down and report surviving objects by allocation site. This is an O1 cycle/leak reporter with no collector in release builds (G2 is safe), and serves G8.
4. **`lang anti`-style listing.** For a method pair, print "what close/drop will undo" so it can be reviewed in code review.

## 8. Verdict

**Kernel worth stealing.** As a full memory model it is a dead end: value-level undo is unsound for non-nested spans, swapping and moving destroy objects, and implementation risk is the maximum. Its specification idea is the most useful single takeaway for scenario (c): compiler-derived, identity-based un-registration on `close`, plus generated identity tests.
