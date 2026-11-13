# Analysis 02 — Unhappen

Analyst: independent. Inputs read: brief.md, round2.md, CHARTER.md, ideas/02-unhappen.md. Nothing else.
All code below is illustrative only — not a syntax decision.

## 1. The idea in three sentences

Objects live in a tree of *acts* (bump arenas), and every call is a tiny scratch "step" that is reset on return unless a store barrier saw it publish something. You never free. You `unhappen` an act, and at the end of the event-loop turn its children go, its `undo` blocks run in reverse order, and its chunks are dropped. Every cross-act reference was logged as a *claim* when it was stored, so each one is then "un-stored": a field goes back to its last surviving earlier value or nil, and a List or Map entry is removed.

## 2. Prior art

The parts are known. The combination is new: an explicit region delete that un-stores every inbound reference (falling back to the previous surviving value), used as the language's only memory model.

- **Gay & Aiken, RC regions** (PLDI 2001) — https://dblp1.uni-trier.de/rec/conf/pldi/GayA01.html , https://www.cs.cornell.edu/courses/cs612/2000SP/papers/gay-regions.pdf. Explicit regions, with a barrier that counts cross-region references. In RC, deleting a region that still has inbound references fails. Unhappen *un-stores* them instead. The memory half of the idea is "RC regions where delete nulls instead of failing".
- **talloc / APR pools** — https://www.samba.org/~tridge/etest/lib/talloc/talloc.3.html. Hierarchical allocation contexts with destructors, where freeing a parent frees its children. These are acts plus `undo`, minus claims.
- **Linux devres** — https://kernel.org/doc./html/latest/driver-api/driver-model/devres.html. Resources a driver acquires (IRQs, mappings, registrations) are released automatically in reverse order when the driver detaches. This is the "registrations are owned by the act's history" story, in production for about 20 years.
- **SolidJS owner tree** — https://docs.solidjs.com/v2/reference/advanced/owner-introspection/create-root , https://docs.solidjs.com/v2/reference/advanced/specialized-reactivity/on-cleanup. Computations and subscriptions created under an owner are disposed with it, and `onCleanup` runs on disposal. This is exactly the UI case (c).
- **Self-adjusting computation / Hammer & Acar, ISMM'08** — https://cs.umd.edu/~hammer/ismm08. A trace records allocations and writes. Change propagation discards parts of the trace and reclaims their memory. This is "retract a computation and its allocations vanish", in the research literature.
- Not searched, general knowledge: Unity's `Destroy` / "fake null" gives explicit destroy where every reference then reads as null. The generational-GC remembered set is the barrier this design reuses.

**Verdict on novelty:** a new synthesis, not a rename. The truly new semantics is *previous-value resurrection* plus semantic container removal across every field. As shown below, that is also the weakest part.

## 3. Soundness: counterexamples

**C1. Intra-act publication dangles (memory unsafety in the stated mechanism).** The barrier fast path is "same act or ancestor → plain store, no claim". The step dissolves if it has no outbound claims and its return value does not point into its range. So:
```
class App { recent: List of Entry
  fun addRecent(p: String) { recent.append(Entry(p)) } }  // step on App's act
```
`Entry` is allocated in the step. The append is a same-act store, so no claim is made. The step returns unit, dissolves, and the bump pointer is reset, so `recent` now holds freed memory. Rule 2 says this is a publication, but the barrier never sees it. The fix is a step-aware barrier: a store from a step object into a pre-step object has to be logged too. Then claims are no longer rare: every "create, then append to a long-lived list" makes one. The claimed one-compare fast path and low claim counts do not survive the fix.

**C2. Escape through `var` value parameters and value containers.** Lists are "values" with no lifetime, and locals are exempt from the barrier:
```
fun fill(var xs: List of Node) { xs.append(Node()) }      // callee step, home = caller's home
var nodes = []; fill(var nodes)                            // step: no claims, returns unit → dissolves
nodes[0].value                                             // dangling
```
A value container that holds object references has to be act-tracked, and then it is not a plain value. Copying such a list into a heap field also needs N new claims, one per element.

**C3. Async frames break "frames do not survive a turn".**
```
fun onOpen(e: Editor) async { let data = await net.fetch(e.url); e.show(data) }
// user closes e during the await → turn ends → e unhappened → e is a dangling local
```
UI code (G11) wants async. A suspended frame is heap state, so its locals need barriers. A non-optional local `e: Editor` would then have to revert to nil, which breaks the type system.

