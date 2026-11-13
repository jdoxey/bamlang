# 01 — Tissues and Nerves

## 1. Name

**Tissues and Nerves**: homing cells, whole-tissue apoptosis, and inert dead references.

## 2. Inspiration

| Biology | Memory |
|---|---|
| **Cell** | A heap object with identity (class instance, list, map, closure). |
| **Tissue** | A group of cells that live and die together, for example a window, a document, a session or a cache. Tissues form a tree. |
| **Nucleus** | The cell a tissue was grown from. The parent tissue keeps the whole tissue alive by holding its nucleus. |
| **Stem cell / homing** | A new cell belongs to no tissue yet. When something first stores it, it moves into that holder's tissue and stays there. |
| **Metabolism** | Inside a tissue, ordinary non-atomic reference counting frees unused cells straight away. |
| **Apoptosis** | Programmed death of a whole tissue at once. Cycles inside it don't matter. It is deferred while the tissue is in use, the way a cell won't die halfway through mitosis. |
| **Nerve** | A link that reaches into another tissue. It carries signals but doesn't feed the target. When the target dies, the nerve is cut and the end goes dead. |
| **Necrotic tissue** | A dead reference points at an inert tombstone. Signals sent to it do nothing. |
| **Host / niche** | Every cell knows which cell holds it. This back-pointer is automatic and doesn't keep the holder alive. |
| **Hormone** | A frozen value secreted into the "blood", readable from every thread. |
| **Gland** | A shared mutable tissue guarded by a lock. |
| **Transplant / rejection** | A whole tissue moves to another thread. All nerves into or out of it are cut. |

The key move: the programmer often knows a lifetime that the compiler can't infer, such as "this lives as long as the window". In this model the programmer states it **by deciding which tissue a thing is grown in**, not by annotating references. The runtime then decides, at each store, whether a reference owns its target or is a nerve. No `weak` keyword, no capture lists, no lifetime annotations.

## 3. Pitch

Every object is a cell, and every cell lives in a tissue. A tissue is a lifecycle the programmer already thinks in: "the editor window", "this HTTP session", "the thumbnail cache". Inside a tissue, references are ordinary counted references. Cycles are allowed, and whatever the counts miss is freed in one sweep when the tissue dies. A reference that crosses into another tissue is a *nerve*: it never keeps its target alive. When the target dies, the nerve is cut and points at an inert dead cell, so calls on it do nothing. A new object joins the tissue of whatever first stores it. Builder-style UI code and "construct it and hand it over" APIs therefore put things in the right place without any syntax. Tissues die when their parent drops them or when they're told to die. Death waits until no running code is inside the tissue, so a button can close its own window. No tracing, no collector, no lifetime annotations. There is one new keyword for making lifecycles (`grow`) and one rule for what dead means.

## 4. The rules

1. **Values vs cells.** Numbers, strings and `struct`s are values and are copied. Class instances, `List`, `Map` and closures are *cells* and are shared by reference.
2. **Locals keep cells alive.** While a local variable or parameter holds a cell, that cell can't die, and neither can its tissue.
3. **First store wins.** A new cell belongs to no tissue. When it is first stored into a field or collection of some cell, it joins that cell's tissue for good. Any other new cells it holds join with it. Use `x.copy()` to get a fresh cell you can place elsewhere.
4. **`grow` starts a tissue.** `grow Window(...)` makes a cell that is the *nucleus* of a new tissue. The new tissue's parent is the tissue where the nucleus is first stored (rule 3).
5. **Tissues die whole.** A tissue dies, with all its cells and cycles, when one of these happens:
   - its parent no longer holds the nucleus;
   - someone calls `x.die()` on the nucleus;
   - its parent tissue dies.

   It dies only once no local holds any of its cells (rule 2).
6. **Crossing a tissue boundary makes a nerve.** A field that refers to a cell in another tissue doesn't keep it alive. The one exception is a parent tissue holding its child's nucleus.
7. **Dead is inert.** A nerve whose target died points at a dead cell:
   - method calls do nothing and return the zero value (`0`, `""`, empty, dead);
   - field writes are ignored;
   - `alive x` tells you whether a cell is still alive;
   - a closure with any dead capture does nothing when called.
