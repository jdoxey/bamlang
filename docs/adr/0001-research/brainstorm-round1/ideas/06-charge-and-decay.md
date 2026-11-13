# 06 — Charge & Decay

## 1. Name

**Charge & Decay**: landing-based ownership with entangled links, plus decay deferred while an object is being observed.

## 2. Inspiration: how the lens maps onto memory

| Physics | Memory |
|---|---|
| **Conserved charge.** Every particle carries exactly one unit, and it can't be created or destroyed, only moved. | Every object has exactly one owner, always. Ownership is the only thing that keeps an object alive, and it can only move. |
| **Neutral pairs.** Pair production makes a particle and an antiparticle with net charge zero. | A *link* (non-owning reference) is a pair: one end sits in the holder, the other end is registered on the target. A link carries zero charge, so it never extends a lifetime and can never form a leaking cycle. |
| **Annihilation.** When one member of a pair goes, its partner can't stay as it was. | When the target dies, every link to it collapses to **vacuum** at once. When the holder dies, its link end is removed from the target. Nothing is ever left dangling. |
| **Capture.** A free particle binds to the first nucleus it meets. | A new object belongs to the **first lasting place it lands in**. You don't declare ownership. Where you put the object decides it. |
| **Decay chain.** A nucleus decays, then its products decay in turn. | When an owner dies, everything it owns decays depth-first, deterministically. |
| **Excited state / observation.** A measurement in progress delays the collapse. | An object that is in use (bound to a local variable, or running a method) can be *dropped*, but its *decay* waits until the use ends. |
| **Light cone / spacelike separation.** Some events can't influence each other. | Each thread is its own *universe*. Links can't cross universes. Only frozen objects ("crystals") are visible across them. |

## 3. Pitch

There is no `weak`, no `unowned`, no capture list, no lifetime, no `Rc<>`, and no move syntax in ordinary code. An object belongs to the first field, container slot, closure or global it is stored in. Every other reference to it, anywhere, is a **link**. A link is a zero-charge, two-ended pair that the runtime keeps registered on its target. When an owner lets go, the object decays immediately, along with everything it owns. All links to it become vacuum in the same step, so memory can be freed right away. No tracing, no generations, no counts are needed for lifetime. Containers silently drop entries whose links went to vacuum, so caches and observer lists clean themselves up. A closure whose captured link has gone to vacuum also decays: calling it does nothing. This is the UI-callback crux, solved by semantics rather than by programmer discipline. If you drop an object while it is mid-use, its decay waits until the use finishes, so re-entrant "close the window from its own button" code is safe.

## 4. The rules (everything a programmer must learn)

1. **Values vs objects.** Numbers, bools, strings and `value` structs are copied. Class instances (and `List`, `Map`) are objects with identity.
2. **One owner.** Every object has exactly one owner at all times: a field, a container slot, a closure, a global, or a local variable.
3. **The landing rule.** A new object belongs to the first *lasting* place it is stored in (a field, container slot, closure or global). Until then, its local variable or parameter holds it. If it never lands anywhere lasting, it decays when that local's scope ends.
4. **Everything else is a link.** Storing or passing an object that already has an owner makes a link. Links never keep anything alive.
5. **Decay.** When an owner lets go (its scope ends, the field is reassigned, the entry is removed, or the owner itself decays), the object decays. Its `decay` method runs, then everything it owns decays too.
6. **Vacuum.** When an object decays, every link to it becomes vacuum. Using a vacuum link traps, and the trap reports where and why the object decayed. Use `x is here` to test a link first.
7. **Self-cleaning containers.** If an entry in a `List` or `Map` is a link and it goes vacuum, the entry is removed. If the container is being iterated at the time, the removal waits until the loop ends.
8. **Decayed closures.** A closure links everything it captures that already has an owner, including `self`. If any of those links goes vacuum, the closure decays: calling it does nothing and returns `none`. Callback lists drop decayed closures, as in rule 7.
9. **Observation.** An object you are currently using can't vanish under you. That covers an object bound to a local, passed as a parameter, or running a method. If its owner drops it, its links go vacuum at once, but its `decay` waits until your use ends (the local's last use, or the method's return).
10. **`take`.** `take x` removes x from its current owner (the field becomes `none`, or the container entry is removed) and makes it ownerless again, so it lands wherever you put it next. Taking an object into something it owns traps.
11. **Universes.** Each thread owns its own objects. `send(thread, take x)` moves x and everything it owns to that thread. Links that cross the boundary in either direction go vacuum.
12. **Crystals and chambers.** `freeze x` makes x and everything it owns permanently immutable, and other threads can then link to it. A `Chamber(x)` holds shared mutable state: other threads link to the chamber and get at its contents only inside `enter c as s { … }`, which takes a lock. Objects inside a chamber can't link to objects outside it.

That is 12 rules. In practice, rules 1–6 and 8 cover single-threaded application code, and 10 is rare.

