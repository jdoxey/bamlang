# 08 — Ground Plane: soldered parts, checked wires, clock-edge frees

## 1. Name

**Ground Plane** (also called "Boards & Wires"). Components are mounted on boards, references are wires, and a
wire is legal only if it runs *toward ground*. Memory is reclaimed only on the *clock edge*.

## 2. Inspiration: how the lens maps onto memory

| Hardware | Memory model |
|---|---|
| A PCB holds chips; daughterboards plug into sockets | Ownership tree. Every component is mounted on exactly one owner |
| **Soldered** chip: comes off only when the whole board is scrapped | `part` field: set at construction, never replaced. Lives exactly as long as its owner |
| **Socketed** chip: hot-swappable | `socket` field / owning list slot: can be emptied or replaced |
| A trace to the ground plane or a power rail is always safe: those outlive every chip | A **plain wire** to anything that can't be removed without also removing the wire's holder is always safe. It is a raw pointer with zero runtime cost |
| A trace into a hot-swap socket floats when the card is pulled; a pull-down resistor makes it read 0 | An **optional wire** (`T?`) into a socket reads `none` once its target is pulled |
| Design Rule Check (DRC) rejects illegal traces before fabrication | The runtime checks a wire when it is *connected*, not on every read. Many checks are discharged at compile time |
| Synchronous logic: state settles between clock edges, registers latch on the edge | Nothing is freed mid-tick. Removed components are reclaimed on the **tick** (event-loop turn, task end) |
| Clock domains talk through async FIFOs; dual-port RAM sits on a shared bus with an arbiter | Threads are clock domains. They exchange values over channels or move subtrees; `shared` components sit on a process *backplane* behind `with` |
| A blown fuse disconnects the load | A closure in an optional slot is "blown" (`none`) once something it captured is removed |

## 3. Pitch

Every class instance is a component with exactly one owner, so ownership forms a tree that the runtime can actually see:
each component's header records its owner. Owning fields come in two kinds. *Soldered* (`part`) fields are fixed for
life. *Socketed* (`socket`) fields can be swapped. Every other reference is a **wire**. The language has one design rule:
**a plain wire may only point at something that cannot be removed unless the wire's holder is removed too.** That covers
any owner-ancestor, anything reached from an ancestor through soldered parts only, and your own soldered parts. Such wires
can never dangle. They are raw pointers with no reference counts and no generation checks, and cycles among them are
harmless because nothing is counted. A wire that breaks the rule must be optional (`T?`). It reads `none` after its target
is pulled. Locals and parameters may point anywhere, because nothing is freed until the clock edge, when no user stack
frames remain. Declarative UI trees are mostly soldered, so callbacks that capture `self` or a sibling are legal by
construction. Callbacks that reach into a hot-swap area act as fuses and stop firing when that area goes away. No
annotations, no lifetimes, no RC traffic, no collector.

## 4. The rules (everything a programmer must learn)

1. **Values vs components.** Numbers, strings and structs are *values*. Assigning one copies it (big ones are
   copy-on-write internally), and nothing can point into a value. Class instances, `List` and `Map` are *components*.
   They have identity, and passing one passes a reference.
2. **One owner.** Every component is owned by exactly one place: a `part` field, a `socket` field, a slot in an owning
   list (`List of part T`), or a local variable. Ownership moves with `take` (and implicitly when you assign a freshly
   constructed component). When the owner lets go (a socket is emptied or replaced, an element is removed, a function
   returns without handing off its local), the component **and everything it owns** is removed.
3. **Soldered or socketed.** A `part` is set during construction and never replaced, so it lives exactly as long as its
   owner. A `socket` (and every owning list/map slot) can be emptied or replaced at any time.
4. **Wires point toward ground.** Any other field, list element or closure capture of component type is a wire. A plain
   (non-optional) wire may point only at a target that can't be removed without removing the holder too: an
   owner-ancestor, anything reachable from an ancestor through `part` fields only, or the holder's own `part`s. A
   violation **traps at the moment of connection**, and the error names both ends by tree path, for example
   `App/tabs[2]/editor`.
5. **Optional wires may point anywhere.** A `T?` wire that breaks rule 4 reads `none` as soon as its target is removed.
   A closure stored in an optional slot reads `none` ("blown fuse") once anything it captured is removed.
6. **Locals are always safe.** Locals and parameters may refer to anything. A removed component stays readable (its
   `deinit` has already run) until the tick ends.
7. **Bench leniency.** A component held only by a local is "on the bench", and its wires are not checked yet. They are
   checked when it is installed into a `part`/`socket`/owning slot, and again whenever it is moved with `take`.
8. **Ticks reclaim.** Memory of removed components is freed at the tick: when the event loop finishes dispatching, when a
   thread's task finishes, or at an explicit `tick` statement in `main`/a thread entry function.
