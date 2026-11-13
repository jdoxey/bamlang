# 17 — Scenes and Call Sheets

## 1. Name

**Scenes and Call Sheets**: dynamic, overlapping regions ("scenes") that may reference each other only along a declared, acyclic call sheet. All freeing happens at the end of a "cue".

## 2. Inspiration

| Theatre | Memory |
|---|---|
| **Production** | The program. Its scene never closes (globals and the app root live here). |
| **Scene** | A runtime region. It is opened, it runs, and it is **struck**: everything in it is removed at once. Scenes overlap freely and do not have to nest (a session, a window, a request). |
| **Lead** | The actor a scene is opened around (the Window, the Session). The scene's handle is held through its lead. |
| **Actor** | A class instance. It has identity, can be referenced, and lives in exactly one scene. |
| **Prop** | A plain value (struct, String, List, Map). It is held by one owner and leaves when that owner lets go. |
| **Call sheet** | The list of *earlier* scenes that a scene may call on. Its actors may point at actors in those scenes. |
| **Waiting in the wings** | A struck scene that a still-running scene calls on. It stays alive until its last caller is struck. |
| **Cue** | One unit of action, such as an event dispatch or a loop iteration. Nothing leaves the stage in the middle of a cue. Strikes happen at the cue's end. |
| **Cast list** | Who is on stage right now: the actor references held in locals across a cue boundary. The stage manager checks it before striking anything. |
| **Understudy** | A reference that may outlive the scene of its target. When that scene is struck, the understudy stands in: the reference reads as empty. |

The real stage manager's insight is that you never track each prop's life individually. You track **which scene it belongs to**, and **which scenes depend on which**, and you only strike between cues.

## 3. Pitch

Every actor (class instance) is born into a scene, which by default is the scene of the `self` that creates it. Inside a scene, references are raw pointers: cycles, parent pointers and closures capturing `self` cost nothing and need no counting. Scenes are opened around a lead actor and can overlap arbitrarily. When a scene is opened, it gets a **call sheet** listing the already-existing scenes its actors may point into. Because you can only call scenes that exist before you, the dependency graph is a DAG by construction, so cycles between regions are impossible. A scene is struck when its move-only handle is dropped. If later scenes still call on it, it waits in the wings until they are struck too. That is reference counting per *scene*, never per object or pointer, and it changes only when a scene opens or closes. All frees are deferred to the end of the current **cue** (event dispatch or `cue {}` block). So inside a cue every reference is valid, with no checks at all. Only locals that span a cue are registered on a tiny per-thread cast list. Anything else, such as references "upward" to a younger scene or pointers into unrelated scenes, goes through an **understudy** reference, which empties when its scene is struck. There are no lifetimes, no annotations, no per-object counts and no tracing.

## 4. The rules

1. **Props and actors.** `struct`, `String`, `List`, `Map` and so on are *props*: plain values. Assigning one copies it, and the compiler turns last uses into moves. `class` instances are *actors*: they are referenced and have identity.
2. **Passing props.** A prop parameter is read-only by default. Write `edit` at both the declaration and the call site to let the callee mutate it in place. You may not pass the same variable as `edit` and also as another argument.
3. **Birth.** An actor is born into the scene of the `self` whose method creates it. A free function inherits its caller's scene. Use `new X() on s` to choose a different scene. Code outside any actor runs in the Production scene.
4. **Opening a scene.** `open Window(args)` creates a new scene with a new `Window` as its lead. It returns a **stage handle**, `stage Window`, which acts as a reference to the lead. Its call sheet defaults to the opener's scene. Write `calling [a, b]` to list other scenes instead. You can name only scenes that already exist.
5. **Handles are move-only.** A stage handle has exactly one owner. Assigning it moves it. When the handle is dropped (it goes out of scope, gets overwritten or removed from a list, or its owning scene is struck), its scene is **struck**.
6. **The reference rule.** An actor's fields, and props stored inside them, may point only to actors in its own scene, in scenes on its call sheet (transitively), or to the leads of stage handles it owns. Anything else is a "not on the call sheet" error. The compiler reports it when it can see it; otherwise the error is raised at runtime when the field is stored.
7. **Understudies.** `~T` is a reference that may point anywhere. You read it with `if let x = ref { ... }`. It becomes empty the moment its target's scene is struck.
8. **Closures are actors.** A closure is born in the scene of the `self` that wrote it. Rule 6 applies to whatever it captures.
9. **Curtain.** Nothing reachable through an actor or a stage is freed before the end of the current cue. Each event-loop dispatch and each thread entry is a cue. In a long-running loop, write `cue { ... }`. Props held in locals are freed immediately as normal.
10. **Struck scenes wait in the wings.** A struck scene stays in memory while a running scene calls on it, or while a local on the cast list still points into it. It is freed at the first cue end after both are gone.
11. **Threads.** A scene belongs to one thread. Three operations cross threads:
    - `send s to t` moves a whole scene to thread `t`. It is allowed only if nothing calls on `s`.
    - `freeze s` makes the scene read-only and callable from any thread.
    - A `guarded` scene can be touched only inside `backstage s { ... }`, which takes its lock. Only props (never actors) may leave that block.

