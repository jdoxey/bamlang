# 19 — Dominion: dominator-relative references over a containment tree

## 1. Name

**Dominion.** Ownership is a tree. Every non-owning reference is stored *relative to that tree*, as a position or a path, never as a raw address. The heap behaves like a filesystem: containment is the directory structure, and references work like relative symlinks.

## 2. Inspiration: how the lens maps onto memory

- **Graph theory (dominators, LCA, articulation points).** If ownership is a tree rooted at the thread, a node's dominators are exactly its ancestors. Every path from the root to X passes through each of them. So **a reference from X to one of its dominators cannot outlive its target.** The target can only die by being cut off from the root, and X is cut off with it. These "upward" references are safe without counting. A "sideways" reference from X to Y goes through their lowest common ancestor (LCA), the nearest node that dominates both. Every internal node is an articulation point: removing it disconnects exactly its subtree. That subtree is what gets destroyed, and it covers exactly the links whose path runs through that node.
- **Type theory (de Bruijn indices, contextual modal types).** An upward reference is stored the way a de Bruijn index stores a variable: "the nearest enclosing `Editor`", not "object at 0x7f…". A closure that captures `self` is a *contextual* term, and its context is supplied by **where the closure sits in the tree when it is called**, not by where it was created. This is the modal box `[Ψ]A`, with Ψ filled from position.
- **Topology (boundaries).** Treat a subtree as a closed region. A link whose LCA lies *inside* the region is internal. One whose LCA lies outside crosses the boundary. **Theorem: moving a subtree leaves every internal link valid**, because both its ends and its anchor move together. Only links that cross the boundary are re-checked, and that check happens lazily, when they are next used.
- **Separation logic.** Disjoint subtrees are separate heap fragments joined by the separating conjunction. Handing a subtree to another thread is an O(1) transfer of a separated fragment. Destruction is a recursive walk over one fragment, so there is no tracing and no possibility of cycles.
- **Effects and quiescence.** The compiler infers *turn roots*: functions with no callers that can hold borrows, such as `main`, thread entry points and event handlers. Destruction of detached objects is an effect that is postponed to the end of the turn.
- **Graded types.** The compiler grades every reference store internally as *fresh* (contain it), *dominating* (upward) or *lateral* (anchored path). The programmer never writes or sees these grades.

## 3. Pitch

Every object lives in exactly one place, and the places form a tree: thread, then app, then windows, then editor, then toolbar, then button. Anything you build in a method counts as being inside `self` until you put it somewhere. When you store a reference to an object that already lives somewhere, the runtime does one of two things, chosen by a dominance test at store time. If the target *encloses* the holder, it records "my enclosing Editor". If not, it records "from our common ancestor, go to `windows[#17].editor`". Neither form can dangle. Resolving one is a walk through the live tree, and it either finds the object or returns `none`. Closures capture objects this way automatically. That makes `onTap: { self.save() }` correct by construction: there is no retain cycle, no `[weak self]`, and nothing to annotate. When the editor is closed, its buttons go with it, and a callback that still sits somewhere else simply finds no editor. Memory is freed by destroying subtrees. Destruction of anything removed from the heap waits until the current turn ends, which makes every reference held on the stack safe without borrow rules.

## 4. The rules: everything a programmer must learn

1. **Every object has exactly one container**: a local variable, a field, or a slot in a collection. When the container lets go of it, the object and everything inside it is destroyed.
2. **New objects go where you put them. To relocate an existing object, write `move`. To duplicate it, write `copy`.** Passing an object to a function *lends* it: the function may change it but not keep it. If a function does keep a parameter, the compiler asks callers to write `move`. Numbers, strings, structs and frozen values copy freely.
3. **`outer Editor` means the nearest Editor that contains me** (or `none`). Bare `outer` means my immediate containing object.
4. **A field or element of type `link T` refers without containing.** Reading it gives the object, or `none` if the object has been removed or moved out of where it was. Links never dangle. Moving a whole structure keeps the links inside it working.
5. **Closures capture objects as links automatically.** If the closure is stored inside the captured object, the capture means "my enclosing one of those". If a callback runs when something it captured is gone, the call does nothing and returns `none`. Debug builds log this.
6. **When things die.** Locals die at the end of their scope. Objects removed from a field or collection die when the current event or turn finishes. Until then, any reference you are holding in a local stays valid.
7. **Threads.** `send(move x)` gives a subtree to another thread, and it arrives when your turn ends. `together { … }` lends disjoint parts to parallel tasks and waits for them. Mutable data shared between threads lives in a `Shared` and is used inside `lock`. Frozen objects can be read by any thread.

That is seven rules plus two keywords (`move`, `link`). There are no lifetimes, no exclusivity or borrow rules, no weak/strong choice and no cycle concerns.

## 5. Under the hood

**Object header (about 24 bytes):** a parent pointer, a slot key within the parent (field index or collection slot id), a 64-bit uid, and a class id. Collections keep stable slot ids per element, and build the slot-to-index map lazily, only for collections that something links into.

