# 05 — Chronicle: pointers point to the past, names point to the present

## 1. Name

**Chronicle.** Its slogan: *strong pointers may only point to the past. Anything that changes is reached by name.*

## 2. Inspiration — how the lens maps onto memory

Git works in a way that maps onto memory:

- **Commits and blobs are immutable**, and each one can only point at objects that already existed. So the commit graph is acyclic by construction. Nobody needs a cycle collector for git objects. Dropping a ref and pruning what is unreachable is enough.
- **The working tree is where identity lives.** `src/editor.swift` is a *path*, which is a name. The path keeps its identity across many versions of its contents. If you delete it, the name stops resolving, but every old commit that saw the file still has it.
- **Deletion is staged and then committed.** Nothing disappears in the middle of a command.
- **Concurrent writers do not share a working copy.** They work on their own copy and send changes to a single place where they are applied in order (push and merge, or event sourcing).

Chronicle maps each of these onto memory:

| Git | Chronicle |
|---|---|
| blob/commit | **value**: immutable, ref-counted, acyclic |
| path in the working tree | **object**: a slot in a *world tree*, reached by a **link** |
| staged `git rm`, applied on commit | **`remove`**: takes effect at the end of the current **turn** |
| an old commit still shows a deleted file | a **snapshot** you hold stays valid after its object is removed |
| push / event log to one upstream | **`send`**: cross-thread writes are queued to the object's home thread |
| turn boundaries | **epochs**, used to reclaim memory shared across threads |

## 3. Pitch

Chronicle splits the heap in two, along the line between time and identity. **Values** cover everything that is just data: numbers, strings, records, lists, maps and closures. Values are immutable and reference-counted. A value can only point to values that existed before it was built, so cycles are impossible and plain RC is complete. There are no weak refs and no cycle collector. **Objects** (`class`) are the things with identity: editors, windows, sessions, caches. They do not float in the heap. Each one sits at a location in an explicit, inspectable **world tree**, and its parent owns it. Every variable, field or capture that refers to an object holds a **link**. A link is a generation-checked name that never keeps anything alive. Reading an object's field gives you a snapshot value. Writing a field makes a new version, done in place when nobody holds the old one. `remove` is staged until the end of the current *turn* (one event handler or one message). Within a turn, every link you hold therefore stays valid. A callback that fires after its object is gone is simply skipped. Threads read anything as snapshots and change foreign objects only by sending messages to the object's home thread. The result: no ownership, no borrows, no lifetimes, no weak refs, no cycles and no GC run.

## 4. The rules (everything a programmer must learn)

1. **There are two kinds of thing.** *Objects* are instances of a `class`. Everything else is a *value*: numbers, strings, records, `List`, `Map` and closures.
2. **Values never change under you.** Assigning or passing a value gives the receiver its own copy as far as meaning goes. `var` locals and parameters can be modified (`xs.append(x)`, `xs[i] = y`), but that only changes *your* version. A value is never physically copied unless someone still holds the old version.
3. **Values free themselves.** A value lives as long as something holds it. There is nothing to do and nothing to annotate.
4. **Every object has a place in the world tree.** `Editor(...)` puts the new object under `self`. Outside any method it goes under `app`. Write `Editor(...) in w` to put it under `w`, or `in turn` for a scratch object. Every object has `parent` and `children`. `move x to y` re-parents it.
5. **Object-typed variables, fields and captures hold links.** A link names an object. It never keeps the object alive. Only the tree does that.
6. **`remove x` removes x and everything under it, at the end of the current turn.** A turn is one event handler, one `send`-ed message, or one `turn { }` block. Each iteration of a loop in `main` or in a thread body is also a turn.
7. **Using a link to a removed object traps.** The trap message says which object it was, who removed it and in which turn. Test with `x.alive` when it might be gone.
8. **Reading an object's field gives you a snapshot. Writing it makes a new version.** Anyone holding the old snapshot keeps seeing the old data, safely, even after the object is removed.
9. **Closures capture values as frozen snapshots and objects as links.** To mutate shared state from a closure, put the state in an object, usually `self`. If a callback (a closure that returns nothing) is called after an object it captured has gone, the call is skipped.
10. **Threads.** Values can go to any thread. An object belongs to the thread that made it. Other threads can read its fields as snapshots. They change it only with `send obj.method(args)`, which runs later as a turn on the object's home thread.

There are no lifetimes, borrows, moves, weak/unowned, `inout` or ownership annotations. The cost is a split between two kinds of type (rule 1), which is the same split as Swift's struct/class but with simpler semantics on each side.

## 5. Under the hood

