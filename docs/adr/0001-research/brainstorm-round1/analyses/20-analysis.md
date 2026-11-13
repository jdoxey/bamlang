# Analysis 20: Tide (one world tree, everything else goes out with the tide)

Independent analyst review. Pseudo-code is illustrative only, not a syntax decision.

## 1. The idea in three sentences

During a *turn* (one event, callback or `main`) nothing is freed, so references can be aliased freely with no refcounts or borrow checks. Between turns the only thing that survives is a single-owner tree rooted at `world`. Storing an object into a field or container makes it a child, and every other relationship is a generation-checked `link` that reads back as `T?`. At turn end, anything left unowned is freed. Stored closures capture objects by address, so "gone" means the call does nothing. `await` ends the turn and re-resolves locals, cancelling the task if one is gone. Threads get separate worlds (*realms*), and unattached subtrees can move between them.

## 2. Prior art: a new combination, not a new primitive

Each part has a close precedent:

- **Turn-granular deferred free** is the Cocoa autorelease pool. The main run loop drains a pool once per event-loop iteration, which is exactly "free at turn end". Nested `turn {}` is `@autoreleasepool {}` inside a loop. https://developer.apple.com/documentation/foundation/nsautoreleasepool.md
- **Ownership tree + deferred removal + validity-checked references** is Godot's scene tree. Parents own child nodes, `queue_free()` deletes the node in the next frame (it stays usable until then), and `is_instance_valid()` checks stale references. https://caioraphael1.github.io/studies/Godot%20Engine/Godot/Godot-nodes.html. Tide is roughly "Godot's node model made the language's only memory model".
- **Single owner + non-owning refs, no cycles by construction** is Gel / "Ownership You Can Count On" (Dingle & Bacon), plus owners-as-dominators ownership types. https://lists.puremagic.com/pipermail/digitalmars-d/2021-November/321376.html
- **`link` = slot map + generation** is O6 (Vale) and the covered slot-map tool, used only at the edges.
- **Realms with zero-copy subtree hand-off** match Project Verona's isolated regions, and loosely Pony's `iso` and Erlang's per-process heaps. Verona *statically* stops references escaping a region being transferred, which Tide does not do (see C3). https://www.microsoft.com/en-us/research/publication/reference-capabilities-for-flexible-memory-management/ ; https://arxiv.org/abs/2309.02983

What is actually new is putting these together under one memory rule. Two specific moves are interesting and not in the covered list:
1. Closures capture objects by address by default, so "gone" means a no-op.
2. `await` is a turn boundary that re-resolves locals and auto-cancels.

## 3. Soundness: counterexamples

**C1. Use-after-free through nested turns (spec bug).** §5 puts subtrees "detached this turn" on the *current* turn's floating list. The depth barrier only traps young-into-old stores, not old-into-young ones.
```
fn main()                       // turn depth 1
  a = world.items[0]            // raw ref, fine for "the whole turn"
  t = Temp()                    // depth-1 temporary
  turn {                        // depth 2
    detach(world.items.remove(0))   // goes on the depth-2 list
    n = Node(); n.child = t         // old-into-young: not trapped; t now owned by n
  }                             // depth-2 list freed: items[0], n, and t
  print(a.name)                 // dangling
  print(t.x)                    // dangling
```
This breaks rule 2 ("nothing is ever freed during a turn") for the enclosing turn. Fix: a detached object goes on the list for `min(current, its creation depth)`, and old-into-young attach traps. Fixable, but it adds yet another runtime trap.

**C2. Ordinary collection code traps.** Rule 3 says *any* list element store takes ownership.
```
fn bfs(root: Node)
  queue = List of Node()
  queue.push(root)              // root is owned by world.doc: TRAP "already owned"
active = world.users.filter { it.online }   // filter builds a new list of owned objects: TRAP
selection.push(clickedShape)    // the selection list in an editor: TRAP
```
Worklists, filtered views, selections, sorted copies and adjacency lists all need a `List of link T` that the rules never mention. If it exists, every element read is `T?` plus a slot-table lookup, and every object visited gets an address slot. This is the most important expressiveness gap, and it hits Java/Python-style users on day one.

