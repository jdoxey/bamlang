# 14 — Biome: habitat trees, upstream migration, seasonal die-off

## 1. Name

**Biome.** Objects live in *habitats* arranged in a tree. They *migrate* upward when stored somewhere longer-lived. They die in bulk when their habitat is *felled*, and that death is processed at the next *season turn*.

## 2. Inspiration

| Ecology | Memory |
|---|---|
| Habitat | A region: a set of objects that die together. Pointers inside one habitat are free, cycles included. |
| Watershed / food web | Habitats form a tree. Water and nutrients flow downhill, so a child habitat can always depend on its ancestors. An ancestor depending on a child is the case that needs handling. |
| Migration | If you store a reference to an object in a place that outlives it, the object (and its herd, i.e. what it reaches) moves to the nearest habitat that outlives both. It never goes further up than that, and it never moves down. |
| Keystone species | A `habitat class` instance founds a habitat and anchors it. When the keystone is removed, the habitat collapses. |
| Seasons | Deaths are not processed immediately. Felled habitats die at the next *season turn* (an event-loop tick). At that point no stack frame is holding anything, so bulk death is always safe. |
| Rooted plants | A closure cannot migrate. It lives in the habitat of what it captured. Anyone else who holds it holds a *track*, and the closure goes *dormant* when its habitat dies. |
| Decomposition / soil | A dead habitat's census is walked and freed, and its pages go back to a thread-local pool (the "soil") for reuse. |
| Islands | Habitats that a thread can send away or share. Anything crossing the shore is copied, so no pointer can cross it. |
| Carrying capacity | Each habitat keeps a census, which tooling reports, so a leak is reported against a named habitat. |

## 3. Pitch

Biome is region-based memory where the regions are a **dynamic tree of habitats tied to objects, not to scopes**. The store barrier keeps one invariant: **a heap pointer only ever points at a habitat that outlives the habitat it is stored in.** A store that would break this does not fail. The target object migrates up to the nearest common ancestor, and since migration only moves objects toward the root, it never invalidates a pointer. This differs from "promote to global" because a cache shared by two windows rises only to the app habitat, not to the program root. Death is coarse and explicit: you `fell` a window, a session or a cache entry. It is applied at the next season turn, which is what makes stack references safe with no borrow checker and no refcounting of locals. Closures stay in the habitat of what they captured, and everything else reaches them through tracks that are checked per habitat. So the UI-callback crux (c) needs no `weak self`, cannot form a retain cycle, and a callback whose window has closed quietly becomes a no-op. There is no tracing collector, no lifetime annotations and no refcounts on ordinary objects.

## 4. The rules (everything a programmer must learn)

1. **Values vs. objects.** Numbers, strings and `struct`s are values. Their container owns them and they are freed when overwritten. `class` instances (including `List`/`Map`) are objects and live in habitats. There are no interior pointers to values.
2. **Scratch by default.** Each function call has a scratch habitat (a *puddle*). An object nobody stores anywhere dies when the function returns. A returned object moves into the caller's habitat.
3. **Storing never dangles.** `a.f = b` just works. If `b`'s habitat might die before `a`'s, `b` and whatever it reaches move up to the nearest habitat that outlives both. Mental model: *storing something somewhere makes it live at least as long as that place.*
4. **`habitat class` founds a habitat.** Each instance (a *keystone*) gets a new habitat. That habitat is a child of the habitat that created it, or of the thread root. Objects stored into a keystone's fields live in its habitat.
5. **`fell k`** ends a keystone's habitat, together with its child habitats. It takes effect at the next **season turn**. Season turns happen on every event-loop tick, and at `turn` statements, which are only allowed in a thread's root function. A keystone you never fell lives as long as its parent habitat.
6. **Keystone references may be gone.** Outside the keystone's own habitat, a reference to a keystone is a *track*. Read it with `k?.field` or `if k is live`. Inside a keystone's own methods, `self` is always live.
7. **Closures live with what they capture.** A stored closure (in a field or container) may be dormant. Calling a dormant closure does nothing and gives `none`. Closures passed as parameters are always live.
8. **Threads don't share habitats.** `send` copies values and plain objects to another thread. A keystone declared `island habitat class` can be sent whole: it is moved at the next season turn, and the sender's tracks go dormant.
9. **Islands copy at the shore.** Storing an outside object into an island copies it in. Reading an island object into outside storage copies it out. Islands shared between threads are touched only inside `graze isl { ... }`, which holds the island's lock. References obtained inside the block can't outlive it.

