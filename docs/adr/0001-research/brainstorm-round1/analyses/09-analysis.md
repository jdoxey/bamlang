# Analysis 09: Tick & World

*All code is illustrative only, not a syntax decision.*

## 1. The idea in three sentences

All work runs in **ticks** (`main`, each event, each `update()`). Anything allocated during a tick lives in a per-thread bump **frame** with free aliasing, and the whole frame is reset in O(1) when the tick ends. Data that must outlive the tick is **copied** (baked) into a **world** of entities: the world is an ownership tree, every non-parent link is a generation-checked ID, all world frees wait until tick end (the graveyard), and stored closures capture entities by ID and are skipped if any of those entities has died.

## 2. Prior art

The idea combines known techniques. The way it combines them, and two of its mechanisms, are new.

| Piece | Prior art |
|---|---|
| Per-event scratch freed at the end of the event | AppKit creates an autorelease pool at the start of each event-loop cycle and drains it at the end ([Apple, NSAutoreleasePool](https://developer.apple.com/documentation/foundation/nsautoreleasepool.md)). Ur/Web emits C with no GC, and in the worst case an allocation lives until the end of the page request ([ICFP'15](https://adam.chlipala.net/papers/UrWebICFP15/), [ur list](https://mail-archive.com/ur@impredicative.com/msg00267.html)) |
| Scene-tree ownership, deferred `despawn` | Godot: `queue_free()` waits until the end of the frame, and freeing a node frees its children ([Godot nodes and scenes](https://www.mintlify.com/godotengine/godot/concepts/nodes-and-scenes)). Unity's `Destroy` does the same |
| Frozen world plus ordered command buffers | Bevy `Commands`/`Deferred`: mutations are queued and applied at `ApplyDeferred`, so systems can run in parallel without mutable World access ([docs.rs](https://docs.rs/bevy/latest/bevy/prelude/struct.Deferred.html)) |
| Generation-checked IDs | Slot maps and Vale-style handles (O6, and "arenas & slot maps" in the brief) |
| Copy-on-send messages | Erlang's per-process heaps (well known) |

**Genuinely new:**
- (i) These pieces become the language's *only* memory model, with time (the tick) as the lifetime axis instead of lexical scope.
- (ii) One store barrier, keyed on arena depth read from the pointer's address, drives world commits, nested `frame{}`, thread joins and messages.
- (iii) Rule 9: a callback is skipped when an entity it captured is dead.
- (iv) Compared with the brief's "scope-bound regions + promote": promoted data goes into an *owned* tree with deterministic despawn, not into a global heap that leaks. This is a real twist, not a rename.

## 3. Soundness: counterexamples

**C1. Unbounded growth in a long tick, which `frame{}` cannot fix.** The graveyard is freed only at tick end (§5), and a CLI's `main` is a single tick.
```
fun main() {
  for (i, line) in stdin.lines().enumerated() {
    frame { app.status = "processed \(i)" }   // bake into world; the old string goes to the graveyard
  }
}                                             // 10M dead strings are held until exit
```
`frame{}` only resets scratch. World data that is overwritten cannot be freed early, because an older frame might hold a reference to it, and the design deliberately doesn't track that. Ur/Web and AppKit both hit this "long unit of work" problem; Apple's own docs say long-lived threads must drain pools periodically or the footprint grows. This is a **leak by design for programs that aren't event-shaped**.

**C2. Baking a DAG blows up exponentially.** Shared sub-nodes are duplicated when copied into the world, and only true cycles trap.
```
var n = Leaf()
for i in 0..40 { n = Pair(l: n, r: n) }   // 41 objects in the frame
app.tree = n                              // 2^40 copies: hang or OOM, no diagnostic
```
Even small DAGs silently lose identity: after the bake, `app.tree.l` and `app.tree.r` are distinct objects.

**C3. The idea's own scenario (d) copies the whole image on every call.**
```
let img = cache.images[url] ?? decode(fetch(url))
cache.images[url] = img     // hit: a world ref stored into the world, so depth 0 → bake → full copy
draw(img)                   // and img is used after the store, so this is NOT its last use → no move on a miss either
```
The claimed "hit is a reference, miss moves the buffer" is false as written. Every `show()` deep-copies an image and graveyards the old one.

**C4. A write through a stale world reference is silently lost.**
```
let d = editor.doc
editor.doc = Document(path: "new")   // the old doc goes to the graveyard; d still points at it
d.text = typed                       // memory is valid, so no trap; the write vanishes at tick end
```
This is memory-safe, but it is exactly the class of bug that a trap or a borrow error would catch.

**C5. A data race on caller-frame data inside `parallel`.** Rule 12 freezes only the *world*.
```
let hits = []                                         // caller frame, depth 1
parallel for e in all Particle { if e.y < 0 { hits.push(e) } }   // concurrent push and realloc: a race
```
Worker values stored into `hits` also point into worker arenas. The fix is to record an owner thread in each chunk header and trap on any store into a chunk the current thread doesn't own. As specified, though, it races.

**C6. `frame{}` and stores to outer locals.** §5 says "stores into a local are always plain pointers", but rule 11 says values that flow out must be copied.
```
var best: Line? = nil
for l in lines { frame { let p = parse(l); if p.score > best?.score ?? 0 { best = p } } }
print(best.text)   // dangling unless assignment to an outer local is treated as a barriered store
```
The same happens through a frame closure created outside the block and called inside it. Captured mutable locals must be boxed in the heap. This is fixable, but it is a silent use-after-free (UAF) if the compiler gets it wrong.

**C7. Nested ticks.** "At invocation the runtime … opens a tick and calls the closure." If code calls a stored closure *synchronously* in the middle of a tick, a nested tick end would free the graveyard while the outer frame still holds world references: a UAF. The spec must say that ticks never nest, and that a synchronous call opens only a frame.

**C8. Skip-if-any-captured-entity-is-dead throws away unrelated work.**
```
button.onTap = { if analytics.alive { analytics.log("tap") }; self.save() }
```
`analytics` is captured. Once it dies, the whole closure is skipped and `save()` never runs: silent data loss, even though the programmer wrote a liveness check. Also, dead closures are never removed. The toolbar in scenario (c) gains one dead closure per editor ever opened, which is a logical leak.

**C9. Gaps in the spec.** Re-parenting isn't specified: moving a view between containers or a tab between windows means copying it, which makes every ID held elsewhere stale. C code that writes pointers into language objects bypasses the barrier, which the idea itself admits. OS or C callbacks on foreign threads (audio, for example) can't open a tick while the main world is in one; they have to be marshalled.

No deadlock was found. The worst blocking behaviour is that a long `parallel` stalls the event loop, which is a UI freeze rather than a deadlock.

## 4. Scenarios

| | Verdict |
|---|---|
| (a) | Works for small inputs. A real CLI over large input grows without bound unless the user knows rule 11, and graveyard growth (C1) can't be fixed even then. **Partial.** |
| (b) | **Genuinely works.** The parent link is guaranteed alive and costs nothing, and subtree despawn is natural. Re-parenting is unspecified. |
| (c) | **Genuinely works**, with no `weak` and no capture list. Caveats: C8 (skip-all semantics, dead closures accumulate), and a non-entity `self` is copied into the closure, so UI state must be modelled as entities. |
| (d) | **Works semantically** (owned once, accessed by ID, no RC or lock), but as written it copies on every access (C3). |
| (e) | **Genuinely works.** Pass-by-reference with in-place mutation is safe because nothing is freed mid-tick. |
| (f) | **Partial.** Fork-join and messages are sound once C5 is fixed. There is no long-lived shared mutable state across threads, and the world is single-threaded, so a server serializes on it. |

## 5. Gates

- **G2: pass.** There is no tracing collector. Tick reset is a deterministic bulk free. A bake traverses only the value being stored, and only because of an explicit store. Graveyard and despawn frees are deterministic.
- **G3: pass, with the standard needs-john flag.** `entity`, `spawn`, `later` and `frame` are keywords, not annotations, and the per-type bake and destroy routines are internal to the compiler. The model relies on built-in `[T]` and `[K:V]`, the same pending question as every other option.

## 6. Scores

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 3 | No borrow, RC or weak rules inside a tick is very simple. But there are 10+4 rules, and three assignment semantics: frame refs, copies into the world, entity IDs. Programs must be tick-shaped, and there are runtime traps for cyclic world data. Overall more concepts than O1. |
| Memory safety | 15 | 4 | Sound by design (graveyard plus generations), but as specified C5, C6 and C7 are UAF or race holes, and the FFI barrier can be bypassed. All are fixable. |
| Expressiveness (b, c, d, OO self, G11) | 15 | 4 | Excellent for (b) and (c), and implicit `self` on entities. Persistent graphs must become entities, there is no re-parenting, and DAG identity is lost on bake. |
| Implementation risk (AI agent, LLVM) | 15 | 2 | Many novel, interacting invariants with no reference implementation: a barrier on every heap store, address-masked depths, allocation at the destination's depth for growth inside `frame{}`, bake with cycle detection and liveness-driven moves, graveyard ordering, frozen-world threading, plus an event-loop runtime. Mistakes are silent UAFs. |
| Performance & predictability | 10 | 3 | Allocation is fast, resets are O(1), and there is no RC traffic or pauses. Against that: hidden O(n) bakes (C3), exponential DAG bakes (C2), high peak memory within a tick, and the barrier tax. |
| Concurrency fit | 10 | 3 | Deterministic, race-free fork-join and message passing are strong. The world is single-threaded, there is no shared state across threads, and C5 races as specified. |
| Tooling, debuggability & C FFI | 10 | 4 | Best in class for debugging: a hierarchy view, rewind, replay, save/load, and stale-ID provenance. FFI is weaker: pointers are valid only until tick end, barrier bypass, foreign-thread callbacks. |

**Total = (25·3 + 15·4 + 15·4 + 15·2 + 10·3 + 10·3 + 10·4) / 5 = (75 + 60 + 60 + 30 + 30 + 30 + 40) / 5 = 325 / 5 = 65.**

That is 18 below O1 (83) and 17 below O4 (82). It sits level with O5 (65), just below O2 (67), and above O8 (60). The gap comes almost entirely from simplicity (−10 against an O1 at about 5) and implementation risk (−6 to −9).

## 7. Fatal flaw and salvageable kernel

**Fatal flaw for the "default model" role:** the tick is the only reclamation boundary for world garbage, and general-purpose programs (CLIs, background loops, long handlers, library code with no event loop) are not tick-shaped. C1 shows that even the escape hatch (`frame{}`) can't reclaim overwritten world data. The other route, cutting work into `update()` ticks, imposes a game-loop structure on all code. Add the split assignment semantics (frame data aliases, world data copies) and the user model costs more than O1's `weak`, the very thing it set out to remove.

**Kernel worth stealing, adoptable into O1 or O4:**
1. **Auto-weak stored closures with liveness skip (rule 9).** In O1: a closure stored into an object field captures its object references weakly by default, and the call is skipped if any captured target is dead. For (c), this removes capture lists and `[weak self]`. C8 suggests a refinement: skip only when `self` is dead, and make other captures strong or `T?`.
2. **A per-event bump arena as an optimization.** Values that escape analysis proves never leave an event handler are allocated in a per-tick arena with no RC, and the arena is reset when the handler returns. Invisible to users, so G1 is unaffected.
3. **Built-in scene-tree ownership for UI.** Children are owned by their parent, `parent` is always valid, and destruction is deferred to the end of the event. In O1 this kills the parent/child `weak` back-pointer for UI trees.
4. **Frozen-world `parallel` with ordered `later` command buffers** as a deterministic concurrency construct in the standard library.
5. **Hierarchy view and stale-handle provenance** for the debugger (G8).

## 8. Verdict

**Kernel worth stealing.** It is not a contender: 65 against 83 and 82, high implementation risk, and a structural memory-growth problem for programs that aren't event-shaped.
