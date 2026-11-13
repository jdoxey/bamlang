# Analysis 10: Supervised Homes (homes, leases, links)

Analyst: independent. Inputs: brief.md, CHARTER.md, ideas/10-supervised-homes.md. No other ideas or analyses were read.
All code is *illustrative only, not a syntax decision.*

## 1. The idea in three sentences

The heap is divided into *homes*. Each home is a single-threaded, actor-like heap: inside it, objects reference each other freely and are freed by non-atomic RC. A home is stopped explicitly or through its supervisor, and stopping it frees its whole heap at once, cycles included. Homes interact only through incarnation-checked leases (`far T`) using `ask`/`tell`, with arguments copied or moved; closures handed to another home become callbacks that run back in the home they came from and die with it.

## 2. Prior art: new, or a recombination?

It is mostly a recombination. The parts are well known; the new part is how they are put together.

| Element | Prior art |
|---|---|
| Per-actor private heap, copy-on-send, process death frees its heap, supervision, links | Erlang/OTP. Erlang runs a per-process *GC*. |
| Actor heaps with data-race freedom by construction | Pony. Each actor has its own heap, collected by ORCA, a per-actor GC. https://tutorial.ponylang.io/runtime-basics/garbage-collection , https://www.doc.ic.ac.uk/~scd/ORCA_17.pdf |
| Regions with one entry point, objects that die together, cowns as the unit of concurrency, frozen immutable data shared by RC | Project Verona. https://tamnd.github.io/brain/research/memory-management/ownership/07_project_verona_regions/ . RC of cyclic deeply-immutable data: https://microsoft.com/en-us/research/uploads/prod/2023/10/oopslab23main-p377.pdf |
| Vats (event-loop heaps), *near* vs *far* references, eventual send, broken refs when a vat dies | E language. Even the name `far` comes from E. https://en.wikipedia.org/wiki/E_(programming_language) |
| Isolated heaps, copy on send, zero-copy transfer of a final result | Dart isolates, `Isolate.exit`. https://api.dart.dev/dart-isolate/Isolate/exit.html |
| Callback linked to a context object, auto-disconnected when that object dies; callback runs on its origin's thread | Qt `connect(sender, sig, context, functor)` and COM STA / main-thread dispatch (known; no URL fetched) |
| Non-atomic in-home RC with Perceus elision | Perceus (Koka), Lobster |

**What is new:** every system above that gives full aliasing inside an isolated heap reclaims memory with a tracing GC (Erlang, Pony, Dart, E). This idea removes that GC. RC frees acyclic garbage, and **stopping the home is the only backstop for cycles**, with the home's lifetime tied to an application lifecycle event. Rule 8 (callbacks run in their origin home) also turns closure placement into a safety mechanism. That is a real twist. Verona is the closest relative, but it frees regions by scope, while here a home is a dynamic, user-stopped object. Compared with the covered options, it is "scope-bound regions" made dynamic, with an actor runtime added. It is not a rename, but it is not a new primitive either.

## 3. Soundness: counterexamples

### C1. Detached subtrees always leak in a long-lived home (contradicts the idea's claim in (b))
The idea says a detached subtree is freed by RC if `detach` clears `parent`. That only holds for **leaves**.
```
// inside a long-lived home (main, an app-wide document service, an IDE's AST home)
s = Node("s"); s.add(Node("k1")); s.add(Node("k2"))
root.add(s)
s.detach()          // root.children.remove(s); s.parent = nil
s = nil
// s is still referenced by k1.parent and k2.parent; s.children references k1 and k2.
// The cycle s <-> {k1,k2} is never freed by RC. It lives until the home stops.
```
Any internal node with at least one child forms a cycle. AST rewrites, DOM removals and scene-graph edits in a home that never stops grow memory without bound. The only fixes are a recursive manual teardown (`detach` walks the subtree and clears every `parent`), which is safe manual freeing, or weak parent pointers, which is O1 and which the idea explicitly omits.

### C2. The crux scenario (c) leaks at component granularity
```
class Row { label; button
    fn init(item) { button = Button(item.name); button.onTap = { self.toggle() } } }
// Window home, open all day, showing an infinitely scrolling feed:
feed.onScroll = { rows.append(Row(nextItem())); rows.removeFirst() }
```
Row → button → closure → Row is a cycle. Each row that scrolls off is leaked until the **window** closes. The idea handles (c) at the window level, but in a G11 declarative UI the objects that capture `self` (rows, cells, tabs, popovers, sheets) are created and destroyed constantly *inside* a window. The idea's remedy, "give it a home", does not work here. A spawned Row can no longer be a plain node in the window's layout tree (the idea itself says "a layout tree is just objects in one home"), and every read becomes an `ask` returning a copy. This is the same leak ARC has, without the weak-ref escape hatch ARC offers.

