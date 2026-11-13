# Analysis 08: Terrain (watershed liveness on a geometric heap)

Analyst: independent. Inputs read: brief.md, round2.md, CHARTER.md, ideas/08-terrain.md only.
All code is illustrative only, not a syntax decision.

## 1. The idea in three sentences

The heap is a 3D grid of 64-byte cells. A stored reference can only reach a cell within radius 2, and the runtime builds chains of relay cells ("roads") for longer links, so every object has at most 124 in-neighbours, recorded exactly in a 16-byte bitmap. Each object keeps one "drainage parent" pointing towards an anchor (a local, global or thread). When a link is cut, the subtree that drained through it is marked falling, re-attaches through any non-falling in-neighbour, and whatever cannot re-attach is freed at that statement, cycles included. Threads own disjoint regions of the grid, and a reference into another thread's region becomes a blocking message proxy (a "postbox").

## 2. Prior art

The parts are known. Putting them together this way looks new.

- **Spanning-tree / strong-weak cyclic RC.** Brownbridge 1985 ([doi](https://www.doi.org/10.1007/3-540-15975-4_42)) has the same shape: one "strong" parent edge per object, and a search for another parent when it is cut. The original was unsound. Corrected versions include Pepels/van Eekelen/Plasmeijer 1988 ([report](https://www.cs.ru.nl/~marko/research/pubs/1988/IR88-10CyclicProof-incl-fig.pdf)) and later Brandt et al. ([ACM](https://unpaywall.org/10.1145%2F2602988.2602990)). Lazy cyclic RC (Lins) is related ([JUCS](https://lib.jucs.org/article_preview.php?id=28084)). The inventor names this family. Fall/regrip is essentially a corrected Brownbridge with exact referrer sets.
- **Reverse-reference tracing.** Maheshwari & Liskov's back tracing ([entry](https://www.sciweavers.org/node/173466)) decides liveness by walking inrefs backwards from suspects. The same trick appears here, on one machine.
- **Dynamic reachability theory.** Keeping a spanning tree up to date under edge deletion is the dynamic-connectivity / decremental-reachability problem ([Wikipedia](https://en.wikipedia.org/wiki/Dynamic_connectivity); directed decremental SSR, [arXiv 1901.03615](https://arxiv.org/pdf/1901.03615)). Even the best algorithms only bound *amortised* or *total* cost. None gives a small, bounded cost per deletion. The "height" field with lowest-height re-parenting is an Even-Shiloach-style BFS layering.
- **Spatial computing.** Ackley's Movable Feast Machine ([overview](https://highscalability.com/pursue-robust-indefinite-scalability-with-the-movable-feast/)) uses a grid of sites with bounded local event windows and no global addressing. That is the "geometry as semantics" ancestor. Self-relative and based pointers are old techniques.
- **Territories and postboxes** are actor isolation (Erlang, Pony, Swift actors) with automatic proxying of references that cross a border.

**Verdict on novelty:** using geometry to bound in-degree, so that exact reverse edges cost a fixed bitmap per object, is a real and new twist. Everything downstream of it is known.

## 3. Soundness: counterexamples

**C1. Out of room: a store that cannot be completed.** Suppose all 124 neighbours of a popular `P` are ordinary objects, for example its siblings in a dense street.
```
for i in 0..124 { row.add(Item() near P) }   // fills P's neighbourhood
far.ref = P                                    // needs a relay adjacent to P: no free cell
```
A new in-link needs a relay cell next to `P`, and none is free. The runtime has to move a neighbour. Moving it can push that neighbour's own links out of radius, which needs more roads, and so on: relocations cascade. A pinned neighbour cannot move at all. The idea does not specify this case. Rule 4 ("performance only, never meaning") cannot promise anything here. Worst case is a runtime failure of the form "no room to link".

**C2. Road memory blowup (index structures).** Take a heap of N cells. Its diameter is about N^(1/3), so a far link costs about N^(1/3)/2 relay cells of 64 bytes each.
```
index = Map of Int to User()
for u in allUsers { index[u.id] = u }          // 1M users scattered across the map
```
With N = 1M cells, the average road is roughly 50 relays, about 3 KB per entry, against 64 bytes of payload. Roads to different targets do not merge, and they compete for free cells. This is a 3D maze-routing problem solved greedily at every store. Every `index[k]` lookup then chases about 50 dependent loads. Global indexes, caches and registries are exactly the structures that are worst here.

**C3. A landslide that frees nothing, repeatedly (acknowledged, and worse than stated).** A UI keeps a `selection` reference to a deep widget, and every widget has a `parent` link:
```
selection = panel.find("field42")
window.remove(panel)        // panel subtree (S widgets) falls; regrip at field42,
                            // spreads up the parent links: O(S) work, nothing freed
```
The same thrash happens with (d) whenever components holding the cache open and close alternately. Each close re-roots the drainage tree, costing O(cache), so one keystroke can cost O(heap). Choosing the lowest-height parent does not help, because the regripped tree then drains through whichever component closes next. Pseudo-code `fall` is also written to mark the entire subtree *before* trying `o`'s own in-neighbours. Without a "try `o` first" fast path, even the claimed O(1) case (a temporary stored and then unpinned) is O(subtree):
```
n = Node(); for i in 0..10000 { n.kids.add(Node()) }   // kids drain via n (n is ANCHORED by pin)
root.add(n)                                            // only sets inbits
// scope ends: n unpinned -> fall marks 10001 cells, regrip, nothing freed
```
The fast path fixes this example but not C3.

**C4. Resurrection in `drop` gives a dangling pointer.** Stranded cells run `drop` and are then freed.
```
class Conn { drop { Pool.idle.add(self) } }   // classic "return to pool" idiom
```
After the strand phase, `Pool.idle` holds a link to a freed cell, which is a use-after-free. A `drop` that reads a link to a *peer* in the same stranded cycle and stores it does the same thing. The fix needs either a rule ("drop may not store links to self or peers", checked how?) or a second regrip after the drops, which means more traversal and objects whose `drop` has already run. Drops inside a cycle also see peers whose `drop` already ran, in an order that depends on placement.

**C5. Postbox deadlock in the idiomatic (f).**
```
stats = Stats()
t = spawn { for job in jobs { stats.record(job.run()) } }   // record() = message to main
t.join()                                                    // main blocks; never services postbox
```
This deadlocks the first time the program runs. There are two ways out, and both need a rule. Either the owner services messages while waiting, which brings re-entrancy: `stats` changes underneath main in the middle of a method, so invariants held across a call break. Or it services them only at explicit yields, so join deadlocks. The idea specifies neither. A tight compute loop on main also starves the worker indefinitely.

**C6. Sending changes meaning elsewhere.**
```
byId[order.id] = order;  batch.add(order)
send batch to worker      // order emigrates; byId's link becomes a postbox
byId[k].total             // now a blocking cross-thread call; deadlocks if worker awaits main
```
`send` silently turns unrelated main-thread code into distributed calls. Some questions are also unanswered. Is a thing passed as an argument through a postbox moved, proxied or copied? What happens to postboxes into a territory whose thread has exited? Do they hang, or does the territory merge into its parent? Postbox cycles between territories leak, as the inventor admits. That covers the common progress-callback-plus-job-handle pair.

**C7. GC-style retention leaks come back.** Tracing semantics with no weak references means the lapsed-listener leak:
```
EventBus.shared.on("theme") { self.restyle() }   // editor (and its window) live forever
```
This is not unsafe, but (c) is only half solved. Callbacks never dangle, but they keep their captures alive indefinitely, and the language has no `weak` tool to stop that.

**C8. Cost of 3D on 1D memory.** With constant offsets (`offset_table[b]`), the layout must be row-major. The z-neighbours are then a whole plane apart, hundreds of MB in a huge reserved range. One neighbourhood touches 25 separate memory runs and pages. "Near" in the grid is not near in cache or TLB, and pages committed on touch inflate memory use for sparse maps. (A 1D window of ±62 cells gives the same 124-neighbour bound with real locality, but road length becomes O(N).)

Overall: liveness detection itself (fall/regrip, given the invariant) is sound. The real holes are C4 (unsafe as specified), C1 (stuck or unspecified), and C5/C6 (deadlock and surprising semantics).

## 4. Scenarios

- **(a) works.** Strings are values in cellars and the list grows as a street. The only costs are perf (64-byte cells).
- **(b) works.** Plain parent pointers and the tree is freed on cut. Detaching a subtree while a deep node is held costs O(subtree) (C3).
- **(c) works, with a caveat.** No `[weak self]` is needed and it can never dangle, but there are GC-style lapsed-listener leaks with no tool to break them (C7).
- **(d) partial.** Semantically correct, but far links are slow (C2) and component churn causes O(cache) landslides (C3).
- **(e) works.** A link is passed and the mutation is visible to the caller.
- **(f) partial, leaning fails.** Race-free by construction, but idiomatic join deadlocks (C5), `send` has side effects elsewhere (C6), cross-territory cycles leak, and there is no shared read-only parallelism.

## 5. Gates and charter

- **G2: needs-john, leaning fail.** There is never a whole-heap trace. But fall/regrip is a mark phase over an unbounded subgraph, triggered by an ordinary store (C3), so on a bad write it is a GC run. It belongs to the same class as O7's gated cycle collector, except it runs synchronously at the write instead of deferred. "Proportional to what moved" is false: the cost is proportional to what *drained through* the cut, which can be the whole heap.
- **G3: pass**, with the shared flag: `List of T` / `Map of K to V` are compiler-known parameterised containers. No annotations are needed, and `near` is an optional hint expression, not an annotation.
- **Other goals strained.** P-GO/P-JAVA: a managed, moving (drift) runtime heap with write barriers is the kind of runtime the charter is trying to avoid, even if it is native. G1: five stated rules, but hidden rules about postbox servicing, re-entrancy, `drop` restrictions and FFI pinning. G8: needs a custom debugger, since lldb/gdb cannot follow 1-byte relative links or relays without bespoke formatters (also an opportunity, see §7). P-PY: placement-dependent performance risks "too slow" in exactly the code shape (indexes) that C2 hits.

## 6. Score

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 4 | One reference kind and no weak. Hidden rules on postbox servicing and re-entrancy, drop, and placement performance. |
| Memory safety | 15 | 4 | Tracing semantics, so no dangling in normal code. Drop resurrection is a use-after-free as specified (C4). FFI pins. |
| Expressiveness (b)(c)(d), OO | 15 | 5 | Plain references everywhere and cycles just work. Equal to a GC language. |
| Implementation risk (AI, LLVM) | 15 | 1 | Custom geometric heap, 3D routing, annexes, cellars, drift, fall/regrip invariants, territories, postboxes, debugger. |
| Performance & predictability | 10 | 1 | Barrier on every store that scans up to 40 bytes, unbounded landslides, road blowup and hop chains, 64-byte cells, page scatter. |
| Concurrency fit | 10 | 2 | Race-free, but the idiomatic program deadlocks, cross-territory cycles leak, and every shared access is serialised. |
| Tooling, debug & C FFI | 10 | 2 | The map debugger is appealing but bespoke. C cannot hold links, and pin/drift interact with FFI. |

Total = 25·4/5 + 15·4/5 + 15·5/5 + 15·1/5 + 10·1/5 + 10·2/5 + 10·2/5
     = 20 + 12 + 15 + 3 + 2 + 4 + 4 = **60**.

That is 23 below O1 (83), 22 below O4 (82), and 8 below round 1's best (68). The inventor's self-score of 72 assumed performance 2, concurrency 3 and tooling 3. C2, C5 and C8 push each of those down a point.

## 7. What the premise teaches, and the kernel

**Lessons from the premise.**
1. The cost of cycle collection is *finding the referrers*. Terrain shows that once referrer sets are exact and cheap, cycle-correct deterministic freeing reduces exactly to dynamic reachability maintenance. That problem has no bounded worst-case cost per deletion: the known algorithms bound total or amortised cost. So the triangle "deterministic death + cycle-complete + no programmer hint + bounded work per store" cannot be had. Something has to give: hints (O1's `weak`), deferral (O7), or restricted graph shapes (O2/O4). This is useful to state in the ADR, because it closes a whole family of "local rule" ideas.
2. Geometry was only a way to bound in-degree. The bound did the work. Space is expensive (routing, page scatter), and the same bitmap could come from a side table in debug builds.
3. A drainage parent, meaning *one* witnessed path from an anchor to each live object, is a very good explanation artefact. It answers "why is this still alive?" in O(depth).

**Kernel worth stealing (for O1, also applicable to O4's `shared`):**
- **Debug/test-mode leak detection at the moment of the cut.** In debug builds, keep a reverse-edge side table and a drainage parent per RC object. When a strong release leaves count > 0, run a watershed check. If the object is stranded, report "cycle leaked at editor.lang:42: Editor → Button → closure → Editor; consider `weak` on Button.onTap's capture or Editor.button". The unit-test runner fails tests that leak cycles (G9/G10). This turns O1's main weakness, silent cycle leaks, into a deterministic diagnostic that points at the exact statement, with zero release-build cost.
- **A "why alive?" debugger command (G8):** print the anchor path for any object, with the heap-map visualisation as an optional view.
- Minor: auto-proxy objects that cross threads as an actor mailbox is a possible design for O4's concurrency story. It is not new (Pony, Swift actors), and C5 shows the servicing rule has to be explicit.

## 8. Verdict

**Kernel worth stealing.** As a runtime model it is a dead end: routing, unbounded landslides, `drop` resurrection, and postbox deadlocks. Its debug-mode watershed check would make O1's weak-reference discipline far easier to learn.