**C3. Data race through a move with live aliases (structural).** Unrestricted in-turn aliasing is incompatible with synchronous zero-copy moves.
```
job = Job(); alias = job
enter workerRealm { it.queue.push(job) }   // job "moved" to the worker's world
alias.status = "edited"                    // caller thread writes while the worker thread reads: RACE
```
`worker.send(detach(...))` has the same problem whenever a local alias into the subtree exists. "No raw pointer survives a turn" holds only *between* turns, but sends happen *mid*-turn. Deferring `send` delivery to turn end fixes `send`, but not the synchronous `enter`. Fully fixing `enter` needs either deep copies or a poison check on every access, which is the cost Tide set out to avoid.

**C4. Auto-cancel leaves invariants stuck.**
```
fn upload()
  busy = true; toast = world.toasts.show("Uploading")   // toast is a world object
  await net.post(data)          // the user dismisses the toast meanwhile
  busy = false                  // never runs: toast is gone, so the task is cancelled
```
Cancelling because *any* object local is gone (rule 7) means the editor is stuck "busy" forever. Liveness analysis narrows the problem but does not remove it. The model needs `defer`/`finally`-on-cancel, which adds another rule.

**C5. Turn-long retention.** Destructors run at turn end and overwritten field strings go on the floating list.
```
fn main()
  for p in dir.files()          // 50,000 files
    h = File.open(p); self.last = h.readLine()
                                // EMFILE "too many open files"; every `last` string retained
```
RAII-style cleanup is gone unless every loop body is wrapped in `turn {}`. Compilers, CLIs and servers that don't yield turn into memory hoards.

**C6. Silent no-op in DSL code (G11).**
```
fn body() -> View
  counter = Counter()                          // a temporary, never attached
  return Button("+", onTap: { counter.n += 1 })  // freed at turn end; tapping does nothing, silently
```
Every other closure language keeps `counter` alive here. Tide needs state to be attached explicitly. That is workable as a convention, but the default failure mode is invisible.

**C7. Hidden writes inside `parallel`.** Creating a `link` to a world object, or capturing one in a closure, lazily allocates an address slot. That writes to the object header and the realm slot table from several workers at once. Attaching a caller's floating temporary inside a worker writes its `owner` word. Neither write is a "store into depth < d", so neither traps. Both race unless the slot table is made concurrent.

**Also:** `enter` ordering deadlocks (acknowledged). Swapping children (`a.left = a.right`) traps without a detach dance. Cross-realm `link` reads are unspecified (do they lock, or return `none`?).

## 4. Scenarios

- **(a) Works.** It reads naturally. The only cost is turn-long retention in big batch jobs (C5).
- **(b) Partial.** The structure and the `up` link are clean. Traversal with temporary worklists traps (C2) unless an unspecified `List of link` exists.
- **(c) Works genuinely.** This is the best answer to the crux in the set so far: no `[weak self]`, no possible cycles, implicit `self` intact. The caveats are silent no-ops (C6) and cancel-after-await (C4).
- **(d) Works.** Single owner plus links, and eviction semantics are right. Two co-equal owners are impossible, so manual removal can leak (acknowledged).
- **(e) Works.** Reference semantics, as in Java. No copy and no `inout`.
- **(f) Partial.** `parallel` over a frozen world is good. Subtree hand-off races with aliases (C3), `parallel` has hidden writes (C7), and `enter` can deadlock.

## 5. Gates

