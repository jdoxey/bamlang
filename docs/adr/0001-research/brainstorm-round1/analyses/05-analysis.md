# Analysis 05: Chronicle

Analyst: independent. Sources read: brief.md, CHARTER.md, ideas/05-chronicle.md.
All code is illustrative only. It is not a syntax decision.

## 1. The idea in three sentences

Plain data is immutable, reference-counted values. A value can only point at older values, so the value heap is a DAG and plain RC frees all of it, with in-place updates whenever a value has only one holder (Perceus/Koka style). Things with identity (`class` objects) live in an explicit parent-owns-child "world tree". Everyone else reaches them through uncounted, generation-checked links, and `remove` is staged to the end of the current event-loop "turn". A void callback whose captured object has died is skipped. Cross-thread mutation is done only by `send`-ing a message to the object's home thread, and memory shared across threads is reclaimed by epochs.

## 2. Prior art: what is new and what is a recombination

Almost every part already exists. The novelty is in how they are put together.

| Chronicle part | Existing equivalent |
|---|---|
| Immutable RC values, in-place reuse when unique, no cycle collector | Koka/Lean 4 Perceus (https://www.microsoft.com/en-us/research/publication/perceus-garbage-free-reference-counting-with-reuse/), and O2/O3 mutable value semantics with CoW |
| "Identity is a name for a succession of immutable values"; snapshots stay valid | Clojure's epochal time model (https://www.infoq.com/presentations/are-we-there-yet-rich-hickey) |
| Parent owns children, a cascading delete of the subtree | Qt QObject trees (https://doc.qt.io/qt-5.8/qobject.html), Godot scene tree |
| Staged destroy that takes effect after the current frame | Unity `Object.Destroy` (https://docs.unity3d.com/ScriptReference/Object.Destroy.html), Godot `queue_free` + `is_instance_valid` (https://coddy.tech/docs/gdscript/null-and-is-instance-valid), ObjC autorelease pools drained per run-loop turn |
| Generation-checked non-owning links | O6 (Vale) and slot maps, both already covered |
| Callback skipped when its target dies | Qt auto-disconnects a connection when the receiver is destroyed (same Qt doc) |
| Home-thread objects + mailboxes | Actors (Erlang, Pony) |
| Epoch reclamation | crossbeam-epoch, RCU |

The value half is O3 without its opt-in RC type. The object half is O6, with the owner being a tree location instead of a variable. What is actually new:
- (i) Using turn-staged removal as a soundness argument that lets generation checks be hoisted across a whole turn.
- (ii) Making "callback auto-skips" a language rule rather than a framework feature.
- (iii) Treating "pointers point to the past" as the explicit invariant that rules out cycles.

This is a carefully designed composition of Qt/Godot, Koka and Clojure. Each piece is known to work. The composition itself is new.

## 3. Soundness: counterexamples

**C1. A cross-thread "publish" race. This is a real hole in the spec as written.** "Published" status is set by the *reader* the first time it reads. Until then, the home thread mutates `state` in place and uses non-atomic RC.
```
// thread A (home of doc)               // thread B
doc.items.append(x)  // unique: in place  let s = doc.items   // first foreign read:
                     // non-atomic RC--   //   mark published, RC++ (non-atomic?)
```
B can see a half-written RRB tail. A's non-atomic decrement and B's increment can lose an update, which leads to use-after-free. Marking the state transitively atomic while A is still using it also races. Two fixes exist:
- Publication is a handshake: B asks A to publish and waits until A reaches a turn boundary. Reads then block for up to a turn, which runs into C3.
- The *sender* marks values as shared, as Koka does. Then foreign reads of objects are no longer free.

Either fix works. The design needs one before the safety claim holds.

**C2. A silent skip drops important side effects.** The skip rule checks every *directly* captured link, including ones that are incidental to the main work.
```
fun upload() {
  let bar = ProgressBar() in window
  net.put(doc.bytes, onDone = { bar.hide(); self.markSaved() })
}
// user closes the progress window -> bar removed -> onDone skipped
// -> doc never marked saved; no trap, no log
```
`{ if verbose { debugPanel.log() }; self.save() }` has the same problem. Changing the closure to return `Bool` turns the skip into a trap. A link reached *through* a captured value (a `List` of links) is not pre-checked, so that case traps partway through the callback. So whether a callback skips, traps or partly runs depends on how you captured something and on its return type.

**C3. Blocking inside a turn deadlocks.** The mailbox is drained only between turns.
```
let stats = Stats()                 // home: main
let t = spawn { send stats.add(1); while stats.total == 0 {} }
t.join()                            // main blocked inside one turn -> never drains -> deadlock
```
The same holds for any synchronous wait on a worker that needs the waiter's objects to change. Example (f) has a related bug. Its final `print(stats.total)` reads a snapshot before any `send` has been applied, so it prints a value that depends on timing (usually 0). The model gives no join-then-drain rule.

**C4. A stalled epoch makes memory grow without bound.** One thread blocked in `socket.read()` for an hour never announces an epoch. Every write to a published object on any other thread retires a state that cannot be reclaimed. This is the classic problem with epoch-based reclamation (EBR). It is fixable: blocking syscalls announce quiescence, as in RCU's extended quiescent states. It must be specified, or long-running servers leak.

**C5. Lifetime is decided by which object's method ran the constructor.** Rule 4 places a new object under `self` of the method that constructs it.
```
let p = JsonParser() in turn
self.doc = p.parse(text)      // Doc() constructed inside parse -> child of p
// end of turn: p removed, and its child doc with it
self.doc.title                // next turn: trap
```
The fix is `move d to self`, and the user must know to write it. The reverse is a leak. `class Server { fun handle(r) { let tmp = Scratch() ... } }` adds one object under `Server` per request, forever. The default placement leaks, and putting objects in other places causes action at a distance. In effect, object lifetime is **manual** (`remove`) behind a safety net.

**C6. Generation wraparound.** A 24-bit generation wraps after 16M reuses of one slot. A churny slot reused 10k times a second wraps in about 28 minutes. A stale link then resolves to a different live object. `classId` catches a different class, but not the same class. Fix: retire a slot when its generation saturates, as Vale does. With 8 thread bits, the limit is 256 threads.

**C7. Turn boundaries change when you refactor.** "Each iteration of a loop in `main` or a thread body is a turn." Move that loop into a helper function and removal timing and mailbox draining both change.

**C8. Snapshot surprise.** `var xs = self.items; xs.append(x)` silently changes nothing on `self`. This is the Swift struct footgun, applied to every field read.

Things that hold up. I could not break the acyclicity invariant. Self-append, CoW and reuse all preserve "points to the past", for the same reasons they do in Koka and Lean. Staged removal does make a link that resolved once valid for the rest of a single-threaded turn. It does *not* hold for links into a foreign thread, whose turns end on their own schedule. Those links are memory-safe only because of EBR, so the hoisting optimisation must not apply to them.

## 4. Scenarios

| | Verdict |
|---|---|
| (a) | **Works.** Unique value with in-place appends is as fast as a `Vec`, a proven technique. |
| (b) | **Works well.** The world tree is the data tree, and parent links are free. `parent` is untyped, so you need an `is` check. |
| (c) | **Works, best in class for the simple case.** No `[weak self]`, and destroying an object inside its own callback is safe. Undermined by C2's silent-skip semantics. |
| (d) | **Works.** Snapshot reads survive eviction. The cache object itself still has to be explicitly owned and removed. |
| (e) | **Works,** with `x = f(x)` handover. The cost of keeping the old version is visible in the profiler but not in the source. |
| (f) | **Partly hand-waves.** Value sharing is fine. The example's final read is racy (C3), the publish protocol is unsound as specified (C1), and there is no parallel in-place mutation. |

## 5. Gates

- **G2: pass.** Nothing traces the heap. Freeing happens at the last RC drop or at turn-end removal, and the work is bounded by what is being freed. Epoch reclamation is deferred freeing, not a collection. C4 must be addressed, but that is a memory-bound problem, not a GC.
- **G3: needs-john,** for the same reason every option does: it depends on built-in `List`/`Map`. Otherwise it passes. `in`, `in turn`, `move … to`, `remove`, `send` and `.alive` are keywords and operations, not annotations. Because `parent` is untyped and lists hold untyped links, expect a lot of `is` narrowing if there are no generics.

## 6. Scores

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 3 | No borrows or lifetimes, but about 10 rules and two semantic worlds. The user must also learn placement defaults, staged removal, what counts as a turn, skip vs trap, frozen captures and async-only `send`. That is more than ARC's "refs + weak". |
| Memory safety | 15 | 4 | The design intent is fully safe: dead links trap, nothing is undefined behaviour, and there are no data races. Lost a point because C1 and C6 are holes as specified and object leaks are the default. |
| Expressiveness (b,c,d, OO, G11) | 15 | 4 | (b) and (c) are excellent and implicit `self` is natural. G11 pays a tax because captured locals are frozen, and C2/C8 make the semantics surprising. |
| Implementation risk (AI-written, LLVM) | 15 | 2 | Perceus dup/drop and reuse analysis, RRB, HAMT, slot tables, a runtime that owns the tree, a turn/event-loop runtime as part of the language, mailboxes, EBR, and a publish protocol. The concurrency parts are where subtle bugs live. This is the most runtime-heavy proposal against the rubric. |
| Performance & predictability | 10 | 3 | Fast when values are unique and checks are hoisted. The uniqueness cliffs are invisible in the source. A published object loses in-place updates permanently, and the first publish marks the state atomic in O(n). Persistent structures are slower than flat arrays once shared. |
| Concurrency fit | 10 | 4 | Immutable values plus home-thread objects is a strong, race-free model, close to Pony/Erlang. Points lost for C1, C3 and C4, and for having no synchronous or parallel-mutation story. |
| Tooling, debug & C FFI | 10 | 4 | Debugging is outstanding: a live world-tree view, history ring buffers, and traps that name who removed an object. FFI is weaker. Values are RC'd persistent nodes, so C sees pinned pointers only for the length of a call, and only `Bytes` is flat. |

Arithmetic:
- Simplicity: 25×3 = 75
- Memory safety: 15×4 = 60
- Expressiveness: 15×4 = 60
- Implementation risk: 15×2 = 30
- Performance: 10×3 = 30
- Concurrency: 10×4 = 40
- Tooling: 10×4 = 40

Sum = 335, so the total is 335/5 = **67**.

That is 16 below O1 (83) and 15 below O4 (82), and roughly level with O2 (67). Chronicle beats O1 on scenario (c), concurrency and debugging. It loses heavily on simplicity, because it has two worlds plus turns, and on implementation risk. Those are the two criteria that together carry 40% of the weight.

## 7. Fatal flaw and salvageable kernel

**Closest thing to a fatal flaw:** object lifetime is manual. Chronicle replaces ARC's one burden (`weak` for back-edges) with explicit `remove`, or careful placement, for *every* identity object. Leaks are the default (C5), and placement causes action at a distance. The brief warns that manual schemes are simple to specify but unsafe. Chronicle makes the manual part safe, but it is still manual. It also pays for this with the largest runtime of any option. No single flaw kills it. It loses because the costs add up, and none of them buys a win over O1 or O4 on the heavily weighted criteria.

**Kernel worth stealing, into O1 (or O4's `shared` kind):**
1. **Turn-deferred destruction.** In ARC, run deinit at the end of the event-loop turn when an object's count drops to zero inside a callback (an autorelease-pool-style drain). This makes "destroy self in my own `onTap`" safe, and it is cheap to implement.
2. **Callbacks that do not keep their receiver alive.** For void closures stored into an object field, capture `self` as a non-owning reference, and make the call a no-op if `self` is gone. This is Qt-style auto-disconnect, and it removes `[weak self]` for (c). To avoid C2, apply it **only to `self`**, not to every captured link. Traps should log, and skips should be visible in debug builds.
3. **Debug tooling.** Add an ownership-graph inspector and "who freed this, in which turn" provenance on traps for O1's weak and dead references.

## 8. Verdict

**Kernel worth stealing.** It is not a contender, because it has more concepts than O1 and the highest implementation risk. It is not a dead end either, because turn-staged destruction plus non-owning callback capture of `self` addresses scenario (c) better than O1's `[weak self]`.
