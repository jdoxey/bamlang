# Analysis 01: Witnesses

Analyst's verdict: **Kernel worth stealing**. Total **53 / 100**.

## 1. The idea in three sentences

References never keep anything alive. Every object belongs to a set of "witnesses": nodes in a tree tied to real-world lifetimes such as the process, threads, windows, connections and single handler invocations ("turns"). A write barrier keeps the invariant "a target is seen by at least everyone who sees its holder" by spreading sight sets along new edges. An object is freed in bulk when the last witness that sees it ends. Objects that must die before their surroundings are declared as `witness class` instances, and the handles to them are generation-checked and can raise `Gone`.

## 2. Prior art

The pieces are known. The combination is new.

- **Promote-on-store into a heap hierarchy that mirrors the task tree.** This is MPL's disentanglement and promotion work by Guatto, Westrick, Acar and others. Each task has its own heap, the heaps form a tree, and a write that would create a down-pointer first copies the target and everything reachable from it upward. The idea even reuses MPL's word "entanglement". MPL merges heaps on join and still uses GC inside them. https://arxiv.org/pdf/1801.04618 ; https://cs.nyu.edu/~shw8119/23/epfpe.pdf
- **The same mechanism for thread-local heaps.** Doligez and Leroy, and later Multicore OCaml and GHC's local heaps, promote the transitive closure to the shared heap when an object escapes through a store. Rule 3's spread is this barrier. https://arxiv.org/pdf/2004.11663 ; https://www.cs.tufts.edu/~nr/cs257/archive/simon-marlow/local-gc.pdf
- **Lifetimes tied to external events.** APR pools have a pool per process, connection and request, with subpools destroyed along with their parent. This is the witness tree almost exactly, but unsafe. Ur/Web has no GC and frees per-request memory at the end of each page; that detail is from memory, while the Wikipedia page says only "does not use garbage collection". Objective-C autorelease pools per run-loop turn are rule 5. https://apr.apache.org/docs/apr/trunk/group___pool_debug.html ; https://en.wikipedia.org/wiki/Ur_(programming_language)
- **Runtime-checked assignment between scoped regions.** RTSJ ScopedMemory throws `IllegalAssignmentError` where Witnesses would promote instead. https://rtsj.org/specjavadoc/javax/realtime/ScopedMemory.html
- **What is new.** An object can belong to a *set* of unrelated regions at once, interned sight sets are merged with union-find when a region ends, and the regions are created by OS and UI events rather than by lexical scope or a task fork. I found no system that frees by "last of N regions ends" without counting or tracing.

## 3. Soundness: counterexamples

Pseudo-code is illustrative only and is not a syntax decision.

**C1. Witness classes created in handlers die at once (this breaks (b) and (d) as written).** Rule 2 says a witness is watched by the witness it was born in, and rule 5 says handler code runs in a turn witness. So:
```
button.onTap { cache.put("k", v) }   // put() does: entries[k] = Entry(value: v)
// Entry is born in turn#77, so it is watched by turn#77.
// Turn#77 ends, so Entry ends. The next get("k") finds it Gone.
```
The same applies to (b): `Node(...)` created inside `add()` is not "born inside the parent" unless someone writes `parent.watch { Node(...) }`. The fixes all cost something:
- Explicit parenting at every construction site adds a rule and ceremony.
- Re-parenting a witness on store breaks the strict tree.
- "The nearest non-turn witness" makes the cache's entries children of component A's window. When A closes, B gets `Gone`.

