# 02 — Unhappen

## 1. Name

**Unhappen**: you free memory by retracting the event that created it.

## 2. The crazy premise

Every memory model has two sacred assumptions:

1. **Freeing is a forward operation on an object** (`free`, `drop`, refcount reaching 0).
2. **A store is permanent until someone overwrites it.** If `a.f = x` ran, `a.f` holds `x` until code writes `a.f` again.

Unhappen breaks both. Nothing is ever freed. Instead, an *act* (a run of code that built something) can be **retracted from history**. When an act unhappens, its objects stop existing, and **every store that ever put a reference to one of those objects anywhere is retroactively un-done**. Each such slot goes back to what it would hold if that store had never run. The program's heap is a history that the runtime edits backwards.

The trick comes from reversible computing (Bennett's compute / copy-out / uncompute) and from selective undo in collaborative editors. It is not "time runs backwards for the whole program". Only *existence* is reversible. Value writes (counters, strings, I/O) are never undone.

## 3. Pitch

You never write `free`, `weak`, `unsubscribe` or `removeObserver`. To close an editor, you un-open it: `unhappen editor`. The runtime removes its button from the app toolbar, takes its closure off the global event bus, removes it from `app.editors`, clears the cache's back-pointer to it, runs its `undo` blocks in exact reverse order of creation, and drops its memory in bulk. No dangling reference can exist, because every cross-act reference was recorded *when it was stored*. This is the remembered set of a generational GC's write barrier, reused as an **undo log instead of a root set**, so nothing is ever scanned. Short-lived work needs no thought at all. Every call is a tiny act that vanishes when it returns unless it published something.

## 4. The rules (everything a programmer must learn)

1. **Values vs objects.** Numbers, strings, lists, maps and structs are values. They are copied or moved and have no lifetime. A function may take a value as a `var` parameter to mutate it in place. Class instances and closures are **objects**, and each one lives in exactly one **act**.
2. **Scratch is automatic.** Objects made during a call die when the call returns, *unless* the call published one: it returned it, or stored a reference to it into an older object. In that case the call's objects stay alive with the object whose method was running (its *home*).
3. **`begin expr` starts a new act.** Everything the expression builds belongs to that act, which is a child of the current home. It lives until it unhappens or its parent does.
4. **`unhappen x`** retracts the act that `x` began, along with its child acts. It takes effect at the end of the current event-loop turn. It traps if `x` is not the root of a `begin`.
5. **Un-storing.** When an act unhappens, each slot that holds a reference into it reverts:
   - a field goes back to its most recent earlier value that still exists, or `nil`;
   - a List element is removed;
   - a Map entry goes back to its most recent earlier surviving value, or is removed.
6. **Required vs optional fields.** A non-optional reference field may only hold an object from the same act or an enclosing act. Anything shorter-lived must go in an optional (`T?`) field. Breaking this traps at the store, with a message naming both acts.
7. **`undo { }` blocks** (destructors) run when their object's act unhappens, in exact reverse order of creation. Unhappening never reverts value writes or I/O.
8. **Threads.** An act belongs to one thread. Values cross threads by move or copy, through `spawn` captures and channels. `shared` objects hold only values and lock their methods.

That is 8 rules. There is nothing about cycles, weak refs, lifetimes, borrows or annotations.

## 5. Under the hood

**Acts and arenas.** Every act has its own bump-allocated chunks. Chunks are 64 KB-aligned, so `act_of(ptr)` is a mask plus a header load. Acts form a tree, and each act stores its depth. An ancestor test walks up by the depth difference, which is usually 0–2 hops.

**Steps.** Every call that allocates objects opens a *step* on its home act (`self`'s act, or the caller's home for free functions). Steps on one act nest last-in, first-out, because acts are confined to one thread. The compiler skips steps for calls that allocate no objects.
- A step records the bump mark when it starts.
- At return, the step **dissolves** (reset to the mark, O(1)) if its outbound-claim list is empty and its return value does not point into its range.
- Otherwise it **splices** into the enclosing step on the same act, or into the act itself: it does not reset, and its claims are re-tagged.
- Escape is known *exactly*, with no inference and no tracing, because the store barrier saw every escape.

**Store barrier (heap slots only; locals are exempt).** On `slot = ref`:
- If `act_of(ref)` is the slot's act or one of its ancestors: plain store, and prune the slot's claim chain.
- Otherwise: allocate a **claim** `{slot, value, older}` and link it onto two lists: `act_of(ref).outbound` and `act_of(slot).inbound`. The slot then holds a tagged pointer to the claim. Reads test one bit.
- A slot's claims form a chain. An older entry is pruned as soon as a newer entry comes from an act that outlives it, because the older entry can then never resurface. In practice the chain length is the number of *distinct live sibling acts* that have written that slot, which is usually 1.

**Unhappen X (at end of turn, when no user frames are on that thread's stack):**
1. Unhappen X's children, depth-first.
2. Run `undo` blocks in reverse allocation order. The arena is walked backwards, which is the literal "un-running".
3. For each outbound claim, unlink it from its slot's chain. The slot now shows the next surviving entry or `nil`. List and Map slots do a semantic remove.
4. For each inbound claim, unlink it from the provenance act's outbound list.
5. Return the chunks.

The cost is O(objects with `undo` + claims + chunks). It is deterministic, and nothing is ever scanned.

**Containers.** `List` and `Map` are compiler-known. They know which elements are tagged. A reallocation moves those elements' claim slot pointers, at a cost proportional to the claimed elements only.

**Deferral protects locals.** Locals never create claims. Unhappen waits for the turn boundary, and frames do not survive a turn, so no local can hold a retracted object. A worker thread's turn ends at its `yield`, or when its loop iteration returns.

**FFI.** C may hold object pointers for the length of a call. Longer holds go through a runtime `Handle` slot, which is an ordinary claimed slot, so C sees `nil` after unhappen.

## 6. Scenarios (illustrative only — not a syntax decision)

**(a) Read lines.** The step never published an object, so it dissolves and the file closes via `undo`.
```
fun readLines(path: String) -> List of String
  var lines = []                       // value
  let f = File.open(path)              // object, in this call's step
  while let line = f.readLine() { lines.append(line) }   // String values copied in
  return lines                         // value moved out → step dissolves, f's undo closes it
```

**(b) Tree with parent pointers.** Cycles are irrelevant inside an act.
```
class Node { value: Int; parent: Node?; children: List of Node }
class Tree {
  root: Node?
  fun add(under: Node, v: Int) -> Node {
    let n = begin Node(v, parent: under)   // own act: individually removable
    under.children.append(n)               // claim in n's act
    return n
  }
  fun remove(n: Node) { unhappen n }       // drops subtree, removes itself from under.children
}
```
`parent` must be optional (`Node?`): the parent is in an enclosing act, so it is allowed, but the root's parent is nil. If nodes never get removed one at a time, use plain `Node(...)` without `begin` and the whole tree lives in one act. That is faster and needs no claims.

**(c) UI callback capturing `self`.** This is the crux.
```
class Editor {
  doc: Document; dirty: Bool
  init(app: App, doc: Document) {
    let save = Button("Save")
    save.onTap = { self.save(); self.dirty = false }   // closure lives in editor's act
    app.toolbar.add(save)                // claim: un-stored when editor unhappens
    app.bus.on("autosave") { self.save() }   // claim
  }
  fun close() { unhappen self }          // allowed: self is the act root
}
class App {
  editors: List of Editor
  fun open(doc: Document) { editors.append(begin Editor(self, doc)) }   // claim
}
```
After `close()`, the end of the turn removes the button from the toolbar, the handler from the bus and the entry from `editors`. The callback cannot fire after close, because nothing refers to it any more. Each tap runs as a step on the editor's act. Scratch is freed unless the tap published a new object into the editor.

**(d) Shared cache used by two components.**
```
class ImageCache {
  entries: Map of String to Image
  fun get(key: String) -> Image {
    if let img = entries[key] { return img }
    let img = begin Image.load(key)      // one act per entry, child of the cache's act
    entries[key] = img
    return img
  }
  fun evict(key: String) { if let img = entries[key] { unhappen img } }
}
class Gallery  { thumb: Image? }         // must be optional: Image is shorter-lived
class Preview  { current: Image? }
gallery.thumb = cache.get("cat")         // claim
preview.current = cache.get("cat")       // claim
cache.evict("cat")   // end of turn: map entry gone; both fields revert to prior surviving value or nil
```

**(e) Mutate a big list in place.**
```
fun normalize(var xs: List of Float) { let m = max(xs); for i in xs.indices { xs[i] /= m } }
normalize(var samples)                   // in place, no copy, no act involvement
```

**(f) Threads.**
```
let out = Channel of List of Int
for chunk in chunks { spawn { out.send(crunch(chunk)) } }   // chunk copied in, result moved out
shared class Progress { done: Int; fun tick() { done += 1 } } // values only, methods lock
```
Each spawned thread has its own root act. Sharing a mutable object graph across threads is disallowed.

## 7. What is new

- **Remembered set used as an undo log.** The barrier is the same one generational GCs use, but its log is *replayed backwards on death* instead of being scanned as roots. Safety comes without tracing, refcounts or generation checks.
- **"Un-storing" instead of nulling.** A slot goes back to its *previous surviving value*, and lists and maps do semantic removes. This is the selective-undo semantics of collaborative editors applied to the heap. Round-1 auto-cleared refs set the slot to nil, and only for declared non-owning refs. Here every field is covered, and authors declare nothing.
- **Exact, free escape detection for scratch.** A call's objects die at return unless the barrier logged an escape. This is region-like, with no region inference and no `promote`.
- **Unregistering disappears as a concept.** Subscriptions, observers, toolbar entries and timers registered by an act are owned by that act's history.
- **Destruction is literally un-running.** Objects are torn down in exact reverse creation order, deterministically.

## 8. Less crazy than it sounds, or more?

**Less crazy.**
- Each component exists today: write barriers with remembered sets, bump arenas, aligned-chunk ownership lookup, tagged pointers, selective undo (OT/CRDT), Time Warp rollback, and ROOPL's `construct`/`deconstruct`.
- The barrier fast path is "same act or ancestor", which is one compare in the common intra-act case.
- Browsers already "unload a document" and quietly drop everything it registered. This makes that a language guarantee.

**More crazy.**
- Your fields change *behind your back* at turn boundaries.
- `preview.current` can quietly go back to the *previous* image instead of nil.
- A List can shrink between two turns, so cached indices become stale.
- You can trust it only if "this reference exists because someone stored it, and that store can be retracted" becomes part of how you think. That is a new mental model, even if it has few rules.

## 9. Known weaknesses

1. **Leaks inside long-lived acts.** An object that is removed from a structure *without* `unhappen` stays until its act ends. This is the classic region leak, moved to programmer intent: individually removable things must be `begin`ned. The rule is safe, but easy to forget. A debug-mode offline reachability report can find these; it is a tool, not a runtime GC.
2. **Splice drag.** When a call publishes one object, it keeps all of that call's object scratch. Value-first code keeps this small, but it is a performance trap that users must learn to see.
3. **Surprising reversion semantics.** Previous-value resurrection, shrinking lists and no notification to observers. UI frameworks would need an `onUnstore` hook on containers, which adds API surface.
4. **Implementation risk is high** for an AI-written compiler:
   - claim chains with pruning;
   - two-list claim linking;
   - claim moves when containers reallocate;
   - barrier codegen on every heap reference store;
   - turn-boundary deferral on every thread;
   - step marks per act.
   Bugs here are silent memory-corruption bugs.
5. **Per-act overhead.** An act per cache entry or per tree node costs a header and at least one chunk, unless small acts sub-allocate from their parent with a free list (more machinery).
6. **The concurrency model is weak.** Values and value-only shared objects work, but there is no shared object graph across threads.
7. **Deferral to the turn boundary.** A long synchronous computation cannot release a retracted act mid-turn. The `yield` points of worker threads become semantically significant.
8. **The required/optional rule is a dynamic trap**, not a compile error. Act relationships are runtime facts.

**Gates.** G2 passes: no scan ever happens, and every free is deterministic. G3 passes: `begin`, `unhappen`, `undo` and `T?` are keywords and type forms, not annotations. As usual, compiler-known `List`/`Map` are flagged. Determinism is kept.

**Self-assessment** (score × weight / 5):

| Criterion | Score | Points |
|---|---|---|
| Simplicity | 3 | 15 |
| Safety | 4 | 12 |
| Expressiveness (c is excellent; b and d need `begin` discipline) | 4 | 12 |
| Implementation risk | 2 | 6 |
| Performance | 3 | 6 |
| Concurrency | 2 | 4 |
| Tooling / FFI (debugger can answer "who stored this, and when was it un-stored") | 4 | 8 |
| **Total** | | **≈ 63** |

The strongest piece to transplant elsewhere is "claims as an undo log" for UI registrations, possibly on top of O1 or O4.
