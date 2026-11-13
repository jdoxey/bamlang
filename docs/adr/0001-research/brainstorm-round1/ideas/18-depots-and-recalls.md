# 18 — Depots, Delivery and Recall

## 1. Name

**Depots, Delivery and Recall** ("consignment memory").

## 2. Inspiration — how the lens maps onto memory

| Logistics | Memory |
|---|---|
| Shipping container / depot | A region of heap that is allocated, moved and freed as one unit |
| Goods are delivered *to the consignee*, not left at the factory | A new object is built in the depot of whatever it's being handed to |
| Inside one container, goods can be strapped to each other in any way | Inside one depot, references are unrestricted: cycles and back-pointers are fine |
| Bill of lading: a document referring to goods somewhere else | A `far` reference: a cross-depot pointer recorded in the target depot's ledger |
| Product recall: the maker knows every outstanding bill and voids them | Closing a depot walks its ledger and empties every far ref into it, right away |
| A parcel addressed to someone who has moved: returned to sender | A closure that captured something now gone isn't run. It's "returned" |
| Ship the whole container, not each box | Hand a depot to another thread in O(1), cycles and all |
| Bonded warehouse: shared, under customs lock | A shared depot that you can only enter while holding its lock |
| Packaging vs goods | List buffers and string bytes are packaging, owned and freed eagerly |

The key point from logistics: **lifetimes belong to places, not to scopes.** A window, session or cache isn't a block of code. It's a warehouse that opens and closes when its owner decides. Non-nesting lifetimes are handled by *which depot an object is in*, not by *where it was created in the code*.

## 3. Pitch

Every object lives in a **depot**. A depot is a first-class value that you own like any other object, so a window owns its depot, a cache owns its depot, and a session owns its depot. Inside a depot you write code as in a garbage-collected language: parent pointers, cycles, and closures that capture `self` all just work. You never write `weak`. Non-cyclic garbage is freed straight away by invisible, non-atomic, depot-local reference counting. Cycles are freed when the depot closes, deterministically and without tracing. Allocation is **destination-driven**: `button.onTap = { self.save() }` builds the closure in the button's depot, so most stores are same-depot without the programmer thinking about it. References that cross depots must be `far`. Far refs are listed in the target's ledger, and when the target goes away they are **recalled** (emptied) in one bounded pass. Closures that capture across depots become **addressed parcels**: if the addressee is gone, the callback simply isn't delivered. This dissolves the UI-callback crux. Whole depots can be shipped to another thread in O(1).

## 4. The rules (everything a programmer must learn)

1. **Values vs objects.** Numbers, strings and `struct`s are values and are copied when assigned. Class instances, lists, maps and closures are objects, and every object lives in a depot.
2. **Depots.** `depot(expr)` creates a depot and builds `expr`'s result inside it as the depot's *root*. Whoever holds the depot value owns it. The program starts in the `main` depot.
3. **Delivery.** A new object is built in the depot of where it's going. That means the depot of the object whose field or list it's stored in, or the depot of the receiver of the method it's passed to. Otherwise it goes in the *current depot*: `self`'s depot inside a method, or the caller's current depot in a free function. `in d { ... }` overrides this.
4. **Inside a depot, anything goes.** Cycles, parent pointers and closures capturing `self` need no special handling.
5. **Ordinary fields stay home.** A normal field or element may only hold objects from its own depot. Storing an *existing* object from another depot there is an error: at compile time when it's obvious, otherwise a trap at the store. The fix is a `far` field or `copy x`, which deep-copies the object into the destination.
6. **`far` refs.** A `far` field or element may point anywhere, including into its own depot as a non-owning back-pointer. It is *returned* (emptied) when its target is freed. You read one with `receive f as x { ... } else { ... }`.
7. **Locals hold.** Locals and parameters may refer to anything. What you hold stays alive while you hold it.
8. **Freeing.** An object is freed as soon as nothing in its depot and nothing on the stack refers to it, or when its depot closes, whichever comes first. Cycles inside a depot wait for the close.
9. **Closing.** A depot closes when its owner drops it or someone calls `close d`. Every far ref into it is returned at once. Its memory is released when no running code is still inside it.
10. **Closures are parcels.** A closure captures objects from other depots as far refs, automatically. When it's called and any of those objects is gone, a callback with no result is skipped and dropped by whoever was holding it. A closure that returns a value panics with `undeliverable`.
11. **Threads.** Each depot belongs to one thread. `ship d to t` hands over the whole depot in O(1), and far refs that cross the handoff are returned. A `bonded depot(...)` is shared between threads. `receive` on it takes its lock, and it may only hold far refs into other bonded depots.

