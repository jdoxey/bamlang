# 09: Standing Calls

## 1. Name

**Standing Calls.** There is no heap. A long-lived object is a function call that hasn't returned yet.

## 2. The crazy premise

It breaks the assumption that **objects are data on a heap, reached through pointers**. In this design:

- No user value ever lives on a heap. Each one lives in a stack frame, or in a "lane" that a frame owns (see below).
- Nothing can point into another stack. The only thing that crosses from one stack to another is a **door**, which lets you ask a stack to do something but never lets you read its memory.
- A thing with identity and its own lifetime (a window, a session, a cache) is a **suspended function call on its own stack**. Its fields are the function's local variables. Its methods are entry points into that frame. It is freed when the function finishes.

Gates: G2 and G3 are kept, not broken. The built-in `List of T`/`Map of K to V` question is flagged in section 8. Determinism is kept for freeing; thread scheduling is as nondeterministic as any threads.

## 3. Pitch

Simula 67 had the right idea and then put it on a garbage-collected heap. Here it goes back on the stack. You write `fn Editor(doc)` with locals and `on save()` handlers. `start Editor(doc)` runs that function on a brand-new stack. When the body reaches its closing brace, the call *stands*: its frame stays alive and waits for callers. `me.save` is a value you can hand to a button. When the button fires, the runtime switches onto the editor's stack and runs `save` on top of the suspended frame. That gives it the editor's locals for free, so `self` is implicit because self *is* the frame. Arguments are copied in and results copied out. Inside one stack, every value dies when the frame holding it returns. Across stacks there are only doors: a call through a door can fail with `gone` or `busy`, but it can never dangle or race. You free a window by letting its story end. No RC, no GC, no lifetimes, no borrow checker: one concept (the stack) replaces class, actor, closure environment and thread.

## 4. The rules

1. **No pointers to data.** Assigning, passing and returning a value copies it. Lists, strings and maps are values too. (The compiler turns a copy at a variable's last use into an O(1) move. You can't see this.)
2. **`edit` parameters.** `f(edit xs)` lets `f` change the caller's variable in place for the length of the call. An `edit` can't be stored.
3. **Values die with their frame.** When a function returns, everything it held is gone, except the return value, which is handed to the caller. That is all there is to know about freeing ordinary data.
4. **Standing functions are classes.** `start F(args)` runs `F` on a new stack and returns a **door** right away. `F`'s locals are its fields. `on name(...) { }` blocks inside `F` are its methods, and they see `F`'s locals directly. `me` is the door to the stack you are running on. Any `on { }` block written anywhere inside `F`'s body is an anonymous handler, and its value is an *entry* (door plus handler).
5. **A standing call lives until it says `stop`, or until its owner stops.** After its body finishes, it waits for calls. `stop` (run from a handler or the body) unwinds its stack and frees everything on it in one go.
6. **Doors are plain values.** You can copy them anywhere: into lists, into other stacks, across threads. `d.save(x)` switches onto `d`'s stack, runs the handler, and copies the result back. The caller waits.
7. **Door calls can fail.** A door call returns its result, or fails with `gone` (that call has stopped) or `busy` (the call would re-enter a stack that is already in your current call chain, or would deadlock). Handle the failure with `else`, or pass it up with `?`. `owner` is never `gone`.
8. **Ownership tree.** A standing call belongs to the stack that started it, or to the one you name with `start F() in d`. When an owner stops, its children stop first, deepest first, and each child's `on stop` runs.
9. **`send d.m(args)`** queues the call and returns at once. Queued calls run one at a time per stack, in order, on whatever thread is free. This is the concurrency story.
10. **Trailing blocks can touch the caller's locals** (read and write) because the caller is suspended while the call runs. A trailing block can't be kept after the call returns. To keep a callback, use an entry (`me.save`, or `on { }`). A stored plain `fn` value captures copies.

That is ten rules. There is no `weak`, `unowned`, `shared`, `Rc`, lifetime syntax, `async` or `Sendable`.

## 5. Under the hood