## 5. Under the hood

**Object header** (about 4 words): `owner`, a pointer to the owning slot, or null while the object is ownerless (held by a local); `links`, the head of an intrusive list of incoming link cells; `pins`, the observation count, which is a non-atomic integer except on crystals and chambers; and `flags`, made up of universe id, decaying, frozen and pending-decay.

**Slots.** Every object-typed slot is a tagged pointer. Tag 0 means *charged*: the slot owns the object and points straight at it. Tag 1 means *neutral*: the slot points at a heap **link cell** `{target, prev, next, holder}`. The cell sits in the target's `links` list. `holder` records the container and key, so rule 7 can remove the entry. Because cells are separate allocations, slots can move freely, for example when a list grows.

**A store** `place = obj` compiles to one branch:
- If `obj.owner == null`, write a charged pointer and set `obj.owner = place`.
- Otherwise, allocate a cell, push it onto `obj.links`, and write a neutral pointer.

The slot's old contents are released first. If the old slot was charged, its object decays. If it was neutral, its cell is unlinked and freed.

**Local links are pins, not cells.** A local bound to an owned object does `pins++` and does `pins--` at its last use (the compiler shortens it to last use). Parameters work the same way, and so do method receivers for the duration of the call. Escape analysis removes most pins, for example when the callee provably can't reach the owner. Leaving a pin in where it isn't needed is always correct, just slower.

**`decay(obj)`** runs from an explicit worklist, so it doesn't recurse:
1. Set the decaying flag.
2. Walk `obj.links`: set each cell's target to null, and schedule removal for cells held by containers or closures (rules 7–8).
3. If `pins > 0`, set pending-decay and stop. The last unpin resumes from here.
4. Otherwise, run the user's `decay` method.
5. Push every charged child onto the worklist.
6. Unlink every outgoing cell from its target.
7. Free the memory.

The work is proportional to the owned subtree plus its links. There is no reachability tracing, so G2 holds. Ownership is a forest, and the only way to tie a knot in it is `take`. A `take` into a descendant is caught by walking the destination's `owner` chain.

**Threads.** The universe id lives in the header. Creating a cell checks `target.universe == holder.universe || target.frozen`. `send` re-tags the subtree and vacuums its boundary links, which costs O(subtree + links). Crystal pins are atomic. Links held from other threads are pins, not cells, so a crystal whose owner drops it decays when the last foreign pin is released. A chamber is a crystal-like shell that wraps a mutex and its own universe id.

**Tooling.** The owner pointers give the debugger an exact "who owns this, and why is it alive" chain for every object. It can also list every link to an object, which is the object's field lines. Vacuum traps include the decay site. A leak can only be a container that keeps growing, never a cycle. Lint: *"`self.current` captured ownership of this Node, but it is later added to `children` as a link. Did you mean to add it to `children` first?"*

**C FFI.** Pass a pinned raw pointer for the duration of the call. Handing ownership to C uses `take`, plus an explicit `adopt` on the way back.

## 6. Scenarios

All code below is *illustrative only — not a syntax decision.*

### (a) Read a file into a growing list

```
func readLines(path: String) -> List of String {
  let f = File.open(path)        // ownerless; held by local f
  let lines = List of String()   // ownerless; held by local lines
  for line in f.lines() { lines.add(line) }   // strings are values: copied in
  return lines                   // still ownerless -> lands in caller's place
}                                // f never landed -> decays here -> file closed
self.lines = readLines("a.txt")  // self.lines now owns the list
```

Strings are values, so the list stores them inline and grows by reallocating, which is safe because nothing points into the buffer. The file decays deterministically at the end of the scope.

### (b) A tree with parent pointers

```
class Node {
  var parent: Node?
  var children = List of Node()
  func addChild(name: String) -> Node {
    let n = Node(name)       // ownerless
    n.parent = self          // self already has an owner -> link
    children.add(n)          // first lasting place -> children owns n
    return n                 // n is owned now -> caller gets a link
  }
  func moveTo(newParent: Node) {
    newParent.children.add(take self)   // removed from old list, lands in new
    parent = newParent                  // link
  }
}
```

Child edges are charged and parent edges are neutral, and nobody had to declare either. Removing a subtree decays it, and every parent link inside it goes with it. A link from outside, such as `selection`, goes vacuum.

### (c) UI callback capturing enclosing state (the crux)

```
class Editor {
  var doc: Document
  var saveButton = Button("Save")          // Editor owns the button
  init() {
    saveButton.onTap = {                   // the closure lands in the button
      self.save()                          // self captured as a link
      self.doc.dirty = false
    }
    App.toolbar.onUndo.add({ self.undo() })  // toolbar outlives editors
    closeButton.onTap = { self.window.close() }  // closes us while we run
  }
}
```