Eleven rules. Rules 4, 7 and 8 are mostly "you don't have to do anything".

## 5. Under the hood

**Depot layout.** A depot is a set of 64 KiB-aligned chunks with a size-class allocator. Each chunk starts with a header pointing to the depot record, so finding an object's depot is `ptr & ~0xFFFF` followed by one load. Large objects get their own aligned chunk. The global depot table holds: id, name (for debugging), owner thread, state (`open | sealed | shipped`), pin count, an **incoming ledger** (target object → addresses of far slots pointing at it), an **outgoing far list**, and a lock if bonded.

**Depot-local RC.** Every object header has a non-atomic count of near references (fields, elements, locals). It is never atomic because only one thread touches a depot at a time, and bonded depots are only touched under their lock. Standard ARC optimisations apply (+0 parameters, eliding retain/release pairs). When the count reaches zero:
1. run `deinit`;
2. release the object's near children;
3. unregister its outgoing far slots;
4. recall far slots aimed at it;
5. return its memory to the depot's free list.

**Near-store barrier.** Each store into an ordinary field compares the chunk headers of holder and value. On a mismatch it traps with: `stored object from depot "Image cache" into Editor.thumb (depot "Editor window"); use far or copy`. The compiler drops the check when it can prove both sides share a depot. Provenance analysis within one function covers most cases: values derived from `self` or `self`'s fields, values just built by delivery to that holder, and values passed to a method of that holder. Most stores in OO code fall into these cases.

**Destination passing.** Every function gets a hidden `shipTo` depot argument. `x.f = make()` passes `depot(x)`. `r.m(Thing())` evaluates `Thing()` with `shipTo = depot(r)`. A method body's current depot is `depot(self)`. This is compile-time plumbing with no user syntax.

**Far slots.** A far slot holds a plain pointer, and storing one updates the ledger. A recall writes null. `receive` is a null check plus +1 on the object plus a pin on its depot. Far locals on the stack are registered in the ledger too, and unregistered when their scope exits.

**Pins and closing.** The pin count says how many running frames are inside a depot. Pins are taken by `receive`, by `in d {}`, by delivering a closure, by run-loop dispatch, and by any local whose provenance the compiler can't tie to an already-pinned depot. `close` does three things:
1. It sets the state to `sealed` and recalls every incoming far slot. After this, no new deliveries reach the depot.
2. If pins are 0, teardown runs now. Otherwise it runs when the last pin drops.
3. Teardown has three phases: run every live object's `deinit` while all memory is still valid, unregister outgoing fars, then release the chunks.

Teardown doesn't trace reachability, so it isn't a GC run. Its cost is the depot's own object count, or just the chunk count if no `deinit`s exist.

**Closures.** At creation the runtime compares each capture's depot with the closure's own depot. Captures from the same depot are stored near (counted). Captures from other depots are stored far (ledgered). A call checks the far captures, pins their depots and runs the body. Callback registries (run loop, timers, event buses) prune any entry whose closure is undeliverable.

**Ship.** `ship` requires that the sending thread has pin count 0 on the depot, otherwise it traps with "container still being loaded". It recalls the incoming far slots that live in the sender's depots and the depot's outgoing fars into the sender's depots. Then it changes the owner thread. No object is copied or touched.

**Bonded.** `receive` on a bonded depot locks it. Far slots that point into bonded depots are loaded atomically and re-checked after the lock is taken. `receive a, b` locks in depot-id order.

