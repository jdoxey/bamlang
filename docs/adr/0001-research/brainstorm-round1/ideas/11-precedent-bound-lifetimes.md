# 11 — Precedent-Bound Lifetimes ("Cells and Formulas")

## 1. Name

**Precedent-Bound Lifetimes.** Data is *cells*, each with one owner. Every reference that is not
ownership is a *link*. Every closure is a *formula*. In a spreadsheet, deleting a cell does not
wait for the formulas that use it to let go. Instead the formulas turn into `#REF!`. This model
makes that the memory rule.

## 2. Inspiration — how the lens maps onto memory

| Spreadsheet / dataflow | Memory model |
|---|---|
| A cell lives on a sheet. The sheet owns it, not the formulas that read it | Every cell has exactly one owner. References never keep anything alive |
| A formula's *precedents* are the cells it reads | A closure's precedents are the cells it captures |
| Delete a precedent and the dependents become `#REF!` | When a cell dies, death travels forward along the dependency graph: link fields go blank, formulas are disposed, and their slots go blank |
| A range shrinks when you delete a row inside it | A container slot that goes blank is removed |
| Trace Precedents / Trace Dependents | The debugger shows why something is blank: "disposed because `editor` died at tabs.ox:41" |
| Edits are not applied in the middle of a recalculation | A cell that is in use (pinned) dies when the use ends, not part-way through |
| Paste-as-values breaks the formulas in a copied block | Moving a subtree to another thread cuts every link that crosses its boundary |

ARC lets *life flow backward*: whoever holds a reference keeps the target alive, and that is where
cycles come from. Spreadsheets let *death flow forward*: the target decides when it dies, and the
things that depend on it are told. That reversal is the whole idea.

## 3. Pitch

Every object has one owner. That owner can be a local, a field, a list slot or a formula, and the
object dies the moment its owner lets go. There is no shared ownership, so cycles that leak cannot
exist. Every other reference is a link. Links never extend a lifetime. Instead each target keeps a
list of its dependents. When the target dies, its link fields become `none` and the closures that
captured it are disposed automatically, which blanks the slots holding them. Lists and maps
quietly remove slots that go blank. Closures are formulas, and a formula lives exactly as long as
the shortest-lived of its home slot and its captured cells. So a button's `onTap` that captures
`self` cannot form a retain cycle. It needs no `[weak self]`, and inside its body `self` is
guaranteed to be alive. If code is using an object at the moment its owner drops it, the object's
death is put off until that scope ends. It never dangles and it never traps. Nothing scans the
heap, and every free happens at a known point.

## 4. The rules

1. **Values and cells.** Numbers, booleans, strings and small records are *values* and are copied.
   Objects, lists and maps are *cells*: they have identity and live on the heap.
2. **One owner.** Every cell has exactly one owner: a local variable, a field, a container slot or
   a formula. When the owner goes away or is overwritten, the cell dies, and so does everything it
   owns.
3. **Everything else is a link.** If you create a cell (a constructor, or a function that returns
   one), you own it. Any other way of getting at a cell, such as reading a field, indexing a list
   or receiving a parameter, gives you a *link*. Links never keep anything alive.
4. **`take` moves ownership.** You must write `take` to move a cell into an owning place, for
   example `list.add(take b)`, a field, or another thread. Taking from a field leaves `none`
   behind, so only optional fields can be taken from. Lists use `remove`.
5. **Link fields blank.** A field declared `link` is always optional. When its target dies it
   becomes `none`, so you check it (`parent?.name`, `if let p = parent`).
6. **Links you are using don't vanish.** A link held in a local variable or parameter is always
   valid in its scope. If the owner lets go while you hold it, the cell dies when your scope ends.
7. **Closures are formulas.** A formula's *precedents* are the cells it captures, including an
   implicit `self`. It is disposed as soon as **any** precedent dies or its home slot lets go, and
   the slot becomes `none`. Inside the body, every precedent is guaranteed to be alive.
8. **`take` in a capture.** A formula can own state: `{ take counter ... }` moves `counter` into the
   formula, so it is not a precedent.
9. **Blank slots leave containers.** In a `List of link T`, a `Map of (link K -> V)` or a list of
   formulas, any element that goes blank is removed. A dead key's entry is removed together with
   its value.
10. **One book per thread.** Links cannot cross threads. `send take x` moves a subtree to another
    thread and cuts every link that crosses its edge ("paste values"). `parallel { }` lets child
    threads read, but not write, the parent's cells. Shared mutable state lives in a `sheet` and is
    reached with `lock s { }`.

