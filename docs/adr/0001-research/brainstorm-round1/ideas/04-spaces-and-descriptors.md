# 04 — Spaces and Descriptors

## 1. Name

**Spaces and Descriptors** (short form: "turns, spaces, descriptors").

## 2. Inspiration

How an OS manages memory, mapped onto objects:

| OS concept | Memory model concept |
|---|---|
| A short-lived process: all its memory is reclaimed at exit, whatever its shape | A **turn** (event handler, thread body, `turn {}` block). Its **scratch** is freed in one go when it ends |
| A file or shared-memory segment that outlives the process | A **space**: a heap with its own lifetime, not tied to lexical scope |
| `write()` copies your buffer into the file | Storing a scratch object into a space **moves it in** |
| Pointers within one address space are just addresses | Refs within one space are plain refs. Cycles are free |
| File descriptors: checked handles to things outside you; `EBADF`/`EPIPE` when the other end is gone | Refs that cross spaces become **descriptors**. Touching a descriptor to an exited space is a checked `Closed` |
| Process tree; killing a parent kills its children | **Space tree**: `exit()` frees a space and its subtree |
| `fork()` with copy-on-write page tables | `fork(s)` copies a whole object graph through the MMU in O(pages) |
| `unlink()` of an open file is deferred until the last `close` | `exit()` is deferred until no turn is still inside the space |
| Passing fds over a Unix socket (`SCM_RIGHTS`) | Sending a whole space to another thread with no copying |
| `ps` / `top` | The debugger shows the live space tree with sizes |

## 3. Pitch

Code runs in short **turns**: one event handler, one thread body, one `turn {}` block. Anything a turn allocates is scratch, and it disappears when the turn ends, the way a process's memory disappears at exit. Data that must outlive a turn lives in a **space**. A space is a heap with an explicit, non-nested lifetime, such as a window, a session or a cache entry. Inside a space, references are ordinary pointers. Parent pointers, closures that capture `self`, and cycles cost nothing and never leak, because the space is freed as a whole. A reference that crosses into another space becomes a **descriptor** automatically. A descriptor is a checked, fd-like handle, so a window that has closed can't be dangled into. It answers `Closed`, the way a dead pipe answers `EPIPE`. Intra-space pointers are self-relative. So the runtime can fork, move, snapshot or hand off an entire space with page-table tricks, without walking the objects. The programmer never writes lifetimes, never writes `weak`, and never counts references. Their one decision is "which space does this belong to?", which is the question they already know the answer to.

## 4. The rules

1. **Turns.** Code runs in turns. These are `main`, each callback or event invocation, each thread or task body, and each `turn { }` block. Everything allocated during a turn is scratch, and it is all freed when the turn ends. Function calls within a turn share its scratch, so returning values costs nothing.
2. **Leaving a `turn {}` block.** Values the block assigns to variables declared outside it are copied to the enclosing turn. Everything else is freed.
3. **Spaces.** `space()` creates a space. `expr in s` evaluates `expr` with `s` as the allocation target.
4. **Storing moves in.** Storing a scratch object into a field of an object that lives in a space moves that object, and everything it reaches in scratch, into the space. Your existing references follow it, so identity is preserved.
5. **Inside a space, anything goes.** Any shape is allowed: cycles, parent pointers, closures capturing `self`. Nothing in a space is freed individually. Overwritten data stays until the space exits or is renewed (rule 8).
6. **Across spaces, descriptors.** A reference stored from one space to an object in another becomes a descriptor, and you don't write anything to make it one. If the target space has exited, touching the descriptor aborts the current turn with `Closed`. If that is an expected case, test with `alive(x)` first. Event sources unregister a callback whose turn ends with `Closed`.
7. **Space tree and exit.** Every space has a parent. The default parent is the space of `self`, or the root space. `s.exit()` frees `s` and its whole subtree. The free waits until no turn is still using the space. A space that is never exited lives until its parent exits.
8. **Renew.** `s.renew()` compacts a space at the end of the current turn. It keeps only what is reachable from `s.root` and from descriptors held by other spaces. Use it for long-lived spaces with churn. Or avoid churn by giving short-lived parts their own child spaces.
9. **Fork.** `fork(s)` makes a cheap copy-on-write copy of a whole space. Its descriptors still point at the same other spaces, just as a forked process shares its open files.
10. **Threads.** A space belongs to one thread. `send s to t` hands it over without copying. A `shared space()` may be used by any thread, but only inside `with s { }`, which locks the space. Scratch never crosses threads, and a value sent over a channel is copied.

Ten rules, and 3, 5 and 9 are near-trivial. There is no `weak`, no capture lists, no lifetimes, no borrow rules, and no `Rc`/`Arc`.

## 5. Under the hood

**Scratch.** Each thread has a bump allocator. Entering a turn records a mark, and ending the turn resets to that mark. At the end of a `turn {}` block, the compiler copies out the outer variables it can see assigned inside the block. Copy-out of a fresh graph is a linear copy.

