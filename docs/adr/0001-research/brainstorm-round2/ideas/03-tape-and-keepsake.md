# 03 — Tape & Keepsake

## 1. Name

**Tape & Keepsake.** Memory is an append-only tape that is never freed. The only thing that survives is a *keepsake*: a plain value that the program carries into its next life, when it rewrites itself.

## 2. The crazy premise

**Sacred assumption broken: "a long-running program must reclaim memory while it runs."**

No object is ever freed, moved or reused within a run. The language has no concept of lifetime: no ownership, no borrows, no refcounts, no weak refs, no scopes that kill things. Every address is valid forever.

The program still stays bounded, because at idle moments it is **rewritten and restarted**. The current value of every `keep var` is baked in as that variable's new initializer. The old tape is thrown away whole, like a process exit, and `main` runs again.

Also broken:
- **"Memory is RAM."** The tape is tiered: RAM, then compressed RAM, then SSD.
- **"Address space is a scarce resource."** Each life gets a fresh, never-reused virtual range.

## 3. Pitch

Write code as if you had infinite memory, because within one life you do. Cycles, parent pointers, closures capturing `self`, and callbacks that fire after their window closed are all trivially safe: nothing they point at can ever die. Allocation is one pointer bump with no header and no RC traffic.

The bill comes due in one place. Durable state, meaning anything you'd mind losing, must live in top-level `keep var`s holding **values** (no identity, no references, no closures). The runtime is allowed to reincarnate your program at any idle moment. The mental model fits in one sentence: *"At any quiet moment, the program may be re-run from the top with each `keep var` initialised to its current value."*

UI programmers already write "the view is a function of the state" (Elm, React, SwiftUI). This model makes that the memory model. As side effects you get crash recovery, hot code reload and omniscient time-travel debugging.

## 4. The rules

1. **Nothing is ever freed.** Creating anything appends it to the tape. Every reference stays valid for the rest of the life. There are no weak refs, no ownership and no lifetimes.
2. **Two kinds of types:**
   - **Objects** (`class`) have identity and are mutable in place. Overwriting a field does not grow the tape.
   - **Values** (`struct`, `enum`, `String`, `List`, `Map`, `Set`) have no identity and are immutable. `x.f = 1` or `xs.add(y)` on a `var` rebinds the variable to an updated version.
3. **`keep var` declares durable state.** It may only appear at the top level, and its type must be a value type, all the way down. The compiler rejects any class reference, closure or OS handle inside it. Graphs in durable state use ids.
4. **Rebirth.** Between events, when the event loop is idle, or when you call `rebirth()`, the runtime may end the current life. Every non-`keep` object vanishes, the `keep var`s retain their current values, and `main` runs again from the top.
5. **Write `main` to rebuild from keepsakes.** Windows, widgets, caches, controllers and threads are all re-derived from the `keep var`s.
6. **OS resources are not memory.** Files and sockets close at the end of their `use` block, on explicit `close()`, or at rebirth. Windows (and any other OS handle you want to survive rebirth) persist only if their id is held in a `keep var`.
7. **Threads.** A `spawn` closure may capture only values, `Channel`s and `Locked` objects. Threads end at rebirth, and `main` restarts the ones it still needs. Rebirth waits for threads marked `finish`, up to a deadline.
8. **Allocation is a budget, not a hazard.** Hot loops should overwrite fields in place rather than construct new things. This rule is about performance; it has nothing to do with safety.

## 5. Under the hood

**Tape.**
- Each thread bump-allocates in its own segment of a fresh virtual range: on the order of 2^44 bytes per life, mapped `NORESERVE`, never reused.
- Objects need no RC or mark bits; the header is just a type id, kept for the debugger and FFI.
- **An address is a birth timestamp.** `a < b` within a segment means `a` was born first. Everything below uses this.

**Tiering.**
- Pages move from RAM to compressed RAM to an SSD page file, LRU by page.
- An append-only tape compresses extremely well, and most old pages are pure garbage that is never touched again, so they sink and stay sunk.
- Per-life budgets (all defaults):
  - soft: 256 MB resident; triggers rebirth at the next idle point
  - hard: 8 GB resident plus SSD; forces rebirth after the current event finishes

**Values.**
- Values are persistent structures: RRB vectors, HAMTs, ropes for `String`/`Text`. An "update" appends an O(log n) path copy.
- A value that was created in the current call and not yet published is mutated in place (Clojure-style transients, inferred automatically).
- Non-escaping temporaries go on the stack via escape analysis. This is invisible to users, because a stack slot never escapes, so the user still sees "nothing is freed".