**What happens on `place = r`, where the place belongs to holder `h`:**
- `r` is fresh (no container): set `r.parent = h`. This is the contain case.
- The place has type `link T`:
  - *Dominance test*: walk up from `h`. If `r` is found, store `Up(class(r), k)`, where k is how many closer objects of the same class were skipped (normally 0).
  - Otherwise compute the LCA `L`: walk up from `r` into a small stack set, then walk up from `h` until a node matches. Store `Link(L.uid, path of slot keys from L down to r, r.uid)`.
  - When the compiler can prove the classification statically (very common for builder code and child-to-parent links), it emits the fixed form and skips the walk.

**Resolution:**
- `Up`: walk up from the holder, counting matches of the class. Cost is O(depth).
- `Link`: walk up looking for `L.uid` (comparing uids only, never dereferencing anything that is not a live ancestor), follow the path, then check the final uid.
- Each link caches `(pointer, structureVersion)`. Every thread has a counter that increases on each detach, so most resolutions cost one compare.

**Frames are nodes.** A method frame's lookup parent is `self`, which is why "things made in a method are inside self". A free function's frame hangs off the thread root. Frames carry activation uids, so a link anchored at a frame breaks when that frame returns.

**Graveyard (deferred destruction).** Detaching a subtree from the heap tree updates the parent pointer at its root, bumps `structureVersion`, and appends the root to the thread's graveyard. At a *quiescent point*, the graveyard is destroyed by an iterative subtree free that runs destructors. There is no scan of live objects, and no tracing.
- Quiescent points are inferred, not annotated: the return of runtime-dispatched handlers, back-edges of loops in turn-root functions where no borrowed locals are live, and between top-level statements of `main`.
- Fast path: if escape analysis proves nothing on the stack can hold a borrow into the detached object (locals that never escaped, list buffers of locally owned lists), it is freed immediately.
- List buffer reallocation uses the same mechanism. The old buffer is a graveyard item unless the fast path applies.

**Why the stack needs no borrow checker.** Locals hold raw pointers. Raw pointers can only become invalid through destruction, and destruction never happens while a non-root frame is live. Two mutable aliases of the same object are therefore *memory-safe* (at worst, a read is stale), so no exclusivity rule is required.

**Threads.** Each thread owns a root.
- `send` detaches the subtree into an outbox. The outbox is handed over at the next quiescent point, which guarantees the sender holds no borrows into it. Links inside the subtree survive by the move-invariance theorem. Links crossing its boundary fail to find their anchor and return `none`. The two thread trees are never walked together.
- `together` blocks the parent. Child tasks treat their lent subtrees as their own, and whatever they detach goes into the *parent's* graveyard.
- `Shared` is the one atomically counted handle. Inside a Shared, references to other Shareds must be links, so counts cannot form cycles. Frozen trees are immutable and shared by an atomic count on the frozen root only.

**FFI.** Pointers handed to C are borrows valid until the end of the turn. C-owned memory is wrapped in an object with a destructor.

**Debugger.** Shows the containment tree directly. For a failed link, it shows the anchor, the path, and the step at which resolution broke.

## 6. Scenarios

*All code: illustrative only — not a syntax decision.*

**(a) Read a file into a growing list**
```
fn readLines(path: String) -> List of String
  let lines = List of String()        // contained by this frame
  let f = File.open(path)             // contained by this frame
  while let line = f.readLine()
    lines.add(line)                   // strings are values
  return lines                        // fresh: caller's place will contain it
                                      // f closed and freed at scope end
```
`lines` is a local that never escaped as a borrow, so the old buffer is freed immediately when the list grows (fast path). There is no graveyard traffic. The cost is the same as C++ `vector`.

**(b) Tree with parent pointers**
```
class Node
  var name: String
  var children: List of Node
  fn path() -> String
    if p = outer Node then return p.path() + "/" + name
    return name
root.children.add(Node("src"))                    // fresh: contained
let n = root.children[0]
n.children.add(move other.children.removeAt(2))   // re-parent a subtree
```
There are no stored parent pointers to maintain, because `outer Node` comes from the header the runtime already keeps, and it can never be stale. Removing a node sends its subtree to the graveyard, and every link whose path ran through that node now returns `none`.

**(c) UI callback capturing `self` (the crux)**
```
class Editor
  var doc: Document
  var toolbar: Toolbar
  var dirty = false
  fn build()
    toolbar = Toolbar()
    toolbar.add(Button("Save", onTap: fn() { self.save(); self.dirty = false }))
    app.clock.onTick(fn() { self.refreshStatus() })     // stored OUTSIDE the editor
  fn save() …
```
- The `Button` is built in a method frame, so it is inside `self` when its `onTap` field receives the closure. The dominance test passes, and the capture becomes `Up(Editor, 0)`. On tap, the runtime walks button → list → toolbar → editor and calls `save`.
- Closing the window removes the editor. Its subtree, buttons included, is destroyed at the end of the turn. There is no cycle, because the closure never owned the editor.
- The clock is not inside the editor, so that capture becomes `Link(App, windows[#17].editor, uid)`. After the window closes, the clock's callback resolves to `none` and is skipped. The clock can prune callbacks that are no longer resolvable.
- The programmer writes nothing: no `weak`, no unsubscribe, no lifetime annotations.

