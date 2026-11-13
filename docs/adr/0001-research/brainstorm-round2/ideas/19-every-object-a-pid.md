# 19 — PIDs: every object is a process

## 1. Name

**PIDs**: every class instance is a process-like cell; every reference is a file-descriptor-like handle.

## 2. The crazy premise

Sacred assumption broken: **objects share one address space, and calling a method on another object is a cheap jump.**

In PIDs, each object is its own isolated compartment, like an OS process. It has a private heap, a private lock and an entry in a "kernel" cell table. No object can point into another object's memory. A method call on another object is an IPC: the call crosses a boundary, copies its arguments in, and comes back with a value or the error `gone`. Memory is reclaimed the way an OS reclaims it: **when a process exits, its whole heap goes**. Inside a cell nothing can be shared by reference, so nothing inside a cell can dangle.

A second assumption breaks with it: **memory safety does not have to be proven by the compiler. Isolation and containment can supply it.** A fault kills one cell, not the program, and the cell's parent finds out, as in Erlang's "let it crash".

Gates: G2 passes (handle counting plus tree kill, no tracing). G3 passes, apart from the pending question of built-in `List`/`Map`. Determinism is kept: every death has a defined trigger and a defined order.

## 3. Pitch

Programmers already understand processes. A process has a parent. Killing the parent kills its group. A process exits when its last reader closes the pipe. Talking to a dead process gives you ESRCH, not a corrupted heap. PIDs applies that model to objects. A `struct` is a plain value, copied and freed deterministically, and it never contains a reference. A `class` instance is a cell, and you hold it through a handle. The process tree gives every cell a guaranteed upper bound on its lifetime: it can never outlive its parent. Handles to ancestors are free and can never dangle, because if the ancestor were dead, you would be too. That makes parent pointers, UI callbacks into the owning editor and children talking to their window trivially safe. Handles that point down or across the tree are counted, like fds. When the last one closes, the cell gets EOF and exits. Cycles across branches can leak at worst until their common ancestor dies. Most UI and session lifetimes are subtrees, so they die together anyway. Each cell admits one thread at a time, so data races cannot happen. In `--isolate` builds every cell really is a separate OS process or CHERI compartment, so `ps`, `lsof`, `kill` and `strace` become your object-graph debugger.

## 4. The rules

1. **`struct` is a value.** It is copied on assignment and when passed. It is freed when the variable, field or list slot holding it goes away. Values never contain references to other values.
2. **A `class` instance is a cell.** `Editor()` spawns a cell and returns a handle. The cell that spawned it is its **parent**. Variables of class type hold handles.
3. **A cell's fields are private to its own methods**, which use an implicit `self`. Other cells can only call its methods. `e.title` from outside is sugar for a generated getter call.
4. **Crossing a boundary moves values and handles only.** Arguments and results are copied (large ones are zero-copy, see §5). A `mut` parameter lends the caller's value for the duration of the call.
5. **A cell dies when** (i) it calls `exit`, (ii) its parent dies, or (iii) **EOF**: no *counting* handle to it remains. Handles held by the cell itself or by any of its descendants do not count.
6. **Dying:** the cell's descendants die first, deepest first. Then its `on exit` block runs. Then every handle it holds is closed, which may cause further EOF deaths. Then its heap is released whole. A death is delivered only when no thread is inside the cell, the same way signals are delivered at syscall boundaries.
7. **Calling a dead handle raises `gone`.** Handle it inline with `h.m() or <fallback>`, or test `h.alive` first. `gone` is the only new error kind.
8. **Faults crash the cell, not the program.** Faults are uncaught `gone`, bounds errors, overflow and failed asserts. The crashing cell dies (rule 6), and the cell that called into it receives `gone`. A parent may define `on child crash(c)`.
9. **One thread inside a cell at a time.** A thread that calls out from cell A keeps A, but it can re-enter A on the same call chain. `go h.m(args)` runs a call on a new thread and returns a `Task` handle.
10. **`adopt h`** makes the current cell the parent of `h`. It is refused if `h` is an ancestor of the current cell.
11. **Closures capture values by copy and handles as handles.** A closure stored in a cell's field is held by that cell, which is what decides whether its handles count under rule 5.

That is eleven rules. Rules 1, 2, 3 and 9 are familiar from struct/class languages and from monitors. The rules that are new to learn are 5, 6, 7, 8 and 10.

## 5. Under the hood

