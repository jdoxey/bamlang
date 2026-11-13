# 07 — Scent Trails

## 1. Name

**Scent Trails.** Memory works like ant pheromones. Shared objects live because they are used, not because something can reach them.

## 2. The crazy premise

It breaks the assumption that **an object that can be reached is alive.** Every sensible design (ARC, ownership, tracing GC, regions) frees an object only once nothing can reach it. Here, an object that has ever been shared can be freed **while it is still reachable**, if nobody walks to it for long enough. Reaching it afterwards gives `lost` (a safe, checked result), never freed memory.

It also breaks a second assumption: **that destruction happens at a predictable moment.** A shared object's `deinit` runs "some time after W", not at a known point in the code.

Gates touched:
- **G2: needs-john.** There is no heap tracing. But at each checkpoint the runtime does a bounded scan of the stack and globals (a root scan only, never a heap walk).
- **G3: one keyword (`faint`) plus one built-in container (`Scent`).** Same pending question as `List` and `Map`.

## 3. Pitch

No owners, no counts, no weak refs, no lifetimes. Storing a reference somewhere *lays a trail*. Overwriting or removing it *cuts the trail*. Reading a reference out of a field *walks the trail*. Data with one holder at a time (most of it: lists, trees, buffers) is freed as soon as its only trail is cut. That is precise and prompt, but nobody declared an owner: it is a runtime fact. An object that has ever had two trails at once is marked *shared* (a sticky bit, not a count). When any trail to a shared object is cut, the object starts to **fade**. Every walk renews its scent for a window W, measured in the colony's allocation rather than in time. If W passes with no walk, it evaporates. Cycles cost nothing: a garbage cycle is never walked, so it evaporates. Callbacks capture `self` freely. Caches fall out of the model: hot entries live, cold ones fade. You pay for this in two ways. A holder who keeps a shared thing *idle* after someone else dropped it must use it or store it again. And destruction of shared objects happens late and at an imprecise time.

## 4. The rules

1. There is no `free`, no owner, no `weak`, no lifetime syntax. Objects come from constructors.
2. **Lay:** storing a reference into a field, list or map element, or closure capture *holds* the object.
3. **Cut:** overwriting or removing a stored reference cuts that trail. When an object is freed, every trail it held is cut.
4. **Unshared objects:** an object that has never had two trails at once is freed as soon as no trail and no hand (rule 6) holds it.
5. **Shared objects fade:** once an object has had two trails at once, any cut makes it *fade*. Each **walk** (reading the reference out of any field, element or capture) gives it another W. If no walk comes within W, it evaporates. Storing it again makes it held, so it stops fading.
6. **Hands are safe:** nothing referenced directly by a live local variable, parameter, temporary or global is ever freed.
7. **`faint` fields** (back-pointers, observers, memo tables) lay trails that never hold, never mark an object shared, and never cut. An object reached only through faint trails fades from the moment it is stored and lives only while it is walked: pure pheromone. `Scent` is a built-in map whose values are faint.
8. Reading a trail to an evaporated object gives `lost`. `x.f()` traps and reports where the trail was cut. `x?.f()` and `if alive x` let you handle it.
9. `take a.f` reads a field and cuts it in one step. Use it to move a reference without marking the object shared.
10. Each thread is a **colony** with its own heap and clock. Object graphs cross between colonies only by `send`, which moves them.
11. W counts the colony's allocations, not time. An idle program never fades. Tests run in **drought mode** (W = 0), which makes any reliance on fading fail at once, deterministically.

The idiom that follows from the rules: *if you keep something someone else let go of, store it again* (`self.doc = self.doc`).

## 5. Under the hood

- **Reference** = pointer plus generation (48+16 bits packed into one word, or a 16-byte fat ref). Heap slots come from size-class slabs. A slot's generation word outlives the object in it, so a stale reference is always detected (the O6/Vale safety mechanism, reused).
- **Header word:** `gen | shared | fading | fresh | deadline` (the deadline is in 64 KB units of the colony clock).
- **Store `h.f = x`:** the old target is cut. If it was unshared, it goes on the *candidate* list. If it was shared, it gets `fading=1, deadline=now+W` and is filed in the timing wheel. Then `x` is laid: if `x` was already held and not fading, set `shared`. Clear `fading` and `fresh`. No increments, and nothing on local copies.
- **Load `h.f`:** check the generation. If `fading` is set, write `deadline=now+W`. The hot path is one compare and one bit test, both in the same header word. Settled objects get no write on read (cheaper than ARC).
- **Scope exit** of a local holding a `fresh` object (one never stored anywhere) makes it a candidate. Escape analysis puts most of these on the stack instead.
- **Checkpoint** (on the allocation slow path, about every 64 KB):
  1. Conservatively scan this colony's stack, registers and globals into a small hash set. These are the hands.
  2. Candidates not in a hand are freed. Candidates in a hand stay on the list.
  3. Process the due bucket of the timing wheel. Skip an entry if its generation changed, if `fading` is clear, or if its deadline moved (then re-file it). If it is in a hand, re-file it. Otherwise evaporate it.
- **Free or evaporate:** bump the generation, run `deinit`, cut each reference field (by type layout, no graph walk), return the slot to its slab. Cascades are incremental, with a work budget per checkpoint.
- **Work** is proportional to cuts plus garbage, never to the live heap. Floating garbage is bounded by about W of allocation for shared data and about one checkpoint for unshared data.
- **C FFI:** a pointer handed to C is not a hand. `pin x` registers it as a global hand until `unpin`.

