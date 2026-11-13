# Analysis of idea 20: Amnesia

All code below is illustrative only and not a syntax decision.

## 1. Restatement

1. The program's irreducible data, called State, is a cycle-free tree of plain values. Only event handlers change it, and it is managed by acyclic RC with in-place reuse (as in Perceus).
2. Everything else is the result of a pure, memoized `derive` function. These results may alias and form cycles. The runtime may evict any of them between events under a byte budget and rebuild it on next use, so freeing them never asks whether anything is still live.
3. Closures capture State *paths* (such as `/editors[k7]`), not objects. When a closure fires, its path is resolved again, and if the key is gone an `else` branch runs.

## 2. Prior art

The pieces are known. The combination, used as a general-purpose language's *only* heap model, is new as far as I can find.

- **Evict under a budget, recompute on access:** this is Dynamic Tensor Rematerialization ([ICLR 2021 slides](https://iclr.cc/media/iclr-2021/Slides/2537.pdf)). It is a runtime that evicts tensors when memory is short and replays the producing op on access, using a cost/size/staleness heuristic. The rematerialization line of work is the same idea in static form ([NeurIPS 2019](https://papers.nips.cc/paper/9653-efficient-rematerialization-for-deep-networks), [Coop, NeurIPS 2023](https://papers.neurips.cc/paper_files/paper/2023/file/9c534edc7ac1d6438216311be6d42eb2-Paper-Conference.pdf)). Amnesia applies DTR to general program data.
- **Memo database with LRU eviction:** Salsa evicts least-recently-used memoized values "at the start of each new revision" ([salsa tuning](https://docs.rs/crate/salsa/0.26.1/source/book/src/tuning.md)). That is almost exactly rule 5's "between events".
- **A language built around memoized pure functions:** Skip ([github.com/skiplang/skip](https://github.com/skiplang/skip)) is LLVM-compiled and tracks side effects so that pure functions can be memoized with reactive invalidation. It still has a collector, which only scans memory reachable from the root of a computation. Skip is the closest language-level ancestor.
- **Demand-driven incremental computation:** Adapton ([PLDI 2014](https://people.mpi-sws.org/~hammer/adapton-pldi2014.pdf)).
- **Model tree, derived view, callbacks as messages:** this is the Elm architecture and React/SwiftUI (no search; well known). The State layer is Koka/Lean Perceus.

**Verdict:** a genuine synthesis (DTR + Salsa + Elm + Perceus), not a rename. The novel claim is that rebuildability replaces liveness as the safety argument for the derived heap.

## 3. Soundness: counterexamples

**C1. Cache snapshots defeat in-place mutation. This breaks (e) and the performance story.** Each entry holds RC'd snapshots of its inputs (§5). So once any derive has read a State node, that node has RC>1, and the next handler write must copy it.
```
derive status(s: Samples) -> String { "\(s.count) samples" }   // rendered every frame
on Clean { dedupe(&state.samples) }    // samples is shared with the cache entry, so the whole 50 MB list is copied
on Key(c) { state.doc.text.append(c) } // a 1 MB text is copied per keystroke if view() has read it
```
"Unique, mutated in place" is true only for data no derivation has looked at, which is exactly the data you don't care about. The fix is persistent vectors or ropes everywhere, which gives O(log n) per write for all lists. Amnesia then pays a persistent-data tax on the State that O1 never pays.

**C2. Memory is bounded by history, not by the budget.** A view entry might be 1 KB but pin a distinct old 1 MB text version. With a 100 MB budget charged by entry size, 100k keystrokes keep about 100 GB of old State alive before any eviction happens. Charging the pinned snapshots correctly needs "bytes this entry uniquely keeps alive". Under structural sharing, finding that out means walking the snapshot, which is a trace.

**C3. A single long event never frees anything.** Rule 5 says that within one event anything you've touched stays put. CLI tools, batch jobs and servers often *are* one event.
```
on Start { for line in File.lines(huge) { total += parse(line).value } }  // derive parse
```
All N parse results stay resident until the event ends. If "touched" instead means "still held by a local", the runtime must track local liveness of entries, and that is RC on derived data, the thing the design meant to avoid.

**C4. A blocked world stalls the whole heap.** The safe epoch is the minimum over all worlds. A world inside a long handler (an `accept()` loop, a 10 s read, a `parallel for`) freezes eviction for every world, and the cache grows without bound. This is the classic epoch-based reclamation stall, now applied to the whole heap.

**C5. Late resource release, which loses data and breaks RAII.**
```
on Close(k) { state.docs.remove(k) }          // the doc holds an exclusive file lock or socket
on Reopen(p) { File.lockExclusive(p) }        // FAILS: a cache entry's snapshot still holds the old doc
```
Destruction timing now depends on cache pressure. Either resources may never be read by a derive, or they must be excluded from snapshots. Both are new rules.

**C6. Paths can point at the wrong object or at nothing (handle ABA in disguise).**
```
lines: List of Line          // not Keyed, so the path is /lines[5]
on DeleteLine(2) { ... }     // the old /lines[5] is now the former line 6, and its tap button edits line 6
on MoveTab(k7, w1, w2) {...} // /windows[w1]/editors[k7] is gone, so Save runs `else` and the user loses work
```
Key reuse has the same effect: remove `k7`, insert a new `k7`, and an old callback mutates the new editor. Keys need generations, and moves break paths. The memory is safe, but the actions are silently misdirected or dropped.

**C7. Rule 1 contradicts (b).** "There is no reference type you can write", yet `outline()` builds `o.kids[i].parent == o` with real pointers. A value-semantics language cannot construct that cycle without a hidden reference or mutable-cell construct that exists only in `derive`. The design also needs a "storable vs derive-only" type split. Otherwise rule 6 ("storing into State copies") must deep-copy a cyclic graph into an acyclic tree, which diverges or is undefined:
```
on Snapshot { state.saved = outline(state.root) }   // compile error? infinite copy?
```

**C8. Cache keys are underspecified, which causes false hits and leaks.** The key is `(fn id, argument version stamps)`. Stamps are per-world State versions, so world 1 node v5 and world 2 node v5 collide unless node identity is part of the key. Arguments that are locals, such as a freshly decoded `img` passed to `thumbnail`, have no stamp. They must be content-hashed, which is O(n), or given a fresh stamp, which never hits and fills the cache with dead entries that pin their inputs. So (d)'s "shared automatically" holds only when the data lives in State.

**C9. Function colouring spreads purity through the language.** Purity can't be checked inside `derive` without effect-typing closures. `List.map(f)` has to be callable from both derives and handlers, which needs effect polymorphism (Koka-level type machinery) or two copies of every higher-order function. Closures created inside `view()` mutate State, so there are two closure kinds.

**C10. A closure sent to another world resolves against the wrong State.**
```
indexer.send(Index(doc, onDone: { self.status = "done" }))  // runs in the Indexer world
```
`/editors[k7]` is resolved against the Indexer's State, so it misses (runs `else`) or hits an unrelated node. Paths must carry a world id, and invoking such a closure must turn into a message. That is a new rule.

**C11. Stale captured locals.** `n = items.count; Button(onTap: { log(n) })` captures `n` at derive time. It is the same as React's stale-closure bug: defined behaviour, but a classic source of confusion.

**C12. The recall-link dilemma.** Do recall links pin their target's input snapshot? If yes, they keep old State alive (C2). If no, "never dangles" is false and they are weak refs with an `else`. Links to *interior* nodes of another entry also need a key plus an intra-result path to re-find the node after a rebuild. So every derived dereference pays a generation check, and some pay a recompute in the middle of a read.

No race or deadlock surfaced beyond C4. Concurrent recompute of the same key needs single-flight, and a cyclic derive dependency is infinite recursion, as in any memo system.

## 4. Scenarios

| | Verdict | Reason |
|---|---|---|
| (a) | **works** | A local value grows uniquely in place. The cache is not involved (but see C3 if it is). |
| (b) | **partial** | The zipper parent works for State reached by path. The derived pointer graph contradicts rule 1 (C7), and local copies have no parent. |
| (c) | **works** | The best story in either round. No capture cycle is possible and the dead-target behaviour is defined. Path ABA and moves (C6) and cross-world calls (C10) are the caveats. |
| (d) | **partial** | The pure memo is free. A mutable cache is Elm's "State at the common ancestor" with global paths (`root.users`), which couples components to the world layout. IO-backed caches are never evicted. |
| (e) | **partial** | In place only if no derive has read the list. Otherwise it is a full copy, or a persistent-vector tax (C1). |
| (f) | **partial** | Actors plus an immutable shared cache are data-race free. `parallel for … frozen borrow` is an unlisted rule. The epoch stall (C4) and stamp collisions (C8) remain. |

## 5. Gates

- **G2: pass (soft needs-john).** Eviction does not trace and does not decide liveness. Per-entry free is O(1), plus RC cascades on released snapshots, which is the same pause class O1 accepts. It is still a runtime policy that frees memory on its own schedule, so John should confirm that a budgeted evictor is not a "GC run" in spirit.
- **G3: needs-john.** `derive` is a keyword, but in practice it is a function colour like `async`, and closures need an effect distinction (C9). Pin hints for latency (weakness 1) would be annotations. `Keyed of`/`List of` rely on the pending built-in-containers question.
- **Other charter strain:** G1 (every program must be architected as State plus derivations), G8 (non-deterministic breakpoint hits and timing-dependent behaviour), and P-SWIFT (keys, paths, worlds, derive, purity, `else`, resources, storable types: a lot of features).

## 6. Score

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity | 25 | 2 | 8 stated rules plus about 6 hidden ones: purity/closure colours, path vs local `self`, storable types, resource rule, world-qualified paths, granularity design. The State/derive split is forced on every program. |
| Memory safety | 15 | 4 | No use-after-free or dangling memory by construction. Paths/keys reintroduce handle ABA (wrong-object writes, silently dropped actions). |
| Expressiveness (b,c,d,OO) | 15 | 3 | (c) is excellent. (b) and (d) are partial. Mutable object graphs (games, DLLs) collapse to keys, like O2. |
| Implementation risk | 15 | 1 | Incremental runtime, concurrent memo cache, epochs, recall links, purity/effect checker, Perceus reuse, version stamps and zippers. Far beyond O1. |
| Performance & predictability | 10 | 2 | Latency depends on budget. Copy-on-pinned-write (C1), stamp propagation, a generation check on every derived read, release timing tied to the cache (C5). |
| Concurrency | 10 | 4 | Race-free by construction (actors plus an immutable cache). Points off for the epoch stall and cross-world paths. |
| Tooling / debug / FFI | 10 | 2 | Chaos mode is a real plus. Breakpoints fire on rebuild, derived objects have no identity, and C pointers are valid for one event only, so copy-out is needed. |

Total = 25·2/5 + 15·4/5 + 15·3/5 + 15·1/5 + 10·2/5 + 10·4/5 + 10·2/5
     = 10 + 12 + 9 + 3 + 4 + 8 + 4 = **50 / 100**

That compares with O1 at 83 (−33), O4 at 82 (−32) and the round 1 best at 68 (−18). The inventor's self-assessed 64 is too generous on simplicity and implementation risk. C1–C3 also cut the performance score.

## 7. What the premise teaches

1. **Liveness doesn't disappear; it turns into purity.** "Free it any time" is only safe for data that has a recipe. Proving there is a recipe is an effect-typing problem (C9), and it spreads through the language the way lifetimes do. The complexity moved rather than vanished.
2. **Memory turns into time, and that time is unpredictable.** Every byte freed early is a recompute paid later, and it lands at a moment chosen by cache pressure. For a language that promises "no GC pauses", that is a pause by another name.
3. **Any cache that pins mutable inputs fights in-place mutation (C1).** Snapshots for rebuildability and Perceus uniqueness work against each other. This lesson transfers to any CoW-plus-cache design (O3).
4. **The real insight is about (c).** The UI capture-cycle problem only exists because view objects are *owners*. If a view is disposable output and a callback is an *address plus an action*, there is nothing to retain and nothing to cycle. Most non-nesting lifetimes in UI code are really derived data that someone stored. Neither O1 nor O4 needs Amnesia to get this, but it does tell the UI DSL (G11) what shape to take.

### Salvageable kernel (for O1 or O4)

- **K1, key-addressed callbacks with a mandatory `else` (O1/O4 UI DSL):** `onTap: editors[id].save() else log(...)`. The callback holds an id into an owning collection, not a strong or weak `self`. It turns the `[weak self]` problem in O1 into a library or DSL convention. Keys must carry a generation to avoid C6. This is not round 1's "no-op when captures die", because no capture is tracked; resolution is by lookup and the `else` branch is explicit.
- **K2, a built-in purgeable `Memo` cache (std library):** a budgeted LRU map whose entries hold a recompute function (similar to NSCache, or Salsa's LRU), evicted on memory pressure or at event boundaries. It covers the pure half of (d) without lifetime reasoning. Inputs are captured by value or key, never as RC snapshots of mutable State (lesson 3).
- **K3, an `--amnesia` chaos test mode (G8/G10):** the test runner evicts every `Memo` entry after every event and fails if behaviour changes. This makes "my code doesn't depend on cache residency" mechanically checkable. It costs almost nothing to implement.
- **K4 (optional), per-result arena for immutable builders:** a pure builder's result graph allocated as one arena, with internal cycles allowed and one RC for the whole block. This is close to round 1's "freed whole" groupings, so it is an optimisation only.

## 8. Verdict

**Kernel worth stealing.** As a heap model it scores 50 and fails on hidden rules, implementation risk and predictability (C1–C5). Its callback-as-address view of (c), together with an evictable memo cache and its chaos mode, transfers cleanly into O1 or O4.
