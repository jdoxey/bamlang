# 10 — Supervised Homes (homes, leases and links)

## 1. Name

**Supervised Homes.** Memory is split into *homes*, single-threaded heaps that work like Erlang
processes. They are reached through *leases* and arranged in a supervision tree. Closures *link*
back to the home they were written in.

## 2. Inspiration — how the lens maps onto memory

| Distributed-systems idea | Memory meaning |
|---|---|
| Actor / Erlang process / shard | A **home**: a private heap plus a mailbox. Each object lives in exactly one home. |
| Process death frees its heap at once | **Stopping a home frees its whole heap**, cycles included, in one deterministic step. |
| Supervision tree (OTP) | Homes form a tree. A stopping home stops its children first. A crashed home is reported to its supervisor. |
| Pid with an incarnation number | A **lease** (`far T`) holds a home id that is never reused. A lease to a stopped home answers `down` and never dangles. |
| Copy-on-send messaging | Values that cross a home boundary are **copied**, or **moved** at no cost when the sender held the only reference. |
| Links and monitors | A closure handed to another home becomes a **callback lease** linked to its origin. When the origin dies, the callback is dead and gets pruned. |
| "Let it crash" | A crash means **dropping the heap**. Memory cleanup needs no unwinding. |
| Deadlock detection over a wait-for graph | Cycles of `ask` calls are detected and raised as an error. |

The key move: **the hard non-nesting lifetimes in the brief (sessions, windows, cache entries,
UI screens) are usually things that already have a lifecycle event**, such as close, logout,
evict or disconnect. So the programmer *names* each of these lifetimes by giving it a home and
stops the home on that event. Nothing is inferred and nothing is annotated. The lifetime is a
runtime object, like a process.

## 3. Pitch

A program is a tree of homes. Inside a home, everything feels like Python: objects reference
each other freely, cycles are fine, any reference can mutate, and the compiler adds cheap
**non-atomic** reference counting that frees most garbage promptly. Garbage that RC can't free
(cycles) lives at most as long as its home, and homes are cut to the lifetimes that matter: one
per window, session, connection, document or cache. Closing the window stops its home and frees
everything in one bump, including the editor↔button↔closure cycle that plagues ARC. Between
homes there are no references, only leases. You `ask` or `tell` a home to run a method, and
arguments and results are copied or moved. So data races are impossible by construction, and
"thread-safe" just means "in another home". A closure always runs in the home where it was
written, so capturing `self` is always safe. If `self`'s home is gone, the callback is silently
dead and never dangling.

## 4. The rules

1. **Every object lives in a home.** Code always runs inside some home, and `new` objects go
   into the current home. A program starts in the `main` home.
2. **Inside a home, references are free.** Share them, store them, form cycles, mutate through
   any of them. An object is freed when its last reference goes away, or when its home stops,
   whichever comes first.
3. **`spawn T(args)` makes a new home** whose root object is a new `T`, and returns a lease of
   type `far T`. The home that spawned it is its **supervisor**.
4. **A home stops** when someone calls `stop` on its lease, when its supervisor stops, or when it
   crashes. Stopping frees all of its memory at once, after its child homes have stopped.
   Resources it owns (files, sockets) are closed.
5. **Homes talk only through leases.** `ask h.m(args)` runs `m` in `h`'s home and waits for the
   result. `tell h.m(args)` queues it and doesn't wait. A home handles one call at a time.
6. **Whatever crosses a boundary is copied.** This covers arguments and results, including whole
   object graphs. If you held the only reference, the value is *moved* instead, which costs
   nothing. Leases themselves can be passed anywhere.
7. **A stopped home answers `down`.** Every `ask` needs an `else` branch, or the asking home
   crashes when it gets `down`. A `tell` to a stopped home is silently dropped.
8. **A closure runs in the home where it was written.** Passed to another home, it becomes a
   callback lease. Calling it is a `tell` back to its origin. Once the origin stops, the callback
   is dead, and event lists drop it on their own.
9. **A crashed child is reported to its supervisor** via `on child_down(child, reason)`. The
   supervisor can respawn the child, ignore the crash, or crash too. The default is to crash too.
10. **Homes may run on different threads, but one home never runs on two at once.** Threads
    share nothing else. If `ask` calls form a cycle (A waits on B, which waits on A), the call
    that closes the cycle gets a `deadlock` error.
11. *(Optional rule.)* `freeze x` makes a deeply immutable value that crosses boundaries without
    being copied. Frozen values are atomically counted.