8. **`host`.** Every cell has a built-in `host`: the cell whose field holds it. For an element of a collection, it's the collection's host. `host` never keeps anything alive and becomes dead when the holder lets go. Use it for parent pointers.
9. **Threads.** A tissue lives on one thread.
   - `send t to worker` moves a whole tissue to another thread, and every nerve into or out of it goes dead.
   - `secrete v` makes a frozen copy that any thread can read.
   - `gland X()` makes a tissue that threads share under a lock. Its cells are only alive inside `with g { ... }`.

That is nine rules. Rules 1 and 2 are the same as in ARC languages. A programmer never declares weak, unowned, lifetimes, capture lists, borrows or moves.

## 5. Under the hood

**Cell header.** About five words:
- a vtable pointer;
- a non-atomic RC plus flag bits;
- a tissue pointer (null means a stem cell that belongs to no tissue yet);
- a `host` pointer;
- intrusive next/prev links in its tissue's cell list.

Cells with incoming nerves also get an entry in a side table (`receptors`) that lists the slot addresses pointing at them.

**Tissue record.**
- parent, nucleus and children;
- the owning thread;
- the cell list;
- a `pins` count (how many locals hold any of its cells);
- a `doomed` flag.

**Tagged pointers.** In a field, low bit 0 means an owning (counted) reference and low bit 1 means a nerve. Locals are always counted.

**Store barrier.** Every store of a reference into a field (the compiler emits it, written in the runtime in C or the language itself):
```
store(container, slot, v):            // illustrative only — not a syntax decision
  if container is TOMB or container.tissue.doomed: drop; return
  release_old(slot)                    // RC-- or unregister a nerve; clear old.host if it was container
  if v.tissue == null: home(v, container.tissue)        // rule 3: walk v's stem subgraph, tag it
  if v.tissue == container.tissue:
       if v is that tissue's nucleus: plain store       // internal refs to the nucleus don't count
       else: v.rc++                                      // metabolism
  elif v is nucleus and v.tissue.parent == container.tissue: v.rc++   // the one owning cross edge
  else: tag slot as nerve; receptors[v].add(slot)        // rule 6
  if v.host == null: v.host = container (or collection's host)        // rule 8
```

**Homing.** `home` walks only cells that belong to no tissue yet, and each cell is homed once. The cost is amortised O(1) per allocation, and the walk never visits old cells, so it is not a GC run. References that stem cells held while waiting were provisionally counted. At homing time they are reclassified as counted or nerve. Where `grow` created the cell, homing sets the new tissue's parent instead.

**Local retain.** This increments `c.rc` and also `c.tissue.pins`, both non-atomic.

**Cell death by RC.** When a cell's RC reaches 0, the runtime:
1. cuts its incoming nerves (writes `TOMB` into each registered slot);
2. releases its fields;
3. unlinks it from its tissue;
4. frees it.

This is exactly ARC plus zeroing weak references, except that which references are weak is chosen automatically.

**Tissue death (apoptosis).** When a tissue is doomed (nucleus RC from the parent reaches 0, `die()` was called, or the parent died) and `pins == 0`, the runtime:
1. cuts every incoming nerve to every cell;
2. dooms its child tissues;
3. unregisters outgoing nerves;
4. runs `deinit`s, which cannot resurrect anything because stores from a doomed tissue are dropped;
5. frees every cell in the list without decrementing RCs between tissue-mates.

This last step is how cycles get reclaimed: no tracing, just a list walk.

**`TOMB`.** One zero-filled block per program, as large as the largest class.
- Each class gets a compiler-generated *dead vtable* whose methods return zero values.
- Statically dispatched methods get a one-compare check of `self == TOMB` at entry.
- A null class reference *is* `TOMB`, so field reads of reference type stay safe.
- A closure call first checks whether any captured cell is `TOMB`.