That is eleven rules. In single-threaded code, rules 1–9 cover nearly everything. Rules 10–11 explain what you observe.

## 5. Under the hood

- **Scene allocator.** Each scene is a chain of 64 KiB-aligned chunks with bump allocation. A chunk header points to its `Scene` record, so `scene_of(p)` is `*(p & ~0xFFFF)`. A `Scene` record holds:
  - its id and a generation (used by understudies);
  - its reach set, a sorted array of scene ids: its own call sheet plus the closure of that sheet's reach sets, computed once when the scene opens;
  - a caller count, owner thread, state flags (running, struck, frozen, guarded), and a list of the stage handles it owns.
- **Store check (rule 6).** The check runs on actor-field stores. The compiler proves "same scene" in the common cases (`self.x = new X()`, `child.parent = self`, a closure capturing `self`) and emits no check. Otherwise it emits a lookup of `scene_of(b)` in `reach(scene_of(a))`, with a one-entry cache because the answer is nearly always yes. Lists that hold actors keep a small summary of their elements' scenes, so storing a list into a field checks the summary, not every element.
- **Strike.** Dropping a handle marks the scene struck: its generation goes up, so understudies empty, and it is queued on the thread's curtain list. It also decrements the caller count of every scene on its call sheet.
- **Cue end.** This happens only at the end of the *outermost* cue on the thread:
  1. The runtime reads the cast list (a shadow stack, described below).
  2. A struck scene with a caller count of 0 and no cast-list pointer into it is freed. The runtime walks its chunks linearly, using per-actor type headers, to drop each actor's prop fields (String and List buffers are malloc'd), then releases the chunks.
  3. Freeing a scene cascades to the stage handles it owned, and decrements the callers of the scenes it called.
  4. Prop buffers that were replaced during the cue are freed from a deferred list at the same point.

  The work is proportional to what is being freed. No live object is ever traversed.
- **Cast list.** The compiler infers a `may-cue` property for each function. A function has it if it contains `cue`, runs an event loop, or calls something that has it. Indirect calls and C callbacks are assumed to have it. No annotation is involved. Any actor-typed local, or prop-containing-actors local, that is live across a may-cue call is pushed onto a per-thread shadow stack and popped afterwards. These are typically a handful of slots in `main` and the run loop.
- **Understudy layout.** An understudy is `(ptr, scene id, generation)`. Reading one compares the generation stored in the scene table. A successful read produces an ordinary local, which is safe for the rest of the cue by rule 9.
- **Threads.** `send` is deferred to the cue end like strike, so the same cast-list check guarantees the sending thread keeps no locals into the scene. `freeze` sets a flag that the store check enforces. `backstage` is a mutex plus a compile-time type check that the block's result type contains no actor references. Caller counts are atomic only for frozen and guarded scenes.
- **Debugging.** Every actor can report "scene: Window#12, opened at editor.x:40". The debugger can list scenes with their call sheets, sizes and whether they are waiting in the wings, which also serves as a leak inspector.

## 6. Scenarios

*All code is illustrative only — not a syntax decision.*

### (a) File into a growing list of lines

```
func readLines(path: String) -> List<String>
  var lines = List<String>()
  for line in File.open(path).lines()
    lines.add(line)          // prop: grows, old buffer freed immediately (a local, not behind an actor)
  return lines               // moved out
```

No scenes are involved. Props behave like simple owned values. If `lines` were a field of an actor, each superseded buffer would be freed at the cue end instead (rule 9). Under geometric growth, the waste is bounded by about 2×.

### (b) Tree with parent pointers

```
class Node
  var name: String
  var parent: Node?
  var kids = List<Node>()
  func addChild(name: String) -> Node
    let k = new Node(name)   // born in self's scene
    k.parent = self          // same scene, proven statically: no check, no count
    kids.add(k)
    return k
```

The cycle (parent ↔ child) costs nothing. The whole tree goes away when its scene is struck. However, a subtree removed with `kids.remove(i)` stays in memory until then (see weaknesses).

### (c) UI callback capturing self: the crux

```
class App
  var windows = List<stage Editor>()
  func newDocument()
    windows.add(open Editor())                 // new scene; calls App's scene by default
  func closed(i: Int)
    windows.remove(i)                          // handle dropped → scene struck at cue end

class Editor
  var text = ""
  var dirty = false
  func build()
    let save = new Button("Save")              // born in Editor's scene
    save.onTap = { self.save(); self.dirty = false }  // closure born here, captures self: same scene
    app.menu.saveAll.listen({ self.save() })   // App's Signal stores an understudy to this closure
  func save() { ... }
```