- **The cell table, i.e. the "kernel".** Each entry holds a generation number, the parent index, a depth, an atomic count of counting handles, a monitor (owner thread plus recursion depth) and a pointer to a private arena. A handle is `{index, generation}`. A generation mismatch means `gone`. This is a cheap check, not a validity guess.
- **Counting rule at store time.** When a handle to `T` is stored into a field of cell `H`, the runtime checks whether `H` is `T` or a descendant of `T`. It does this by walking `H`'s parent chain for `H.depth − T.depth` steps. A parent pointer costs one step. If `H` is a descendant, the handle is stored uncounted. Otherwise the count is incremented. Locals in method frames use ARC-style elision: borrowed locals do not count. Escapes do.
- **`adopt` re-checks the handles that change status.** Re-parenting changes which handles are "up-tree". The runtime rescans only the handle fields in the adopted subtree and recomputes their counting bit. The cost is proportional to the size of the subtree's handle tables, not to the heap. It is a rare, explicit operation.
- **Memory inside a cell.** Each cell has a value-semantics arena: lists, strings and maps of structs, with move/copy-on-write and freeing at end of scope or on overwrite, like O2 but simpler because there are no handles-as-references inside values that could alias. Small cells take their arena from a slab, so a typical cell costs about 64 to 96 bytes of overhead.
- **Boundary crossing.** In release mode a call into another cell is software isolation: check the generation, acquire the monitor (uncontended, so a CAS), switch the current-cell register, and run the callee in the same OS thread. This is "migrating threads", as in L4/Mach. Values of a page or more cross by page remap with copy-on-write, so passing a 100 MB list is O(pages), not O(bytes). A `mut` parameter across cells needs no copy: the caller is blocked on this call chain and holds its own monitor, so nobody else can observe the value.
- **`--isolate` mode.** Each cell runs as a real compartment: an OS process with shared-memory IPC, or a CHERI compartment where the hardware supports it. Semantics are identical because the language never lets references cross anyway. It is slow, but you get true blast-radius containment, and the OS tools become your debugger: `ps` lists your objects as a tree, `lsof` shows their handle tables. You can also run a single foreign C library as an `extern cell`, so a C memory bug kills only that cell.
- **Deadlock.** The kernel owns the wait-for graph of monitors. An acquisition that would close a cycle raises `gone` in the thread that closed it. This is deterministic and reported with both call chains.

## 6. Scenarios (illustrative only — not a syntax decision)

**(a) Grow a list of lines.** It is all values inside one cell.
```
fn readLines(path: String) List of String {
  f = File.open(path)              // File is a cell; we hold the only handle
  lines = List of String()
  while line = f.readLine() { lines.add(line) }   // the returned String is copied in
  return lines                     // value moves out; f's handle drops -> EOF -> file closes
}
```

**(b) A tree with parent pointers.**
```
class Node {
  parent: Node?          // up-tree handle: uncounted, cannot dangle
  kids = List of Node()  // down-tree handles: counted
  fn add(name: String) Node {
    k = Node(parent: self, name: name)   // spawned by self, so self is its parent
    kids.add(k); return k
  }
  fn remove(k: Node) { kids.remove(k) }  // last counting handle gone -> k and its subtree exit
  fn path() String { return (parent?.path() or "") + "/" + name }
}
```

**(c) A UI callback capturing the editor (the crux).**
```
class EditorWindow {
  editor = Editor()                     // child of the window
  saveButton = Button("Save")           // child of the window
  fn init() {
    saveButton.onTap = { editor.save(); editor.dirty = false }
    // The closure lives in the Button cell and holds a sibling handle to Editor (counted).
    // Editor and Button are both children of the window.
  }
}
// The window closes -> exit -> the editor and the button both die (rule 6). No cycle, no leak.
// If a document is closed on its own while a stray callback survives elsewhere:
//   { editor.save() or log("editor gone") }   // no crash, no dangling
```
If `Editor` stores `onSaved = { saveButton.flash() }`, that is a sibling cycle. Both cells still die with the window, because the parent kill (rule 5ii) ignores counts.

**(d) A shared mutable cache used by two components.**
```
class App {
  cache = Cache()                       // child of App
  search = SearchPane(cache: cache)     // the cache handle is counted in each pane
  detail = DetailPane(cache: cache)
}
class Cache { map = Map of String to Doc()
  fn get(k: String) Doc? { return map[k] }        // Doc is a struct, so callers get a copy
  fn put(k: String, d: Doc) { map[k] = d } }
// Calls from the two panes serialise on Cache's monitor. No locks to write.
```

**(e) Pass a large list to a function that mutates it.**
```
fn normalise(mut xs: List of Float) { for i in xs.indices { xs[i] = xs[i] / 255 } }
normalise(mut pixels)            // same cell: in-place, no copy
gpuPrep.normalise(mut pixels)    // another cell: lent; zero-copy, because the caller is parked on this call chain
```