**Rebirth.** Two phases:
1. **Snapshot (concurrent).** At time T, read the `keep var` roots, which are a few pointers. A background thread copies those values into a fresh keepsake segment. The code is type-directed and generated by the compiler: a fold over value types with a sharing memo, because values are DAGs. Values are immutable, so this needs no write barrier, and the old life keeps running.
2. **Handover (brief pause, at idle).** Re-read the roots and copy only nodes whose address is greater than T. Newness is an address comparison, so the delta is cheap. Then `munmap` the old segments, unwind the shallow idle-time stack, and call `main`.
   - Kept window ids are re-bound to the same OS windows, so the window doesn't flicker; only the widget tree is rebuilt.
   - Unkept handles are closed.

**This is "compaction by rewriting the program".** The keepsake segment is literally a new data segment for the same code: "`keep var docs = <current value>`". Three consequences:
- If you swap in a **new binary**, rebirth becomes hot code reload. Fields keep matching by name, new fields take their initializer, and the compiler checks that removed fields aren't kept.
- If you persist the keepsake to disk at each rebirth, a crash restarts from the last keepsake. That gives crash-only software for free.
- **Debug "chaos mode"** rebirths after every event, so lost-state bugs surface immediately (like React StrictMode's double render).

**FFI.** Tape pointers handed to C are stable for the whole life: no pinning, no moving, no surprise frees. C must not keep them across a rebirth, and callbacks registered with C get re-registered by `main`.

**Debugger.** Nothing is overwritten except class fields in place, and those writes are journaled optionally in debug builds. So the whole history of the life is inspectable:
- "who allocated this, and during which event?" (the address tells you)
- reverse stepping
- heap diffs between any two moments

## 6. Scenarios

*Illustrative only — not a syntax decision.*

**(a) Read a file into a list of lines.** `lines` is fresh and local, so the compiler appends in place, and the list is published once at the return. The file closes at the end of the `use` block. Within the life the list stays forever. That costs nothing; it's freed at rebirth if no `keep var` holds it.
```
fn readLines(path: String) -> List of String
  var lines = List of String []
  use f = File.open(path)
    for line in f.lines()
      lines.add(line)
  return lines
```

**(b) Tree with parent pointers.** Within a life, a cycle is just a reference: no `weak`, no ids. The node ids are needed only if the tree has to survive rebirth, in which case it is stored as a value and the parent links are rebuilt (or held as ids).
```
class Node
  var parent: Node?
  var kids = List of Node []
  fn add(k: Node)
    k.parent = self
    kids.add(k)

keep var outline = OutlineValue { nodes: [], rootId: 0 }   // only if durable
```

**(c) UI callback capturing `self`.** The closures capture `self` strongly, with no cycle problem and no weak dance. After a window closes, its `Editor` is unreachable tape garbage that sits in cold pages until rebirth. If a stray timer fires later, it runs on a perfectly valid (if irrelevant) object, so nothing is undefined.

The catch: `dirty` and `cursor` are not kept, so rebirth resets them. If that matters, move them into `Doc`. Chaos mode will show you on the first run.
```
struct Doc { path: String, text: Text, cursor: Int }
keep var docs = Map of DocId to Doc {}
keep var windows = List of WindowId []

class Editor
  var id: DocId
  var dirty = false
  fn save()
    Disk.write(docs[id].path, docs[id].text)
    dirty = false
  fn view() -> View
    Column
      TextArea(docs[id].text, onChange: { t -> docs[id].text = t; dirty = true })
      Button("Save", onTap: { self.save() })

main
  for w in windows
    w.show(Editor(w.docId).view())
```

**(d) Shared mutable cache used by two components.** It's a plain shared object that both components hold. Evicted entries become tape garbage. The cache is not kept, so it starts cold after each rebirth, which is free cache invalidation. To make it durable, make it a `keep var` of `Map` type.
```
class ThumbCache
  var map = Map of Url to Image {}
  fn get(u: Url) -> Image
    map[u] ?? { let i = decode(fetch(u)); map[u] = i; i }

main
  let cache = ThumbCache()
  Gallery(cache); Sidebar(cache)
```

**(e) Pass a large list to a function that mutates it.** A `Buffer` is an object: it's passed by reference and mutated in place, so the tape doesn't grow and nothing is copied.
```
fn normalize(xs: Buffer of Float)
  let m = xs.max()
  for i in 0..xs.count
    xs[i] = xs[i] / m

let data = Buffer of Float(loadSamples())
normalize(data)
```
With a value `List`, you would write `data = normalize(data)` and pay path copies, unless `data` is fresh.

**(f) Share data between threads.** Values are immutable and never freed, so threads share them **by pointer with no copying, no atomic refcounts and no lifetimes**. Mutable sharing goes through `Locked`. Each thread has its own tape segment, so allocation has no contention.
```
let corpus: List of String = readLines("big.txt")      // a value
let counts = Locked(Map of String to Int {})
for chunk in corpus.chunks(8)
  spawn finish { for w in chunk { counts.with { m -> m[w] = (m[w] ?? 0) + 1 } } }
```

## 7. What is new

- **No lifetime concept at all inside a run.** Unlike ARC, O4 or the round-1 ideas, the hard cases (c), (b) and (d) cost zero rules, because nothing can die.
- **Reclamation is a program rewrite.** The surviving state is a programmer-declared value, baked in as initializers. It is not a heap region, not a tick arena, and not a traced object graph. Identity objects (the cyclic, callback-tangled part) are never traversed; they are dropped wholesale.
- **Address = birth time.** That gives:
  - an incremental, barrier-free snapshot (the delta is everything with address > T)
  - age-based tiering with no per-object metadata
  - "who made this, when" in the debugger for free
- **Crash recovery, hot reload and memory management are one mechanism.**
- **Thread sharing of immutable data needs no RC at all**, unlike O1 and O4, which pay atomics.

## 8. Less crazy than it sounds, or more?

**Less crazy:**
- Many real programs already never free: compilers (several production compilers deliberately leak), CLI tools, and request handlers in arena-per-request servers.
- 2^64 bytes is about 580 years at 1 GB/s.
- A UI app that overwrites fields in place and memoizes its views allocates only on real change. Typing 8 hours a day at a few KB per keystroke is around 1 GB, which fits comfortably between idle rebirths.
- Elm/Redux apps already keep all durable state as one value and treat everything else as derived.
- Erlang and Unicorn already "free" memory by restarting processes.

**More crazy:**
- Squint and rebirth is a **copying collector with a programmer-declared root set**, run at idle. I claim it is not a GC run in the G2 sense:
  - it never traces the object graph
  - it runs at programmer-visible points
  - it costs O(size of keepsake delta), not O(heap)
  - it is what an app does when it "saves and restarts"

  An analyst may reasonably disagree. **G2 verdict: needs-john.**
- **G3:** `keep` is a storage-class keyword like `var`, not an annotation. `List of T` / `Map of K to V` are built-in parameterised containers; flagged as the pending question.
- **Determinism:** rebirth timing depends on memory pressure, so *when* non-kept state resets is non-deterministic. Chaos mode makes it deterministic for testing.

**Self-assessment (honest):**

| Criterion | Score | Weighted |
|---|---|---|
| Simplicity | 3 | 15 |
| Safety | 5 | 15 |
| Expressiveness | 4 | 12 |
| Implementation risk | 3 | 9 |
| Performance & predictability | 2 | 4 |
| Concurrency | 4 | 8 |
| Tooling & FFI | 4 | 8 |
| **Total** | | **≈71** |

## 9. Known weaknesses

1. **Working-set inflation.** A long-lived object created at startup sits on a page that is otherwise 99% garbage. That page stays hot, so resident memory is roughly (live objects × page size), not live bytes. Rebirth is the only compaction, so the soft budget must trigger it fairly often.
2. **Lost-state bugs are a new bug class.** Scroll position, an in-flight network request or a half-finished drag silently resets if not kept. Chaos mode helps, but every programmer must internalise rule 4.
3. **The keep boundary brings back O2's pain for durable graphs.** Durable parent pointers and cross-links become ids. The pain is confined to durable state, but it's real.
4. **"Idle" may never come.** Under continuous load (servers, long renders, games) there may be no idle point. You need rolling rebirth across worker processes, or forced rebirth that cancels work. `finish` threads can block rebirth.
5. **OS and toolkit state is not a value.** Native widgets with internal state, IME composition and accessibility focus are hard to re-bind seamlessly. Rebirth must wait for "true idle", which is runtime policy complexity.
6. **Persistent values are 2–5× slower than arrays for heavy updates.** Hence the value/class split, which is a Swift-like two-kinds rule (P-SWIFT risk).
7. **Allocation-heavy code burns tape.** For example, building strings per frame. The design leans hard on escape analysis and memoization to be pleasant.
8. **SSD wear and footprint.** Tiering garbage to disk is wasteful by design, and on low-RAM machines rebirths become frequent and visible.