**C4. Previous-value resurrection (logic and security bug).** Banking-flavoured:
```
session.user = begin User("alice")   // act A
session.user = begin User("bob")     // act B: sibling, does not outlive A → A's claim stays in the chain
unhappen session.user                // bob logs out → session.user == alice, silently
```
Overwriting A also never unhappened A, so A leaks inside the parent act and comes back on its own. The same thing happens to `Map` entries and to `preview.current` in (d). "Undo the store" is the wrong semantics. "The slot is empty" is the safe one.

**C5. Lifetime is decided by whose method happened to allocate.** Rule 2 sets the home to `self`'s act:
```
class Editor { fun close() {
  app.recent.append(RecentEntry(doc.path))   // allocated in the EDITOR's act (claim)
  app.bus.on("uploadDone") { app.notify("ok") }  // closure in the editor's act
  unhappen self } }
```
At the end of the turn the recent-files entry disappears and the upload notification never fires. This is silent data loss, the mirror image of a leak. The workaround is an unstated ninth rule: "allocate in a method of the intended owner". The language has no way to allocate into an ancestor act.

**C6. The inventor's own scenario (b) leaks.** `Tree.add` runs with `self = tree`, so every `begin Node` is a child of the *tree's* act. All nodes are siblings, not nested. `unhappen n` frees n and removes it from `under.children`. It does not free n's children: they stay alive and unreachable until the tree dies, with their `parent` reverted to nil. To be correct, `add` must be a method on `Node`, which is C5 again.

**C7. Unbounded growth in long-lived acts and in batch programs.**
```
// App act lives forever
fun tick() { status = StatusMsg(clock.now()) }   // the old StatusMsg is never freed
// CLI main is ONE turn:
for f in files { let p = begin Parser(f); p.run(); unhappen p }   // nothing is reclaimed until main returns
```
In the root act, `begin` plus `unhappen` is manual `free` with auto-nulling: forget it and you leak. Splice drag adds to this. A tick handler that publishes one object keeps all of its scratch forever.

**C8. Invariants drift because value writes are not reverted.** Suppose `app.count += 1` runs next to `editors.append(e)`, and `app.selected = 2` holds an index. After unhappen, `count != editors.count` and `selected` points at a different editor. Selective undo is known to break invariants for exactly this reason (OT/CRDT systems pay heavily to avoid it).

**C9. Monitor deadlock in rule 8.** `shared A.m()` locks A and calls `B.n()`, while `shared B.n2()` locks B and calls `A.m2()`. That is the classic lock-order deadlock, and nothing in the model prevents it.

**C10. Assorted traps and stuck states.**
- `unhappen self` from a non-root object traps at run time.
- Rule 6 (required vs optional) is a run-time trap that depends on the act tree, so moving code between methods changes whether it traps.
- A worker that never yields never reclaims anything.
- Parent `undo` blocks run after the children are gone, so an editor cannot "save its tabs" on close.
- An `undo` that stores `self` somewhere or `begin`s a new act needs semantics nobody has specified.
- The ancestor test is O(depth), and a nested-act linked list of length n makes stores O(n).

## 4. Scenarios

| | Verdict | Why |
|---|---|---|
| (a) read lines | **works** | Value list, `File` as scratch, `undo` closes it. |
| (b) parent pointers | **partial** | Whole-tree-in-one-act works. Per-node removal leaks orphans as written (C6), and the parent field must be optional. |
| (c) UI callback | **works**, with caveats | The best case anywhere: unregistration is automatic and no cycle question arises. But async breaks it (C3), and callbacks meant to outlive their creator vanish (C5). |
| (d) shared cache | **partial** | Eviction is clean, but resurrection (C4), forced optional fields, and component-created images dying with the component. |
| (e) mutate big list | **works** for value lists | A `var` list of objects hits C2. |
| (f) threads | **partial** | Values and value-only monitors only. No shared object graphs, and deadlock is possible (C9). |

## 5. Gates and charter