**Values.** Values are heap nodes with a refcount. The compiler inserts dup/drop operations, Perceus-style, and moves a value on its last use. Any update to a node with RC==1 reuses it in place. `List` is a chunked or RRB vector with a mutable tail, and `Map` is a HAMT. While a value is unique, appends and sets are in place and amortised O(1). Once it is shared, the update copies only the path to the change. **The invariant "pointers point to the past":** a node can only reference nodes that existed when it was built. In-place reuse cannot break this, because any node that someone points at has RC > 1 and is never reused. A closure environment is a value, and the links in it are not counted. So the value heap is a DAG. Freeing is deterministic and happens at the last drop, so RC is complete. There is no weak-ref table and no cycle scan.

**World tree.** There is one slot table per thread. Each slot holds `{generation, state: value*, parent, firstChild, nextSibling, classId}`. A link is a 64-bit `(thread:8, index:32, gen:24)`. To resolve a link the runtime compares one generation number. An object's fields are a single record value (`state`). A field write such as `self.items.append(x)` becomes an update on the `state` path, done in place when the state and `items` are unique. This is the common case.

**Turns are commits.** `remove` pushes onto the thread's removal queue. At the end of a turn the runtime walks each queued subtree. For each object it bumps the generation, drops `state` (which cascades RC frees, bounded by what was removed) and frees the slot. Because removal is staged, **a link that resolved once in a turn stays valid for the rest of that turn**. The compiler can therefore hoist generation checks out of loops and across calls. One check per link per function is typical. Debug builds keep a tombstone side table `(slot, gen) → {removed by, stack, turn #}`, which is what rule 7's trap message comes from.

**Closures.** A closure is `{code, env value, captured-links[]}`. The call stub for a closure that returns nothing checks the generation of each captured link and returns early if any is dead. A closure that returns a value traps instead (rule 7).

**Threads and epochs.** An object read from another thread is marked *published*. From then on, writes to its `state` swap an atomic pointer and never mutate in place. Values that become reachable from a published state are marked atomic-RC, transitively, stopping at nodes that are already marked. A replaced state, or a freed slot, of a published object is *retired*, not freed. It is reclaimed when every thread has passed a turn boundary (epoch-based reclamation). Long turns in thread bodies get a cheap epoch-announce store at loop back-edges. Nothing ever scans the heap. `send` enqueues `(link, method, args)` on the home thread's mailbox, and the mailbox is drained one message per turn.

**C FFI.** For the duration of a call, a value is passed to C as a pinned borrowed pointer. `Bytes` is a flat buffer that is mutated in place while unique. Objects cross the boundary as their 64-bit link, which is an opaque handle to C.

**Tooling (G8).** The debugger shows the world tree live, in the style of `git ls-tree`. Every leak is a visible subtree, never a hidden cycle. Debug builds can keep a ring buffer of the last N states of each object, so you can step back through an object's history. Values are immutable, so this is cheap.

## 6. Scenarios

*(All code: illustrative only — not a syntax decision.)*

### (a) Read a file into a growing list of lines

```
fun readLines(path: String) List {
  var lines = List()
  for line in File.open(path).lines() {
    lines.append(line)          // unique, so appended in place
  }
  return lines                  // moved out, not copied
}
```
`lines` is a value with exactly one holder, so each append mutates the tail in place, as fast as a `Vec`. There is a bonus from versioning. `for x in self.items { self.items.append(...) }` iterates over the snapshot taken when the loop started, so iterator invalidation cannot happen.

### (b) Tree with parent pointers

```
class Node {
  name: String
  fun add(n: String) Node { return Node(n) }      // new node goes under self
  fun path() String {
    if parent is Node p { return p.path() + "/" + name }
    return name
  }
}
let root = Node("root")          // under app
let b = root.add("a").add("b")
print(b.path())                  // root/a/b
remove root.children[0]          // "a" and "b" go at end of turn
```
The world tree *is* the data tree. Parent pointers are built in and cost nothing extra. The parent owns its children and a child names its parent, so there is no cycle. If you want a tree with no identity (a pure data tree such as a parse tree), make it a value. It then has no parent pointers. Walk it with a path or zipper instead.

### (c) UI callback capturing enclosing state (the crux)

```
class Editor {
  text: String
  dirty: Bool
  fun build() {
    let save = Button("Save")           // child of this editor
    save.onTap = { self.save() }        // captures a LINK to self
    let close = Button("Close")
    close.onTap = { parent.remove(); log("closing") }   // safe: removal is staged
  }
  fun save() { File.write(path, text); dirty = false }
}
```
There is no `[weak self]`, no retain cycle and no lifetime. The button's closure names the editor but does not own it. When the window is removed, the editor and its buttons go at the end of that turn. A tap that is already queued arrives in a later turn and finds its button or its `self` gone, so it is skipped (rule 9). Destroying an object inside its own callback is a classic crash, and here it is harmless: `log("closing")` still runs, because the removal is only staged. Mutating the editor from the callback is just a field write on `self`.

### (d) Shared mutable cache used by two components