**Tooling.** The debugger shows the **manifest** of each depot: its objects by class, bytes, pins, and incoming/outgoing far refs. In debug builds every recall records a **chain-of-custody** entry, so a returned far explains itself: `returned: depot "Editor window" closed at editor.x:88 by Window.close`. C FFI: depot memory is ordinary memory, so pointers passed to C are valid for the duration of the call. `hold x` pins x for C code that keeps the pointer longer.

## 6. Scenarios

*All code is illustrative only — not a syntax decision.*

### (a) Read a file of unknown length into a list of lines

```
func readLines(path: String) -> List of String {
    lines = List()
    f = open(path)
    while f.readLine() as line { lines.add(line) }
    return lines
}
self.doc.lines = readLines("notes.txt")   // shipTo = depot(self.doc)
```

`lines` is built straight into the depot of `self.doc`, which is where it ends up, so nothing is moved or copied. When the list grows, its backing buffer (packaging) is reallocated and the old buffer is freed immediately. Lines are strings, which are values stored inline in the buffer. There are no rules to think about.

### (b) Tree with parent pointers

```
class Node {
    parent: Node?            // near: fine, cycle is OK
    children: List of Node
    func addChild(v) { c = Node(v); c.parent = self; children.add(c) }
}
tree = depot(Node("root"))
// short-lived tree (parse, use, discard): near parents; dropping `tree` frees all
class LiveNode { far parent: LiveNode?  children: List of LiveNode }
// long-lived editable tree: far parent → removed subtrees freed immediately by RC
```

`Node(v)` runs inside `self`'s method, so it's in the same depot, and the parent pointer is a near ref. Near parents create cycles. In a parse-and-discard tree that doesn't matter, because the cycles go when the depot closes. In a long-lived tree where subtrees get removed, making `parent` a `far` ref to the same depot turns it into a non-owning back-pointer. A removed subtree's count then hits zero and it's freed straight away, and any lingering far refs to it are recalled. `weak` is an optimisation here, not a requirement for correctness.

### (c) UI callback capturing enclosing state (the crux)

```
class Editor {
    doc: Document
    dirty = false
    saveButton: Button
    init() {
        saveButton = Button("Save")
        saveButton.onTap = { self.save(); self.dirty = false }   // built in button's depot = self's
        timers.after(30s) { self.autosave() }                      // built in timers' depot → captures self far
    }
}
func openEditor() { windows.add(depot(Editor())) }      // windows list owns the depot
func closeEditor(w) { windows.remove(w) }                // depot closes
```

The editor, its button and the `onTap` closure share one depot. The closure captures `self` with a near ref, and the cycle (button → closure → editor → button) costs nothing. The UI system registers the button with a far ref. On a tap, the run loop receives the button, pins the depot and calls `onTap`. When the window closes:
- the depot closes;
- the UI's far refs are recalled and the run loop prunes them;
- the timer's closure, built in the timers' depot, holds `self` as a far capture, so after the window is gone the parcel is undeliverable and is skipped and dropped.

There is no `[weak self]`, no capture list, no leak and no dangling callback.

### (d) Shared mutable cache used by two components

```
imageCache = depot(ImageCache())                    // app holds it
class Gallery    { far cache: ImageCache
    func show(url) { receive cache as c { img = c.get(url); draw(img) } else { drawPlaceholder() } } }
class Thumbnails { far cache: ImageCache  ... same pattern ... }
// inside ImageCache.get: entries = Image(bytes) → built in cache's depot (receiver)
```

Both components refer to the cache with far refs and mutate it through `receive`. Allocations inside the cache's methods land in the cache's depot automatically. A component that wants to keep an image keeps a `far` ref to it. When the cache evicts that entry, its count hits zero and the component's far ref is recalled. That is exactly the semantics a cache wants. Storing `img` into an ordinary Gallery field traps and points at `far` or `copy`. If the app shuts the cache down, both components see `else`.

### (e) Passing a large list to a function that mutates it

```
func normalize(xs: List of Float) { m = max(xs); for i in 0..xs.count { xs[i] = xs[i] / m } }
normalize(self.samples)
```

Objects are passed by reference, so the list is mutated in place with no copy and no `inout`. `xs.add(Thing())` inside the function would deliver into `xs`'s depot. Iteration is index-based and bounds-checked, so growth during a loop can't dangle.