Rules 1–3 cover ordinary code. Rules 4–7 cover long-lived or UI code. Rules 8–9 cover threads. There is an optional tool, `burn`, in section 5, which is not a rule.

## 5. Under the hood

**Object header (8 bytes):** a 32-bit habitat id and a 32-bit census slot. Each habitat has a descriptor holding its parent, depth, generation, thread, census (a chunked array of object pointers) and its kind (puddle, keystone or island). Descriptors are pooled and never freed, and their generation is bumped on reuse.

**Store barrier** on every object-reference store `a.f = b`:
```
illustrative only — not a syntax decision
ha = hab(a) (for a keystone's own fields: its own habitat); hb = hab(b)
if hb == ha → done                       // fast path, one compare
if b is keystone/closure → store track (ptr, hb, hb.gen); done
if outlives(hb, ha) → done               // ancestor walk by depth; puddles are below everything
T = youngest habitat outliving both (LCA in the tree; puddle-vs-keystone → the keystone's habitat)
migrate(b, T)
```
- **`migrate(b, T)`** moves `b` from its old census to `T`'s (an O(1) swap-remove plus append, with no physical move). It then visits `b`'s reference fields, using compiler-emitted layout maps, and repeats for any child whose habitat does not outlive `T`. It stops at tracks and at objects that are already high enough.
- **Bound:** objects only move toward the root, so each object migrates at most *depth* times over its whole life. Total migration work is ≤ objects × tree depth, and depth is usually 2–5.
- **Puddles** are always treated as younger than every live keystone habitat. That is sound because keystone habitats only die at season turns, and no puddle is alive then except the root frame's.

**Destination passing:** escape analysis finds allocations that flow to a return value or straight into a store (`self.items.add(Item())`). It allocates them directly in the destination habitat, so the common case never migrates. Objects that provably stay in the puddle are bump-allocated and released in one step at return.

**Season turn** (per thread):
1. For each felled habitat, depth-first over its children: run `deinit` on every censused object. A `deinit` may store an object elsewhere, in which case it migrates out and survives ("seed dispersal").
2. Free everything still in the census and return the pages to the soil.
3. Bump the generation so every track into the habitat reads as dormant.
4. Apply any pending `send`s of islands: reparent under the receiving thread's root, bump the generation, change the thread tag.

**Tracks** are `(ptr, habitat id, gen)`. Dereferencing one is a single load and compare against the descriptor's generation. When the track is inside the target's own habitat, the compiler drops the check. The standard-library `Event` type removes dormant handler tracks at each turn.

**Islands:** the barrier refuses to let any island object point outside the island. An outward store copies the herd in instead, and closures can't be stored into an island at all. A plain pointer into an island can only be held by island objects or by locals scoped to a `graze` block. A shared island is felled by any holder. Because liveness is checked under the lock, a dead island fails a `graze` with `none`.

**`turn` check (compile-time, local):** at a `turn` statement, the only reference-typed locals that may be live are tracks.

**Optional tool, `burn k`:** an explicit, opt-in sweep of one habitat at a season turn. It marks from the keystone plus a per-habitat remembered set of incoming child pointers, which the barrier already sees, then frees whatever was not marked. It exists for long-lived habitats with heavy churn. **This is a scoped mark-sweep and needs John's ruling under G2.** The model works without it.