### C3. Use-after-free: zero-cost move vs. wholesale page free (rules 4 + 6 as specified)
```
// (f) exactly as the idea writes it
results = spawn Collector()
w = spawn Worker(chunk, results)
// Worker.run: big = List(); ...fill...; tell results.add(big)   // RC 1 → "moved": pointer handoff
//              then returns, and the supervisor does `stop w`
stop w        // "returns its pages wholesale; no object is visited"
// The Collector's list now points into freed pages of w's heap → UAF
```
Under the hood, a move is "pointer handoff plus re-homing via a remote-free list". That stops the *receiver's* frees from corrupting the sender, but stopping the sender still frees pages that hold live moved objects. `freeze` has the same hole: a frozen table allocated in home H, shared with others, then H stops. Fixes are (i) a move physically relocates, which makes it a copy except for separately mmap'd large buffers, or (ii) per-page foreign-live counts that delay page release, which breaks the "freed at once, nothing visited" promise. Both fixes are doable, but the spec as written is unsound.

### C4. "Move if the root RC is 1" is unsound for buffers of objects
```
shared = Header(); lines = List(); lines.add(shared); keep = shared
tell worker.process(lines)   // lines RC == 1 and this is its last use → moved
keep.mutate()                // this home and the worker now both alias `shared`
                             // non-atomic RC on two threads → race / UAF
```
A safe move needs RC==1 on **every reachable object**, which is an O(n) walk. So a "free" move only exists for flat buffers (bytes, numbers, immutable strings). Scenario (e)'s cross-home "moved out, moved back" therefore costs an O(n) walk at minimum, and the walk's result depends on dynamic RC state, so whether a call copies or moves is not predictable from the source.

### C5. Export-table leak, including cross-home cycles
Rule 8 stores an escaping closure in the origin home's export table. Nothing says when the entry is removed while the origin is still alive.
```
// Editor home (long-lived), every focus change:
toolbar.setAction("Save", { self.save() })   // toolbar replaces its old callback lease
```
The old closure, and everything it captured, stays pinned in the editor's export table. Fixing that needs distributed RC (decrement messages). Even then, editor exports cE, which captures a lease to toolbar export cT, and cT captures a lease back to cE. That is a cross-home cycle no RC scheme reclaims. It is the classic distributed-GC problem that E/CapTP also leaves unsolved, and here both homes are long-lived.

### C6. Synchronous re-entrancy becomes a runtime `deadlock` error
```
// Window home W hosts a table; the model lives in home M.
// W (layout): rows = ask m.visibleRows() else { [] }
// M.visibleRows(): f = ask w.currentFilter() else { "" }   // W is parked waiting on M
// → the cycle W→M→W is detected and raised as `deadlock`
```
Ordinary OO code (a delegate asking its owner for context) is legal at compile time and fails at runtime. Because cross-home callbacks are `tell`-only, synchronous bindings such as `enabled: { self.dirty }` and data-source delegates that return values cannot cross homes at all.

### C7. Identity loss surprises in (d)
`img = ask cache.get(k)` returns a **deep copy**. If the Viewer mutates `img` (marks it decoded, updates metadata), the cache and the Importer never see the change. A "shared mutable cache" therefore holds shared *keys*, not shared *entries*. Each `get` of a large mutable entry costs a deep copy, unless the entry is frozen (and C3 applies to frozen values).

### Smaller issues
- Native UI requires the main thread (AppKit, Win32), but the `ask` fast path runs the callee inline on the *caller's* thread. A worker asking a window home would then make UI calls off the main thread, so homes need thread affinity.
- The crash `longjmp` skips C/C++ frames on FFI paths, which is undefined behaviour for C++.
- A raw pointer handed to C is valid "until the home stops or the RC drops", and nothing can check that.
- Every `ask` needs `else`, which adds boilerplate to every cross-home call.

## 4. Scenarios

| | Verdict |
|---|---|
| (a) | **Works.** Plain in-home code. Sending the result elsewhere is a copy or a walked move (C4). |
| (b) | **Partly hand-waved.** Fine for trees that die with their home. Detached internal subtrees leak in long-lived homes (C1). |
| (c) | **Works at window granularity, hand-waves below it.** Excellent cross-home linked callbacks and safe implicit `self`, but per-component cycles leak (C2) and cross-home callbacks can't return values. |
| (d) | **Works but changes the meaning.** Serialized and safe, but entries come back as copies (C7). Same-home sharing is fine. |
| (e) | **Works in-home** (by reference). Cross-home "moved out, moved back" is not free and is unpredictable (C4). |
| (f) | **Works conceptually** (actors plus freeze). As specified it has a UAF on move then stop (C3). Parallel in-place mutation of one big array requires split/copy. |