**(f) Share data between threads.**
```
counter = Counter()                          // a cell is a monitor
tasks = List of Task()
for i in 1..8 { tasks.add(go counter.addBatch(chunk(i))) }   // chunk values are copied or remapped in
for t in tasks { t.wait() }
print(counter.total)
// Data races cannot happen: cell state is touched only by the thread holding its monitor.
```

## 7. What is new

- **Lifetime is borrowed from process semantics**, not from scopes, owners or region annotations. There are three death triggers (exit, parent death, EOF), and each maps to something every engineer has seen in an OS.
- **"Up-tree handles are free and immortal relative to you."** Uncounted ancestor handles cannot dangle, because the holder dies first. The expensive classic cycle, back-pointers, is removed structurally. The remaining cycles (cross-branch) are bounded by the lowest common ancestor's lifetime, and parent death overrides counts.
- **Object = monitor = isolation unit.** One mechanism provides memory isolation, data-race freedom and fault containment. Concurrency safety is not a separate feature (no `Send`/`Sync`, no `Sendable`).
- **The MMU as a borrow checker.** Cross-cell `mut` lends are safe because the caller is parked. Large values move by page remap. Nothing is annotated.
- **A semantics-preserving `--isolate` debug mode** in which objects are real OS processes, so the operating system's own tools inspect the object graph, and C FFI can be sandboxed per library.

## 8. Why it might be less crazy than it sounds, or more

**Less crazy.** Erlang, Pony, Swift actors and Midori show that isolated units at scale work in production. PIDs differs by making the isolated unit the ordinary OO object, with synchronous calls and an implicit `self`, rather than an opt-in actor with async messages. The struct/class split is already in Swift and C#. Software-isolated cells are a cell-table entry plus a slab arena, not a real process. A cross-cell call is a generation check plus an uncontended CAS, which is comparable to an ARC retain/release pair. UI frameworks already think in view trees and window lifetimes, and PIDs makes the language agree with them.

**More crazy.** Every class-to-class method call takes a lock. Code that dense-calls across thousands of tiny objects (a scene graph, an AST of `class` nodes) pays a boundary toll on every hop. Programmers will learn to push data into structs, which is good for performance but is a style tax. "A crash kills the cell" means half-updated cells are thrown away rather than repaired. That is great for servers and strange for a desktop editor whose `Document` cell dies on an index error.

**Self-assessment against the rubric.** Simplicity 3 (11 rules, and the familiar ones are cheap). Safety 5. Expressiveness 4. Implementation risk 3 (cell table, monitors, store-time ancestry check, remap). Performance 2. Concurrency 4. Tooling and FFI 4. That comes to about **71**: below O1/O4, above the round-1 band.

## 9. Known weaknesses

1. **Cross-branch cycles under a long-lived parent leak.** Example: two children of `App` that observe each other, are meant to die by EOF, and are never explicitly exited. They live until `App` exits. The tooling can show them (a "handles only from siblings" report), but nothing reclaims them automatically.
2. **The boundary tax and per-object overhead.** A million-node `class` tree means a million monitors and handle-table entries. Fine-grained OO is penalised. The answer, "use structs and indices", partly re-creates O2's handle problem for large graphs.
3. **Deadlocks become possible.** Holding your monitor while you call out (rule 9) is what makes cross-cell `mut` safe, but it allows two-thread cycles. They are detected deterministically and turned into `gone`, but the programmer still has to understand why.
4. **Re-entrancy surprises.** A callback chain can re-enter a cell mid-method on the same thread, as in any OO system with callbacks. Isolation does not fix logical re-entrancy bugs.
5. **The cost of the ancestry check.** Storing a handle into a deeply nested cell, such as a 1M-deep cell-linked list, costs O(depth) for the walk. Caching depth intervals helps, but `adopt` complicates it.
6. **Crash semantics divide opinion.** An uncaught `gone` kills the caller cell. Without discipline, one stale callback can take down a pane. The `or` fallback is easy, but forgetting it fails loudly.
7. **No sharing of read-only big data except by copy-on-write remap or by putting it in a cell.** A 2 GB immutable lookup table read by 8 threads must be a cell, which serialises the readers. The alternative is a frozen value remapped copy-on-write into each thread's cell. That works, but it is a special case to explain (it would be rule 12).
8. **`adopt` is a sharp tool.** It moves the kill-cascade guarantee and recomputes counting bits. Removing it is simpler, but then a cell created by one component and handed to another dies with its creator.