That is ten rules, with no strong/weak/unowned choice, no capture lists, no lifetimes and no
cycle-breaking idioms.

## 5. Under the hood

- **Cell header (16 bytes).** `pins: u32`, `state` bits (alive / dying / dead), `book: u16` (the
  thread), and `deps: *DepNode`, the head of an intrusive doubly linked list of dependents.
- **Link field = 3 words** `{target, prev, next}`. It is threaded onto the target's `deps` ring.
  Storing a link is an O(1) splice and overwriting one is an O(1) unsplice.
- **Formula = closure record + one `DepNode` per captured cell + a back-pointer to its home slot.**
  The compiler computes the precedent set syntactically: free variables of cell type, plus `self`
  if any member is used. Captures of value type are copied.
- **Drop(c).** The cell is detached from its owner. If `c.pins > 0`, it is marked `dying` and the
  rest of the work happens when the pin count reaches zero. Otherwise it **dies**:
  1. Walk `deps` using a worklist, not recursion. Each link field is set to `none`. Each formula
     is disposed: its other DepNodes are unspliced, its home slot is set to `none`, and its
     `take`-captured cells are dropped, which can cascade. Container slots get a tombstone.
  2. Run `deinit`.
  3. Drop the owned children. Free.
- **Fast path.** If `deps == null && pins == 0`, the cell is freed immediately, exactly like a
  `unique_ptr`. That covers scenarios (a) and (e) and most temporaries.
- **Pins.** These are non-atomic inc/dec on local links and parameters. The compiler removes them
  when the scope cannot cause a drop: it makes no calls to non-pure functions and does no stores
  to owned or optional fields. A running formula pins its precedents and itself, which makes
  re-entrant self-destruction safe.
- **Containers.** Tombstoned slots are skipped by iteration and compacted when no iterator is
  active. That is the only time indices shift.
- **Threads.** `book` is checked on every link store. Crossing books traps, and when proven
  statically the check is removed. `send` walks the subtree and severs links into it and out of it.
  `parallel` suspends the parent, so its cells are frozen and children need no pins. A `sheet` is
  a mutex-guarded book: links into or out of it trap.
- **Debugging (G8).** In debug builds, every blanking records `(victim, cause cell, drop site)`. The
  debugger offers "trace dependents" on a live cell and "why blank?" on a `none` link or a disposed
  callback slot. In development builds, a formula disposed because a *local* precedent died prints
  a warning, which catches the most common mistake.
- **FFI.** A cell passed to C is pinned for the duration of the call. C code that keeps a cell
  long-term gets an opaque handle, which is a link in a runtime table that blanks the same way.
- **No GC run (G2).** All work happens synchronously at drop or unpin, and its cost is proportional
  to what dies plus its dependents.

## 6. Scenarios

All code is *illustrative only — not a syntax decision.*

**(a) Lines of a file**
```
func readLines(path: String) -> List of String
  let lines = List of String()     // owned
  for line in File.open(path).lines
    lines.add(line)                // values; list grows normally
  return take lines
```
Nothing has dependents, so every free takes the fast path. This is plain unique ownership.

**(b) Tree with parent pointers**
```
class Node
  name: String
  children: List of Node           // owned
  link parent: Node                // optional, blanks
  func add(take child: Node)
    child.parent = self            // a link: splices onto self's deps
    children.add(take child)
  func path() -> String
    if let p = parent { return p.path() + "/" + name }
    return name
```
Dropping the root drops the children. Each child's `parent` link is unspliced as it dies. If you
detach a subtree with `let n = take root.children.remove(0)`, `n.parent` is still valid until the
old parent dies, and then it becomes `none` on its own.

**(c) UI callback capturing enclosing state (the crux)**
```
class Editor
  text: String
  view: Column
  init()
    let save = Button("Save")
    save.onTap = { save(); text = "" }       // formula; precedent: self
    view = Column(take save)
  func save()
    disk.write(text)

// The toolbar outlives the editor tab:
window.toolbar.add(Button("Close", onTap: { window.tabs.remove(editor) }))
```
There are no capture lists and no weak-self dance. The formula does not own the editor, so no
cycle can form. If the editor dies first, the formula is disposed and `onTap` becomes `none`, so the
toolbar button can grey itself out by noticing that. The "Close" formula removes its own precedent
while it is running. The editor is pinned, so it dies when the formula returns, and that death then
disposes the formula. Inside every body, `text` and `self` are guaranteed to be alive.