## 6. Scenarios (illustrative only — not a syntax decision)

**(a) Grow a list of lines.** No objects are shared. Each line is held by one list slot. The old backing buffer is the list's own business, not a trail.
```
fun readLines(path) {
  lines = List()
  for line in File(path).lines() { lines.add(line) }   // lay: held, unshared
  return lines                                          // hand passes to caller
}
```

**(b) Tree with parent pointers.** Back-pointers are `faint`, so nodes stay unshared. `app.tree = nil` frees the whole tree in one cascade. Without `faint` it is still correct, but every node is shared, so the tree evaporates one level per W.
```
class Node {
  faint parent
  children = List()
  fun add(c) { c.parent = self; children.add(c) }
}
```

**(c) UI callback capturing self.** The editor ends up shared (held by `window.editor` and by the closure). No weak capture is needed. Closing the window frees the window and the button (unshared, so promptly). The editor fades and, never walked, evaporates after W. A queued tap that arrives later finds the button `lost` and is dropped.
```
class Editor {
  text = ""
  fun build() {
    return Button("Save", onTap: { self.save(); self.dirty = false })
  }
}
app.windows.remove(w)      // cut -> window freed -> cuts -> editor fades
```

**(d) Shared cache used by two components.** Both components lay trails to the cache, so it is shared. If one component dies, the cache fades and the survivor must keep using it, or store it again. Entries live while they are hot.
```
cache = ImageCache()                          // global = hand: never freed while set
class ImageCache { entries = Scent()          // faint values: hot stay, cold fade
  fun get(url) { return entries[url] ?? load(url) } }
gallery.cache = cache;  preview.cache = cache
```

**(e) Mutate a large list.** Parameters are hands, so there are no scent operations and no cost.
```
fun normalise(xs) { for i in 0..xs.count { xs[i] = xs[i] / 255 } }
normalise(pixels)
```

**(f) Threads.** There is no shared heap. `send` moves a graph to another colony; it must not still be held by a trail in the sender (use `take`). For shared mutable state, a colony owns it and the others send it messages.
```
worker = Colony({ inbox -> for job in inbox { process(job) } })
worker.send(take self.batch)        // runtime rehomes batch's graph
```

## 7. What is new

- **Liveness defined by use, not reachability**, and only for data that has actually been shared. Unshared data gets exact, prompt freeing without anyone declaring an owner. "Shared" is a sticky bit you can observe at runtime, not a type or a count.
- **Cycles and captured `self` need no weak refs.** A garbage cycle is simply never walked again.
- **The clock is allocation, not time.** Floating garbage is bounded by a knob, idle programs are frozen, and a single colony is deterministic.
- **Drought mode:** setting W = 0 turns "it works because of timing" into a deterministic test failure.
- **Pheromone caches (`faint`, `Scent`)** are part of the memory model, not a library you add on.

## 8. Less crazy than it sounds, or more

**Less crazy:**
- Tree-shaped data never fades. Rule 4 makes it behave like ideal single ownership.
- Shared, long-lived things usually sit in globals (hands) or are walked all the time (rendered, queried). Fading only bites the narrow case "shared, then one holder let go, then the survivor sat idle while the colony allocated W".
- Reads of settled objects are cheaper than under ARC, and copies are free.
- The safety net (generation checks) is proven technology.

**More crazy:**
- An object you still reference can vanish, and that cannot be checked statically.
- `deinit` timing for shared objects is fuzzy, so files and sockets must be closed explicitly.
- A program's correctness can depend on W, which drought mode exists to flush out.

## 9. Known weaknesses

1. **Idle survivor.** A document open in two windows: close one and the other must walk the document or store it again within W. If it doesn't, the user sees `lost`. Drought mode catches this in tests, and only in code paths the tests exercise.
2. **Copy-then-clear marks the object shared.** `b.x = a.x; a.x = nil` makes `x` shared and then fading. The fix is `take`, one more thing to learn.
3. **Re-closing a dropped cycle leaks.** Cut a tree root, then store a back-pointer to it into its own still-held child through a non-`faint` field: everything is "held" and nothing ever cuts it. That is rarer than ARC cycles, but needs a tracing leak checker in debug builds.
4. **Deep shared structures free slowly.** Without `faint`, a tree with parent pointers takes depth × W to free.
5. **Root scan.** A conservative stack scan is simple and safe (a false hit only delays a free), but it makes the timing of frees nondeterministic. Precise stack maps on LLVM are hard. It is also arguably a small G2 grey area.
6. **Hot-path cost.** Every heap read does a generation check. Every store touches the old target's header. References are 16 bytes unless packed.
7. **Concurrency is the weakest axis:** colonies plus `send` and actors. No shared immutable heap without adding per-colony visa bits.
8. **Rule count (11) and a new mental model.** That costs points on G1 even though no rule is about types.

**Self-assessed** (in the order of the brief's rubric, weighted total): 2.5, 4, 4, 3, 3, 2.5, 3, for about **62**. That is below O1. Its claim to beat O1 is that cycles and callbacks are free, a claim weakened by the idle-survivor `lost` risk.