Rules 1–8 are the everyday model. Rules 9–11 are only needed for crash recovery, threads, and
performance tuning.

## 5. Under the hood

- **Home record:** `{id: u64 (incarnation, never reused), heap, mailbox (MPSC queue), state
  idle|running|stopped, supervisor id, children, root, export table}`. The heap is a per-home
  size-class allocator (mimalloc-style). Stopping a home returns its pages wholesale. No object is
  visited and nothing is traced.
- **In-home RC:** plain non-atomic increments and decrements. The compiler internally applies
  Perceus/Lobster-style elision and borrow inference. Users never see it, and no type carries
  ownership information.
- **Lease = home id.** The global home table maps an id to a home in O(1), with an incarnation
  check. A stopped home or an unknown id gives `down`. Leases point at *homes*, not at objects,
  so there is no per-object generation tag and no per-object check.
- **`ask` fast path:** if the target is idle, a CAS (idle→running) lets the caller run the method
  inline on its own thread, like a function call. Otherwise the call is queued and the caller
  parks. Version 1 can block OS threads; version 2 can use per-home fibers. **`tell`** always
  queues.
- **Boundary copying:** the compiler generates a deep-copy routine for every class. The routine
  keeps internal sharing and cycles, using a visited map only when the graph contains objects.
  When the root's RC is 1 and the value is a buffer (List, String, Map), it moves. The move is a
  pointer handoff plus re-homing the allocation; per-home heaps allow cross-heap frees through a
  remote-free list, as mimalloc does.
- **Closures:** a closure that escapes to another home is stored in the origin's export table, and
  the other home gets `{origin id, slot}`. Calling it queues a message to the origin. The stdlib
  `Event` type skips and prunes dead callback leases when it fires.
- **Crashes:** a panic in a home longjmps back to the scheduler. The heap is freed wholesale, the
  supervisor gets a `child_down` message, and pending `ask`s against the home get `down`. No
  unwind tables are needed for memory safety.
- **Deadlock detection:** each parked home waits on exactly one home, so the runtime follows the
  wait-for chain when it parks a caller. The chain is short in practice.
- **Debug builds:** stopping a home reports any objects that RC never freed, grouped by class and
  allocation site. This flags "you have a cycle in a long-lived home" without collecting anything
  in release builds.
- **FFI:** C gets raw pointers into the current home's heap. Those pointers are valid until the
  home stops or the object's RC drops. Passing a pointer to C pins it with a +1 until C releases it.

## 6. Scenarios

All code is *illustrative only — not a syntax decision.*

**(a) Growing list of lines**
```
fn readLines(path) {
    lines = List()
    for line in File.open(path).lines() { lines.add(line) }
    return lines              // stays in the current home; RC frees it when unused
}
```
This is plain in-home code, with nothing to learn. If the result is sent to another home, it is
moved, because the sender holds the only reference.

**(b) Tree with parent pointers**
```
class Node { parent; children = List(); name
    fn add(child) { child.parent = self; children.add(child) }
    fn detach()   { parent.children.remove(self); parent = nil }   // stdlib Tree does this
}
doc = spawn Document()        // the whole tree lives in doc's home
```
Parent pointers are ordinary references, which creates cycles, and that is allowed. The usual
tree (a document, an AST, a scene) lives and dies with its home: `stop doc` frees all of it in one
step. A subtree detached inside a long-lived home is freed by RC if `detach` clears `parent`. If
it doesn't, the subtree leaks until the home stops, and the debug build reports it there. There
are no weak references to learn.

**(c) UI callback capturing `self` (the crux)**
```
class Editor { text; saveButton
    fn init() {
        saveButton = Button("Save")
        saveButton.onTap = { self.save(); self.dirty = false }   // captures self, freely
    }
}
win = spawn Window(Editor())  // one home per window
...
on window_closed { stop win } // frees Editor, Button, closure, and their cycle together
```
Editor → button → closure → editor is a cycle. Under ARC it leaks, and under weak-capture it is
noisy. Here it doesn't matter: the cycle lives in the window's home, and closing the window
stops that home. Now suppose the button lives somewhere else, such as an app-wide toolbar home:
```
toolbar.addAction("Save", { self.save() })   // closure written in the editor's home
```
The toolbar receives a callback lease. A tap runs `save` *in the editor's home*, with the
editor's implicit `self`. After the window closes, the callback is dead and the toolbar's `Event`
drops it. The program can't crash on a freed editor, the closure keeps nothing alive, and there is
no cycle. This fits DSLs (G11) well: a layout tree is just objects in one home, and callbacks
write `self.x` with no capture lists.

