# Analysis 18: Actuary (death by forecast)

## 1. The idea in 3 sentences

A trained life table (a build artifact, like a PGO profile) assigns each allocation a predicted death tick, and the runtime releases whole cohort pages when that tick arrives. Safety comes from an invariant on pointer stores: a target may never be predicted to die before the slot holding it expires, and a violating store pushes the target's death later instead of failing. At each tick, threads scan their stacks and renew expiring leased slots, promoting anything still reachable. So a bad forecast costs work or memory but never correctness.

## 2. Prior art

Every component is known. The packaging is new.

- **Lifetime-predicted placement:** [Barrett & Zorn, PLDI 1993](https://bibtex.github.io/PLDI-1993-BarrettZ.html), [NeurIPS 1996 lifetime prediction](https://papers.neurips.cc/paper_files/paper/1996/hash/a9078e8653368c9c291ae2f8b74012e7-Abstract.html), and Google's [LLAMA, ASPLOS 2020](https://cs.utexas.edu/~mckinley/papers/llama-asplos-2020.pdf) all predict lifetime from allocation site and stack context, then group objects into pages by predicted lifetime. In all three, `free`/`delete` still decides when an object dies. The prediction only decides where it lives. Actuary is the first I know of to let the prediction decide death.
- **Per-site lifetime profiles feeding the memory manager:** [profile-based pretenuring](https://cse.buffalo.edu/~mhertz/pretenure-oopsla-2001.pdf) ([TOPLAS 2007](https://people.cs.umass.edu/~moss/papers/toplas-pretenure.pdf)).
- **Lease-and-renew liveness:** [Java RMI DGC](https://cr.openjdk.org/~alanb/sc/api/java.rmi/java/rmi/dgc/DGC.html). Remote references hold leases. If a lease isn't renewed, the reference expires and the object may be collected.
- **Store barrier that promotes the stored object's transitive closure:** this is how thread-local and minor heaps promote into a shared heap ([Multicore OCaml](https://arxiv.org/pdf/2004.11663), [Marlow & Peyton Jones local GC](https://www.cs.tufts.edu/~nr/cs257/archive/simon-marlow/local-gc.pdf)).
- **Root scanning:** this is a precise stack scan at safepoints with an epoch handshake, the same machinery as Go's or a JVM's concurrent collector.

Verdict on novelty: the tick-time protocol (root step, renewal, death) is a non-moving, incremental, age-segregated tracing collector. The expiry queue plays the role of a remembered set, and `promote` plays the role of marking. What's new is that an ML-style table sets each cohort's collection deadline, and that liveness is presumed dead by default and kept alive only by evidence. That is a real twist on scheduling, not a new memory model.

## 3. Soundness: counterexamples

Pseudo-code is illustrative only — not a syntax decision.

**C1. Use-after-free: the stack is scanned and then a value is loaded and the slot cleared.** The design says each thread scans its stack when it acknowledges tick `e`, then keeps running. The lease step and death step happen after all threads acknowledge.
```
// h alive (E=1000); h.f is a leased slot, lease = e, target b.E = e, in expiry[e]
thread A: <safepoint: ack e, root scan: b not on stack>
thread A: x = h.f          // loads b; stack slots have no barrier
thread A: h.f = nil        // a nil store promotes nothing
lease step(e): h.f is nil  -> no renewal
death step(e): b.E <= e    -> freed
thread A: x.name           // dangling
```
A plain load has no barrier, and the scanned stack is never rescanned. This is the black-stack problem that pushed Go to its hybrid barrier. Two fixes are possible. One is a second handshake that rescans every stack after the lease step. The other is a load barrier on leased slots. Either way it is no longer "one compare", and getting it right is the classic hard part of on-the-fly collectors.

**C2. Use-after-free: promotion races with an inherited store.**
```
T1: promote(b, 100)  // sets b.E = 100, then walks b's slots; reads b.g == old
T2: L = b.E          // reads 10, before T1's write is visible
T2: c.E = 10 ok;  b.g = c        // after T1 already walked b.g
tick 10: c freed; b (E=100).g -> c dangles
```
A fix needs a store–load fence plus a re-check of `h.E` after every pointer store (a Dekker pattern), or a per-object lock during promotion. Rule 6 says any object may be shared, so every pointer store in every program pays that fence.

**C3. Permanent leak through an inherited slot of an immortal holder.** The claim that garbage cannot live forever only holds while the holder's `E` is finite.
```
app (global, E = inf)
fn open(p) { app.current = Document.load(p) }   // site not in table -> inherited lease = inf
open("a"); open("b"); ...                        // every Document ever opened: E = inf
```
`E` only ever rises, and `app.current = d` raised each document to infinity. Overwriting the slot does not lower it. Every new code path, untrained site or test workload that never overwrites the slot turns into an unbounded leak in production. ARC frees each document immediately in this case.

**C4. Lingering bounded only by the holder's age.** This applies to long-lived containers.
```
queue = List()                  // global; buffer renewed by doubling
loop { queue.add(job()); process(queue.removeFirst()) }
```
Elements stored into buffer slots inherit `buffer.E`, and doubling keeps pushing that to about the container's age. A removed job lingers until the buffer's current `E`, so a server that has been up for a month keeps jobs for weeks. Giving element slots explicit leases instead puts every element in the expiry queue and renews each one, which is tracing the live set. Actuary has to choose between leaking and collecting, and it cannot avoid that choice. The idea's own weakness section already names it ("promotion can be O(n)").

**C5. Reclamation stops entirely.** A thread blocked in `read()`, a long C call or a busy loop with no safepoint never acknowledges the tick. Under EBR semantics, `now` cannot complete and nothing is freed process-wide. This needs JVM-style "in native means at safepoint" handling, which means some other thread has to scan the blocked thread's stack.

**C6. The perfect oracle is not free.** The root step scans every frame of every thread each tick, and ticks fire every 1 ms or 256 KB. That is up to 1000 stack scans per second per thread, plus a handshake, whatever the table says. "Zero work with a perfect table" is false.

**C7. Different OOM behaviour from the same source.** One table can cause an OOM in production while another passes CI. "A wrong forecast never changes what your program computes" excludes running out of memory, and running out of memory is observable.

**C8. Fragmentation from a single survivor.** A cohort page predicted to die at tick 4 that holds one promoted object stays pinned, because nothing moves. Reusing individual slots "when header `E ≤ e`" requires size-segregated pages and a lazy sweep at allocation. The idea says nothing is swept, but checking headers at allocation is a lazy sweep.

**C9. No weak references, so lapsed listeners can't be fixed.** `NotificationCenter.observe(editor.onChange)` keeps the editor alive. That is correct by reachability, but rule 1 removes `weak` and rule 3 removes deinit. The only fix is a manual unsubscribe, which is Java's lapsed-listener leak with no remedy.

Single-threaded, with a complete promotion recursion, the induction argument holds. Every unsoundness found is in the concurrent protocol, and those problems are fixable with known collector techniques: fences, a double handshake and load barriers. That is exactly the point: once fixed, it is a concurrent collector.

## 4. Scenarios

- **(a) works.** Growth buffers die cohort-wide. The final buffer's renewal re-promotes all lines, roughly O(n log n) total.
- **(b) works.** Cycles share one cohort with no `weak`. A detached subtree lingers until the lease lapses, or until the tree's own `E` if the site is untrained.
- **(c) partial.** It is memory-safe with free `self` capture, but closed windows linger (C4), or leak forever if the `windows.add` site is untrained (C3). There are no weak references or deinit to unsubscribe observers (C9).
- **(d) partial.** Sharing is trivial, but how fast evicted entries are reclaimed depends on training. A cache that is never evicted in tests leaks in production (C3).
- **(e) works.** Pass by reference. Scalar stores skip the barrier.
- **(f) hand-wave.** "Memory needs nothing special" is wrong because of C1, C2 and C5. The barrier needs fences, and the handshake needs a rescan.

## 5. Gates

- **G2: needs-john, and the analyst recommends fail.** The shipped runtime has every component of Go's collector: precise stack maps, safepoint polls, a handshake, a write barrier, worklist marking via promotion, and incremental reclamation. The only difference is who schedules it. The idea itself concedes that it does "work equivalent to an incremental collector". C6 shows that root scanning runs even with a perfect table. The charter's example, "like Java and Go do", describes this design. The training mode also requires building a real exact tracing collector, so the project ends up building a GC either way.
- **G3: pass.** Nothing appears in the source, and the life table is an external artifact like a lockfile. Built-in `List`/`Map` containers are the same pending question as for every option. A soft flag: a data file that changes behaviour (memory footprint) is an annotation in spirit, just stored outside the code. G3's stated concern, code that is "hard to understand", moves to "memory that is hard to understand".
- **Other goals.**
  - P-GO and P-JAVA: it reintroduces their complaint under a new name.
  - G7: training adds a workload stage to the build, and `app.life` produces noisy diffs and non-reproducible footprints.
  - G8: the mispredict report helps, but "why is this alive?" requires reasoning about ticks, leases and cohorts.
  - G1: no extra rules for the user, but the operational model is the hardest of all the options to explain.

## 6. Score (conditional on G2 passing)

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 4 | Day to day it has the fewest rules of any option (GC-like). Diagnosing footprint needs ticks, leases, cohorts and retraining, and `using` replaces destructors. |
| Memory safety | 15 | 3 | Sound single-threaded. As specified, it has two use-after-free races (C1, C2). Both are fixable, but only at a cost. |
| Expressiveness (b, c, d, OO) | 15 | 4 | Cycles and `self` capture are free. With no weak references and no deinit, lapsed listeners have no fix, and reclamation in (c) and (d) depends on training. |
| Implementation risk (AI-built, LLVM) | 15 | 1 | Statepoints, safepoints, a fenced barrier, an on-the-fly handshake protocol and a cohort allocator, plus a full tracing collector for training and the training and adaptation pipeline. |
| Performance & predictability | 10 | 2 | Fenced barrier on every pointer store, stack scans up to 1000/s, masking tags on loads, a 4-byte header, and footprint that depends on the table and the holder's age (C3, C4, C7). |
| Concurrency fit | 10 | 3 | Sharing is free for the user. The runtime needs fences, and one stalled thread stops all reclamation (C5). |
| Tooling, debuggability, C FFI | 10 | 2 | A good mispredict report. C cannot keep pointers past a call without JNI-style handles, tag bits leak into debuggers, and footprint is not reproducible across tables. |

Total = 25·4/5 + 15·3/5 + 15·4/5 + 15·1/5 + 10·2/5 + 10·3/5 + 10·2/5
     = 20 + 9 + 12 + 3 + 4 + 6 + 4 = **58**

If G2 is ruled a fail, the idea is out regardless of score.

Comparison: O1 is 83 and O4 is 82, so Actuary scores 25 and 24 points lower. Round 1's best was 68, so it is 10 points lower. The idea's self-assessment of about 76 assumed safety 5, which C1 and C2 disprove. It also scored performance 2.5 without counting the fence or the per-tick scans.

## 7. What the premise teaches and the kernel

**What the premise teaches.**
- Deciding death optimistically is safe if corrections only ever go upward (monotone `E`). That part is a real insight. A forecast can only be trusted, though, if something checks that the object is unreachable. When the programmer states nothing, which is the whole appeal, the checking has to happen at run time, by tracing or by counting. The forecast doesn't remove the collector. It schedules the collector.
- Every no-annotation, no-ownership design either pays for that check at run time or leaks.
- Profile data that lives outside the source is not an annotation (G3). So any scheme can use it freely, as long as it is used only for optimization and never to decide what the program means.

**Salvageable kernel for O1/O4.**
1. **Lifetime-cohort allocation as a pure optimization** (the LLAMA approach). Under ARC or O4, `build --train` records per-site lifetimes and the allocator groups objects into pages by predicted lifetime. ARC or ownership still decides when each object dies, so the program behaves the same, with better locality, less fragmentation and whole-page release. If the table is missing, the program just runs slower.
2. **"The collector teaches, the binary obeys" as a test-time leak detector for O1.** During `test` (G10) and in debug builds, run an exact tracer over the ARC heap that is never shipped. It reports strong cycles that are unreachable from roots, with allocation sites, for example a closure capturing `self` in (c). Optionally it fails the test. This directly addresses O1's main weakness (forgotten `weak`) and stays G2-clean, because nothing ships.
3. **`actuary report` as a profiler view.** It flags allocation sites where objects live far longer than that site's history says they should, for example "`editor:40` median 3 ms, this instance 900 s". Under ARC that pattern usually means a cycle or a stale cache, and the view fits G8/G9 tooling.

## 8. Verdict

**Kernel worth stealing.** The mechanism is a GC that a forecast schedules: it strains G2 and its concurrent protocol is unsound as specified. Its training-time tracer and lifetime-cohort allocator are good tooling and optimization add-ons for O1 or O4.
