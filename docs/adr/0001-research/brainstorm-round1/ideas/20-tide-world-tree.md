# 20 — Tide: one world tree, and everything else goes out with the tide

## 1. Name

**Tide.** Memory comes in freely during a *turn* (one event, callback, or `main`). When the
turn ends, the tide goes out and anything not attached to the **world tree** is freed.

## 2. Inspiration — how the lens maps onto memory

The hard cases in the brief (sessions, windows, cache entries, callbacks firing later) are
hard because **raw references survive across time** and point at things whose lifetimes
don't nest. Tide doesn't try to manage those references better. It makes them impossible:

- **Inside a turn**, every lifetime nests trivially: nothing is freed until the turn ends,
  so any reference taken during the turn stays valid for the whole turn. Programmers can
  alias freely, like in Java or Python, without refcounts or borrow checking.
- **Between turns** only one structure survives: a single ownership *tree* rooted at
  `world`. Every relationship that isn't a tree edge is stored as an **address** (a
  checked name), never as a pointer.

So lifetime becomes **a place**: a session lives exactly as long as it hangs under
`world.sessions`. The programmer already knows where it belongs, and putting it there replaces
every lifetime annotation. Cycles can't form, because a tree has none and addresses don't own.

## 3. Pitch

A Tide program is a world tree plus a stream of turns. Within a turn you write ordinary
reference-semantics OO code with implicit `self`, and nothing can dangle. At turn end the
runtime frees every tree not hanging from `world`: this turn's temporaries and anything you
detached. To keep something, attach it. To refer to something you don't own, use a `link`
(an address that reads back as `T?`). Stored closures capture objects by address, so
`onTap { save() }` can neither leak its editor nor call into a freed one. Threads get their
own worlds (*realms*), and a detached subtree can be handed to another realm with no copying.

## 4. The rules (everything a programmer must learn)

1. **Values vs objects.** Numbers, bools, strings and `struct`s are values: they are copied.
   `class` instances, `List` and `Map` are objects: variables hold references to them.
2. **Turns.** Every event handler, callback and `main` runs as a *turn*. During a turn,
   nothing is ever freed, so you can use and share references however you like.
3. **Ownership is a tree.** Putting an object into a class-typed field, or into a list or map
   element, makes it that slot's *child*. An object has at most one owner. Storing an object
   that already has an owner traps. Call `detach(x)` first to move it.
4. **The world.** `world` is the root object. **When a turn ends, every object not reachable
   through child edges from `world` is freed.** (This is the one memory rule.)
5. **Links.** A field declared `link f: T` holds an address, not ownership. Reading it gives
   `T?`. It is `none` once the target has been freed.
6. **Closures** capture values by copy and objects by address. If a stored closure runs and a
   captured object is gone, the closure does nothing and returns `none`.
7. **`await` ends the turn.** After an `await`, object variables are re-resolved. If any of
   them is gone, the task is cancelled.
8. **Nested turns.** `turn { … }` frees its unattached temporaries when the block ends, which
   is useful in long loops. Inside one, new objects may be attached to the world or returned
   from the block. Storing them into older temporaries traps.
9. **Realms (threads).** Each thread has its own world. `enter r { … }` runs a turn on realm
   `r` under its lock. Only values and newly created (unattached) objects may cross a realm
   boundary. Objects that cross are moved, not copied.
10. **`parallel`** blocks may read the current world but not write to it (trap). Each worker's
    new objects are moved back to the caller when the block finishes.

Ten rules. Rules 1–6 are all most UI and app code ever needs.

## 5. Under the hood

**Object header** (16 bytes): `owner` (a tagged word: an owner pointer, or this object's
floating-list index if it has no owner), address-slot index (0 until it is first linked),
`depth` (turn depth of creation, 0 for the world), and flags.

**Floating list.** Each turn has a list of *roots*: objects created this turn that have no owner,
plus subtrees detached this turn. **Child store** (`obj.f = x`, `list.push(x)`) is a compiler-
emitted barrier. If `x.owner != null`, it traps "already owned". Otherwise it sets
`x.owner = obj` and swap-removes `x` from the floating list in O(1). Any child being replaced
is pushed onto the list. At turn end, every entry left on the list is freed recursively through
compiler-generated per-class `drop_children`. This is deterministic, linear in the garbage,
never visits live data, and so is **not a GC run**. A huge free (closing a 1 GB window) can be
handed to a background thread, because nothing can reference that memory any more.

