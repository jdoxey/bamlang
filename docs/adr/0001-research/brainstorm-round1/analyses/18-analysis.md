# Analysis 18: Depots, Delivery and Recall

*Analyst: independent. Inputs: brief.md, CHARTER.md, ideas/18-depots-and-recalls.md. No other ideas or analyses were read.*
*All code is illustrative only. It is not a syntax decision.*

## 1. The idea in three sentences

Every heap object lives in a first-class, owned **depot**. Inside a depot, references are unrestricted and counted with cheap non-atomic RC. Cycles are freed when the depot closes. New objects are built in the depot of the place they are stored into or passed to. References between depots must be `far` (non-owning, listed in the target's ledger), and they are nulled ("recalled") when the target dies. Closures automatically capture cross-depot objects as far refs and are silently skipped if any of those objects is gone. Whole depots move between threads in O(1), and `bonded` depots are lock-guarded for sharing.

## 2. Prior art: a recombination with two original twists

Most of the pieces exist already:

- **Project Verona regions + cowns.** Verona has a region with a single entry point where "references within a region are unrestricted". The region is owned by one thread at a time, and cowns wrap regions for locked concurrent access. That matches depots, `ship` and `bonded` almost one for one. Verona also offers per-region strategies (RC/arena/GC) ([summary](https://tamnd.github.io/brain/research/memory-management/ownership/07_project_verona_regions/), [OOPSLA'23 reference capabilities paper](https://arxiv.org/pdf/2309.02983)). Verona enforces this statically with `iso`/`imm` capabilities. Idea 18 does it with runtime traps. Verona's `when` acquires all cowns together in a global order, which makes it deadlock-free. Idea 18's nested `receive` is not.
- **Gay & Aiken's RC / C@.** These are first-class explicit regions with reference counts used to make `deleteregion` safe, and intra-region pointers are cheap ([Berkeley TR](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2000/5340.html), [PLDI'98 paper](https://www.cs.cornell.edu/courses/cs612/2000SP/papers/gay-regions.pdf), [Wikipedia](https://en.wikipedia.org/wiki/Region-based_memory_management)). RC refuses or aborts deletion while outside references exist. Depots instead *null* the outside references. That is the inverse policy.
- **Pony `iso` / Swift SE-0414 region isolation.** Both move a disconnected graph between actors in O(1). Both check it statically ([Pony tutorial](https://tutorial.ponylang.org/capabilities/passing-and-sharing.html), [SE-0414](https://github.com/apple/swift-evolution/blob/main/proposals/0414-region-based-isolation.md)). Depots check it dynamically, using pin counts.
- **Recall ledger.** This is a zeroing-weak-reference side table (ObjC/Swift) kept per region instead of per object.
- **Covered options.** Brief items "Arenas" and "Scope-bound regions" are close, but depots are owned values and not scopes, so the brief's "promote/leak-to-global" objection does not apply. O7's cycle backstop is replaced by region close.

**Genuinely new in combination:**
1. **Destination-driven allocation** as an implicit language rule (a hidden `shipTo` argument on every call).
2. **Closures as "addressed parcels."** Captures are classified near/far at runtime, and a call is silently skipped if any addressee is dead.
3. **Chain-of-custody on recalls.**

Item 1 is the novel core. Items 2 and 3 are novel behaviour on top of known structure.

## 3. Soundness counterexamples

### CE1: The callback goes silent because far captures don't own (rule 10)

```
func startPolling() {                    // free function, current depot = main
    counter = Counter()                  // built in current depot (main)
    timers.every(1s) { counter.tick() }  // closure built in timers' depot -> counter captured FAR
}                                        // local `counter` dropped -> RC 0 -> freed -> far recalled
// Every tick: parcel undeliverable -> skipped and pruned. Nothing ever happens. No error.
```

The same thing happens with `http.get(url) { data in parser.feed(data) }` when `parser` is a local. In O1/Swift/JS a capture owns its object, so this code works there. Here the most common async idiom is a **silent no-op**. The fix is to allocate `counter` "in timers" (`in timers {}`) or to keep it in a field somewhere. Neither is discoverable from the source, because whether a capture is near or far is decided at runtime.

### CE2: An unrelated capture silently drops a save (rule 10, all-or-nothing)

```
saveButton.onTap = { self.doc.save(); session.audit("save") }  // session lives in its own depot
// On login refresh the app closes the old session depot and opens a new one.
// Every later tap: `session` is gone -> the whole parcel is skipped -> doc.save() never runs.
```

The parcel rule turns a dead *secondary* object into silent loss of the *primary* side effect. That is worse than Swift's `[weak self]`, where the programmer at least chose what to guard.

### CE3: Extracting a local changes semantics (rule 3 + rule 5)

```
receive cache as c { c.put(url, Image(bytes)) }   // OK: Image delivered to cache's depot
img = Image(bytes)                                // built in current depot
receive cache as c { c.put(url, img) }            // TRAP inside put: wrong depot; use far or copy
```

`a.f = g()` and `t = g(); a.f = t` are different programs. The same thing happens when a callee changes internally:

```
func defaultStyle() -> Style { return Style() }      // v1: fresh -> delivered -> OK
func defaultStyle() -> Style { return self.shared }  // v2 (memoised): existing -> callers TRAP
```

A refactor *inside* a function can make its callers trap at runtime, and no signature records whether a function returns something fresh or something that already existed.

### CE4: Delivery conflicts in nested calls (spec ambiguity)

`cache.put(k, self.makeEntry(u))`: rule 3 says the argument is built "in the receiver's depot" (cache). But inside the method `makeEntry`, "current depot is `depot(self)`" (Gallery). The two clauses disagree. One reading: hidden `shipTo` wins over self's depot, and every temporary in the method lands in the cache depot. The other: the entry is built in Gallery's depot and `put` traps. The proposal does not say which.

### CE5: A data race through bonded depots (rules 7, 10, 11)

```
var x
receive totals.root as t { x = t.bucket(k) }  // a local outside the block now holds a bonded object
x.n = x.n + 1                                  // no lock held; non-atomic RC and fields race with other threads
h = { t2.inc() }  // closure far-captures an object in a bonded depot.
                  // The spec says a closure call *pins* its far depots; it doesn't say *lock*
```

"Locals hold anything" plus non-atomic RC is unsound for bonded depots unless one of two things is added. Either the compiler forbids receive-scoped values from escaping (a lexical escape rule the proposal doesn't state), or closure calls into bonded depots take the lock (which adds hidden locking and hidden lock-order inversions).

### CE6: Deadlock from deallocation, with no visible lock

Thread A, inside `receive b2 { ... }`, drops the last ref to an object that has a far slot into bonded `b1`. Unregistering that slot needs `b1`'s ledger, and so `b1`'s lock. At the same time, thread B, inside `receive b1`, drops an object with a far slot into `b2`. The result is a deadlock caused by the RC-zero path. Source code can't show it, and depot-id ordering can't prevent it.

### CE7: Leaks in long-lived depots, and an O(graph) `copy`

```
// Editor depot lives for hours. Each "Find" panel opened inside it:
panel = FindPanel(); panel.close.onTap = { self.dismiss() }   // panel <-> closure cycle, near
// Dismissed panels are never freed until the whole editor window closes.
copy someNode          // near `parent` pointers -> deep copy walks up to root -> copies the entire tree
```

There are two ways out. The user can give every sub-panel its own depot (then `far`/`receive` appears everywhere), or bring back `far` back-pointers, which are `weak` under another name. The proposal admits both. `copy` is a reachability traversal that the user writes by hand, which makes it a hidden O(n) cliff.

### CE8: The sealed-but-pinned state is underspecified

A local keeps an object in a closed depot alive (rule 7) and calls `obj.addChild(Node())`. Delivery targets a sealed depot ("no new deliveries reach the depot"). Does it trap, or allocate into a depot that will be torn down? Teardown also runs `deinit` on every live object in an arbitrary order. A deinit can store `self` into a far slot elsewhere (resurrection) or close other depots (cascades). None of this is specified.

**Summary:** Pins plus recall make dangling pointers unlikely. Dynamic traps plus silent parcel drops make *behaviour* surprising. The bonded-depot story has a real race hole (CE5) and a hidden-deadlock hole (CE6).

## 4. Scenarios

| | Verdict |
|---|---|
| (a) | **Works.** It relies on `return lines` being recognised as the returned value so it can be built in `shipTo`. If the result is bound to a local first, it lands in the current depot (CE3). |
| (b) | **Works.** Short-lived trees are elegant. Long-lived editable trees need a `far parent`, which is weak by another name. |
| (c) | **Works for the stated case** (editor, button and closure in one window depot, window-scoped close). It **fails silently** for closures over locals or over secondary depots (CE1, CE2). The crux is moved, not dissolved. |
| (d) | **Works.** Far + `receive`/`else` + recall-on-evict is good cache semantics. It costs `receive` boilerplate at every use, and keeping a cached object traps unless it's far/copied. |
| (e) | **Works.** Reference passing with in-place mutation, no ceremony. |
| (f) | **Partly works.** `ship` is excellent. `bonded` has the escape race (CE5), hidden-lock deadlock (CE6) and coarse locks. |

## 5. Gates

- **G2: Pass.** There is no tracing collector and no background run. Teardown iterates the depot's own objects, not reachability. The only reachability traversal is the user-invoked `copy`, which is a deep-copy, not collection.
- **G3: Pass, flag needs-john for `List of T`/`Map`.** `far`, `depot`, `receive`, `ship` and `bonded` are keywords or modifiers, the same status as O1's `weak`. Like every option, it depends on compiler-known parameterised containers (the pending question).

## 6. Rubric score

| Criterion | W | Score | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 3 | Code inside a depot is trivially simple. But there are 11 rules, a near/far split, `receive`/`else`, `copy`, non-referentially-transparent delivery, runtime wrong-depot traps, and depot granularity as a design skill. "Where does this object live?" is Rust's ownership question asked again, with runtime answers. |
| Memory safety | 15 | 4 | Recall + pins prevent dangling in the single-thread model. CE5 is a real (fixable) race hole, and traps are runtime, not compile-time. |
| Expressiveness (b)(c)(d), OO+self | 15 | 4 | Parent pointers, cycles and implicit `self` captures are excellent within a depot. Silent parcel drops (CE1/CE2) and `receive` boilerplate across depots cost a point. |
| Implementation risk (AI compiler, LLVM) | 15 | 2 | Hidden `shipTo` on every call, provenance analysis for barrier and pin elision, ledgers (including stack far-locals), runtime capture classification, a sealed/pinned state machine, atomic far slots, teardown semantics. Each is known, but the combination is large and has many unspecified corners (CE4, CE8). |
| Performance & predictability | 10 | 3 | Non-atomic RC is good. Store barriers, ledger writes on every far store and far local, pins, hidden argument passing, O(n) teardown pauses, and `copy` cliffs. Placement is hard to predict. |
| Concurrency fit | 10 | 3 | O(1) ship of arbitrary graphs is a real strength. Bonded depots have coarse locks, nested-receive deadlock, and hidden locking in deallocation (CE6). |
| Tooling, debuggability, C FFI | 10 | 4 | The manifest and chain-of-custody are standout debugging features. FFI is plain memory plus `hold`. The debugger must model depots, pins and ledgers. |

**Arithmetic:** 25×3/5 = 15.0; 15×4/5 = 12.0; 15×4/5 = 12.0; 15×2/5 = 6.0; 10×3/5 = 6.0; 10×3/5 = 6.0; 10×4/5 = 8.0.
**Total = 15 + 12 + 12 + 6 + 6 + 6 + 8 = 65.**

**Comparison:**
- **Versus O1 (83):** O1 is 18 points ahead. It wins on simplicity (about 3 rules: RC, `weak`, capture semantics) and implementation risk (very well-trodden). Idea 18's advantages over O1 are no `weak` needed for intra-window cycles, non-atomic RC, and O(1) ship. None of them outweighs the extra rules and runtime surprise.
- **Versus O4 (82):** O4 is 17 points ahead. O4's errors are compile-time, while idea 18's equivalents (wrong depot, undeliverable) are runtime traps or silent skips.
- **Versus the self-assessment (77):** the gap comes mainly from implementation risk (3 → 2), simplicity (4 → 3) and concurrency (4 → 3).

## 7. Fatal flaw and salvageable kernel

**Fatal flaw.** No single bug is fatal, but one structural problem is. **Object placement is implicit, decided by a call-site heuristic, and checked only at runtime.** The programmer must reason about which depot every object is in. The language does not let them write that down, and it does not check it until a store traps or a callback silently disappears (CE1–CE3). That gives users the cost of an ownership model without the compile-time guarantee. On top of that, the all-or-nothing parcel rule (CE2) converts liveness bugs into silent data loss, which is worse than a crash for a banking-grade or editor app.

**Salvageable kernel** (ordered by value):
1. **Chain-of-custody for weak/zeroed refs (adopt into O1).** In debug builds, every weak ref that goes nil records why: "nil because Window 'Editor' deinit at editor.x:88 via Window.close". It is cheap (a side table entry), has no semantic change, and gives large debugging value.
2. **Owner-scoped teardown as a leak backstop (O1/O4 optimisation, opt-in).** An object can be declared a "container" (a window or session) whose allocations are tagged to it. On close, the runtime runs deinits on and frees whatever of its tagged objects RC hasn't freed. That is deterministic cycle cleanup without tracing (G2-safe), bounded by an owner the programmer chose. Using it requires recall-style nulling of outside refs into the container.
3. **Registry auto-pruning.** Run loops, timers and event buses drop entries whose weakly captured `self` is dead. This is a library convention over O1's explicit `[weak self]`, and should **not** use runtime near/far classification or silent all-or-nothing skips.
4. **Chunk-tagged groups for O(1) ship plus non-atomic RC.** If O1/O4 later wants cheap thread handoff of a disconnected graph, the 64 KiB chunk header to group mapping with a dynamic "no outside pins" check is a workable mechanism (cf. Swift SE-0414, done dynamically).

## 8. Verdict

**Kernel worth stealing.** It is not a contender: at 65 it ranks with O5/O2, below O1 (83) and O4 (82). The weak points are implementation risk and the runtime-only placement model. The debugging features (chain-of-custody, manifest) and owner-scoped teardown are good, separable additions to O1.