**Tooling:** a live census per habitat ("window#3: 1,204 objects, 2.1 MB; app: 50k and growing"). A migration log ("`Item` allocated at edit.x:12 moved to `app` because it was stored into `Cache` at cache.x:40"). In debug builds, an orphan detector counts incoming tracks and flags keystones that have no tracks and were never felled. Debuggers can show which habitat owns any address.

**C FFI:** a pointer handed to C is valid until the next season turn. For longer, hand C an island or a keystone and fell it yourself. C-allocated memory is wrapped by a keystone whose `deinit` frees it.

## 6. Scenarios

### (a) Read a file into a growing list
```
illustrative only — not a syntax decision
func readLines(path: String) List {
  lines = List()                 // destination-passed: allocated straight in the caller's habitat
  for line in File.open(path).lines { lines.add(line) }  // strings are values in the buffer
  return lines
}
```
When the list grows, it reallocates its private buffer and frees the old one immediately. That is safe because user code never sees a pointer into the buffer (rule 1). Returning costs nothing because of destination passing. Without it, the list would migrate to the caller in O(1), since strings are values and don't need to be visited.

### (b) Tree with parent pointers
```
illustrative only — not a syntax decision
class Node { parent: Node?  children = List()  name: String }
habitat class Outline {           // the tree's habitat
  root = Node(name: "root")
  func add(under: Node, name: String) Node {
    n = Node(parent: under, name: name)   // allocated in under's habitat
    under.children.add(n)
    return n
  }
}
```
Every node lives in the outline's habitat. Parent pointers are plain pointers with no `weak` and no check. The cycle costs nothing because the whole habitat dies together when the outline is felled. Weakness: a removed subtree stays allocated until the outline dies. For outlines with heavy churn, either `burn` it occasionally or rebuild it into a fresh `Outline`.

### (c) UI callback capturing enclosing state (the crux)
```
illustrative only — not a syntax decision
habitat class Editor {
  text: String = ""
  saveButton = Button(title: "Save")
  init() {
    saveButton.onTap = { save(); text = text + "\n// saved" }  // captures self
    App.shared?.events.onQuit.add({ save() })               // registered upstream, on the app
  }
  func save() { Disk.write(path, text) }
  func close() { fell self }
}
```
- The first closure captures `self`, so it lives in the editor's habitat. The button is also there, so `onTap` is a plain same-habitat reference. The cycle editor → button → closure → editor is free, and it dies with the editor.
- The second closure also lives in the editor's habitat. The app's `onQuit` list is upstream of it, so the list gets a **track**. When `close()` fells the editor, the turn frees the editor, its button and both closures. The track goes dormant, `Event` removes it, and if the app quits later that handler does nothing.
- Nothing has to be marked weak, a retain cycle is impossible, and a use-after-free is impossible. Mutating `text` from the callback is ordinary single-threaded mutation. There is no exclusivity rule, because nothing is freed between ticks.

### (d) Shared mutable cache used by two components
```
illustrative only — not a syntax decision
habitat class Entry { value: Image }
class Cache {
  entries = Map()                              // String -> Entry (tracks)
  func get(k: String) Entry? { return entries[k] }
  func put(k: String, img: Image) { e = Entry(value: img); entries[k] = e }
  func evict(k: String) { entries[k]?.fell(); entries.remove(k) }
}
// in App.init:
cache = Cache()
gallery = Gallery(cache: cache)    // cache moves into gallery's habitat...
editor  = Editor(cache: cache)     // ...then rises to App: the nearest habitat outliving both
```
The cache rises automatically to the common ancestor of its two users, and no further. Each entry is its own small keystone, so eviction really does free its memory (at the next turn). A component that holds an `Entry?` across ticks sees `none` after eviction, which is correct for a cache. If `Image` were a plain class stored straight into the map, evicted images would stay allocated until the app dies. The keystone-per-entry idiom is how you avoid that.