**Threads.**
- RC inside a tissue is non-atomic, because a tissue is confined to one thread.
- `secrete` deep-copies the value into a frozen tissue that has one **tissue-level atomic count**. Any reference to any cell inside it counts on the whole tissue, so cycles in frozen data are free.
- A `gland` is a tissue with a mutex and a tissue-level atomic count. A nerve load from a gland returns `TOMB` unless the current thread holds its lock.
- `send` cuts every nerve into or out of the tissue. It traps if `pins > 1`.

**Static elision.** The compiler skips the barrier or RC when it can prove the case:
- the same tissue (fields of `self` set in a method on cells `self` created);
- cells that never escape, which go on the stack;
- the stores in constructors.

**Debug builds.**
- A *necrosis log* records each touch of a dead cell, with the site where its tissue died.
- A *tumour report* runs at tissue death and reports cells that only cycles were keeping alive, which hints that the tissue should be split. It only reports and never reclaims, so G2 still holds.
- A *misplaced-homing warning* fires when a cell created in this frame ends up as a nerve.
- A tissue-tree view in the debugger.

## 6. Scenarios

All code is *illustrative only — not a syntax decision*.

### (a) Read a file into a growing list
```
func readLines(path: String) -> List
  let lines = List()                 // stem cell, kept alive by the local
  for line in File.open(path).lines()
    lines.add(line)                  // strings are values; the buffer grows by realloc
  return lines                       // still a stem; it homes wherever the caller first stores it
```
No tissues are involved. While a cell only sits in locals, the model is plain ARC. The list's backing buffer isn't a cell, so growing it is just a realloc.

### (b) A tree with parent pointers
```
class Node
  var name: String
  var children = List()
  func add(child: Node)    children.add(child)     // child homes here; child.host = self
  func parent() -> Node    return host as Node     // automatic, non-owning
  func remove(child: Node) children.remove(child)  // host cleared; subtree freed now by RC

let doc = grow Node("root")      // the whole tree is one tissue
```
`host` replaces the hand-written `weak var parent`. The tree has no reference cycles, so a removed subtree is freed immediately rather than when the tissue dies. If someone did add cycles, for example `node.lastFocused = sibling`, they cost nothing until the tissue dies, and then they are freed in bulk.

### (c) A UI callback capturing enclosing state (the crux)
```
class Editor
  var text = ""
  var dirty = false
  var window: Window
  func open()
    window = grow Window("Edit")        // new tissue; child of the editor's tissue
    window.toolbar.add(Button("Save", onTap: {
        self.save()                     // self = editor: the capture crosses a boundary -> nerve
        self.dirty = false
        self.window.die()               // a button closing its own window is safe (rule 5)
    }))
  func save() ...
```
- The Button and its closure are stem cells. They are first stored into `toolbar`, so both join the window's tissue.
- Editor → window owns the nucleus. Window → button → closure are counted references inside the window's tissue. Closure → editor is a nerve, so **there is no cycle and nothing to annotate**.
- `die()` inside the callback is deferred, because the running closure holds the tissue through its locals. The window is freed when the closure returns.
- Now suppose the window was grown by `App` instead, so it can outlive the editor. When the editor dies, the closure's capture is cut, and a tap does nothing. There is no crash, no leak and no `[weak self]`.

### (d) A shared mutable cache used by two components
```
class App
  var cache   = grow Cache()
  var editor  = grow Editor(cache)    // Editor stores cache in a field -> nerve (cache's parent is App)
  var preview = grow Preview(cache)

class Cache
  var entries = Map()
  func put(k: String, v: Thumb)  entries[k] = v      // a fresh Thumb homes into the cache tissue
  func get(k: String) -> Thumb   return entries[k]
  func evict(k: String)          entries.remove(k)   // freed by RC; every nerve to it goes dead

// inside Editor:
  cache.put(path, Thumb(bytes))   // "construct and hand over": the cache owns it
  let t = cache.get(path)         // the local keeps t alive while in use, even if evicted
  self.current = t                // nerve: after eviction, self.current is dead and `alive` says so
```
Both components hold nerves, so the cache's lifetime is App's decision alone. Eviction is always safe: a component that kept an entry sees it go dead, not dangling. Because the first store wins, `put(k, Thumb(...))` makes the cache the owner without a `move` keyword.

