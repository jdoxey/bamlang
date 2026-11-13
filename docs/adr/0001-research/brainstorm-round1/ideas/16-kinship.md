# 16 — Kinship: family-tree ownership with upward kin and a turn orphanage

## 1. Name

**Kinship.** Every object has one guardian. References that point *up* the family
tree are free and safe. Objects that are let go wait in an orphanage until the
current turn ends. Observers join *clubs* and carry their own membership cards.

## 2. Inspiration — how the lens maps onto memory

| Social structure | Memory concept |
|---|---|
| Guardian / ward | Owner / owned object. Each object has exactly one guardian. Ownership forms a single tree (a family tree, or an org chart). |
| Elders outlive their wards | When a guardian dies, its wards die first or with it. So **a reference from a ward to any ancestor can never dangle**. This is the core idea. |
| Reporting line | The implicit `guardian` accessor: every object knows who it reports to, and the runtime keeps this up to date. |
| Adoption | Moving a subtree to a new guardian. The runtime checks that the subtree's ties to its old family are still valid in the new one. |
| Founding members / estate | Fixed (`let`) owning fields can never be removed, so they live exactly as long as their holder. Descendants may hold kin references to them ("extended family": uncles and aunts who can't leave). |
| Orphanage | A dropped subtree isn't freed at once. It waits in a per-thread orphanage until the current *turn* ends, so short-lived local "visits" to it stay valid without any borrow checker. |
| Club membership | Registries (event buses, timers, notification centres) never own their members. The member owns a membership card, and dropping the card leaves the club. |
| Emancipation / emigration | Only a self-contained subtree, with no ties to its old family, can be sent to another thread. |
| Household of a family outing | A structured `family` block of threads. The children may visit the elders' frozen or guarded belongings until everyone comes home. |

The insight the lens gives: **lifetime ordering is already encoded in the ownership
tree**. Ancestors outlive descendants. Most of the references the brief finds hard
point upward: parent pointers, and UI callbacks that capture the editor that owns the
button. If upward references are made first-class, they need no counting, no
`weak` and no lifetime annotations.

## 3. Pitch

Kinship is single ownership in which *the owner tree itself is the lifetime proof*. An
object may permanently hold a plain, uncounted reference to any of its ancestors, or to
a fixed member of an ancestor. The tree guarantees that the target outlives the
holder. Parent pointers come built in as `guardian`. A button's `onTap` closure may
capture `self` (the editor) because the closure lives inside the button, inside the
toolbar, inside the editor. That gives no cycle, no leak and no `weak self`. Local
variables may "visit" any object freely, because anything dropped during a turn sits in
the orphanage until the turn ends: the event-loop dispatch, the task body, or a
`settle` point. Freeing is deterministic and costs time in proportion to what you
dropped. Nothing ever traces the live heap. For the minority of links that point
neither upward nor at fixed members, there are clubs (observer registries that unlink
themselves) and contacts (checked handles).

## 4. The rules

1. **One guardian.** Every object is owned by exactly one place: a field, a container
   slot, or a local variable. Storing an object into an owning place *adopts* it. You
   must give a fresh object, `take` it from its current place (which leaves that place
   empty or removes it), or `copy` it.
2. **Letting go.** Overwriting, removing or leaving the scope of an owning place makes
   the object and all its wards *orphans*. Orphans can be re-adopted for the rest of
   the turn. If they aren't, they are freed at the end of the turn, children before
   parents, and their `farewell` (destructor) runs.
3. **Visits.** Reading a field, or receiving a parameter, gives a *visit*: a
   non-owning local reference. Visits may be used and mutated through freely, but they
   can't be stored in fields or survive the turn. Rules 4 and 7 give the only ways to
   keep a reference longer.
4. **Kin fields.** A field declared `kin` holds a non-owning reference. It must point
   to an ancestor of the object holding it, or to a fixed member of such an ancestor.
   The compiler checks this when it can. Otherwise the check happens at store or
   adoption time, and a failure traps.
5. **`guardian`.** Every object has an implicit `guardian` accessor that returns its
   owner. It updates automatically on adoption, so you never maintain parent pointers.
6. **Fixed members.** A `let` owning field can never be replaced or removed. It lives
   exactly as long as its holder, which is why descendants may hold kin references to it.
7. **Closures are wards.** A closure is an object owned wherever it is stored. Captured
   objects become kin references, so a closure is legal only where it ends up adopted
   below everything it captures. Plain values are copied in.
8. **Clubs.** A `Club` (timer, event bus, notification centre) never owns members.
   `club.join(closure)` returns a `Card` that you own. While the card lives, you're in.
   When the card is orphaned, you're out, immediately and not at the end of the turn.
9. **Turns.** A turn ends when control returns to the event loop, when a task body
   finishes, at an `await`, or at a `settle` statement. `settle` is allowed only in a
   turn root (`main` or a thread body), and only where no visits are live. The
   orphanage is drained at the end of each turn.
10. **Mutation during iteration traps.** Changing a list or map while iterating over it
    traps. This is the only aliasing rule.
11. **Threads.** Inside a `family { spawn … }` block, child threads may visit their
    ancestors' `freeze`-d objects and `Guarded` members, and the block joins before it
    exits. Anything sent to a detached thread or over a channel must be `take`n and
    *self-contained*, meaning it has no kin references leaving the subtree.
12. **Contacts.** For any other long-lived link, `contact(x)` gives a checked handle.
    `c.reach()` returns the object as an optional visit, which is empty if the object
    is gone. This is the escape hatch.

Most programs need rules 1–7. Rules 8–12 come up only when you meet those situations.

## 5. Under the hood

- **Header.** Each heap object carries a `guardian` pointer (8 B) and a flags word:
  fixed, frozen, orphan, has-outward-kin, iterating count, and a 32-bit generation for
  contacts. Containers are transparent. An element of `editor.lines` reports `editor`
  as its guardian, and the slot index is kept for debugging.
- **Adoption.** The runtime unlinks the object from its old place, sets `guardian`, and
  clears the orphan flag. If the has-outward-kin bit is set, it walks the subtree and
  checks that every kin pointer leaving the subtree targets an ancestor of the new
  position (or a fixed member of one). Subtrees without the bit are skipped in O(1).
  Freshly built UI subtrees are usually checked statically. When a subtree is built
  inside a method of `self` and attached under a fixed member of `self`, every capture
  of `self` is provably upward.
- **Kin stores.** If the store can't be proved statically, the runtime walks up from
  the holder until it reaches the target (pass) or the root (trap). Real trees are
  shallow, and the result is cached per (holder, target) pair until the next adoption
  in that chain. On success it sets has-outward-kin on the holder's ancestors up to the
  target's level.
- **Orphanage.** This is a per-thread intrusive list of dropped subtree roots. At the
  end of a turn, each one is freed post-order. The cost is proportional to the bytes
  dropped and never to the live heap, so there is no marking or tracing. Escape
  analysis frees immediately when it can prove no visit exists, for example a
  temporary that was never read through a visit. That covers most churn in tight loops.
  In a turn root, the compiler may insert an automatic `settle` at a loop back-edge
  when no visits are live there.
- **Clubs.** A club is an intrusive doubly-linked list of cards. When a card is
  orphaned it is unlinked eagerly, before the turn ends, so a closed editor never
  receives another tick.
- **Closures.** Each closure is an environment object. Value captures are copied in,
  and object captures are kin pointers, checked at adoption like any kin field.
- **Threads.** Each thread has its own orphanage. A family block runs inside the
  parent's turn, so anything the parent drops while the children run sits in the
  parent's orphanage until after the join. That makes visits to lent frozen or guarded
  data safe. `send` checks the has-outward-kin bit (O(1)) and rejects visits.
- **No counts, no cycles.** Ownership is a tree and kin references are uncounted, so
  there is no RC traffic and cyclic garbage can't exist.
- **Tooling.** Every live object has a path from the root (for example
  `app.windows[2].editor.toolbar.items[0]`). The debugger shows the family tree, a
  "census" shows memory by subtree, and traps report both paths ("kin to `Editor` from
  `Clock.items[3]`: not an ancestor"). For C FFI, a pointer handed out is a visit
  (valid for the turn); use `contact` to hold one longer.

## 6. Scenarios

All code below is *illustrative only — not a syntax decision*.

**(a) Read a file of unknown length into a list of lines**
```
fn readLines(path: String) -> List of String
  let lines = List of String()
  for line in File.open(path).lines()
    lines.push(line)            // fresh String adopted by the list
  return lines                  // ownership moves to the caller
```
The list owns its strings. The old buffers from growth are freed immediately because
no visits into buffers exist (rule 3 forbids interior references). The orphanage isn't
involved. The rules used are 1 and 2.

**(b) A tree with parent pointers**
```
class Node
  name: String
  children = List of Node()
  fn path() -> String
    let p = guardian as? Node            // implicit, always correct
    return p ? p.path() + "/" + name : name
let root = Node("root")
root.children.push(Node("a"))
root.children[0].children.push(take root.children[1])  // reparent: guardian auto-updates
```
There is no parent field to keep in sync. Moving a subtree re-points `guardian` for
free. A user-declared `kin grandparent: Node` would trap on a reparent that breaks
it, so that is the honest cost.

**(c) UI callback capturing enclosing state — the crux**
```
class Editor
  text = ""
  dirty = false
  let toolbar = Toolbar()                            // fixed member
  autosave: Card?
  fn build()
    toolbar.add(Button("Save", onTap: { self.save(); self.dirty = false }))
    autosave = App.clock.every(30.seconds, { self.save() })   // returns a Card
  fn save() ...
```
The `onTap` closure is owned by the Button, which is owned by `toolbar`, which is a
fixed member of the Editor. `self` is an ancestor, so the capture is a valid kin
reference, and it is provable at compile time. That gives no `weak self`, no cycle and
no leak. When the Editor is dropped, the button and closure go with it. The clock is a
club. The Editor owns the `Card`, which owns the closure, so the capture is again
upward. Closing the editor orphans the card and unlinks it from the clock at once.
The mistake case `App.clock.items.push({ self.save() })` is rejected, because Editor
is not an ancestor of `App.clock`.

**(d) A shared mutable cache used by two components**
```
class App
  let cache   = ImageCache()
  let search  = SearchPanel(cache)       // kin to a fixed member of an ancestor
  let preview = PreviewPanel(cache)
class SearchPanel
  kin cache: ImageCache
  fn show(url: String)
    let img = cache.get(url)             // visit, good for this turn
    draw(img)
    keepLatest = contact(img)            // optional: hold across turns, checked
```
Both panels sit below `App`, and `cache` is a fixed member of `App`, so the kin fields
are valid. Each entry has its own non-nesting lifetime: the cache owns its entries.
Eviction orphans an entry, so any visit already in progress stays safe until the turn
ends. Anything held across turns uses a contact, which reaches as "gone" after
eviction. Mutation is single-threaded and memory-safe. Across threads, the field would
be `let cache = Guarded(ImageCache())`.

**(e) Passing a large list to a function that mutates it**
```
fn dedupe(items: List of Track)          // a visit: no copy, mutation allowed
  let seen = Set of String()
  items.removeWhere({ t -> !seen.insert(t.id) })   // removed Tracks become orphans
dedupe(library.tracks)
```
This is plain reference passing, with zero copies and no `inout` ceremony. Removed
elements wait in the orphanage, so a caller still visiting one of them during this turn
is safe. Iterating `items` while also removing from it traps (rule 10).

**(f) Sharing data between threads**
```
let corpus = freeze(loadCorpus())
let tally  = Guarded(Map of String to Int())
family
  for chunk in corpus.chunks(8)
    spawn { for w in chunk.words  tally.lock({ t -> t[w] = t[w] + 1 }) }
// all children joined here; turn may now end
Thread.detached(take job)                // job must be self-contained
results.send(take report)                // channel: same rule
```
The children descend from the family block, so they may visit the frozen `corpus` and
the `Guarded` tally. Neither can be freed during the block, because the parent's
orphanage doesn't drain until after the join. A detached thread gets an emancipated
subtree. The runtime checks the has-outward-kin bit, so a subtree still holding kin
references to its old family can't be sent.

## 7. What's genuinely new vs. the covered options

- **Ancestor-based lifetime proofs (new).** O4, O5 and O6 prove reference validity
  with scopes, lifetimes or runtime checks on every use. Kinship gets permanent,
  uncounted, unchecked-on-use references from the shape of the ownership tree. Upward
  pointers are safe by construction, and that is exactly the shape of parent pointers
  and UI callbacks. Unlike O1 or O7 there is no `weak`, no RC traffic and no cycle
  problem. Unlike O2 or O3 the references are real and need no handles for (b) or (c).
- **Turn-scoped orphanage in place of borrow checking (new combination).** Visits need
  no lifetime analysis because freeing is deferred to a structural program point. The
  only static rule is "visits don't go into fields". This resembles autorelease pools
  or epoch reclamation, but here it is the *safety* mechanism for local references, not
  a convenience. It isn't region inference: the orphanage holds only what was
  explicitly dropped.
- **Adoption-time validation.** Moving a subtree checks its outward ties once, at the
  move, rather than on every dereference (O6).
- **Clubs.** Observer registries that never own their members and unlink eagerly
  through member-owned cards. This removes the classic leak where the observer is
  never removed, and needs no weak references.
- **Structured-concurrency lending via the orphanage.** Child threads may visit the
  parent's data because the parent's turn can't end before the join.
- Contacts reuse O6-style generation handles, but only as the escape hatch.

## 8. Known weaknesses

- **Non-upward, non-fixed links need contacts.** Sibling-to-replaceable-sibling links,
  DAGs and many-to-many graphs fall back to checked handles (O6), and reaching them
  returns optionals.
- **Traps at a distance.** A bad reparent or closure store can trap at the adoption
  site, far from where the kin reference was written. Static checking covers common
  UI-building patterns but not all.
- **Memory held until the turn ends.** A long handler that churns objects can spike.
  Long loops need a turn root with `settle`, or escape analysis, and "turn root" is a
  concept people have to learn. A reviewer might call the orphanage GC-like. It never
  traces the live heap, but **flag G2 as needs-john** to be sure.
- **Reference semantics.** Aliased mutation can cause logic bugs. They are not memory
  bugs, but rule 10 is the only guard. "Stale but valid" orphan visits can surprise.
- **Costs.** There is an 8 B guardian pointer plus flags per object. Unproved kin
  stores and adoptions cost O(depth) or O(subtree with outward kin) at run time.
- **`guardian` is dynamically typed.** It needs `as?` casts, because a Node's guardian
  might be a Tree, a List owner or a Node.
- **G3.** The model leans on compiler-known containers (`List of`, `Map of`,
  `Guarded`). This is the brief's pending question, so flag it.
- **Rule count** is about 12. That is fewer than O5's and comparable to O4's. Rules 8–12
  are situational, but they are still rules.
