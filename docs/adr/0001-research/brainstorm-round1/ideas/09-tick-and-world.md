# 09 — Tick & World

## 1. Name

**Tick & World**: memory that is either *this tick's scratch* or *owned in the world's scene tree*.

## 2. Inspiration

Game engines have dealt with non-nested lifetimes for decades without GC pauses. They do it with four habits:

- **Per-frame allocators.** Temporary memory is bump-allocated and thrown away in one reset at the end of every frame. Nobody frees anything individually.
- **The scene graph.** Anything that lives longer is an entity in a tree. Every node has exactly one parent. Destroying a node destroys its subtree. Ownership is visible in the editor's hierarchy panel.
- **Deferred destruction.** In Unity, `Destroy(obj)` takes effect *at the end of the frame*. Everything you touched this frame stays valid until the frame is over.
- **Handles, not pointers.** Entities refer to each other by ID. A dead ID is detectable, not a dangling pointer.

A fifth habit comes for free: **save games**. Because the persistent world is just entity records plus IDs, it can be serialised.

The mapping is direct. Every unit of program work (an event, a request, a `main`) is a **tick**. Each tick has a **frame** of scratch memory. State that must outlive the tick lives in the **world**, as entities in an ownership tree. Neither side ever frees memory mid-tick.

## 3. Pitch

Inside a tick the language feels like Python or Java. Every value is a reference, you can alias freely, and cycles are fine. There are no ownership or borrowing rules, because nothing is freed until the tick ends and then the whole frame is reset in O(1). To keep data past the tick, you store it in an entity. Storing data into the world **copies** it, so the world never points into a frame. Entities form a scene tree, where each has one owner and `despawn` removes a subtree at the end of the tick. Everything that isn't the parent link is an ID. There is no reference counting, no borrow checker, no `weak`, and no tracing. Cycles cannot leak, because ownership is a tree by construction and every other link is a non-owning ID. UI callbacks capture entities by ID and are silently skipped if their target has died. Parallel jobs see a frozen world and queue their writes as commands, which are applied in order at join. And the whole world can be saved, restored, diffed and replayed, because it is just records and IDs.

## 4. The rules

Core rules (every programmer):