- **Editor → button → closure → editor is a cycle inside one scene.** It is fine, with no `weak` and no `[unowned self]`.
- **The callback outlives the scope that registered it, but not the scene.** It lives exactly as long as the window, which is the lifetime the programmer had in mind and now states once, at `open`.
- **App-wide listeners.** App's scene is older and cannot call the Editor scene, so its built-in `Signal` holds listeners as understudies. Closing a window empties the listener, and `saveAll` skips it silently.
- **Mid-event closes.** If a tap closes the window, the strike waits for the end of the event. The closure that is currently running cannot be pulled out from under itself.

### (d) Shared mutable cache used by two components

```
class App
  var cache: stage Cache
  var search: stage SearchPane
  var preview: stage PreviewPane
  func start()
    cache   = open Cache(limit: 500)
    search  = open SearchPane() calling [cache]
    preview = open PreviewPane() calling [cache]
    // both panes may hold plain refs to cache actors in their fields
```

Both panes store plain pointers to the cache and its actors, and the stores are checked against their reach sets. If App drops `cache` first, the cache waits in the wings until both panes are struck. Evicted cache entries are props (keys and bytes) and are freed at the cue end.

### (e) Large list mutated by a function

```
func normalise(edit xs: List<Float>)
  let m = xs.max()
  for i in 0..xs.count  xs[i] = xs[i] / m

normalise(edit samples)        // no copy; samples can't also be passed as another argument
```

This is in-place and costs one pointer. If `samples` lives inside an actor, any reallocation's old buffer is deferred to the cue end. So a read elsewhere through another path to the same actor is still memory-safe within the cue.

### (f) Sharing data between threads

```
let cfg = open Config(load("app.toml"))  calling []
freeze cfg                                     // any thread may now read cfg's actors

let job = open Batch(cfg) calling [cfg]
job.fill(rows)
send job to worker                             // whole scene moves; this thread keeps no refs

let stats = open guarded Stats()
worker.run({ backstage stats { stats.count += 1 } })
let n = backstage stats { stats.count }        // only a prop (Int) leaves the block
```

The ownership unit for threads is a whole scene, not an object. Moving a scene is just changing its owner field. Frozen scenes need no locks. Guarded scenes are monitors.

## 7. What's genuinely new compared with the covered options

1. **Region dependency is declared as an acyclic call sheet, fixed when the scene opens.** Cyclic regions are impossible by construction, because you can only list scenes that already exist.
   - Scope-bound regions are lexical and must `promote`; scenes are dynamic, overlap and never promote.
   - Region inference infers its regions; here the programmer states each scene's lifetime once, at `open`.
   - Arenas offer no cross-region safety; scenes check every cross-scene store against the call sheet.
2. **Counting at scene granularity only.** The caller count changes when scenes open and strike, never on a pointer copy. This is much cheaper and rarer than ARC (O1/O7), and closures capturing `self` produce no cycles to break.
3. **Cue-quiescent freeing is the safety mechanism, not just a speed trick.** Because nothing reachable through actors dies mid-cue, within-cue references need no generation checks (unlike O6 Vale/Inko) and no borrow rules (unlike O4/O5). Safety across cues comes from a tiny inferred cast list, not from tracing.
4. **Understudy references at scene granularity, and Signals that drop dead listeners.** This turns the "callback outlives its registrar" problem into a standard library type.
5. **Implicit self decides the birth scene.** OO code and the memory model point the same way (P-PY, G11): an actor's helpers are born where the actor lives.

## 8. Known weaknesses

- **Garbage within a scene.** Actors unlinked inside a long-lived scene (a deleted subtree, a replaced actor field) are not freed until the scene is struck. A long-running document scene leaks with the edit history. The mitigations are:
  - Make churn-heavy data props rather than actors.
  - Split it into sub-scenes, though a parent can then reach those children only through stage handles or understudies, which is clunky.
  - An optional `restage(s, root)`, which copies what is reachable from `root` into a fresh scene and strikes the old one. That is programmer-triggered copying of one scene, so it is **needs-john on G2**.
- **Runtime errors for rule 6.** When the compiler can't see both scenes, "not on the call sheet" is raised at runtime, like a bounds error, rather than at compile time.
- **Direction surprises.** Older scenes can't point into younger ones except through their own stage handles or through understudies. Allocating in the wrong `self`, for example a long-lived server's method building per-request actors, silently leaks into the long-lived scene until the programmer moves that work into the request's own actor, or writes `on`.
- **Forgetting cues.** Batch programs without `cue {}` in their main loop never free anything reachable through actors until exit. A lint ("loop allocates actors, no cue") helps.
- **Inferring `may-cue`.** It has to be inferred across modules and C callbacks. Being conservative grows the cast list, and the FFI needs `pin` for pointers that C keeps across cues.
- **Reach-set cost.** It grows with deep call sheets and thousands of live scenes (one per session), so a reach-set representation needs care.
- **Built-in parameterised types.** `List<T>`, `stage T` and `~T` are compiler-known parameterised types, which is the G3 pending question.
- **Self-assessed score: about 70.** Simplicity 3, safety 4, expressiveness 4, implementation risk 3, performance 4, concurrency 4, tooling 3.