**(d) Shared mutable cache used by two components**
```
class App
  var cache: ImageCache
  var gallery: Gallery
  var preview: Preview
  fn start()
    gallery.cache = cache          // existing object into a `link ImageCache` field
    preview.cache = cache
class Gallery
  var cache: link ImageCache
  fn show(name: String)
    if c = cache then draw(c.get(name))
```
Both links are anchored at `App`, with path `.cache`. Both components mutate the cache freely, and no aliasing rules apply. If `App` swaps in a new cache, the uid check makes the old links return `none`. An alternative with no stored reference is to always reach the current cache through the tree: `outer App?.cache`.

**(e) Pass a large list to a mutating function**
```
fn dedupe(lines: List of String)     // lent: may mutate, may not keep
  …lines.removeAt(i)…
let lines = readLines("big.txt")
dedupe(lines)                         // pointer passed, no copy
```
The list is passed as a pointer. Because `lines` is lent, a caller might hold a borrow into its buffer, so if `dedupe` reallocates, the old buffer waits in the graveyard. That waste is bounded by geometric growth. If `dedupe` tried `self.all.add(lines)`, the compiler would require callers to write `dedupe(move lines)`.

**(f) Sharing data between threads**
```
let w = Thread.start(fn(job: Job) { process(job) })
w.send(move job)                      // handed over at end of this turn
together
  spawn sortList(left)                // disjoint lends; parent waits
  spawn sortList(right)
let stats = Shared(Stats())
lock stats { s in s.count += 1 }
let table = freeze(buildLookupTable())    // readable by every thread
```
A sent subtree keeps its internal links, and its links back to the sending thread return `none`. The two threads' trees are never walked together. The only atomic counts are on the `Shared` handle and on frozen roots.

## 7. Genuinely new compared with the covered options

- **Dominance test at store time instead of a programmer's weak/strong choice (O1, O4).** The runtime decides whether a reference points upward or sideways from the actual tree. Upward references need no counting, because dominance guarantees their safety. That is the mathematical core here, and none of O1–O8 has it.
- **References as positions, not addresses.** Upward references are type-directed indices in the de Bruijn style: "my enclosing Editor". They rebind correctly when the holder moves and dissolve when it is detached. This removes the `[weak self]` problem *structurally*, where O1/O7 handle it through programmer choice or a collector.
- **Lateral links resolved through the ownership tree itself.** A link is anchored at the LCA and checked by uid. There is no global handle table or slot map, and no per-dereference generation check on the target (O6). The tree *is* the index.
- **Move invariance.** Relocating a subtree (a window, a session, a cache entry, a thread's job) needs no pointer fix-ups and keeps its internal links. Lifetimes that do not nest become "move the subtree to a different container". Compare scope-bound regions, which leak long-lived objects or need `promote`.
- **Turn-deferred destruction replaces exclusivity and borrow rules (O2, O4, O5).** Stack pointers are safe because nothing is destroyed while a non-root frame is live. This is deterministic and epoch-like, and nothing is traced.
- Cycles are impossible by construction: ownership is a tree and links never own. So no cycle collector (O7) is needed, and no cycle rules either.

## 8. Known weaknesses

- **Overhead.** About 24 bytes of header per object. Each link store costs an O(depth) walk, and a dereference after the structure changes costs a walk plus the path. Graph algorithms that follow links in hot loops will be slow, so those should use indices.
- **Silent no-ops.** An inert callback can hide a real bug. Debug-build logging and the debugger's "where it broke" view help, but do not eliminate this.
- **Imposed tree shape.** Many-to-many data must be given an owning container (for example, a `Graph` that owns its nodes, with edges as links). This is natural for UIs and sessions but awkward for some domains.
- **Graveyard growth and quiescence analysis.** A long computation in a non-root frame that keeps replacing heap objects grows the graveyard until the turn ends. The quiescent-point analysis is load-bearing for safety: a bug there is a use-after-free. Batch programs may need a library `Turn.end()` that only turn roots can call.
- **Stale-but-safe semantics.** Aliased mutation within a turn can read stale data, for example an iteration seeing the old buffer while new items are appended. It is safe, but surprising.
- **Rebinding surprises.** If objects of the same class are nested, `Up(Editor, k)` can bind to a different Editor after a move.
- **Delayed destructors.** A removed object is destroyed at the end of the turn rather than at the moment of removal. File handles should be closed explicitly with `close()` when timing matters.
- **G3 flags (needs-john):** `List of T` and the type former `link T`. `link` reads like Swift's `weak` keyword, which may or may not count as an annotation.
- **Implementation weight.** The runtime is substantial: headers, walks, the graveyard and outboxes. Each piece is simple and testable, but the escape and quiescence analyses need care.
- **Rough self-assessment:** both gates pass, with the G3 flags above. Simplicity 4, Safety 5, Expressiveness 5, Implementation risk 3, Performance 3, Concurrency 4, Tooling and FFI 4, for a total of about 80.