- **G2: pass.** No collector traces live data. Turn-end free walks only floating roots and their children. The single-owner invariant guarantees those are garbage, so this is the same class of deterministic free as an ARC cascade or an autorelease-pool drain. Wording note: rule 4 is phrased as reachability from `world`, which *sounds* like tracing GC. Restate it as "unowned objects are freed at turn end".
- **G3: pass, with the shared List/Map flag.** `link` is a field-modifier keyword (like Swift's `weak`), not an annotation. The model needs built-in `List of T` / `Map of K to V`, which is the same open question as every option. A `List of link T` makes that dependence a little deeper.

## 6. Rubric scores

| Criterion | Wt | Score | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 3 | Ten rules. Owned-vs-`link` per field is the old strong/weak choice under a new name, and on top come turns, detach, depth traps, auto-cancel and realms. C2 makes everyday collection code trap. |
| Memory safety | 15 | 3 | Rules 1–6 are sound in a single realm, but C1 is a UAF in the spec, C3 is a race, and many guarantees are runtime traps. |
| Expressiveness (b, c, d, OO) | 15 | 4 | (c) is excellent and implicit `self` is natural. Non-owning collections and co-equal sharing are weak. |
| Implementation risk (AI-written, LLVM) | 15 | 3 | No static analysis (a big plus). But the runtime semantics are novel and interacting (async re-resolution, depth barriers, realms, parallel freeze) with no reference implementation, and there are spec holes. |
| Performance & predictability | 10 | 3 | No RC traffic and cheap barriers. Against that: turn-long retention, deferred destructors, `T?` lookups, a 16-byte header, a universal store check for `parallel`, and turn-end pauses. |
| Concurrency fit | 10 | 3 | Realms and a read-only `parallel` are the right shape, but C3, C7 and `enter` deadlocks undercut them. |
| Tooling, debug, C FFI | 10 | 4 | A browsable world tree is a real G8 win and traps are clear. Silent no-ops and "C must not keep pointers past a turn" hurt. |

**Total** = (25·3 + 15·3 + 15·4 + 15·3 + 10·3 + 10·3 + 10·4) / 5 = (75 + 45 + 60 + 45 + 30 + 30 + 40) / 5 = 325 / 5 = **65**.

If C1 is patched and sends are deferred to turn end, safety and concurrency could reach 4 each: (325 + 15 + 10) / 5 = **70**. That is still clearly below **O1 (83)** and **O4 (82)**. The inventor's self-estimate of 77 assumes simplicity 4 and safety 4. C2 and C3 argue against both.

## 7. Fatal flaw and salvageable kernel

**Fatal flaw (as a whole model):** "every object store is an ownership transfer" plus "unrestricted aliasing within a turn" puts a lot on runtime traps, and neither half holds up well:
- Collections can't hold non-owning references without a second, unspecified container kind (C2).
- Zero-copy cross-thread moves can't be made safe without the static escape control that Verona uses and Tide deliberately avoids (C3).
- Making the event the lifetime unit fails for code that has no events (C5), which includes the project's own future compiler and tooling.

**Kernel worth stealing (for O1 or O4):**
1. **Escaping closures capture `self`, and objects reachable from it, by weak/generation-checked address. Invoking one whose target is gone is a no-op that returns `none` (logged in debug).** In O1 this is an automatic `[weak self]` for exactly scenario (c), with no new user rule. Keep strong capture for fresh locals to avoid C6.
2. **`await` re-resolves weakly captured `self` after resuming. If it's gone, the task cancels and `defer` blocks still run.** This fixes the "async closure outlives the window" bug class in O1/O4.
3. **Debugger view of the heap as the tree of strong (owner) edges**, with weak/link edges drawn differently. This works in O1 too, since strong edges form a DAG once weak edges are excluded.
4. Optional: an autorelease-style per-event deferred-decrement pool as an O1 *optimisation*, to elide RC traffic on locals within a turn. This is Cocoa's run-loop pool, proven in production.

## 8. Verdict

**Kernel worth stealing.** Tide doesn't beat O1/O4 as a complete model (65 vs 83/82). Its closure-capture-by-address rule with await re-resolution is the cleanest treatment of crux (c) so far, and it can be bolted onto O1 or O4 almost for free.