### (f) Sharing data between threads

```
job = depot(loadBatch(path))                // a whole graph, cycles and all
ship job to worker                           // O(1): no copying, sender loses access
// worker:  receive job.root as batch { process(batch) } ; ship job to main

totals = bonded depot(Map())
// any thread:
receive totals.root as t { t[key] = t[key] + n }   // takes the lock
```

Ownership transfer moves the whole container, and a graph of any shape crosses the thread boundary in constant time. Far refs that would cross threads are recalled at the handoff, so no unsynchronised cross-thread pointer can exist. Truly shared mutable state lives in a bonded depot, with one lock per depot and RC inside it that is still non-atomic. For small messages, `copy x` deep-copies into a fresh depot that you then ship.

## 7. What's genuinely new vs. the covered options

- **Not scope-bound regions.** Depots are first-class owned values whose lifetime is set by whoever owns them (a window, a cache, a session), so non-nesting lifetimes are natural. There's no `promote` and no leak-to-global.
- **Destination-driven allocation as a language rule.** "Build it where it's going" (field owner or method receiver) makes the same-depot invariant hold automatically for most OO and DSL code, with no region annotations (G3) and no inference fragility.
- **Recall at container granularity.** Closing a depot actively empties every incoming reference through a ledger in one bounded pass. Vale's generations check on every dereference. Weak refs are zeroed object by object. Recall is closer to a product recall: the supplier knows every bill outstanding.
- **Cycles freed by container close, not by a cycle collector.** This is O7's backstop with no tracing at all. Cycle lifetime is bounded by an owner the programmer chose.
- **Closures as addressed parcels.** Captures are classified near or far at runtime, and calls are delivered only if every addressee exists. This replaces weak-self capture lists with a semantic that callback registries can act on.
- **O(1) thread transfer of arbitrary graphs** without isolation types (Pony `iso`), using a dynamic pin check.
- **Manifest and chain-of-custody tooling.** Recalls carry their cause, so a dead reference explains itself.

## 8. Known weaknesses

- **"Wrong depot" traps are a new runtime error class.** They happen at the store, which is close to the cause, but they're found by testing, not by the compiler.
- **Cycles in long-lived depots leak until close.** In a `main` depot that lives for the whole program, that means forever. Users of long-lived structures must re-learn "make the back-pointer `far`", so weak refs come back as an optimisation.
- **Choosing depot granularity is a design skill.** Too coarse leaks cycles and makes closes expensive. Too fine produces `far` everywhere and lots of `receive` boilerplate.
- **Delivery heuristics can surprise.** Passing a temporary to a method on a far object builds it in that object's depot even if the method only reads it. It's still freed by RC, but placement is less obvious.
- **Runtime cost.** There's a store barrier on unproven near stores, ledger updates on every far store, non-atomic RC, and pins. This should be cheaper than atomic ARC but costs more than Rust/Hylo.
- **Value-returning closures panic when undeliverable.** That's an abrupt edge on an otherwise forgiving rule.
- **Sealed-but-pinned depots delay freeing.** A long `receive` keeps a closed window's memory alive.
- **Bonded depots use coarse locks.** Nested `receive`s on different bonded depots can deadlock.
- **Teardown time is proportional to object count** when `deinit`s exist. Closing a huge depot has a pause that is predictable but can be large.
- **Implementation risk is moderate.** The pieces needing care are the ledger, pin provenance analysis, destination passing, atomic far slots for bonded depots, and the debugger manifest. Each is well-understood alone, but together they are a lot for an AI-written compiler.

**Gates (self-assessed).**
- **G2:** pass. There is no tracing and no background collection. Close is bounded by the depot's own ledger and object count.
- **G3:** pass. `far`, `receive`, `depot`, `ship` and `bonded` are keywords, not annotations. It relies on compiler-known `List of T`/`Map`, which is flagged as the pending question.

**Rough rubric self-score.** Simplicity 4, safety 4, expressiveness 4.5, implementation risk 3, performance 3.5, concurrency 4, tooling 4, for a total of **≈ 77**.