**Addresses.** A realm-local slot table (index + generation), built only for objects that
are actually linked or captured. `link` load = bounds check + generation compare. Freeing an
object bumps its slot's generation. Addresses carry a realm id for cross-realm use.

**Closures.** The environment stores object captures as addresses and value captures by copy.
Optimisation: a closure the compiler can see doesn't escape the turn (e.g. passed straight to
`List.map`) keeps raw pointers. The semantics are the same, since nothing is freed mid-turn.

**Async.** An async frame is an object owned by the realm's task table. At each `await` the
compiler turns object locals into addresses (live temporaries become the frame's children)
and re-resolves them on resume. **Nested turns and parallel workers** each get their own
floating list and a higher `depth`. One barrier covers rules 8 and 10: storing a depth-d object
into an object of depth 1..d-1 traps, and inside `parallel` any store into depth < d traps.

**Values in objects and interior references.** A string stored in a field is owned by that
field. An overwritten one goes onto the floating list rather than straight to `free`. There is
no address-of operator: `xs[i]` gives a value or an object reference, never a pointer into the
list's storage. So list storage can be `realloc`'d at any time, and iterators are (list, index) pairs.

**Debugger bonus (G8).** Between turns, the whole live heap *is* the world tree. A debugger
can browse it by path (`world.windows[2].editor`), and a leak is a node you can see hanging.

## 6. Scenarios (illustrative only — not a syntax decision)

### (a) Read a file into a growing list of lines

```
fn main()
  lines = List of String()
  for line in File.open("big.txt").lines()
    lines.push(line)              // String is a value; the list's storage grows via realloc
  print(lines.count)
```

`main` is one turn. `lines` is a temporary freed when `main` ends. For a long-running batch
job that processes many files, wrap each file in `turn { … }` and return or attach whatever
should be kept. The per-file temporaries are then freed when the block ends.

### (b) Tree with parent pointers

```
class Node
  name: String
  kids: List of Node        // children: owned
  link up: Node             // parent: an address, no ownership

  fn add(n: Node)
    kids.push(n)            // n becomes kids' child; traps if n already has a parent
    n.up = self

  fn path() -> String
    p = up                  // Node?
    if p == none return name
    return p.path() + "/" + name
```

There's no cycle, because `up` is a link. Removing a subtree (`detach(kids.remove(3))`) frees
it at turn end, and any stray link into it then reads `none`.

### (c) UI callback capturing enclosing state (the crux)

```
class Editor
  text: String
  dirty: Bool
  toolbar: Toolbar

  fn init()
    toolbar = Toolbar([
      Button("Save",  onTap: { save() }),       // captures self *by address*
      Button("Clear", onTap: { text = ""; dirty = true })
    ])

  fn save()
    snapshot = text
    await disk.write(path, snapshot)            // turn ends here
    dirty = false                               // self re-resolved; if the editor closed, task cancelled

fn openEditor()  world.windows.push(Window(Editor()))
fn closeEditor(w: Window)  detach(world.windows.remove(w))
```

A tap starts a turn. The runtime finds the button, runs `onTap`, the closure resolves `self`,
and `save()` mutates the editor through ordinary implicit-`self` code. Closing the window
detaches the whole subtree (window, editor, toolbar, buttons, closures), which is freed at turn
end. There's nothing to choose between weak and strong, no `[weak self]`, and no cycle is
possible. A timer elsewhere that captured the editor quietly becomes a no-op, and an in-flight
save is cancelled after its `await`.

### (d) Shared mutable cache used by two components

```
class Cache
  entries: Map of String to Entry          // cache owns entries
  fn get(k: String) -> Entry?  entries[k]
  fn evict(k: String)  detach(entries.remove(k))

class Gallery
  link cache: Cache
  link hero: Entry                         // survives eviction safely
  fn show(k: String)
    e = cache?.get(k)                      // a plain reference, fine for this whole turn
    if e != none { draw(e.pixels); hero = e }
  fn redraw()
    if hero != none draw(hero.pixels)      // none after eviction

world.cache = Cache()
world.gallery = Gallery(cache: world.cache)
world.search  = Search(cache: world.cache)
```

The cache has exactly one owner (the world). Both components hold links to it. An entry
evicted during a turn stays valid for the rest of that turn and is freed at turn end. Any links
to it read `none` from then on, which is exactly what a cache reference should do.

### (e) Pass a large list to a function that mutates it

```
fn normalize(xs: List of Float)
  m = xs.max()
  for i in 0..xs.count  xs[i] = xs[i] / m

normalize(world.samples)       // in place, no copy
normalize(tmp)                 // works the same on a temporary
```

Lists are objects, so passing one passes a reference. No `inout`, no borrow, no copy. Aliasing
is allowed (same behaviour as Java). Mutating a list while iterating can't dangle, because
iterators are index-based.

### (f) Sharing data between threads

```
// fork-join over shared read-only data
thumbs = parallel for img in world.gallery.images   // workers read the world, writes trap
  makeThumb(img.pixels)                             // new objects, moved back to the caller
world.gallery.thumbs = thumbs

// a long-lived shared cache in its own realm
cacheRealm = Realm(Cache())
bytes = enter cacheRealm { it.get(key)?.pixels.copy() }   // turn on that realm, under its lock

// hand off a whole subtree to a worker thread
job = detach(world.pending.remove(0))
worker.send(job)                                          // a move: no copying, no sharing
```

Between turns a realm contains only tree edges and addresses, so a detached subtree has no
incoming raw pointers. Moving it to another realm means re-registering its address slots, and
that's all. Data races are ruled out structurally: each realm is single-threaded, `enter`
takes a lock, and `parallel` freezes the world for writing.

## 7. What's genuinely new vs. the covered options

- **Lifetime is a place, not a type or a count.** Unlike O1/O4/O7 there is no strong count at
  all. Unlike O5 there are no lifetime parameters. Unlike O2/O3 objects have identity and
  reference semantics.
- **Turn-granular deferred free.** You get unrestricted aliasing within a turn without RC, a
  borrow checker, or generation checks on every dereference. O6 checks every reference. Tide
  checks only `link` reads and closure captures, which are the points where time passes.
- **Not scope-bound regions.** The temporary region is the *event*, not a lexical scope.
  Survivors aren't promoted into a global region that leaks: they're attached to a tree and
  freed deterministically when detached. Unlike MLKit, no GC is needed, because the graph that
  survives a turn is a tree plus addresses.
- **Callbacks capture by address** ("gone means no-op") and **`await` ends the turn**
  (auto-cancel). Together these remove the UI-callback crux instead of mitigating it.
- **Realms with free subtree hand-off**, safe *because* no raw pointer survives a turn.
  The heap is a browsable tree. Slot maps (covered) appear only as how `link` is implemented.

## 8. Known weaknesses

- **Long turns hoard memory.** A batch program that never yields keeps every temporary until
  the turn ends. `turn { }` blocks and escape analysis help, but someone has to remember to use
  them. This is the biggest risk for compilers, servers and other non-event-driven code.
- **Many checks happen at runtime:** double ownership, young-into-old stores, writes during
  `parallel`. They are clear and deterministic, but they are traps, not compile errors.
- **Silent no-ops can hide bugs.** A callback that never fires because its target is gone needs
  debug-mode logging.
- **Non-tree sharing is awkward.** Something genuinely shared by two equal owners (a texture
  used by two scenes) must be given one explicit owner (`world.assets`) and removed by hand.
  Forgetting to remove it is a visible leak, but it is still a leak.
- **Costs:** a 16-byte header per object. `link` reads return `T?` and pay a table lookup.
  Turn-end frees can cause a pause after a big detach (this can be moved to a background thread).
- Destructors run at turn end, not when you detach. C code must not keep pointers past a turn.
  Cross-realm `enter` can deadlock if realms are entered in inconsistent orders.
- **G3 flag:** this needs built-in parameterised `List of T` / `Map of K to V`. It's the same
  open question as for every other option.
- **Self-assessment (rough):** G2 pass (no tracing, but needs-john on whether a turn-end sweep
  of garbage counts as a "run"). Simplicity 4, safety 4 (runtime traps), expressiveness 5,
  implementation risk 3, performance 3, concurrency 4, tooling 4. That's roughly 77/100.