- **G2: pass.** No tracing or scanning. Deallocation is explicit (`unhappen`) or step-reset. The deferral to the end of the turn is a scheduling rule, not a collection run. The debug "offline reachability report" is a tool, so it is acceptable.
- **G3: pass, with a flag.** `begin`, `unhappen`, `undo` and `T?` are language forms, not annotations. Flag for needs-john: semantic un-store requires *compiler-known* List/Map. A user-written container (G6: ring buffer, intrusive list) only gets field-level reversion, so its own count or length fields go out of sync (C8). That makes user containers second-class.
- **Other goals strained.**
  - G1: few rules, but non-local semantics (fields change between turns; lifetime depends on the allocating method).
  - G8: provenance is a debugging plus, but turn-boundary heisenbugs and silent arena corruption are minuses.
  - G11: helped for (c), hurt by the async problem (C3).
  - P-C: the spec as written has dangling holes (C1–C3).

## 6. Score

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity | 25 | 2 | 8 stated rules plus at least 2 hidden ones (home = allocating method's act; turn timing). Behaviour you cannot see locally is worse than more rules. |
| Memory safety | 15 | 3 | Safe by intent. The stated barrier and value containers dangle (C1, C2, C3), and the fixes add machinery. Resurrection is a logic hazard. |
| Expressiveness (b, c, d, OO) | 15 | 3 | (c) is excellent. (b) and (d) need `begin` and method-placement discipline, and data silently vanishes (C5). |
| Implementation risk | 15 | 1 | Step-aware barrier, claim chains with pruning, claim relocation in containers, async frames, per-thread turn deferral. Every bug is silent heap corruption. |
| Performance & predictability | 10 | 2 | Bump allocation and bulk free are fast. But there is a barrier on every heap reference store, claims become common after C1's fix, splice drag, per-act chunks, and unbounded growth in root acts and CLI programs. |
| Concurrency | 10 | 2 | Copy and move only, monitors only, deadlock-prone. |
| Tooling / FFI | 10 | 3 | "Who stored this, and when was it un-stored" is a superb debugger feature. The handle-based FFI is fine. Debugging is hampered by turn-boundary mutation. |

Total = 25·2/5 + 15·3/5 + 15·3/5 + 15·1/5 + 10·2/5 + 10·2/5 + 10·3/5
= 10 + 9 + 9 + 3 + 4 + 4 + 6 = **45 / 100**

That is against O1 at 83, O4 at 82 and round 1's best at 68. The inventor's self-assessment of 63 is too generous on simplicity and implementation risk, and it does not account for C1, C5 or C6.

## 7. What the premise teaches, and the kernel

**What the premise teaches.**
1. The hard part of (c) is *unregistration*, not memory. Leaks and dangling callbacks in UI code come from registrations that outlive their registrant. If a registration is owned by whoever made it, the problem goes away, and so do the O1 cycle and the weak-capture question. devres and SolidJS reached the same conclusion from the outside.
2. Deletion is better defined as retracting a *store* than as freeing an *object*. A reference's existence has provenance, and provenance is cheap to record at the few places that matter.
3. The counterpoint: retracting stores while keeping value writes breaks invariants (C4, C8). The only safe retraction result is *empty or removed*, never *previous value*.
4. Lifetime cannot be inferred from "which `self` was running" without surprising data loss (C5). Ownership has to follow intent: what is stored where, not who allocated it.

**Salvageable kernel: owner-scoped registrations, for O1 or O4.**
- A built-in idea: when an object registers a closure, or inserts itself, into a *compiler-known registry container* (event bus, child list, toolbar, timer set), the insertion is recorded on the registrant's cleanup list.
- When the registrant is `close`d or deinitialised, every entry it inserted is semantically removed, in reverse order. Entries are removed, never reverted.
- In O1, this plus "closures stored in registries hold their captured `self` non-owning" breaks the toolbar → button → closure → editor cycle with no `weak` keyword. In O4 it is a `shared`-aware `close`.
- The cost is only paid at registry calls. There is no barrier on general stores.

**Also worth taking.**
- A **provenance debug mode** for G8: the debug build logs reference stores per object, so the tool can answer "why is this still alive?" with file:line and the turn. This is an excellent ARC leak hunter.
- Idea for later: **step-reset scratch arenas** as an O4 optimisation, only where escape is already proven by moves.

## 8. Verdict

**Kernel worth stealing.** As a memory model it is a dead end:
- The stated mechanism has dangling holes (C1–C3).
- Its signature semantics, previous-value resurrection, is a correctness hazard (C4).
- Lifetime-by-allocating-method silently loses data (C5).

Its insight about (c), that registrations should be owned by and retracted with their registrant, is the cleanest answer to the crux scenario seen so far. It transplants onto O1 or O4 at low cost.