## 5. Gates

- **G2: Pass.** In-home RC is not a GC run (same standing as O1). Stopping a home frees pages without tracing, and deep copy at a boundary is an explicit message traversal, not collection. The optional `renew()` is a copying collection and would be **needs-john**, but it sits outside the core model. Note: the C3 fix (ii), per-page live counts, stays within G2.
- **G3: Pass, flagged.** There are no annotations or macros. `far T` is a compiler-known type former, which is the same pending question as `List`/`Map`, so it rides on John's existing decision.

## 6. Rubric

| Criterion | W | Score | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 3 | In-home code is Python-simple, but actors are *mandatory* for the UI (one home per window). Users must learn ask/tell/else, copy-vs-move-vs-identity, tell-only callbacks, runtime deadlocks, home sizing, and manual cycle-breaking with no weak refs. That is about 8 rules plus a design skill. |
| Memory safety | 15 | 4 | No dangling by design once C3/C4 are fixed. Leaks are not unsafety. FFI pins are unchecked. |
| Expressiveness (b),(c),(d), OO/self, G11 | 15 | 3 | Implicit `self` and cross-home callbacks are genuinely good. Intra-window cycles (C2), subtree leaks (C1), copy-only sharing (C7) and the lack of synchronous cross-home bindings pull it down. |
| Implementation risk (AI-written, LLVM) | 15 | 2 | Scheduler, MPSC mailboxes, per-home allocators with remote free, generated deep-copy with cycle maps, export tables with distributed RC, wait-for deadlock detection, thread affinity, longjmp crash recovery and later fibers, across 3 OSes. Each piece is known; together they are a large runtime. |
| Performance & predictability | 10 | 3 | Non-atomic RC and bulk free are good. Implicit deep copies, move-vs-copy decided by dynamic RC, `ask` latency, and memory that grows in long-lived homes are not. |
| Concurrency fit | 10 | 4 | Data-race free by construction, with no Send/Sync. The costs are runtime deadlocks and no shared mutable parallelism without copying or splitting. |
| Tooling, debuggability & C FFI | 10 | 3 | The per-home leak report is nice but fires only at stop, so it fires late or never for `main`. Async cross-home stacks are hard to debug, and FFI lifetimes are unchecked. |

Weighted total = Σ W × score / 5:
- 25×3/5 = 15.0
- 15×4/5 = 12.0
- 15×3/5 = 9.0
- 15×2/5 = 6.0
- 10×3/5 = 6.0
- 10×4/5 = 8.0
- 10×3/5 = 6.0

**Total = 62 / 100.** That is 21 below O1 (83) and 20 below O4 (82), and below the idea's own estimate of 75–79. The gap comes mainly from simplicity (the mandatory actor model) and implementation risk.

## 7. Fatal flaw and salvageable kernel

**Fatal flaw:** cycles are bounded by home lifetime, but the homes that matter most never stop: `main`, the app shell, and long-lived windows and services. Inside them, the idea gives no answer to cycles. It drops weak refs by design, and "give it a home" turns shared object graphs into copy-on-access actors. So the crux, (c), is fixed only at the coarse grain and returns as an unbounded leak at the fine grain (C1, C2). The C3/C4 move/free unsoundness is fixable, but it shows the "zero-cost" claims depend on the hardest part of the runtime.

**Salvageable kernel for O1/O4:**
1. **Origin-linked callbacks.** A closure stored in an `Event`/registry is linked to the object it captured as `self`. The registry does not keep that object alive, and it prunes the callback automatically when the object dies (Qt context-object semantics). In O1 this removes the weak-capture-list ceremony from the common UI case (c) without a new user rule.
2. **An opt-in actor/"home" library for concurrency (f).** Isolated heaps let RC inside them be non-atomic, with copy or walked-move at the boundary, `freeze` for sharing, and incarnation-checked handles that answer `down`. This would sit beside O1/O4 as the threading story, not as the memory model.
3. **A debug-build leak report** when a scope, window or arena ends, grouped by class and allocation site.

## 8. Verdict

**Kernel worth stealing.** It is not a contender against O1/O4: it scores lower and has an unfixed cycle story in long-lived homes. It is not a dead end either, because origin-linked callbacks and actor-isolated, non-atomic-RC heaps are worth adopting into O1 or O4.
