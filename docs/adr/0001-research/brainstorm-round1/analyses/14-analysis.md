# Analysis 14 — Biome (habitat trees, upstream migration, seasonal die-off)

## 1. Restatement (plain)

Every class object belongs to a region ("habitat"). Regions form a tree anchored to particular objects ("keystones"), and a store barrier moves an object, plus everything it reaches, *up* to the nearest common ancestor whenever it gets stored somewhere that would outlive it, so a heap pointer never points to a region that dies sooner.
The program kills regions explicitly with `fell`. The actual freeing happens in bulk at the next event-loop tick ("season turn"), when there are no stack frames, so stack references need no borrow checking or refcounting.
References to keystones and closures held from outside their region are generation-checked handles ("tracks") that go dormant when the region dies, and threads share data only through copied-at-the-shore "islands" guarded by a lock (`graze`).

## 2. Prior art

Every component has close prior art. The combination is new, and so is using upward migration *instead of* a collector.

| Biome piece | Prior art |
|---|---|
| Barrier that promotes an object (and what it reaches) to the ancestor heap so no pointer goes "down" the tree | Hierarchical heaps in MaPLe/MLton: Guatto et al., *Hierarchical Memory Management for Mutable State*, PPoPP 2018. A write that would make a down-pointer promotes the object to the ancestor heap. https://arxiv.org/pdf/1801.04618 . Their heaps follow the fork-join task tree and still have a GC. Biome follows an object tree and has none. |
| Only "parent pointers" (upward) allowed across regions | Gay & Aiken, RC regions / *Language Support for Regions* (PLDI 2001), with `parentptr`/`sameregion` qualifiers. https://www2.eecs.berkeley.edu/Pubs/TechRpts/2000/5340.html , https://dblp1.uni-trier.de/rec/conf/pldi/GayA01.html . Biome swaps their static annotations for dynamic migration. That is the real contribution. |
| Object-anchored region tree; killing the parent kills the children; destructors | Samba `talloc` hierarchical contexts: https://www.samba.org/~tridge/etest/lib/talloc/talloc.3.html ; Qt QObject parent/child trees. |
| Death deferred to the event loop | Qt `deleteLater()` (https://blog.devgenius.io/qts-qobject-memory-management-how-parent-child-hierarchies-delete-objects-for-you-afb4346cf8a9) and Cocoa autorelease pools drained once per runloop tick. |
| Callbacks auto-disconnected when the receiver dies | Qt signal/slot auto-disconnect on QObject destruction. |
| Region tree, isolated regions sent between threads, lock-guarded shared region | Project Verona regions + cowns + `when`: https://arxiv.org/pdf/2309.02983 , https://www.microsoft.com/en-us/research/publication/reference-capabilities-for-flexible-memory-management/ . `graze` is roughly `when`. `island` is roughly an isolated region. |
| Generation-checked handles | O6 (Vale), slot maps. Biome checks per region rather than per object. |

Verdict on novelty: the parts are all known (hierarchical-heap promotion, talloc/Qt object trees, `deleteLater`, Verona isolation, generational handles). Using hierarchical-heap promotion *as the whole safety mechanism without a GC*, and anchoring it to objects, is not on the covered list. It also differs from "scope-bound regions + promote to global", because migration stops at the nearest common ancestor rather than going all the way to global. Still, it inherits that option's main flaw (§7).

## 3. Soundness — counterexamples

All code is illustrative only, not a syntax decision.

**CE1 — unbounded leak in a long-lived habitat (the decisive one).**
```
habitat class Game {
  enemies = List()
  hud: HudModel
  func tick() {                          // 60 Hz for hours
    if rand() < 0.1 { enemies.add(Enemy()) }  // destination-allocated in Game's habitat
    enemies.removeWhere { it.hp <= 0 }   // removed Enemy stays in Game's census
    hud = HudModel(score)                // previous HudModel is never freed
    enemies = enemies.filter { it.visible }   // previous List object is never freed
  }
}
```
Rule 1 says only *values* are freed when overwritten. Every class instance ever stored into `Game`, including every `List`/`Map` you replace, survives until `Game` is felled. Memory grows without bound. There are two escape hatches. (i) Make `Enemy`/`HudModel` a `habitat class`. Then every reference is a 16-byte optional track (`e?.hp`) and you must `fell` on removal, which amounts to manual `free` with generation-checked dangling, i.e. O6/O8 with nicer words. (ii) Use `burn`, a mark-sweep, which hits G2. The same pattern shows up in undo stacks, chat histories, document models and the App habitat in general.

**CE2 — use-after-free across a nested event loop or `await`.**
```
habitat class Editor {
  doc = Document()                       // plain object in Editor's habitat
  func onExport() {
    d = doc                              // plain local pointer, unchecked
    fmt = Dialog.runModal("Format?")     // nested runloop; the user closes the editor → fell self
    d.export(fmt)                        // if the nested loop ran a season turn: dangling
  }
}
```
The safety argument ("at a turn no frame holds anything") holds only if *no* tick ever runs with frames suspended underneath it. Modal loops, `await`, coroutines and generators all break it. With `await`, rule 6 ("`self` is always live in its methods") becomes false after the suspension point. The two ways out both hurt G11: forbid turns in nested loops and forbid `await` (no reclamation during modals, no async UI), or require every local that lives across a suspension to be a track.

**CE3 — the migration walk as written moves objects sideways.**
```
p = Pair()                  // puddle
p.left = win1.model         // model lives in W1; puddle is "below everything" → no migration
win2.slot = p               // p → W2; walk visits p.left: W1 doesn't outlive W2 → migrate(model, W2)
fell win2; turn             // model freed with W2; win1.model now dangles
```
§5 says it "repeats for any child whose habitat does not outlive T". To be sound it must move each child to `LCA(hab(child), T)` (App here), never to `T`. This is fixable, but it means the barrier computes an LCA on every edge it visits, and it is exactly the kind of subtle bug an AI-written runtime would ship.

**CE4 — rule 2 contradicts rule 7 (returned/puddle closures).**
```
func makeCounter() Closure { c = Counter(); return { c.n += 1 } }
button.onTap = makeCounter()
```
Rule 2 says a returned object moves to the caller. Rule 7 says closures never migrate. If rule 7 wins, the closure lives in a dead puddle, the button holds a dormant track, and **tapping silently does nothing**: no error, no log. If rule 2 wins, closures can migrate, and the "cycles are impossible" argument for (c) has to be re-proved. A similar hole: rule 7 says "closures passed as parameters are always live", but `list.sort(by: self.cmp)` can pass a dormant stored closure, so a check is needed at the call boundary, with no defined result if it fails.

**CE5 — finaliser resurrection.**
```
habitat class Session { conn = Conn(); log = Log(conn: conn) }
class Conn { deinit { socket.close() } }
class Log  { conn: Conn; deinit { App.shared?.archive.add(self) } }  // "seed dispersal"
```
Whether `Conn` is rescued closed (a zombie) or rescued and then never finalised depends on census order. This is the classic resurrection problem, and Biome adds it on purpose.

**CE6 — deadlock.** `spawn { graze a { graze b {…} } }` together with `spawn { graze b { graze a {…} } }`. Nothing orders the locks or detects the cycle. Re-entrant `graze a { f() }`, where `f` also grazes `a`, is unspecified.

**CE7 — herd cliff (surprising, not unsafe).** In (b), `App.shared?.recent.add(node)` follows the parent pointer to the root and from there to every node. The whole outline migrates into App, so a later `fell outline` frees almost nothing, and the one store costs O(tree). That is a hidden pause plus a permanent leak from a single logging line.

## 4. Scenarios

- **(a) Growing list:** works. The buffer is private, destination passing makes the return free, and old buffers are freed immediately.
- **(b) Parent pointers:** works for structure (free cycles, no `weak`). But removed subtrees leak until the outline dies, and any single escape lifts the whole tree (CE7).
- **(c) UI callback:** for synchronous callbacks this is the best treatment of the crux I've seen: no `weak self`, cycles are free, and stale handlers prune themselves. But it breaks under async/modal code (CE2), the rules contradict each other for returned closures (CE4), and a dead handler fails silently.
- **(d) Shared cache:** the cache only works with the keystone-per-entry idiom, which is manual `fell` plus checked handles. A cache of plain objects leaks every evicted image. Whether "rises to App" happens depends on construction order.
- **(e) Mutate a large list:** works. Aliasing mutation on one thread is safe because nothing is freed mid-tick.
- **(f) Threads:** works, Verona-style. But it adds deep copies at the shore, coarse locks, deadlock (CE6), and a lexical "can't outlive the `graze` block" rule that amounts to a small borrow check.

## 5. Gates

- **G2: pass for the core, needs-john for `burn`.** Migration is a bounded traversal triggered by the barrier and never searches for garbage, and fell/turn is bulk region freeing. However, CE1 shows the core alone is not viable for churn-heavy long-lived state. In practice the model is "regions + optional mark-sweep", so John's ruling on `burn` decides whether the model is usable, not just whether an extra is allowed.
- **G3: pass, flag.** `habitat class` / `island habitat class` / `fell` / `graze` are declaration kinds and statements, not annotations. The model depends on built-in `List`/`Map` (the pending question). The idea's code writes `Map()  // String -> Entry`, which leaves element typing unresolved.

## 6. Score

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 2 | There are 9 rules and about 8 new nouns (habitat, keystone, puddle, fell, season/turn, track, island, graze), and every keystone or stored-closure use is optional. Worse, the user must make a whole-program lifetime decision, which classes are keystones, and getting it wrong causes silent leaks. |
| Memory safety | 15 | 4 | No UAF in synchronous code, and tracks are checked. CE2/CE3 are holes in the spec as written, but both can be fixed. FFI "valid until next turn" is unchecked. |
| Expressiveness (b,c,d, OO/self) | 15 | 4 | (c) synchronous and (b) structure are excellent, and implicit `self` is natural. Docked for the (d) idiom, async (CE2) and silent dormancy. |
| Implementation risk (AI on LLVM) | 15 | 2 | A novel runtime with no reference implementation: an LCA barrier on every store, layout-map walks, per-object census upkeep, escape analysis that performance depends on, season scheduler, deinit semantics, island copying. Subtle soundness bugs like CE3 are likely. |
| Performance & predictability | 10 | 3 | No RC traffic on locals and cheap bulk free. Against that: a barrier on every store, an 8-byte header plus census slot per object, herd spikes (CE7), and memory footprint that is unpredictable because of in-region leaks. |
| Concurrency fit | 10 | 3 | No data races, and O(1) habitat send is good. But copies at the shore, coarse `graze`, and deadlock-prone. |
| Tooling, debug, C FFI | 10 | 3 | Census and migration log are a real advance in leak attribution. Silent no-op closures and a custom runtime the debugger must understand pull it down. C cannot run the barrier, so C writing pointers into objects breaks the invariant. |

Total = (25·2 + 15·4 + 15·4 + 15·2 + 10·3 + 10·3 + 10·3) / 5
     = (50 + 60 + 60 + 30 + 30 + 30 + 30) / 5 = 290 / 5 = **58**

That is 25 below O1 (83) and 24 below O4 (82), and under O8 (60). The gap comes mostly from simplicity (−2 vs a plausible 4 for O1/O4, i.e. −10 points) and implementation risk (−2 to −3 vs O1, i.e. −6 to −9).

## 7. Fatal flaw and salvageable kernel

**Fatal flaw.** Biome moves the region-leak problem rather than solving it. The brief already lists "scope-bound regions … leaks long-lived objects" as covered, and Biome inherits that flaw for every long-lived habitat (App, a document, a game): any class object that is overwritten or removed stays allocated (CE1). There are only two remedies: keystone-per-object (manual free with checked handles, i.e. O6/O8 territory) or `burn` (a scoped GC, which strains G2). On top of that, the core safety argument, "deaths only happen when the stack is empty", fails as soon as the language gains modal loops or `await` (CE2), which G11-style UI code will want.

**Kernel worth stealing (for O1, secondarily O4):**
1. **Owner-scoped closure handles plus a self-pruning `Event`.** A closure stored outside its captured owner is held through a checked handle tied to that owner's lifetime. Calling it after the owner dies is a no-op (ideally logged in debug builds), and the built-in `Event` drops dead handlers. Under ARC this is roughly "an escaping stored closure captures `self` weakly by default, with no annotation", i.e. Qt's auto-disconnect. It removes the main reason O1 needs `weak self` in scenario (c), with no new syntax.
2. **Leak attribution tooling.** Per-owner census and a "why is this alive" log (allocation site → the store that extended its life). For O1, a debug build can record which retaining store created a cycle.
3. Optionally, per-tick deferred release (autorelease-pool style) as an O1 optimisation that batches refcount decrements at event-loop ticks.

## 8. Verdict

**Kernel worth stealing.** It is not a contender: it scores 58 vs 83/82, it has a structural leak in long-lived habitats, it is fragile under async, and it carries high implementation risk. Its treatment of synchronous UI callbacks is good, and point 1 above can be adopted into O1 cheaply.