**Space layout.** Each space is one contiguous virtual reservation. Large spaces are backed by an anonymous shared-memory object: `memfd` on Linux, a Mach memory entry on macOS, a pagefile-backed section on Windows. The space header sits at the base. Small spaces start as **pocket spaces**, sub-allocated from a shared slab (256 B upward), and are promoted to their own mapping when they pass about 64 KiB. Thousands of cache-entry spaces are therefore cheap.

**Self-relative pointers.** A reference field inside a space stores `target - &field`. Moving a whole space therefore keeps every intra-space pointer valid. Spaces move by `mremap`, or by `mach_vm_remap`, or by re-mapping the Windows section. The runtime relies on this for fork, growth, send and renew. Deref costs one add.

**Tagged reference fields.** The low bit of a field selects either a self-relative offset or a descriptor slot. Scratch locals hold plain absolute pointers.

**Store barrier.** It runs on every reference store into a space object. The barrier finds the source and target spaces through a global two-level radix table keyed by `address >> 16`; this is a software page table. There are three cases:
- Same space: write the offset.
- Value in scratch: move it in. The scratch subgraph is deep-copied, and each copied scratch object gets a forwarding header. Other scratch references then follow the copy. This needs a one-bit check on scratch accesses that the compiler can't prove unforwarded. The compiler places allocations in the target space directly when an allocation flows straight into a store, so most move-ins never copy.
- Value in another space: allocate a descriptor.

**Descriptors.** Three levels, as in the fd table, the open file table and the inode table:
- The holder space keeps a descriptor table inside its own pages, so `fork` duplicates it automatically.
- Each entry is `{target space id, space generation, export slot}`.
- The target space keeps an **export table** that maps export slots to offsets. Exports are refcounted by holder entries, which are bumped on store and on fork and dropped on holder exit or renew. These counts exist only on cross-space edges, never on ordinary objects.

Loading a descriptor field into a local does four things. It checks the generation, which yields `Closed` if the space has gone. It checks the owner thread (`NotYours`). It pins the target for the current turn. It returns a raw pointer. The compiler hoists repeated loads of the same descriptor within a turn.

**Exit.** Exit bumps the space's generation, so every descriptor to it is dead at once. It recursively marks the children as exiting. It unmaps the pages when the pin count reaches zero.

**Renew.** Renew copies from the roots (`s.root` and the export table) into a fresh reservation. It rewrites the export offsets and unmaps the old space. It is deferred to the end of the turn, so no scratch pointers into the old copy survive. It is a trace of one space that the programmer explicitly requests, not a background collector. See §8 on G2.

**Fork.** For mapped spaces, fork maps the backing object `MAP_PRIVATE` / `FILE_MAP_COPY` at a new reservation, so the hardware does the copy-on-write. Pocket spaces are copied with `memcpy`. Fork bumps the export refcount for every entry in the copied descriptor table.

**Containers.** List and Map buffers are owned exclusively by their container, and there is no syntax for a reference to a slot. Buffers of 64 KiB or more are separate mappings, so growth uses `mremap` and leaves no garbage. `List.copy()` of a large list is also page-level copy-on-write.

**Optional extension: `atomic turn`.** The turn writes to spaces through private copy-on-write shadow mappings. At the end it either commits by swapping the dirty pages in, or it discards them, which gives free rollback when a handler aborts with `Closed` or an error.

## 6. Scenarios

All code below is *illustrative only — not a syntax decision.*

### (a) Read a file of unknown length into a list

```
fun readLines(path) -> List {
  var lines = List()
  for line in File(path).lines() { lines.add(line) }   // scratch; buffer grows by mremap
  return lines                                         // same turn: free
}
doc.lines = readLines(p)          // moves into doc's space (one linear copy), or:
doc.lines = readLines(p) in doc   // allocate directly in doc's space, no copy
```

Scratch makes this trivial. The list's own buffer never leaves garbage behind, because growing it remaps its pages.

### (b) Tree with parent pointers

```
let t = space()
let root = Node("root") in t
t.root = root
let kid = Node("a"); kid.parent = root; root.children.add(kid)   // kid moves into t
```

The parent pointer is a plain self-relative reference in `t`. The cycle doesn't matter, because `t.exit()` frees the whole tree. Detached subtrees stay until `t.renew()`. If subtrees churn a lot, give each one a child space and exit it on removal.

### (c) UI callback capturing enclosing state (the crux)

```
class Editor {
  fun build() {
    saveButton = Button("Save") in self.space
    saveButton.onTap = { self.save(); self.dirty = false }   // closure moves into
  }                                                          // editor's space; self is
  fun close() { self.space.exit() }                          // a plain intra-space ref
}
let w = space()
let ed = Editor() in w
ed.build()
appMenu.add(MenuItem("Save", { ed.save() }))   // appMenu lives in root space
```

The editor, the button and the closure form a cycle inside `w`, which is fine: no `weak`, no capture list. The closure registered on `appMenu` moves into the root space, and its captured `ed` becomes a descriptor. After `ed.close()`, tapping the menu item aborts that one handler turn with `Closed`, and the menu unregisters the item, much like `EPIPE` on a dead pipe. If `close()` runs from inside the editor's own handler, the exit waits until that handler's turn ends.