### (e) Pass a large list to a function that mutates it
```
func normalize(xs: List)
  for i in 0..xs.count
    xs[i] = xs[i].trim()

normalize(lines)                 // a reference passed: no copy, no inout, no borrow
```
Lists are cells, so they alias the way they do in Python. Strings are values, so the stores are just stores.

### (f) Sharing data between threads
```
let config = secrete loadConfig()      // frozen; one atomic count for the whole graph
let stats  = gland Stats()             // shared, mutable, guarded by a lock

spawn {
  with stats { s in s.hits += 1 }      // s is alive only inside `with`
  log(config.name)                     // reading frozen data takes no lock
}

let job = grow Job(input)
send job to worker                     // the whole tissue moves; nerves to it here go dead
```
Data races are ruled out by construction: thread-local tissues use non-atomic RC, frozen data can't be written, and glands are only touched under their lock.

## 7. What's genuinely new vs. the covered options

- **Ownership decided at the store, never declared.** O1/O7 make the programmer pick strong or weak; O4/O5 make them pick owning or borrowed. Here the *tissue graph* decides at each store. The programmer only decides which lifecycle a thing is grown in.
- **Homing ("first store wins").** Scope-bound regions and arenas assign memory by where it is allocated or by scope. Homing assigns it by **the first holder**. This puts builder-DSL output and construct-and-hand-over arguments in the right lifecycle without `move` or `promote`, which helps G11.
- **Cycles are bounded by a lifecycle the programmer chose, and freed by a list walk.** O7 needs a cycle collector, and O1 leaks cycles forever. Here a cycle lives at most as long as its tissue, which might be a window, a session or a request.
- **Tissues with arbitrary lifetimes that are still safe to point into.** Unlike the covered region schemes, a tissue can die at any moment the program chooses, outside any scope nesting. References into it from outside are cut automatically, at the cost of the nerves pointing at it, not a heap scan.
- **Inert death rather than a trap.** O6 traps on a stale generation. Here a dead target is a tombstone that ignores calls, and that is exactly the semantics a late UI callback wants.
- **Deferred apoptosis.** Code running inside a tissue pins it. That removes the classic "the close button frees its own window mid-callback" crash.
- **An automatic `host` back-pointer.** It removes the most common reason for weak references (parent pointers) without any declaration.
- **Tissue-level atomic counts for frozen and shared graphs, plus transplant-with-rejection.** The tissue is the unit of both lifetime and thread affinity.

## 8. Known weaknesses

- **Silent no-ops hide bugs.** This is Objective-C's nil-messaging problem: a value read from a dead cell can be wrong data. The necrosis log helps in debug builds only.
- **Strong vs nerve is invisible in the types.** A non-optional field can quietly become dead. Readers have to reason about tissues to know which references own their targets.
- **First-store surprises.** Code like `self.recent.add(e); cache.put(k, e)` gives the cache only a nerve, and `e` dies when it leaves `recent`. Moving a cell between tissues needs `copy()`.
- **Runtime cost.**
  - every pointer store goes through a barrier;
  - the header is about five words;
  - receptor-table upkeep;
  - two increments per local retain;
  - zero-checks on calls.

  Static elision cuts this but doesn't remove it. Performance is predictable, but it isn't C.
- **Cycles in long-lived tissues accumulate**, including the program-lifetime "body" tissue. That is ARC's leak problem, bounded only as well as the programmer's choice of tissues.
- **`host` is untyped.** It needs a downcast, and it is ambiguous when a cell has several holders.
- **Identity on dead references is odd.** Every dead reference equals every other one.
- **Implementation risk is moderate to high** for an AI-built compiler: homing, receptors, pins, dead vtables and deferred death are each simple, but together they are a lot of runtime that has to be exactly right.
- **The G3 flag.** The model relies on built-in, compiler-known `List` and `Map`. `host as Node` needs a checked downcast.