```
class Cache {
  entries: Map                                   // String -> Bytes
  fun get(k: String) Bytes? { return entries[k] }
  fun put(k: String, v: Bytes) { entries[k] = v }
  fun evict(k: String) { entries.remove(k) }
}
class App {
  fun start() {
    let cache = Cache()                          // under app
    ImageLoader(cache)                           // each component holds a link
    Thumbnailer(cache)
  }
}
// inside ImageLoader:
let img = cache.get(url)       // a snapshot value
cache2.evict(url)              // (Thumbnailer does this)
draw(img)                      // still fine: img is kept alive by this holder
```
The cache has one owner, its parent in the tree. Both components hold links, and either can mutate the cache. A cache entry's lifetime is not tied to any scope. An entry is freed when it has been evicted *and* the last reader has dropped its snapshot. There are no dangling reads and no stale-pointer bugs.

### (e) Pass a large list to a function that mutates it

```
fun normalise(xs: List) List {
  for i in 0..xs.count { xs[i] = clamp(xs[i], 0.0, 1.0) }
  return xs
}
samples = normalise(samples)     // last use of old samples: handed over, in place
let before = samples
samples = normalise(samples)     // `before` still holds it: ONE copy, before unchanged
```
The handover pattern `x = f(x)` costs nothing when the caller does not keep the old version. When the caller does keep it, the copy is the honest price of keeping history, and the profiler shows it. For a list that lives in an object, a method mutates `self.samples` directly, in place.

### (f) Sharing data between threads

```
class Stats { total: Int  fun add(n: Int) { total += n } }
let stats = Stats()
let table = loadTable()                // a big value
for part in table.split(4) {
  spawn {                              // captures part (value), stats (link)
    let n = countMatches(part)         // pure read, no locks
    send stats.add(n)                  // queued; runs on stats' home thread
  }
}
print(stats.total)                     // snapshot read, from any thread
```
Values are immutable, so sharing them is free and race-free. An object has exactly one mutating thread, so there are no data races and no locks for user code. Event sourcing in miniature: concurrent writers send messages that are applied in order at the object's home. Memory freed across threads waits for turn-boundary epochs, never for a collector.

## 7. What's genuinely new vs. the covered options

- **The arrow of time as the cycle-breaker.** O1 needs weak refs and O7 needs a cycle collector. Chronicle makes cycles unrepresentable: counted pointers only reach immutable, older values, and identity is reached only through uncounted names. Unlike O2/O3, references do exist (links), and closures and OO use them freely.
- **Ownership is by location, not by variable.** O4, O5 and O6 tie ownership to variables, so you need moves and borrows. In Chronicle an object never moves between variables. It sits in a tree that you can inspect, and its lifetime is "where you put it". This handles non-nesting lifetimes such as sessions, windows and cache entries without regions (cf. scope-bound regions) and without promotion.
- **Staged removal at turn boundaries.** Links are valid for the whole turn, so the compiler can hoist checks far more aggressively than per-dereference generational refs (O6). Destroy-during-callback bugs disappear. The same boundaries double as reclamation epochs for threads.
- **Stale is safe.** Holding data from a removed object is legal, because what you hold is a snapshot, as in an old git commit. The only failure is an explicit dead link at an identity operation, and its trap names who removed the object and when.
- **Callbacks die with their subjects.** Callbacks auto-skip when what they captured is gone. This removes `[weak self]`, the most common ARC burden.
- **A built-in version history for debugging, and undo almost for free.** An undo stack is just a `List` of state snapshots that share structure.

## 8. Known weaknesses

- **Leaks are still possible.** A leak is an object that nobody removed. It is visible in the tree, never a hidden cycle, but it is real. Objects made in methods accumulate under `self` unless you use `in turn`.
- **The value/object split must be taught.** Snapshot semantics surprise people who expect reference semantics: after `let d = editor.doc; editor.doc.x = 1`, `d.x` is still the old value.
- **Captured locals are frozen.** Writing `{ count += 1 }` needs `count` to live in an object. This is a real tax for small DSL closures.
- **A dead link is a runtime trap, not a compile error.** It is safe and well reported, but it is still a crash, much like a null.
- **Performance cliffs.** In-place updates depend on uniqueness, which the programmer cannot see. Once data is shared, persistent structures are slower than flat arrays.
- **`send` is asynchronous and fire-and-forget.** A cross-thread request that needs an answer requires a reply callback. Parallel in-place mutation of one huge array means splitting it into values and merging the results.
- **"Turn" is awkward in batch programs.** Removal latency is up to a turn. Long turns delay cross-thread reclamation, which needs back-edge epoch announcements.
- **`parent` is untyped,** so it needs `is` checks.
- **G3 flag:** this design depends on built-in, compiler-known `List` and `Map` (needs-john). **G2:** reclamation deferred by epochs is not a GC run, because nothing traces the heap, but the analysts should confirm this.
- **Implementation risk is medium-high.** The parts are Perceus-style dup/drop and reuse analysis, RRB/HAMT containers, slot tables, epoch-based reclamation and mailboxes. Each is well understood, but together they are a lot for a compiler written ~95% by an AI agent.
