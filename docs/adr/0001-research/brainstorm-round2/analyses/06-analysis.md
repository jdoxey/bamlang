# Analysis 06: Spreadsheet Heap (recompute instead of store)

All code here is illustrative only, not a syntax decision.

## 1. The idea in 3 sentences

Pure functions (`fn`) have their results stored in a budgeted memo table keyed by recipe (fn id + argument keys). The runtime may evict any unpinned entry at any time and recompute it when it's read, and entries hold keys rather than pointers, so cycles and dangling pointers can't exist. Mutable data lives only in `state` slots of `part`s in a tree that is re-derived from a root after every serialized `act`, and a part's state dies when the root stops producing it (Compose/React-style positional lifetime applied to the whole program).

## 2. Prior art

Every mechanism has prior art. The new part is using the combination as the *only* memory model of a general-purpose native language.

- **Dynamic Tensor Rematerialization** (Kirisame et al., ICLR'21; https://arxiv.org/abs/2006.09616, https://sampl.cs.washington.edu/projects/dtr.html) is exactly the heap mechanism: a runtime cache that evicts values under a memory budget and recomputes them on demand from their recipe, with a cost-aware heuristic. As I recall the paper, its heuristic uses cost / (memory × staleness) and also accounts for evicted neighbours. That is precisely the gap noted in §3 C4. The project page itself only says "a heuristic".
- **Skip / Skiplang** (Facebook; https://sdtimes.com/os/sd-times-open-source-project-of-the-week-skip/, https://github.com/kolharsam/skip) is the closest *language-level* prior art. It was a general-purpose language built around memoization-based caching, reactive invalidation and tracking of purity and mutability. It still shipped a GC, scanning memory reachable from a computation's root, and it left active development. That is a cautionary data point.
- **Adapton** (https://people.mpi-sws.org/~hammer/adapton-pldi2014.pdf) and Salsa provide demand-driven, dependency-tracked memoization and red-green validation, which give §5's validity scheme.
- **Jetpack Compose `remember` / slot table** (https://developer.android.com/develop/ui/compose/state-lifespans) gives state lifetime bound to composition position, forgotten when the node leaves. That is rules 6–7 verbatim. React's `key` gives the same semantics, and the same footguns.
- Spreadsheets, Spark RDD lineage and Bazel action caches cover the rest.

**Verdict:** it is a *synthesis* of DTR, Adapton, Compose and actors, not a new primitive. The synthesis is novel as a heap model. The one open problem (§3 C1, recipe roots) is exactly what Skip resolved with a GC.

## 3. Soundness: counterexamples

**C1. Recipes over facts: a dangling recipe, or a hidden GC.** Rule 9 frees facts at scope exit. Keys may be stored in state (§5 "may contain keys").
```
act load() {
  text = read("in.txt")                   // fact, freed at scope exit
  self.report = Report{ counts: wordCounts(text) }   // a key: (wordCounts, key(text))
}
// later: memory pressure evicts wordCounts(text); a view reads report.counts
// the recompute needs `text`, which no longer exists
```
There are three possible repairs, and each one breaks a claim. (i) A key keeps its fact args alive. That turns facts into refcounted or traced objects, and cycles through state come back, which puts G2 in question. (ii) A store deep-copies all keys into values. Then "keys in state" is meaningless, and every store is an O(n) copy. (iii) A key over a fact may not escape the frame. That is an escape or borrow rule, the Rust-lite thing the idea set out to avoid. The spec picks none of these. This is the central hole: lineage only works when the roots are persistent, as with Spark's HDFS inputs. Here the roots are transient.

**C2. Key of a mutable local: a hashing cost or a cache miss.** `longest(lines)` from scenario (a) needs a key for `lines`. A content hash costs O(n) on *every* call. An identity+version key means the entry is useless after the scope ends, and it falls into C1 again.

**C3. Scribbling breaks rule 3 (aliasing).** Pins hand out raw pointers within a frame, and rule 5 allows in-place mutation.
```
fn g(t) {
  a = t[0]            // fast-path pointer into table(csv)'s entry, pinned
  c = cleaned(t)      // sortInPlace on the same buffer
  return (a, t[0])    // rule 3 promises t[0] == a; the buffer was mutated
}
```
For this to be sound, the scribble has to copy whenever another pin exists. That needs a pin count, which is a refcount. The result is copy-on-write with RC, essentially O3, plus a recompute fallback.

**C4. Eviction turns memoized code exponential, so the program gets stuck.**
```
fn fib(n) = n < 2 ? n : fib(n-1) + fib(n-2)
```
Each entry is tiny and cheap *as measured with its inputs cached*, so GreedyDual drops these entries first. Under pressure, reading `fib(80)` after the intermediate entries are evicted costs about 2^80. The "measured recompute cost" is the cost with inputs present, not the transitive cost, which is the flaw DTR's evicted-neighbour heuristic exists to fix. Any deep pure dataflow (a parse feeding an analysis feeding a layout) can storm the same way.

**C5. Pinned set exceeds the budget.** A recursive `fn depth(t, path)` over a 10^6-deep tree pins one entry per frame. Pinned entries can't be evicted, so the "hard RAM cap" is false. The only outcomes are OOM or blowing through the budget.

**C6. Positional identity corrupts data.** The spec allows "position or explicit `key`".
```
view = Tabs(for id in open { Editor(id) })   // forgot `key id`
// user closes tab 0; Editor(doc2) now sits at position 0 and inherits doc1's
// `text` state; user taps Save; doc1's text is written to doc2
```
In React a missing key is a UI glitch. Here identity *is* the memory model, so the same mistake writes the wrong data to disk.

**C7. Rule 3 versus an act's own writes.**
```
act add(x) { n1 = total(items); items.add(x); n2 = total(items); assert n2 == n1 + 1 }
```
Under an MVCC snapshot pinned at act start, rule 3 forces `n2 == n1`, so the act can't observe its own write through any `fn`. If the act sees its own writes instead, rule 3 is false. Either way it is a day-one surprise.

**C8. Live keys give torn reads across threads.** Rule 10 lets keys go anywhere, and `fn`s may read state.
```
worker: avg = sum(app.scores) / count(app.scores)   // two reads, no common moment
```
A root act between the two reads changes the version, so `avg` mixes two versions. It's not a memory-safety race, but it is a logical race, and nothing in the rules prevents it.

**C9. Serialized acts freeze the UI, and async reopens lifetimes.** `act save() { write(docId, text) }` blocks the whole root, including typing, for the length of the I/O. If acts can suspend instead, the Editor can be dropped at a settle while `save` is mid-flight, and the act resumes against `gone` state. That loses the save, or needs a new rule.

**C10. State leaks remain.** These are acknowledged: an always-produced `Session` with a growing `users` map, or an HTTP response cache made of facts that are never evicted. "Derived data can't leak" doesn't cover the common case of I/O-derived caches.

**C11. Request/reply between roots can deadlock.** Root A runs an act that waits on an act on B, and B in turn waits on A. Rule 10 doesn't say whether a send can be awaited. If it can, this deadlock is possible. If it can't, everything becomes callbacks.

## 4. Scenarios

- **(a) Partial.** The local list grows fine, but the key for `longest(lines)` is unspecified (C2), and it dangles if the result escapes (C1).
- **(b) Partial.** Derived trees are trivial and elegant. Mutable trees fall back to ids in a `Map`, which is O2-style handles with logical dangling ids.
- **(c) Works, with footguns.** No cycles and clean teardown. Positional identity (C6), blocking acts (C9) and live-at-tap-time semantics are traps.
- **(d) Works for pure caches; partial for mutable ones.** The memo table really is the shared cache. A mutable cache must be lifted to a common ancestor, and caches of facts are pruned by hand.
- **(e) Partial.** Zero-copy only if the caller doesn't reuse the argument. Otherwise there is a hidden recompute (a CSV re-parse), or a copy for facts. The aliasing rule is unsound as stated (C3).
- **(f) Partial.** Pure parallelism and actor state are good. Cross-version reads (C8) and the absence of shared mutable data are limits.

## 5. Gates

- **G2: needs-john.** Eviction and claim-set diffing are not a heap trace, so the letter passes. But C1 forces either reachability over facts held by keys (a GC by another name, which is exactly what Skip ended up shipping) or an escape rule. A background evictor that frees memory at unpredictable times will also feel GC-like to John, judging by P-GO and P-JAVA.
- **G3: pass, with a flag.** `fn`/`act`/`state`/`part` are keywords, not annotations. However, `fn` versus `act` is function colouring, an effect annotation in substance, and any "keep" hint (weakness 1) would cross into annotation. `Map()`/`List` rely on the pending ruling on built-in containers.
- **Other goals strained:**
  - G1: three new mental models.
  - P-PY: no `print` in a `fn`, no free-standing mutable objects, and slowness.
  - G8: a breakpoint inside a `fn` may never hit on a memo hit.
  - G9: coverage depends on cache state, so it is nondeterministic.
  - G6: every library must be written as parts plus formulas.

## 6. Score

| Criterion (weight) | Score | Justification |
|---|---|---|
| Simplicity (25) | 2 | 10 rules, plus three foreign models (effect split, positional state, live references) and a perf model nobody can see. |
| Memory safety (15) | 4 | No address dangling in safe code. C1 and C3 are real holes, but fixable at a cost. Ids can dangle logically. |
| Expressiveness (15) | 3 | Excellent for (c) and pure (d). No free-standing mutable objects anywhere, so classic OO is gone. (b) falls to ids. |
| Impl risk (15) | 1 | Needs a concurrent memo table, red-green validation, MVCC, claim sets, a cost-aware evictor, strict purity enforcement and hint pointers. It is the largest runtime proposed, and Skip didn't survive it. |
| Perf & predictability (10) | 1 | A memo key on every call, recompute storms that can turn exponential (C4), and hidden recomputes on scribbling. The cap fails under pins (C5). |
| Concurrency (10) | 4 | No data races, pure work runs anywhere, state is actor-style. Torn reads (C8) and blocking acts cost a point. |
| Tooling / FFI (10) | 2 | C pointers are valid only while pinned. Debugging and coverage are cache-dependent and need a lineage viewer. Time-travel debugging is a genuine bonus. |

Total:
- Simplicity: 25×2/5 = 10
- Memory safety: 15×4/5 = 12
- Expressiveness: 15×3/5 = 9
- Implementation risk: 15×1/5 = 3
- Performance: 10×1/5 = 2
- Concurrency: 10×4/5 = 8
- Tooling / FFI: 10×2/5 = 4
- **Sum: 10 + 12 + 9 + 3 + 2 + 8 + 4 = 48 / 100.**

This is below the inventor's own estimate of 64, mainly on performance (1 rather than 2), simplicity (2 rather than 3) and implementation risk (1 rather than 2), with C1 and C4 as the reasons. It is 35 below O1 (83), 34 below O4 (82) and 20 below round 1's best (68).

## 7. What the premise teaches, and the kernel

**What the premise teaches.**
1. Most of the heap in a UI or compiler-style program is *derived*. Derived data needs no lifetime story at all if it can be regenerated, so lifetime management only matters for the small set of real state plus the I/O facts. That shrinks the hard problem rather than solving it.
2. The retain cycle in scenario (c) exists because closures capture an *owning address*. If they capture an *identity resolved at call time*, the cycle disappears structurally, with no `weak` keyword.
3. The premise also shows the limit. Recomputation needs persistent roots, and the moment the roots are transient (facts, locals), you are back to an ownership or reachability question (C1). "Reference = recipe" relocates the lifetime problem to the leaves of the lineage graph; it doesn't remove it.

**Salvageable kernel (for O1, or O4):**
- **K1: positional state for the G11 DSL.** In O1's declarative layout DSL, mutable view state goes in compiler-known `state` slots owned by the tree node and released when the node leaves the tree. Callbacks capture node identity, not a strong `self`. That fixes (c) in O1 without asking users to reach for `weak`. SwiftUI's `@State` uses an annotation; a `state` keyword doesn't. Make `key` mandatory in `for` inside views to avoid C6.
- **K2: a stdlib budgeted memo cache.** Provide a `Memo` container as a stdlib tool for pure derived data: a byte budget, a cost-aware eviction policy that includes transitive cost (per DTR), and a key that keeps its arguments alive by ordinary ARC, which removes C1. This is an optional tool, not the memory model.
- **K3: debug and test modes.** One mode evicts all memo entries every tick and re-runs memoized pure functions, comparing the results to catch impurity and cache dependence. Separately, the lineage log ("why was this recomputed?") makes a good addition to the debugger (G8).
- **K4: frame-scoped pinning for C FFI.** A pointer handed to C is valid for the call's frame only, and C code that retains it must copy. This is the same as O4's parameter-only borrow, which confirms that design rather than adding to it.

## 8. Verdict

**Kernel worth stealing.** As a memory model it is a dead end: unsound at the recipe roots (C1), unpredictable (C4, C5), and it carries the highest runtime risk in the set, along a path Skip already walked into a GC. Positional state plus identity-capturing callbacks for the DSL (K1), and a budgeted memo cache as a library (K2), drop cleanly into O1.