9. **Threads.** Each thread owns its own tree. Between threads you send values, or `take` a component subtree. A sent
   subtree's plain wires must not point outside it (trap), and its optional wires are cut to `none`. A `shared class`
   instance declared at top level hangs from the process backplane. Any thread may wire to it, but its members can be
   touched only inside `with x { ... }`, and references obtained inside the block can't be kept outside it except in
   optional wires.

A built-in `owner` property (every chip knows its board) is a convenience, not a rule.

## 5. Under the hood

- **Header** (about 24 B per component): `owner*`; `ground*` (the root of its soldered cluster: walk up while the link is
  `part`. It never changes after construction, because solder links are immutable); `depth:u16`; `flags` (soldered,
  verified, removed); `slot:u32` (only grounds, meaning socketed components, own a slot in the per-thread generation
  table, and soldered parts share their ground's slot).
- **DRC check** for holder X and target T: legal iff X is a descendant of `ground(T)`. Implementation: walk X's owner
  chain up `depth(X) - depth(ground(T))` hops and compare pointers. **Key theorem:** a socketed subtree S can never
  receive a legal plain wire from outside S, because the solder chain of any target inside S stops at or below S's root.
  So removing S never leaves a dangling plain wire, and destruction needs no back-pointer lists.
- **Static elision.** The compiler knows statically that `self`, `owner`, `self.part.part...` and a closure literal
  built inside a part initializer that captures `self` or soldered siblings all satisfy rule 4. That covers most DSL/UI
  code, which pays no runtime check at all.
- **Optional wires** are stored as `(ptr, slot, gen)`. A read compares the generations. Removing a ground bumps its
  generation immediately (so `none` shows up at once), and the memory is freed later.
- **Moves (`take`)** re-run DRC over the moved subtree's *outward* wires using compiler-emitted per-class wire maps
  (offsets of wire fields, like GC type maps but used only for moves, sends and destruction). Each component carries a
  `verified` bit. Bench components skip store-time checks and are verified when installed. The invariant is that a
  verified component's subtree is fully verified, so verification costs O(1) amortised per component. At a `tick` in
  `main`, live bench locals of the entry frame are verified (once each).
- **Removal**: run `deinit` (so files close promptly), bump the generation, and push the component onto the per-thread
  **retire list**. **Tick**: free the retire list (subtree walk, iterative). There is no tracing of live objects, ever.
  The tick only frees things that were explicitly removed, a bit like an autorelease pool that releases nothing but
  removals. Old `List`/`Map` buffers from reallocation are also retired to the tick, so an in-place mutation of a value
  element can never write into freed memory.
- **Threads** each have their own generation table and retire list. `send take x` walks x's wire map, traps on outward
  plain wires, cuts outward optional ones, bumps x's generations (cutting probes from the old thread) and re-homes the
  subtree. A `shared` root has an RW lock. Its retire list flushes when the lock becomes fully free, because by rule 9
  no locals pointing inside survive a `with` block (a lexical check).
- **FFI**: a raw pointer handed to C is valid until the tick. For long-lived C `void* userdata`, pass an optional wire
  encoded as a u64 handle (slot+gen).
- **Tooling**: the ownership tree is real runtime data, so the debugger gets a "board view" (live tree, solder/socket
  links, wires drawn as traces). DRC traps print both endpoints' tree paths, and blown fuses can be logged.

## 6. Scenarios (illustrative only — not a syntax decision)

**(a) Read lines of unknown length**
```
fun readLines(path: String) -> List of String {
  f = File.open(path)              // f on the bench (owned by this call)
  lines = List of String()         // bench
  while line = f.readLine() { lines.add(line) }   // String is a value: moved into the buffer
  return lines                     // ownership moves to the caller
}                                  // f removed: deinit closes the file now, memory freed at tick
```
The list grows by reallocating its buffer. Values have no aliases, and old buffers are retired to the tick.

**(b) Tree with parent pointers**
```
class Node {
  name: String
  socket children = List of part Node()
  parent: Node?                    // upward wire: always legal, stored raw, never a probe
  fun adopt(take child: Node) { child.parent = self; children.add(take child) }
}
b.adopt(take a.children.take(0))   // move subtree: re-DRC its outward wires, parent re-set
a.children.remove(1)               // whole subtree removed; nothing outside can point in by rule 4
```
Parent↔child cycles leak nothing because nothing is counted. (Alternatively use the built-in `owner`.)

**(c) UI callback capturing enclosing state (the crux)**
```
class EditorScreen {
  part doc = Document()
  part toolbar = Toolbar {
    part save = Button("Save", onTap: { self.save() })   // captures self: an ancestor, legal statically
  }
  fun save() { doc.write(); toolbar.save.enabled = false }
}
class Workspace {
  socket tabs = List of part EditorScreen()
  current: EditorScreen?                            // points down into a socket: optional wire
  part menu = Menu { part saveAll = Item("Save", onTap: { self.current?.save() }) }
  fun closeTab(i: Int) { tabs.remove(i) }           // `current` reads none immediately
}
Timer.after(5.seconds, { screen.autosave() })      // runloop at app root holds `(() -> ())?`: a fuse
```
The closure lives inside the button, inside the screen. It captures the screen, which is upward, so it is a raw pointer
with no weak/strong dance and no retain cycle. If `onTap` closes its own tab, the running closure and `self` stay valid
until the tick. The timer, or a global notification centre, holds downward captures as fuses, which gives automatic
"unsubscribe on destroy".

**(d) Shared mutable cache used by two components**
```
class App {
  part cache = Cache()
  part search  = SearchPanel(cache: cache)    // cache: soldered sibling under common ground App
  part preview = PreviewPanel(cache: cache)
}
class SearchPanel { cache: Cache; pinned: Entry? }   // plain wire to cache; optional wire to an evictable entry
class Cache { socket entries = Map of String to part Entry() }
```
Both panels mutate the cache through raw pointers, with no RC and no locking (single thread). An entry pinned by a
panel reads `none` after eviction.

**(e) Pass a large list to a mutating function**
```
fun normalize(xs: List of Float) { m = xs.max(); for i in 0..xs.count { xs[i] = xs[i] / m } }
normalize(self.samples)          // reference passed, mutated in place, no copy, no inout/borrow syntax
```
Even if a callback removes `samples` during the call, `xs` stays valid until the tick.

**(f) Sharing data between threads**
```
shared class Stats { part counts = Map of String to Int() }
shared stats = Stats()                         // top level: on the process backplane

fun worker(take job: Job, out: Channel of Report) {
  r = job.run()                                // this thread's own tree
  with stats { stats.counts[job.kind] += 1 }   // lock; no references escape the block
  out.send(take r)                             // r's outward plain wires must stay inside r
}
spawn worker(take nextJob, reports)
```
Data races are impossible: each tree is touched by one thread, and backplane data only inside `with`.

## 7. What's genuinely new vs. the covered options

- **Direction-based reference legality.** Safety comes from *which way a wire points in a runtime-visible ownership
  tree*, checked once at connect time. It does not come from types and lifetimes (O5), per-dereference checks (O6),
  counts (O1, O4 `shared`, O7), or programmer discipline (O8). Legal wires cost exactly what C pointers cost to read.
- **Solder vs socket.** Structural immutability of an owning field is used as a *lifetime equality* proof, which makes
  sibling and cousin references (the UI case) safe with no annotation. This leads to the "no incoming plain wires into a
  socketed subtree" theorem, so removal needs no back-pointer bookkeeping.
- **Tick-deferred reclamation as the borrow checker.** Locals and parameters need no rules at all because nothing is
  freed until a point where no user frames exist. This is not region inference or scope regions: there is no
  promotion, and long-lived objects don't leak, because removal is explicit and per-subtree.
- **Probes per solder cluster**, not per object. Generation slots exist only for socketed components.
- **Fuse closures**: an optional slot gives "callback silently retires with its target" semantics for free.
- **Clock domains / backplane** for threads, where the "upward is always legal" rule extends naturally to shared data.

## 8. Known weaknesses

- **DRC failures are runtime traps, not compile errors**, in the cases static elision can't prove. They are loud and
  early (at connect time, not at use), but still runtime. A lint could flag likely violations.
- **Memory high-water within a tick.** A long batch function that churns *components* holds them until `main` ticks, and
  only entry functions may `tick`. The mitigation is to use values for churn data. A future `cycle { }` block could free
  things born and removed inside it, but its soundness rules are subtle, so it is left out here.
- **`take` of a big subtree is O(subtree)** (re-DRC of its outward wires). **Deep ownership chains** (a linked list built
  from nested sockets) make a DRC store O(depth).
- **About 24 B header per component**, plus a generation slot per socketed component.
- **Zombie reads.** A removed component is still readable via locals until the tick, with its `deinit` already run. That
  is memory-safe but can hide logic bugs. Optional wires and fuses going `none` silently can also mask mistakes
  (mitigated by debugger logging).
- **Forces a tree-shaped design.** Arbitrary graphs (cross edges between sockets) become optional wires everywhere, or
  should use slot maps.
- **Gate notes:** G2 passes (no tracing, deterministic free points), though analysts may want John to confirm that
  "deferred free at tick" isn't GC-like in spirit. G3 depends on built-in `List of part T` / `Map of K to part V`: flag
  for the pending containers question. `shared`, `part`, `socket`, `take`, `with` and `tick` are keywords, not
  annotations.
- Rough self-assessment: about 70/100 (simplicity 3, safety 4, expressiveness 4, implementation risk 3, perf 4,
  concurrency 3, tooling 4).