The chain is editor → owns button → owns closure → links editor. There is no strong cycle and nothing to remember, because `self` is never captured as an owner. When the editor decays, its own buttons decay with it. The closure it registered on the long-lived toolbar has a vacuum `self`, so it decays and drops out of `onUndo` (rules 7–8). There is no `[weak self]`, no `guard let`, and no stale callback crash. `close()` drops the editor while its own closure is still running. The editor is pinned (rule 9), so its links vacuum at once, but its `decay` runs when the closure returns.

### (d) A shared mutable cache used by two components

```
class App {
  var images = Map of String to Image()    // App owns the cache
  var gallery = Gallery(cache: images)     // link
  var editor  = Editor(cache: images)      // link
}
class Gallery {
  var cache: Map of String to Image        // link (it already had an owner)
  var thumbs = List of Image()
  func show(key: String) {
    if cache[key] is none { cache[key] = Image.load(key) }  // cache owns it
    thumbs.add(cache[key])                 // a link inside our list
  }
}
// cache eviction: images.remove(key) -> the Image decays -> its entry
// silently disappears from gallery.thumbs and editor.thumbs (rule 7)
```

The ownership question that is hard in single-ownership systems, "who owns the shared cache?", gets the natural answer: the composition root owns it. Eviction propagates to every consumer automatically and deterministically.

### (e) Pass a large list to a function that mutates it

```
func dedupe(xs: List of String) {      // parameter = pinned link, no copy
  let seen = Set of String()
  var i = 0
  while i < xs.count {
    if seen.has(xs[i]) { xs.removeAt(i) } else { seen.add(xs[i]); i += 1 }
  }
}
dedupe(self.lines)                     // mutated in place
```

Lists are objects, so passing one passes a link, the way Java or Python would, but memory-safe. Elements that are objects are boxed, so growing a list never moves an element anyone is using. Aliasing such as `merge(a, a)` is defined behaviour: index-based semantics, never UB.

### (f) Sharing data between threads

```
let table = loadBigTable()             // ownerless
freeze table                           // now a crystal: immutable, cross-thread
let stats = Chamber(Stats())           // shared mutable, behind a lock
for part in 0..4 {
  spawn {                              // closure links table & stats (rule 8)
    let r = analyze(table, part)       // read freely, no lock
    enter stats as s { s.merge(r) }    // locked; s pinned inside
  }
}
send(worker, take job)                 // hand off a mutable subtree outright
```

There are exactly three ways to share: **send** (move), **freeze** (share immutable), and **chamber** (share mutable under a lock). A data race needs either a link that crosses universes or a mutable crystal, and the runtime rejects both.

## 7. What's genuinely new compared with the covered options

- **Ownership decided by where an object lands, at run time, not by type.** O1 and O4–O6 make you declare or annotate strong, weak, `shared` or borrowed. Here, one runtime tag bit on each slot, set by "first lasting store wins", replaces all of those declarations. You never write `weak`, `shared` or `move` in ordinary code.
- **Eagerly annihilated two-ended links.** O6 (Vale) keeps memory around so it can check generations later, and Inko panics on outstanding borrows. Here the target actively vacuums its links the moment it dies, so memory is freed immediately and there is no lazy check.
- **Self-cleaning containers.** Weak collections are built into ordinary `List` and `Map`, which makes caches, observer lists and selection sets correct by default.
- **Decayed closures.** A callback whose world has gone becomes a no-op. This answers (c) at the level of language semantics; O1's capture lists and O4's `shared` both make you handle it yourself.
- **Observation-deferred decay.** A drop during use defers the destructor instead of panicking (Inko) or crashing (C). Links still vacuum at once, so lifetime stays owner-determined.
- **The universe tag** gives one uniform rule for threads: links never cross a universe boundary unless the target is frozen.

## 8. Known weaknesses

- **History-dependent ownership.** The same field may own an object in one run and link to it in another, depending on store order. "Accidental capture" (`self.current = Node()` before adding it to `children`) is the main new footgun. Lints and the debugger help, but this is real reasoning cost.
- **Silent no-op callbacks** can hide a bug: a button that does nothing because its target decayed early.
- **Vacuum traps** are memory-safe but are a crash class, like a null dereference.
- **Overhead.** About 4 header words per object, a heap cell per stored link, a branch on every object store, and pin traffic, much of which escape analysis can remove. It is likely slower than O4, and similar to ARC.
- **Self-shrinking containers** change indices underneath index-based code. Deferring removal while a container is iterated helps, but not with indices held across calls.
- **Long pins delay decay.** A local holding an object across a run loop keeps it pending. Crystals are effectively atomically refcounted.
- **Cascade latency.** Decaying a huge tree is O(subtree) on the spot, the same as with RC or Rust drops.
- **G3 flag.** This needs compiler-known `List of T` and `Map of K to V`, which is the brief's pending question.
- **Implementation risk.** Moderate. The runtime is simple and local, with no static lifetime analysis, but the interactions between pins and deferred removal need careful testing.
