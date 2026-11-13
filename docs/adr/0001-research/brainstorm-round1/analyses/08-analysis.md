# Analysis 08: Ground Plane (Boards & Wires)

Analyst: independent. Sources read: brief.md, CHARTER.md, ideas/08-ground-plane.md only.

## 1. Restatement

Every class instance has exactly one owner, held in an owner pointer that exists at runtime. Owning fields are either
immutable `part` fields or replaceable `socket` fields. Any non-owning reference is a raw "wire", and a wire is allowed
only if its holder is inside the target's soldered cluster ("ground"), so the target cannot die before the holder.
Other references must be optional and generation-checked. Locals may point anywhere because explicitly removed objects
are only freed at a "tick" (event-loop turn or task end), when supposedly no user frames remain. Threads own separate
trees, can move subtrees between them, or use top-level `shared` objects inside `with` locks.

## 2. Prior art: a combination with one new twist

Most of the pieces already exist:

| Ground Plane piece | Prior art |
|---|---|
| Runtime ownership tree; deleting the parent deletes the children | Qt `QObject` parent/child ([qtlabs](https://qtlabs.readthedocs.io/en/latest/lab1/qobject.html), [devgenius](https://blog.devgenius.io/qts-qobject-memory-management-how-parent-child-hierarchies-delete-objects-for-you-afb4346cf8a9)); Godot node tree; Delphi `TComponent.Owner` |
| Free deferred to the event-loop turn ("tick") | Qt `deleteLater()` ([Qt blog](https://www.qt.io/blog/2012/02/02/qt-commercial-support-weekly-12-to-delete-or-not-to-delete-2)); Godot `queue_free()` ([forum](https://forum.godotengine.org/t/discussion-of-best-practices-regarding-queue-free/5159)); ObjC autorelease pools; RCU quiescent states |
| Optional wire that reads `none` once its target is removed | `QPointer`; Godot `is_instance_valid` ([coddy](https://coddy.tech/docs/gdscript/null-and-is-instance-valid)); Delphi FreeNotification; Vale/slot-map generations (O6) |
| Fuse closures (auto-disconnect on destroy) | Qt signal/slot connections auto-disconnect when the receiver dies |
| A reference is legal only from inside the owner's context | Owners-as-dominators ownership types, Clarke/Potter/Noble OOPSLA'98 ([dblp](https://dblp.org/rec/conf/oopsla/ClarkePN98)) |
| ...checked at runtime instead of by types | Dynamic ownership, Gordon & Noble ([paper](https://scg.unibe.ch/assets/files/c6/opsksd9r9temhrro67y49sdxhulque/p41-gordon.pdf), [SCG project](https://scg.unibe.ch/research/DynamicOwnership), [DLS'12 follow-up](https://conf.researchr.org/details/dls-2012/dls-2012-papers/3/Ownership-filters-and-crossing-handlers-flexible-ownership-in-dynamic-languages)); gradual ownership ([Sergey & Clarke ESOP'12](https://ilyasergey.net/assets/pdf/papers/gradual-esop12.pdf)) |
| Moving or sending a subtree with no incoming references | External uniqueness, Clarke & Wrigstad ([record](https://bvbvf1.bib-bvb.de/vufind/PrimoRecord/cdi_pascalfrancis_primary_15671379)); Haller & Odersky capabilities ([pdf](https://infoscience.epfl.ch/record/148219/files/haller-odersky10-Capabilities_for_uniqueness_and_borrowing.pdf?version=1)); Pony `iso`; dynamic region ownership ([PLDI'25](https://pldi25.sigplan.org/details/pldi-2025-papers/64/Dynamic-Region-Ownership-for-Concurrency-Safety)) |
| Raw upward reference | Swift `unowned` / `unowned(unsafe)` |

**What is new:** using *immutable owning fields* (solder) to make the dominator context bigger. The context becomes the
whole solder cluster, not one owner, so references to siblings and cousins are provably safe and cost nothing to read.
It comes with a cheap O(depth) check when a wire is connected, and the theorem "no plain wire can enter a socketed
subtree", which makes removal and move bookkeeping-free. I have not found this exact combination. Using the tick in
place of a borrow checker for locals is essentially Qt's `deleteLater` idiom, turned into a language rule.

## 3. Soundness: counterexamples

All code is illustrative only, not a syntax decision.

**CE1: use-after-free across an explicit or nested tick (memory-unsafe as specified).** Rule 6 assumes that "no user
frames remain" at a tick. That is false for `tick` in `main` and thread entry functions, and for nested event loops
(modal dialogs). Section 5 only verifies *bench* locals at a tick. Non-owning locals are not checked.
```
fun main() {
  app = App()
  e = app.cache.entries["k"]          // local: "may point anywhere"
  app.cache.entries.remove("k")       // e is a zombie
  tick                                // frees e's memory
  print(e.name)                       // use-after-free
}
// The same bug inside a UI callback:
onTap: { t = self.current!; if confirm("Close?") { ... }; t.title }
// confirm() runs a nested modal loop; a timer closes the tab and the nested loop ticks; t dangles
```
Fixes add rules. (i) A component-typed local that does not own its target cannot be used after a `tick` in the same
frame (a lexical check). (ii) Only the outermost loop ticks, and nested loops accumulate garbage. (iii) Coroutines or
async, if they are added later, break rule 6 completely, because suspended frames survive ticks.

**CE2: data race through an optional wire into the backplane.** Rule 9 lets references escape a `with` block "in
optional wires". The target, an `Entry`, is a normal class, so nothing stops a later access outside the lock.
```
shared class Cache { socket entries = Map of String to part Entry() }
// thread A
with cache { self.pinned = cache.entries["k"] }   // pinned: Entry?  -- allowed
self.pinned?.hits += 1                            // outside any lock
// thread B
with cache { cache.entries["k"].hits += 1 }       // race. The generation check on pinned is also a cross-thread read
```
Also, "lexical check" cannot see a reference passed into a function called inside the `with` that stores it. The
connect-time check needs an "in-backplane" flag, and every optional read needs a lock-held check. That is more runtime
machinery and is not in the spec.

**CE3: resurrecting a zombie and skipping deinit.** Removed components stay readable and, as written, mutable until the
tick, and `deinit` has already run on the whole subtree.
```
z = tabs[0]; tabs.remove(0)            // deinit has run on z's whole subtree
z.panel = LogPanel(file: open(p))      // installed into a zombie; freed at tick, its deinit never runs -> fd leak
w = take z.children.take(0)            // w's deinit already ran (file closed)...
win2.tabs.add(take w)                  // ...and now it is live again, half-destroyed
```
Memory stays safe if the retire walk follows current ownership, but the semantics break. A rule is needed: a removed
component is frozen, and any socket write or `take` from it traps.

**CE4: performance cliff on subtree moves.** `depth` is stored per component, and a `take` re-checks the outward wires
of the moved subtree, so moving a subtree costs O(subtree). A red-black or AVL rotation moves subtrees, so a node-based
balanced tree becomes O(n) per insert. A UI reconciler that re-parents large views pays the same price. In practice the
workaround is a slot map with indices, which is the "arenas as library tools" option already covered.

**CE5: correct-looking code traps at runtime, far from the edit.**
```
class App { part console = Console() }
fun main() { app = App(); log = Logger(out: app.console); tick }  // trap: log is on the bench, not under ground(console)
// refactor: `part cache` becomes `socket cache` so it can be reset
// -> every SearchPanel/PreviewPanel `cache: Cache` wire now traps when connected; all must become Cache? and be unwrapped
// dragging a tab to another window: any plain wire inside the tab pointing at its old Window traps during `take`
```
Whether a wire is legal depends on the runtime tree shape, not on its type. Whether a field should be `T` or `T?`
therefore depends on where its target will be mounted. The language enforces this with crashes, not compile errors.

**CE6: lost update through a retired buffer.** `ps[0].x = grow(ps)` where `grow` appends and reallocates. If the
address of the element is taken before the right-hand side runs, the write goes into the retired buffer and is lost
without any error. It is memory-safe but surprising. Swift added exclusivity enforcement for exactly this case.

**Minor issues.** The header says `ground*` "never changes after construction". That is false for bottom-up
construction: a `Toolbar`'s parts get a new ground when the Toolbar is soldered into the `EditorScreen`. `depth:u16`
caps ownership chains at 65,535 levels. It is unspecified whether a struct value may hold a wire. If it can, every
struct copy needs a DRC check, and sending a struct to another thread could smuggle a raw cross-thread pointer.
Initializer closures that capture `self` need definite-initialization rules, Swift two-phase style. Nested `with a` /
`with b` in opposite orders deadlocks; that is not unique to this model.

## 4. Scenarios

- **(a) Read lines:** Works. Lines are values, the list is owned by a local and returned, and old buffers are retired.
- **(b) Parent pointers:** Works well. The raw upward wire is checked statically. Moving between trees takes a bench
  dance (take to a local, fix the wires, install), learned from traps.
- **(c) UI callback:** Works for the intra-screen case, with no weak/strong dance, and is better than O1 here. Downward
  callbacks become fuses, which is good. The flaw is that `self` used after `closeTab` is a zombie whose `deinit` has
  already run.
- **(d) Shared cache:** Partial. It works only if the cache can be hoisted to a common soldered ancestor. "Free it when
  the last user goes" cannot be expressed; you hand-roll a refcount with a socket and optional wires.
- **(e) Mutate a big list:** Works. It is passed by reference with no syntax. There is no exclusivity rule, hence CE6.
- **(f) Threads:** Hand-wave in places. `shared` is top-level only, so there is no dynamic `Arc<Mutex>` equivalent.
  CE2 is a race. Sending values that contain wires is unspecified. `send take` costs O(subtree).

## 5. Gates

- **G2: pass.** Nothing is traced. The tick frees only objects that were explicitly removed, at fixed points, like
  `deleteLater` or an autorelease pool. The time it takes depends on how much was removed, not on how big the live heap
  is. John may still want to confirm he is comfortable with deferred freeing, but it is not a collection run.
- **G3: needs-john.** The model relies on `List of part T`, `Map of K to part V`, `Channel of T` and `T?`. It also puts
  an ownership modifier (`of part`) inside type arguments, which goes beyond the plain `List of T` question.
  `part`/`socket`/`take`/`with`/`tick`/`shared` are keywords, comparable to O1's `weak`.

## 6. Scores

| Criterion | W | Score | Justification |
|---|---|---|---|
| Simplicity | 25 | 2 | 9 rules and about 10 concepts (part, socket, wire, optional wire, bench, take, tick, zombie, fuse, backplane). Users must predict the runtime tree to choose `T` or `T?`, and CE1–3 fixes add more rules. Borderline 3 at best. |
| Memory safety | 15 | 3 | The core theorem is sound, but the spec has a real use-after-free (CE1) and a race (CE2). Failure modes are crashes or silent `none`. Fixable, which would make it a 4. |
| Expressiveness (b,c,d,self) | 15 | 4 | (b), (c) and implicit `self` are excellent. (d) has no dynamic shared lifetime, and graphs need optional wires everywhere. |
| Implementation risk | 15 | 2 | Novel runtime with no reference implementation: owner/ground/depth headers, connect-time DRC, static elision analysis, per-class wire maps, verified-bit amortisation, per-thread generation tables, retire lists, backplane flush, OS event-loop integration. Its invariants fail silently when wrong. |
| Performance & predictability | 10 | 3 | Wire reads cost nothing and there is no RC traffic. Against that: a 24 B header, O(depth) stores that aren't elided, O(subtree) moves (CE4), memory high-water within a tick, and runtime traps. |
| Concurrency | 10 | 2 | Separate thread trees plus `send take` is fine, but shared data is top-level only, CE2 is a race, and sends cost O(n). |
| Tooling, debug, FFI | 10 | 4 | The board view and tree-path trap messages are a real debugging win. FFI with "valid until tick" plus u64 handles is workable. C-owned long-lived objects are awkward. |

Total = (25×2 + 15×3 + 15×4 + 15×2 + 10×3 + 10×2 + 10×4) / 5 = (50+45+60+30+30+20+40)/5 = 275/5 = **55**.

Comparison: **55**, against O1 = 83 and O4 = 82, 27–28 points behind. It is also below O8 (60). Even generous scores
(simplicity 3, safety 4, concurrency 3) only reach 65, which still loses to both. The gap is mostly simplicity and
implementation risk, the two heaviest criteria after simplicity.

## 7. Fatal flaw and salvageable kernel

**Fatal flaw:** whether a reference is legal depends on the dynamic shape of the ownership tree, so a type error turns
into a runtime trap. Users must learn the topology rules anyway to avoid crashes. That gives the cognitive load of
ownership types without their compile-time guarantee, on top of a novel runtime that is risky to build. The tick's
"no user frames remain" premise is also false in practice (main loops, modal loops, any future async).

**Kernel worth stealing (for O1):** *solder clusters.* A `part` field is an immutable owning field set only at
construction, and every object soldered into a cluster shares **one** refcount, held by the cluster's ground. Retaining
any part retains the ground, like a C++ `shared_ptr` aliasing constructor. References inside a cluster (to the owner,
to soldered siblings, and closure captures of `self` in part initializers) can then be stored **uncounted and raw**,
proven at compile time. They can't dangle, because the whole cluster lives or dies together. They can't leak cycles,
because they aren't counted. That removes most `weak self` cases in declarative UI (scenario c) and parent pointers
(scenario b) from O1 without a new user-facing rule beyond the `part` keyword. Note that this does **not** carry over
as written: in plain ARC, a part can be retained from outside beyond its owner's life, so the shared refcount is what
makes it safe.

Secondary, smaller kernels:
1. **Fuse closures:** a callback-registry slot typed `(() -> ())?` captures weakly and reads `none` once any capture
   dies, giving automatic unsubscribe in O1.
2. **Board-view debugger:** in O1, a debugger view of the ownership/retain graph using tree paths.

## 8. Verdict

**Kernel worth stealing.** It is not a contender: 55 against 83 and 82. The solder-cluster shared refcount is a strong
optimization and ergonomics feature for O1.