- **Stack.** A segmented, growable stack plus a control block: id, generation, state (setting-up / standing / running / stopped), owner, children, mailbox, current runner thread. Control blocks sit in a runtime slot table. A door is `(slot, generation)`, 8 bytes, and every visit checks the generation.
- **Visiting.** A synchronous door call is a fiber switch (saving and restoring registers, Boost.Context/Go-style asm per platform) plus a lock on the target. Handlers compile to **nested functions with a static link** to the standing frame (Pascal-style), so implicit `self` is a frame pointer. LLVM handles static links fine.
- **Lanes: growable values without a heap.** A List/String/Map is a *lane*: a contiguous virtual-memory reservation, committed one page at a time as it grows, so it grows **without moving**. Small values start in a small lane carved from the owning stack's lane area and get promoted to a dedicated reservation when they outgrow it. A lane is owned by a frame and released when that frame pops. Returning a list relinks its lane to the caller's frame in O(1), which is a generalisation of Ada's secondary stack. Passing it as the last use across stacks relinks it the same way.
- **Flat values.** Every value is a position-independent byte blob that uses offsets, not pointers (FlatBuffers-style). A `List of String` is a lane of length-prefixed records plus an offset lane. Copying any value is `memcpy`, and so is copying it across threads. When an element grows in the middle, it is re-pushed at the end with 2× slack and its old slot becomes a tombstone. Once tombstones pass 50%, *that value alone* is compacted. This is local, triggered by the value's own mutation, and bounded by the value's size: it works like a `Vec` realloc, not a collection run.
- **Busy detection.** Each thread waits on at most one stack, and each stack has at most one runner. Before blocking, a visit follows the chain from the target's runner, to the stack that runner is waiting on, and so on. If the chain reaches the caller, the visit fails `busy` instead of deadlocking. This also catches same-thread re-entry.
- **Aliasing.** The only in-stack aliasing hazard is a trailing block using a variable that the same call also takes as `edit`. That is a local compile error in one expression, not a rule to learn.
- **`start`** schedules the body on the pool. A door call made before the body finishes waits for setup to complete. UI frameworks can pin stacks to the main thread.

## 6. Scenarios (illustrative only — not a syntax decision)

**(a) Read lines.** A plain function. The list lives in a lane that grows in place and is relinked to the caller on return.
```
fn readLines(path: String) -> List of String {
  var lines = List of String()
  var f = open(path) else return lines
  while f.readLine() is line { lines.append(line) }
  return lines            // O(1) lane relink, no copy
}
```

**(b) Tree with parent pointers.** For a *data* tree (parse tree, JSON), the tree is one value and parents are indices.
```
type Node { label: String, parent: Int, kids: List of Int }
var t = List of Node()
t.append(Node("root", -1, []))
t.append(Node("a", 0, [])); t[0].kids.append(1)
up = t[t[1].parent].label
```
For a *living* tree (scene graph, DOM), each node is a standing call. The parent is `owner`, which is never `gone` (rule 8), and children are doors.
```
fn Shape(name: String) {
  var kids = List of Shape()
  on add(n: String) { kids.append(start Shape(n)) }   // child owned by me
  on path() -> String { return (owner.path() else "") + "/" + name }
}
```

**(c) UI callback: the crux.**
```
fn Editor(doc: Doc) {
  var text = doc.text
  var dirty = false
  on save() { doc.write(text); dirty = false }
  on view() -> View {
    return Column {
      TextArea(text, changed: on { t in text = t; dirty = true })
      Button("Save", tap: me.save)          // entry = door + handler
      Label(dirty ? "unsaved" : "saved")
    }
  }
  on stop { if dirty { doc.writeBackup(text) } }
}
let ed = start Editor(doc) in app.window
```
The view is a value. The window stack holds a copy and re-asks `ed.view()` after each handler. A tap does `entry() else ignore`: once the editor has stopped, the tap gets `gone` and the framework drops the binding. Nothing can retain the editor and there is no cycle, because entries don't own anything (rule 8 decides ownership).

**(d) Shared mutable cache.**
```
fn Cache(limit: Int) {
  var entries = Map of String to Bytes()
  on get(k: String) -> Bytes? { return entries[k] }      // copied out
  on put(k: String, v: Bytes) { entries[k] = v; trim(limit) }
  on peek(k: String, use: block(Bytes)) { if entries[k] is b { use(b) } }
}
let cache = start Cache(1000) in app
let a = start Thumbnailer(cache)       // both hold the same door
let b = start Prefetcher(cache)
// big read without a copy: the block runs on cache's stack, writes caller's local
var size = 0
cache.peek("hero.png") { b in size = b.count }?
```

**(e) Mutating a large list.** On the same stack, `edit` means no copy.
```
fn normalize(edit xs: List of Float) { let m = max(xs); for i in xs.indices { xs[i] /= m } }
normalize(edit samples)
```
On another stack, at the last use, the lane is relinked rather than copied:
```
samples = worker.normalized(samples)?
```