**(d) Shared mutable cache used by two components**
```
class App
  cache: ThumbCache                          // App owns the cache
  gallery: Gallery
  inspector: Inspector
  init()
    cache = ThumbCache()
    gallery = Gallery(cache)                 // param is a link; Gallery keeps `link cache`
    inspector = Inspector(cache)

class ThumbCache
  thumbs: Map of (link Doc -> Image)         // keyed by a link
  func get(doc: Doc) -> Image
    return thumbs[doc] ?? thumbs.put(doc, render(doc))

// in Gallery:  cache?.get(doc)
```
The cache has one owner, and both components hold links to it. The cache is keyed by links, so
when a `Doc` dies its thumbnail entry removes itself. Invalidation on lifetime comes free, with no
eviction code and no weak-map library. A component that holds a link to an entry sees `none` after
eviction, which is the honest answer for the brief's "cache entries" non-nesting case.

**(e) Pass a large list to a function that mutates it**
```
func normalize(xs: List of Float)            // param = pinned link, no copy
  let m = xs.max()
  for i in 0 ..< xs.count { xs[i] = xs[i] / m }

normalize(samples)                           // in place
consume(take samples)                        // only if the callee should own it
```
Mutation goes through the link. Aliasing is allowed and memory-safe, because links point only at
whole cells and never into a list's buffer, so a reallocation cannot leave anything dangling.

**(f) Sharing data between threads**
```
let img = loadImage()
let hist = parallel for band in img.bands { histogram(band) }   // read-only, parent frozen

let stats = sheet Stats()                                      // shared mutable
parallel for f in files { lock stats { stats.count += f.lines } }

worker.send(take job)      // paste-values: links into/out of `job` blank; formulas inside
                           // whose precedents stay behind are disposed
```
Each thread has its own book, and dependent lists are never shared, so they need no atomics.

## 7. What's genuinely new compared with the covered options

- **Death flows forward, transitively and eagerly.** O1/O7 weak refs only blank one hop, and only
  when someone reads them. Generational refs (O6) are checked when used. Inko's counted borrows
  refuse or panic. Here, a death notifies every dependent at once: fields, closures and container
  slots. Disposed closures in turn blank their own slots.
- **Closures as formulas with intersection lifetimes.** A callback lives for
  `min(home, precedents)` and is never ownership. That removes retain cycles and capture lists at
  the language level, not by idiom, and it guarantees non-null captures inside the body. No
  covered option has a closure lifetime rule like this.
- **Pins defer death instead of refusing it.** Using an object is never an error, even when it is
  dropped in the middle of use, and the deferral ends with the scope, so it cannot leak.
- **Self-compacting link containers.** Observer lists, selection sets and maps keyed by dead objects
  clean themselves up, deterministically. They behave like weak containers or ephemerons, without
  a GC.
- **Paste-values thread transfer**, which states what happens to links that cross a moved
  boundary, instead of forbidding them.
- **Built-in provenance for every blank** ("why is this `#REF!`?"), which none of the reference
  options offer as part of the model.

## 8. Known weaknesses

- **Silent `#REF!`.** If a formula captures a short-lived local, the callback quietly stops
  working. Dev-build warnings and "why blank?" make this visible, but it is the new class of bug.
- **Optional noise.** Long-lived links such as `Gallery.cache` are always optional, so every use
  needs `?.` even when the programmer *knows* the cache outlives the component. A possible fix:
  sibling links within one owner, which drop in reverse order, could be non-optional. That would
  be another rule.
- **Single ownership is still required.** Every cell needs one answer to "who owns this?". Truly
  co-owned data has to be lifted to a common ancestor or a `sheet`. There is no RC escape hatch.
- **Overhead.** A 16-byte header on every cell, 3-word link fields, and pin traffic wherever
  elision fails. A cascade of deaths gives unbounded pause time, as with ARC.
- **Deferred death keeps memory alive.** A long-running function holding a local link to a big
  dropped subtree keeps all of it until the function returns.
- **The precedent set is syntactic.** It covers captured cells only, not cells reached through
  them, so the death of `self.doc.owner` does not dispose the formula. Some users will expect it
  to.
- **Containers shift indices** when blank slots are compacted, which is surprising when list
  positions matter.
- **G3 flags (needs-john).** It relies on built-in parameterised containers (`List of`, `Map of`)
  and on a `link` type modifier, which is a keyword, not an annotation.
- **Implementation risk is moderate.** Intrusive dependency rings, worklist cascades, pin elision
  and boundary severing in `send` are all mechanical, but they are fiddly to get exactly right.
  The fast path is simple.