**C2. Churn leaks in ordinary code (the design's own weakness 1, but worse than stated).**
```
server.users = Map()                          // seen by app
on connect(c) { u = User(c.name); server.users[c.id] = u }   // u now seen by {conn, app}
on disconnect(c) { server.users.remove(c.id) } // u goes cold; app keeps it until the process exits
```
Producer/consumer queues, undo stacks, LRU caches, chat histories and job lists all leak the same way. A leak arises from forgetting to write `witness class`, nothing in the code shows it, and no warning is possible because it is legal by construction. With O1, forgetting `weak` leaks only on cycles. Here, forgetting the idiom leaks on *every* removal.

**C3. Compute loops hoard everything until the turn ends.**
```
fun main() { for i in 0..<10_000_000 { p = Point3(i) ; total += p.len() } }  // if Point3 is a class
```
A range is not an event source, so all ten million objects live until `main`'s turn ends, which is process exit. The same happens in any batch job, compiler pass or recursive algorithm that allocates objects. It amounts to "memory is never freed within a turn". The programmer has to insert `watch {}` blocks, which turns them into a region manager.

**C4. Dangling across a suspension point.** If the language has `await`, coroutines or modal nested event loops:
```
onTap { v = cache.get(k)          // v is seen only by Entry; locals cause no spread (sec. 5)
        ok = showModalConfirm()   // nested loop: other turns run; one calls cache.evict(k) and finishes
        use(v) }                  // Entry has ended and v is freed: use-after-free
```
The design says ends wait "until the current turn finishes", but with nested or suspended turns the inner turn is the one that finishes. The fix is to defer ends until *no* turn is on any stack, or to spread on every load into a local. The first can stall frees indefinitely. The second makes the barrier fire on loads as well as stores.

**C5. Use-after-free on value buffers across threads.** Rule 7 restricts only *changes* to entangled objects. Rule 4 frees value buffers eagerly when they are overwritten.
```
T1: sync stats { stats.names.add(s) }      // realloc frees the old buffer immediately
T2: n = stats.names[0]                      // unsynchronised read of the old buffer: UAF
```
Pinning covers objects and not value buffers. Either reads also need `sync`, which brings in a reader lock on every entangled read, or buffers need deferred freeing. That is an unspecified piece of reclamation machinery.

**C6. Deadlock and dynamic faults.** `sync a { sync b {} }` on one thread and `sync b { sync a {} }` on another is the classic lock-order deadlock, with no ordering discipline. Entanglement is dynamic, so `x.n += 1` compiles everywhere and faults only when x happens to be shared. That is a second runtime fault, which contradicts the claim that `Gone` is the only one. It is also untestable by inspection.

**C7. Resurrection in `deinit`.** `deinit { registry.last = self }` stores a dying object into a live one. The spread adds `app` to a class that is being freed, so the result either dangles or needs a rule against it. Rule count +1.

**C8. A single assignment has unbounded latency.** `window2.model = doc` walks a million-node document synchronously, on the UI thread. The amortised bound is real, but an unpredictable pause on an ordinary `=` is the kind of behaviour G2 exists to avoid.

**C9. Unstated value-semantics machinery.** Scenario (e) depends on "inout by default for values" and eager buffer freeing. That requires either unique ownership of buffers (moves, O2/O4-style) or COW with reference counts. Either way it is a second memory model hiding under the first, and its rules are not in the count of seven.

**What holds.** For the object graph alone, the invariant `sight(x) ⊇ sight(y)` for every edge y→x, together with bulk frees at turn boundaries, does give no-dangling without counts or tracing, and it ignores cycles. That core is sound. The holes come from time (C4), threads (C5), finalisers (C7) and the value layer (C9).

## 4. Scenarios

| | Verdict | Why |
|---|---|---|
| (a) file to growing list | **works** | Lines and the buffer are values. It relies on the unstated value model (C9). |
| (b) tree with parent pointers | **partial** | Cycles really are free while the whole tree lives. Deleting a subtree requires a witness-class node, plus explicit parenting (C1), plus `Gone` on handles. |
| (c) UI callback capturing self | **works** | This is the best part: no `weak self`, and window close frees everything. It works only if the window is the right lifetime. A save that must outlive the window needs `app.watch`. |
| (d) shared mutable cache | **partial / hand-wave** | Entries die at the end of the turn (C1). `get` callers can hit `Gone`. Values that escape cause spreads. Two components with different windows stretch the design. |
| (e) mutate a big list in a function | **works** | No spread happens. It rests on an inout/value-semantics layer that the idea doesn't specify. |
| (f) threads | **partial** | Reads race on value buffers (C5). Lock-order deadlocks (C6). Queues leak (C2). Mutation faults are dynamic. |

## 5. Gates and the charter

- **G2: needs-john, leaning pass.** Nothing ever scans roots or traces to reclaim. Reclamation is bulk freeing when a region ends. The spread, however, is the promotion barrier of generational and thread-local GCs: a synchronous transitive walk with no fixed bound per store. If "graph walk on store" counts as a collection run, this fails. The optional "decoherence" compressed-page scheme is not a GC run, but it hides leaks.
- **G3: pass.** `witness class`, `watch {}` and `sync {}` are language constructs, not annotations. There are no generics in the model. The only open point is the usual question about built-in `Map`/`List` in (d).
- **Other charter goals.**
  - G1 is strained: there are 7 stated rules plus at least 4 hidden ones (C1, C3, C7, C9), and a history-dependent mental model.
  - G8 is helped: a witness tree with a memory figure per node is a good debugger view.
  - Determinism is kept on one thread. Across threads, when frees happen depends on how pins interleave.

## 6. Scores

| Criterion (weight) | Score | Justification |
|---|---|---|
| Simplicity (25) | 2 | Seven rules on paper, about eleven in practice. Memory use depends on every store that ever happened, not on the current graph. The correct idiom (witness class) is invisible until you leak. |
| Memory safety (15) | 3 | The object-graph core is sound and `Gone` is a defined fault. But there are real UAF paths through suspension (C4), cross-thread buffers (C5) and `deinit` (C7). |
| Expressiveness (15) | 4 | (c) and cycles are better than O1, and implicit `self` captures for free. (d) and subtree deletion are awkward (C1). |
| Implementation risk (15) | 2 | It needs all of these: a barrier on every pointer store, interned sets with subset caches, union-find classes, per-class pages, pins, OS-event witness integration, and a value layer. Only the single-region version (MPL) has prior art, and it is a research runtime. |
| Performance & predictability (10) | 3 | Throughput is arena-like, with no RC traffic and bulk frees. Footprint grows without bound with churn (C2/C3), and an ordinary `=` can pause (C8). |
| Concurrency (10) | 2 | Entanglement is checked at runtime. Reads are unsynchronised. Deadlocks are possible. Pins complicate frees. There is no static race freedom. |
| Tooling, debug, FFI (10) | 3 | Per-witness memory attribution is excellent. C code that writes pointers into the language's objects bypasses the barrier and creates silent dangles. "Why is this seen by app?" needs spread-history recording. |

Total = 25×2/5 + 15×3/5 + 15×4/5 + 15×2/5 + 10×3/5 + 10×2/5 + 10×3/5
      = 10 + 9 + 12 + 6 + 6 + 4 + 6 = **53**

That is 30 points below O1 (83), 29 below O4 (82) and 15 below round 1's best (68). The inventor's own estimate (about 65) leaves out C1, C3, C4 and C5.

## 7. What the premise teaches

1. **Many non-nesting lifetimes are external.** Windows close, peers hang up and handlers return. The brief's hard case ("lifetimes known to the programmer, not the compiler") is often known to *neither*, because the OS decides. A memory model can therefore treat these external end events as free points without inferring anything. This is the real insight.
2. **Ignoring edge removal means freeing late.** Any scheme that tracks only edge *creation* (monotone sight, regions, promotion) has to keep memory until a region ends. Freeing early then needs an explicit `end()` with checked handles, which is manual disposal plus Vale-style checks. Witnesses is a clean demonstration that RC's decrement-on-unlink is what buys prompt reclamation, and that cycle handling is the price of it.
3. **The crux (c) is a cycle only because nothing ends it.** Editor → window → button → closure → editor is harmless if the window's end severs its handlers. You don't need witnesses for that. You need the framework to treat "window closed" as a hard teardown.

## 8. Kernel worth stealing (into O1 or O4)

- **K1. Teardown on external end (O1, library or runtime, no new language rule).** Built-in anchors (Window, Connection, Request, Timer, Thread) get a deterministic `end`. When an anchor ends it drops every strong reference its subtree holds into closures and handlers, which breaks UI cycles at a point the OS supplies. Under O1, (c) then works with no `weak self` as long as the closure is registered on a view owned by the window. Unlike round 1's "callbacks become no-ops when their captures die", here the callbacks die when their anchor dies.
- **K2. A leak check on closed anchors (debug mode, G8; G2-safe because it runs only in debug builds).** When a debug-build anchor ends, trace what was allocated under it and report survivors with the retaining path. For example: "Window#4 (closed) still retains 1.2 MB via Button.onTap closure → Editor". This turns O1's main failure mode, a silent cycle leak, into a precise report at the moment it happens.
- **K3. Per-turn arenas as an invisible optimisation (O1/O4).** Objects that escape analysis proves never leave a handler invocation go into a turn arena with no RC traffic, freed in bulk when the turn ends, in the style of autorelease pools or Ur/Web. There are no user rules, and the compiler falls back to RC when it is unsure.
- **K4. A per-anchor memory view in the debugger and profiler** ("bytes attributed to each window or request").

## 9. Verdict

**Kernel worth stealing.** As a memory model it is history-dependent, leaks on ordinary removal, and has unspecified holes around suspension and threads. Its sound core is a multi-region version of a known GC promotion barrier. The premise points at something useful: the hard non-nesting lifetimes are mostly external events. O1 can exploit that through anchor teardown (K1) and a leak check on closed anchors (K2), without adding a language rule.