**(f) Threads.** Every stack is a unit of concurrency. Data can be shared only by asking.
```
fn Total() { var n = 0; on add(k: Int) { n += k }; on value() -> Int { return n } }
fn Summer(part: List of Int, into: Total) { into.add(sum(part))?; stop }
let total = start Total()
for part in data.split(8) { start Summer(part, total) in total }   // 8 parallel stacks
// ... later
print(total.value()?)
```
Data races can't be written: no pointer reaches another stack, and only one thread runs inside a stack at a time.

## 7. What is new

- **Objects are suspended activation records with no heap underneath.** Simula had the shape but used GC. Erlang has processes but gives each one a garbage-collected heap. Here, no GC and no RC exist anywhere, not even inside an actor.
- **Freeing is driven by the story, not by references.** A thing is freed when its function finishes or its owner does. References (doors) never keep anything alive, so cycles can't leak memory, and non-nested lifetimes (sessions, windows) are simply calls that end when they choose to.
- **One concept, four jobs.** A standing call is the class (implicit `self` = frame), the closure environment for every escaping callback (an entry), the actor/thread boundary, and the unit of memory accounting.
- **Lanes:** growable values as VM-reserved, never-moving, frame-owned stacks, returned by O(1) relink.
- **Deadlock becomes a value.** The wait-for chain check turns a would-be deadlock or re-entry into `busy`.
- **The debugger shows the whole program as a tree of standing calls**, each with its locals, bytes, age, owner and mailbox. "What is alive and why?" always has a one-hop answer: its owner hasn't stopped it.

## 8. Less crazy than it sounds, or more

**Less crazy.** Every part has a precedent:

- Ada's secondary stack (variable-size returns without a heap)
- Pascal static links (implicit `self`)
- Simula classes (objects as activation records)
- Go/Boost fibers (cheap stack switches)
- Elm/SwiftUI (views as values, state in objects)
- Erlang supervision trees (rule 8)
- Vale-style generation checks, but on stacks, not on every object

Programmers already think of a window as "a thing that runs until closed". The rule count (10) is close to O4's, and (c), (d) and (f) are arguably cleaner than in O1, with no `[weak self]`. Memory safety and data-race freedom fall out of one rule: no pointer crosses a stack.

**More crazy.**

- A "no heap" claim is partly theatre. The runtime's slot table, stack segments and lane reservations add up to an allocator. It is just one users never see and never free through.
- Everything is copied across stacks, so large blobs need `peek`-style blocks.
- Every method call on a long-lived object is a fiber switch that can fail, so `?` and `else` appear everywhere.
- **G3 flag:** `List of T`, `Map of K to V` and `block(T)` are compiler-known parameterised types. Door types are named by the standing function (`Cache`), so no generics are needed there.

## 9. Known weaknesses

- **Synchronous call-backs into the caller fail `busy`.** For example, a table view asking its delegate during a call made by that delegate. Such call-backs must be trailing blocks or `send`. This is the pattern O1 users will trip on most.
- **Graph data (b)** falls back to indices in a value, which is O2's answer. Only "living" trees get real parent links.
- **Leaks still exist** as standing calls that never stop. They are bounded by owner lifetimes and listed by the debugger, but they are still leaks.
- **Performance cost.** Each visit adds about 10–30 ns (switch, lock, generation check, chain walk). Fine-grained objects (a million cache entries as standing calls) are a trap, and users must learn "values inside, standing calls at the edges."
- **Address space.** Lanes need a lot of virtual address space, and tiny lanes still need a small-object path. Many small strings strain the scheme until it is tiered.
- **Mid-value compaction** is local and bounded, but it is still a latency spike proportional to the size of one value.
- **C FFI.** C expects heap pointers. A lane can be pinned and lent for the duration of a call. C-owned memory must be wrapped in a standing call that frees it in `on stop`. This is workable but awkward.
- **Implementation risk is high** for an AI-written compiler: per-platform fiber switching, a VM-reservation allocator, flat value layout, a scheduler, chain-walk atomics, and static-link codegen.

**Self-assessment:**

| Criterion | Score | Weighted |
|---|---|---|
| Simplicity | 3 | 15 |
| Safety | 5 | 15 |
| Expressiveness | 3 | 9 |
| Implementation risk | 2 | 6 |
| Performance | 3 | 6 |
| Concurrency | 5 | 10 |
| Tooling/FFI | 3 | 6 |
| **Total** | | **≈67** |