For declarative layout (G11), each re-render builds into a fresh child space, and the previous render's space exits after the diff. Closures re-created on every render therefore never pile up.

### (d) Shared mutable cache used by two components

```
let cache = space()
cache.root = Map() in cache
fun put(k, v) { let e = space(parent: cache); e.root = v; cache.root[k] = e.root }
fun evict(k)  { spaceOf(cache.root[k]).exit(); cache.root.remove(k) }
searchPanel.cache = cache.root      // descriptor
previewPane.cache = cache.root      // descriptor
```

Each entry lives in its own pocket space, so evicting it really frees the memory. A component that kept an evicted entry gets `Closed`, never stale memory, so `alive(entry)` tells it whether to re-fetch. If the components run on different threads, use `shared space()` and access it with `with cache { ... }`.

### (e) Passing a large list to a function that mutates it

```
fun normalize(xs) { for i in 0..xs.count { xs[i] = xs[i] / xs.max } }
normalize(samples)                  // in place, by reference, zero copy
let backup = samples.copy()         // 80 MB list: page-table CoW, copied lazily
```

Within a turn or a space, references behave as in Python or Java. Data races are excluded by rule 10, not by aliasing rules.

### (f) Sharing data between threads

```
let model = loadModel() in space()           // big, read-mostly
let stats = shared space(); stats.root = Stats() in stats
for i in 0..8 {
  spawn {
    let mine = fork(spaceOf(model))          // O(pages) snapshot, private CoW
    let r = work(mine.root)
    with stats { stats.root.add(r) }         // locked
  }
}
let job = space(); job.root = buildBatch() in job
send job to worker                           // zero-copy hand-off, like SCM_RIGHTS
```

There are three tools, and each has a clear cost. Fork gives a private snapshot. `send` gives a move. `shared` with `with` gives a locked shared space. Using a space owned by another thread is a checked `NotYours`, not a data race.

## 7. What's genuinely new compared with the covered options

- **Non-nested lifetimes without lifetime inference or annotations.** Unlike scope-bound regions, spaces form a dynamic tree with explicit `exit()`. They model windows, sessions and cache entries directly, and nothing is "promoted to global". The long-lived-object leak is bounded by the owning space's life, not the program's.
- **Cycles are free, with no RC and no weak refs**, inside a space, which is where UI cycles actually live (scenario c). ARC (O1, O7) needs `weak` or a cycle collector here.
- **Automatic move-in on store (`write()` semantics).** The store barrier decides placement at run time. There is no escape analysis to get wrong and no manual `promote`.
- **Checked dangling at space granularity.** Safety checks happen only on cross-space edges, through fd-style descriptor tables with export indirection. Intra-space refs carry no generation or count (contrast O6, where every reference is checked).
- **Self-relative object graphs, so the MMU does the work.** Whole-graph fork, zero-copy thread hand-off, relocation and copy-on-write list copies use page tables, not per-object copy-on-write checks (contrast O3).
- **A `Closed` abort per turn plus auto-unregister** gives callbacks that outlive their owner a defined, safe behaviour.
- **An `atomic turn` extension**: transactional handlers built on copy-on-write pages.
- **Tooling:** a `ps`-style live space tree for the debugger (G8). Leaks become visible as "this space is still alive and its parent is root".

## 8. Known weaknesses

- **Garbage inside a space.** Overwrites leak until exit or `renew`. Programmers must learn to "give churny things their own space". `renew` is a programmer-invoked trace of one space, so G2 is **needs-john**. It is not a background or periodic collector, but it is a copy-from-roots pass.
- **Write and read barriers.** Every reference store into a space pays a space lookup. Scratch objects that may have been forwarded need a one-bit check. Descriptor loads pay a generation check, a thread check and a pin. Most of this can be hoisted, but not all.
- **`Closed` is dynamic.** The compiler can't tell which fields are descriptors, so any field load can abort the turn. That is safe, but it is a run-time failure mode the programmer has to anticipate.
- **Move-in can surprise.** Deep-moving a scratch graph on store is O(size) unless the compiler places the allocation directly. And "which space is this in?" is invisible in the source.
- **Platform VM dependence.** `memfd`, Mach VM and Windows sections, plus `mremap`-style moves, are three code paths and real implementation risk for an AI-written runtime. Pocket spaces can't use hardware copy-on-write.
- **C FFI.** C must not keep pointers into a space past the call, because spaces move on growth and renew. C structs containing pointers can't live in a space as-is (self-relative layout), so they need marshalling or a pinned "C space" with absolute pointers.
- **Locks and deadlock.** Nested `with` on shared spaces can deadlock, and a coarse lock per shared space limits parallelism.
- **Forgotten `exit()`** leaks until the parent exits. The model is safe, but not leak-proof by default.
- **G3 flag:** this relies on built-in, compiler-known `List`/`Map`, which the brief lists as a pending question.

Rough self-assessment: simplicity 3, safety 4, expressiveness 5, implementation risk 2, performance 4, concurrency 4, tooling and FFI 3. That gives about 70, conditional on the G2 ruling on `renew`.