1. **Two places.** A value lives either in the **frame** (this tick's scratch) or in the **world** (inside an entity).
2. **Ticks.** `main`, every event handler and every `update()` call runs as one tick. Everything allocated during a tick is freed all at once when the tick ends.
3. **Within a tick, data is shared.** Assigning or passing a value never copies it. Any shape is allowed, including cycles.
4. **The world keeps copies.** Storing data into an entity field copies it. World data is a tree, so storing cyclic data there is a runtime error; use entities for graphs.
5. **Entities.** An `entity` type's instances live in the world and are referred to by ID. Methods have an implicit `self`. Reading an entity's field gives you a reference that is valid for the rest of the tick.
6. **Every entity has one owner.** `spawn T in owner` creates the entity. The default owner is `self`, or the app root inside `main`. `parent` is built in, and an entity's ancestors are always alive.
7. **`despawn e`** removes `e` and all its descendants *at the end of the tick*. Until then, everything still works.
8. **Stale IDs trap.** Using a dead entity through any link other than `parent` is a clean runtime error. Use `e.alive` to test first.
9. **Kept closures.** A closure stored in the world captures entities by ID and data by copy. If any entity it captured is dead when it fires, it is skipped.
10. **`update()`.** An entity with an `update()` method gets it called once per tick. This is how long-running work spans ticks. The program exits when the root entity is despawned, or when no events, updates or background jobs remain.

Advanced rules (most code never needs them):

11. **`frame { … }`** resets scratch early. A value that flows out of the block is copied out. This is rule 4 generalised: *storing into something older copies*.
12. **`parallel`.** Inside a parallel body the world is read-only. Use `later <stmt>` to queue a write; queued writes are applied at join in job order. Results are copied back to the caller.
13. **`background { … }` + `send e, msg`.** A background job can span ticks. It sees only copies, and it talks back by message. A message is delivered to `e` as an event and dropped if `e` is dead.
14. **`on despawn`** runs cleanup for external resources such as files, sockets and C handles.

That is 10 core rules and 4 advanced ones. There is no `weak`, `unowned`, lifetime, borrow, `inout`, `move`, `Rc`, lock or capture list.

## 5. Under the hood

**Frame arenas.** Each thread has a chunked bump allocator. Chunks are 2^k-aligned and start with a header that records the chunk's **depth**: immortal = -1, world = 0, tick = 1, nested `frame{}` = 2 and up. Objects larger than about 4 KB, such as a list's buffer, are allocated out of line and recorded in the arena's large-object list. That lets a growing list `realloc` for real, and a bake can *move* the buffer instead of copying it. At tick end the runtime runs any resource destructors registered in the frame, frees the large objects and rewinds the chunks.

**Store barrier.** Every store of a pointer into a heap object does the same check. It finds the destination's depth by masking the address and reading the chunk header. If `depth(dst) == 0`, or `depth(dst) < depth(val)`, it **bakes** the value. Otherwise it stores the pointer as is. The compiler elides the check where it can prove the outcome. Stores into a local are always plain pointers. Stores into an entity field always bake. Storing a fresh allocation into a same-frame object is a plain store.

**Bake.** The compiler generates a copy routine for each type. This is internal to the compiler and visible to no one, so it needs no templates (G3). The routine copies data recursively. IDs and immortal data such as string literals are copied as plain words. When the destination is the world, the copy is tree-shaped: shared sub-nodes are duplicated, and a node revisited while still on the copy stack is a cycle, which traps. If a source buffer is out of line and this is its last use (from liveness analysis), the buffer is transferred rather than copied.

**World storage.** Each entity type has a table, which is a slot map of generation plus record, in SoA or AoS layout. Each record holds `parent`, `firstChild` and `nextSibling` IDs plus the fields. World data is tree-owned, malloc'd from size-class slabs whose chunk headers say depth 0, and freed by compiler-generated destroy routines. `for e in all Editor` iterates a table directly, which gives ECS-style cache behaviour for systems.

**Graveyard.** Nothing in the world is freed mid-tick. A despawned entity, or world data that has been overwritten, goes on a per-thread graveyard list. Tick end runs in this order: the body finishes, `on despawn` hooks run (each in a mini-frame), generations are bumped, the graveyard is freed, and finally the frame is reset. This ordering is why a frame reference into the world is always valid without borrow checking.

**ID deref.** An ID is a (slot, generation) pair. Deref is a table index plus a generation compare. On a mismatch it traps with provenance, for example `Cache#12 despawned at tick 381 by Window.close`. Derefs of `parent` and of `self` skip the check, because a parent always outlives its children and the dispatcher only calls methods on live entities.

**Closures.** A closure that stays in the frame is a function pointer plus a pointer to its frame environment, which is free. A closure stored in the world is baked: its environment holds copies plus a compiler-known list of captured ID slots. At invocation the runtime checks that those IDs are alive, then opens a tick and calls the closure.

**Event loop.** The runtime owns a queue. Each input event, timer, message or `update` pass becomes one tick. Frame high-water marks and entity counts per type are tracked for each tick.

**Threads.** Every worker has its own arena. While a `parallel` block runs, the main thread waits and a world-frozen flag is set. The store barrier already reads depth, so a write to depth 0 while frozen traps; the compiler rejects such writes statically where it can see them. Each `later` statement goes into a per-job command buffer, and its environment is baked into the caller's frame at join. The buffers are replayed in job index order, which makes the result deterministic. A background job runs on its own thread with a private tick arena it resets itself, via `frame{}`. `send` bakes the message into a malloc'd mailbox. There are no atomics or refcounts anywhere on the hot path.

**Save, debug and FFI.** The world is records plus IDs, so `save(subtree)` and `load` are generic runtime functions. They enable hot reload, undo snapshots, deterministic replay of the event log and "rewind to tick N" in the debugger. The debugger shows a hierarchy view of the live world. A pointer passed to C is valid until tick end; C must not keep it. A resource owned by C is wrapped in an entity with `on despawn`.

## 6. Scenarios

*All code is illustrative only — not a syntax decision.*

### (a) Read a file into a growing list

```
fun main() {                                  // one tick
  let lines = []                              // frame data, bump-allocated
  for line in File.open("in.txt").lines() { lines.push(line) }
  print(lines.count)
  app.log.lines = lines                       // only if it must outlive the tick: baked (buffer moved, last use)
}                                             // tick ends: frame rewound in O(1)
```

The list's buffer becomes large and moves out of line, so growth is a real `realloc`. The strings are bump-allocated. Nothing is freed one at a time.

### (b) Tree with parent pointers

```
entity Node { name: String }
let root = spawn Node(name: "root")
let kid  = spawn Node(name: "kid") in root
print(kid.parent.name)       // always valid: a parent outlives its children
for c in root.children { … } // built-in
despawn root                 // root and kid both gone at tick end
```

The scene tree *is* the language's ownership tree, so parent pointers cost nothing and cannot dangle. A throwaway tree inside a tick can also be plain frame data: `struct T { parent: T?, kids: [T] }`. Cycles are harmless there. You only need entities if the tree must persist.

### (c) UI callback capturing enclosing state (the crux)

```
entity Editor {
  doc: Document
  dirty: Bool
  fun build() {
    let save = spawn Button(label: "Save")             // owner = self (the editor)
    save.onTap = { self.save(); self.dirty = false }   // baked into the world: self captured as an ID
    toolbar.add({ self.save() })                       // toolbar NOT owned by the editor
  }
  fun save() { File.write(doc.path, doc.text) }
}
```

A tap opens a tick. The closure runs, mutates the editor directly and is done. The editor owns the button and the button holds only the editor's ID, so there is no cycle and nothing to mark `weak`. When the editor is despawned its button dies with it. The toolbar closure outlives the editor; the next time it fires, its captured `self` is dead, so it is skipped, with no crash and no zombie save. Captured *data*, such as a string, is copied when the closure is stored, so it cannot dangle into a dead frame.

### (d) Shared mutable cache used by two components

```
entity App {
  fun start() {
    let c = spawn Cache in self
    spawn Gallery(cache: c) in self
    spawn Thumbs(cache: c) in self
  }
}
entity Cache { images: [String: Image] }
entity Gallery {
  cache: Cache                                         // an ID, not ownership
  fun show(url: String) {
    let img = cache.images[url] ?? decode(fetch(url))  // a hit is a reference into the world: no copy
    cache.images[url] = img                            // a miss is baked in (big buffer moved)
    draw(img)
  }
}
```

The cache is owned once, by the app, and both components hold IDs to it. Reads hand back world references that are valid for the whole tick, even if something evicts the entry mid-tick, because of the graveyard. There is no RC, no lock and no `shared` kind.

### (e) Pass a large list to a function that mutates it

```
fun normalize(xs: [Float]) { let m = max(xs); for i in 0..xs.count { xs[i] /= m } }
let s = readSamples()
normalize(s)                       // frame data, by reference, in place
normalize(app.recording.samples)   // world data, by reference, in place: floats are not pointers, so no bake
```

There is no `inout`, `&mut` or `sink`. Everything is by reference. This is safe because nothing can be freed underneath the call.

### (f) Sharing data between threads

```
let total = parallel map samples.chunks(8) { sum(it) }     // jobs read frame and world (frozen)
                                                           // results baked into the caller's frame
parallel for e in all Particle { later e.pos += e.vel }    // writes queued, applied at join in order
background {                                               // spans ticks; sees only copies
  let data = download(url)
  send gallery, Loaded(data)                               // delivered as a future tick event
}
entity Gallery { on Loaded(d) { self.pending = d } }
```

Inside a tick, sharing means read-only fan-out over a frozen world, with deterministic commands for writes. Across ticks, it means copy-in and message-out. Data races are impossible, and so are locks.

## 7. Genuinely new vs. the covered options

- **Time, not scope, as the lifetime axis.** "Scope-bound regions" are lexical and leak through `promote`. Here the region is the *tick*, a dynamic unit of work. Anything promoted goes into an explicitly owned scene tree with deterministic `despawn`, not into a global heap that leaks.
- **Unconstrained aliasing inside a tick.** Making *all* world frees deferred, as in Unity's `Destroy` but applied to every byte, makes frame-to-world references safe without borrow checking (O4/O5), counting (O1/O7) or generation checks on ordinary data (O6). Only entity IDs carry generations.
- **A copy-on-cross store barrier keyed on arena depth, read from the address.** It is one mechanism for world commits, nested frames, thread joins and messages.
- **The ownership tree is the scene graph.** Parent links are guaranteed alive, every other link is an ID, and so cycle leaks are impossible by construction. This is not "slot maps as a library": it is the language's only long-lived ownership form, with tree despawn, automatic dead-callback skipping and built-in hierarchy tooling.
- **Callback liveness semantics (rule 9).** This answers (c) with no `weak`, `unowned` or capture lists.
- **Frozen-world fork-join with ordered command buffers.** This is ECS system scheduling as the concurrency model.
- **Save/replay/rewind falls out of the memory model**, which helps G8.

## 8. Known weaknesses

- **Two behaviours for assignment.** Data is shared in the frame but copied into the world. "I mutated `x`, why didn't `editor.doc` change?" is the same surprise as Swift's struct versus class, and it is the biggest learnability cost.
- **Hidden copies.** Assigning to an entity field can be O(n). The move-on-last-use optimisation helps big buffers, but not deep trees of small objects.
- **Long ticks hurt.** A tick that runs for minutes piles up scratch and graveyard memory. Scripts must split work into `update()` steps or `frame{}` blocks, which imposes an event-loop or game-loop structure that CLI and library authors may find alien.
- **Stale IDs are runtime traps, not compile errors.** Memory safety is preserved, but logic errors surface late, as with O6.
- **Kept data must be acyclic.** Graph-shaped persistent data has to become entities, which are heavier and need ID derefs.
- **The barrier costs on every heap pointer store.** Expect a few percent, and C code that writes pointers into language objects bypasses the barrier, which is an FFI hazard.
- **Peak memory rises within a tick**, because nothing is reclaimed until the end.
- **Concurrency is narrow.** Only fork-join and message passing are supported. There is no long-lived shared mutable state across threads, which is good for safety but limiting for some servers.
- **G3 flag.** The model leans on built-in `[T]` and `[K: V]` containers and per-type bake and destroy routines generated by the compiler.
- **Implementation risk is moderate.** The pieces are each simple: bump arenas, slot maps, a barrier, generated copy routines and an event loop. But the interactions (barrier elision, move-on-bake, the graveyard ordering) need careful testing.