### (e) Pass a large list to a function that mutates it
```
illustrative only — not a syntax decision
func normalize(rows: List) { for i in 0..rows.count { rows[i] = rows[i].trimmed() }  rows.add(Row.footer()) }
normalize(bigList)
```
Lists are objects, so this passes a reference. There is no copy, no `inout` and no borrow. `Row.footer()` is destination-allocated straight into `bigList`'s habitat. Two references to the same list can both mutate it on one thread, and it is safe because nothing is freed mid-tick.

### (f) Sharing data between threads
```
illustrative only — not a syntax decision
island habitat class Stats { counts = Map() }
stats = Stats()
for i in 0..4 {
  spawn { for w in chunk(i) { graze stats { stats.counts[w] = (stats.counts[w] ?? 0) + 1 } } }
}
island habitat class Batch { rows = List() }
b = Batch(); fill(b); send b to writer     // moves whole habitat at next turn; our track goes dormant
```
A `spawn` closure copies its captures, except island tracks, which are shared. The `graze` lock is the only way into a shared island, and the `String` key and the `Int` are values copied in. Sending a whole habitat is O(1): reparent it and bump its generation. Copying only happens at the shore, and the shore is explicit.

## 7. What's genuinely new vs. the covered options

- **Migration to the nearest common ancestor in a dynamic, object-anchored habitat tree.** The covered region scheme ties regions to scopes and promotes to global. Biome ties habitats to keystone objects and migrates only as far as needed. The invariant "migration is monotone upward, so it never invalidates a pointer" gives safety with no inference and no annotations. The amortised bound (≤ depth moves per object) makes the cost predictable.
- **Season-deferred bulk death.** Stack references are safe because habitats only die when the stack is empty. That replaces borrow checking (O4/O5), counted borrows (O6/Inko) and retain/release on locals (O1).
- **Closures that live with their captures, reached through tracks that go dormant.** This makes "callbacks registered on a longer-lived emitter" safe and self-cleaning by construction. ARC (O1/O7) needs `weak self`, and value semantics (O2/O3) have to forbid the pattern.
- **Generation checks per habitat, not per object.** A track checks the habitat's generation, unlike Vale's per-object counters (O6). Ordinary pointers carry no check, and only keystone and closure references can dangle-safely.
- **Moving a whole habitat between threads in O(1)**, by bumping its generation, plus islands that copy at the shore. Neither needs Send/Sync markers.
- **Leaks have an address.** The census and migration log blame a habitat and a store site, not an anonymous retain cycle.

## 8. Known weaknesses

- **Leaks inside regions.** A class object removed or overwritten inside a long-lived habitat stays until that habitat dies. You avoid it with design discipline (keystone per lifecycle, values for churn) or with `burn`, which needs a G2 ruling.
- **Surprising herds.** One store can lift a large subgraph into `app` (for example, logging one tree node globally lifts the whole tree). It is safe and the log explains it, but it is spooky action at a distance and a hidden cost at that store.
- **Every reference store pays a barrier**, plus an 8-byte header and census upkeep. The fast path is a single compare, but it applies to every store.
- **Seasons need a tick.** A long computation inside one tick, or a batch program that never calls `turn`, can't reclaim felled habitats until it reaches one.
- **Track ergonomics.** Keystone references read as optional (`k?.x`), tracks are 16 bytes, and calling a stored closure gives an optional result.
- **Unfelled keystones live as long as their parent.** Forgetting `fell` is a bounded leak, not a crash, and the debug orphan detector helps.
- **Islands cost copies** at the shore, and `graze` is coarse-grained locking.
- **Implementation risk: moderate.** It needs a runtime barrier, layout maps for the migration walk, a dynamic ancestor check, destination-passing escape analysis and per-thread season scheduling. Each part is conventional and testable on its own, but escape analysis quality decides the performance.
- **Gates:** G2 passes for the core model. The migration walk is a bounded traversal of the escaping subgraph only and never searches for garbage. `burn` needs John's ruling. G3 passes: `habitat class` and `island habitat class` are declaration kinds, not annotations. It relies on built-in `List`/`Map` (flag).