**(d) Shared mutable cache used by two components**
```
cache = spawn Cache()                        // the cache is its own home
a = spawn Importer(cache); b = spawn Viewer(cache)
// inside Viewer:
img = ask cache.get(key) else { loadPlaceholder() }
tell cache.put(key, img)                     // img is moved if we held the only reference
```
If both components are in the same home, they just share a plain reference (rule 2). Across
homes, the cache is an actor: mutation is serialized for free and results come back as copies.
Evicting an entry is ordinary in-home RC. A cache of heavyweight per-entry state (for example a
session) can make each entry its own home, and eviction then means `stop`.

**(e) Passing a large list to a function that mutates it**
```
fn normalise(xs) { for i in 0..xs.count { xs[i] = xs[i].trim() } }
normalise(lines)              // same home: by reference, no copy, the caller sees the changes
lines = ask worker.normalise(lines) else { lines } // cross-home: moved out, moved back
```
Within a home, this is reference semantics, as in Python or Java, with no `inout` to learn. Across
homes, the list moves at no cost when it is uniquely held. If it isn't, it is copied, and the
copy is visible in a profiler as a boundary cost.

**(f) Sharing data between threads**
```
results = spawn Collector()
for chunk in data.split(8) { spawn Worker(chunk, results) }   // chunks moved, 8 threads
// Worker: tell results.add(summary)
table = freeze loadBigTable()   // optional: zero-copy, read-only sharing
```
There is no separate threading model: homes are the units of parallelism. Mutable shared state is
a home, and immutable shared state is `freeze`. Data races can't be expressed, there are no
Send/Sync rules, and there are no atomics on the in-home RC fast path.

## 7. What's genuinely new vs. the covered options

- **Lifetimes as runtime objects with lifecycle events, not inferred scopes.** "Scope-bound
  regions" ties a region to lexical scope and needs `promote`. MLKit infers regions. A home is
  dynamic: you create it, pass its lease around, and stop it when the window closes or the session
  ends. That is exactly the non-nesting case the brief calls hard.
- **Cycles are bounded instead of solved.** There are no weak references (unlike O1), no cycle
  collector (unlike O7), and no ownership rules (unlike O4 and O5). A cycle costs nothing beyond
  its home's lifetime, and homes are sized to lifecycles.
- **Callbacks run where they were written.** Capturing `self` in a closure is always safe,
  including when the closure is handed to other components. Closures that cross homes get Erlang
  link semantics and are pruned automatically. No covered option makes closure placement the
  safety mechanism.
- **Memory partitions are concurrency partitions.** One concept (the home) gives memory
  reclamation, data-race freedom and parallelism. Pony has a similar structure, but it uses a
  per-actor GC, which fails G2.
- **Validity checks at home granularity.** Leases are incarnation-tagged *home* ids, so each
  boundary crossing costs one check, not one per object dereference as in O6 (Vale).
- **A crash is a heap drop.** Error recovery and memory reclamation are the same mechanism, so
  memory safety needs no unwinding.

## 8. Known weaknesses

- **Long-lived homes can leak cycles.** `main` and app-wide service homes never stop, so a cycle
  created there persists. Mitigations are the debug-build leak report and guidance like "churning
  graph → give it a home". A possible extension, `renew()`, copies the root's live graph into a
  fresh home and drops the old one. That is a user-triggered copying collection, so **it needs a
  decision from John against G2.** It is not part of the core model.
- **Choosing homes is a new design skill.** Too few homes means bigger leaks. Too many means
  copying and `ask` latency. This is easier than learning lifetimes, but it is not zero.
- **Boundary copies can surprise.** An object sent to another home arrives as a *copy*, so
  identity doesn't carry across. Large non-unique graphs cost a real deep copy.
- **`ask` adds async hazards.** These include latency, deadlocks (detected, but still errors) and
  reentrancy questions. UI code that bounces between many homes gets chatty.
- **Implementation risk is moderate to high.** It needs a scheduler, mailboxes, per-home
  allocators with remote free, generated deep-copy routines, and later fibers, on three OSes.
  Each piece is well understood, but there are many of them.
- **G3 flag:** `far T` is a compiler-known type former, like `List`/`Map`. It is the same pending
  question.
- **FFI pinning:** pointers handed to C must not outlive their home. This can't be checked
  statically.
- **Self-assessment (rough):** simplicity 4, safety 4, expressiveness 4, implementation risk 2–3,
  performance 4, concurrency 5, tooling 3, for a total of roughly 75–79.
