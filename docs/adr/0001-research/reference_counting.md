# Automatic Reference Counting (ARC/RC) as the memory model for a new native language

Scope note (2026-11-07): research covered Swift ARC, Objective-C ARC, Nim ARC/ORC, Lobster compile-time RC, Koka/Lean Perceus, CPython RC (cautionary), Rust Rc/Arc (opt-in RC). Charter goals in play: G1 (simplicity), G2 (no GC run), G3 (no templates/macros/annotations), G11 (DSL/declarative layout, implies closures capturing state), P-RUST, P-SWIFT, P-C.

Provenance markers used below:
- **[measured]** = number from a benchmark or paper.
- **[vendor claim]** = claim by the language's own authors, often on author-chosen benchmarks.
- **[opinion]** = qualitative judgment.
- **[background, not re-verified]** = from prior knowledge, not fetched in this session. URLs in these items are pointers, not verified citations. Treat as lower confidence.

Dating: the key measured sources are old. BRC paper 2018, "Down for the count" 2012, Nim ORC blog 2020, Perceus 2021, Lobster docs undated (roughly 2019-2020). No newer replacement measurements were found. Swift's optimizer has changed a lot since 2018 (OSSA, ownership features), so Swift RC-overhead numbers are likely pessimistic for 2026 Swift.

---

## 1. How do cycles arise in practice, and what does each variant require of the programmer? (includes: does Nim ORC count as a "GC run" under G2?)

### Takeaway
Every pure-RC design leaks cycles. The ways cycles get built are well known: parent/back pointers, delegates/observers, and closures that capture their owner. The last one is the important case for G11, because callback-heavy UI/DSL code produces it all the time. Each variant answers it differently:
- Swift/Obj-C: the programmer annotates (`weak`/`unowned`, `[weak self]`).
- Nim ORC and CPython: a backup cycle collector, which is a tracing pass and arguably a "GC run" under G2.
- Koka/Lean: cycles are mostly impossible to build, because data is immutable.
- Rust: `Weak` plus wrapper types.
- Lobster: report cycles at program exit.

### Cited Findings
- **Cycles are a real share of garbage in OO programs [measured].** In Java benchmarks (DaCapo/SPEC, 19 programs), pure RC reclaims about 84% of objects on average. About 16% are cyclic and need backup tracing. The share varies by program: cycle collection matters a lot for javac, mpegaudio, eclipse, hsqldb and pmd, and reclaims under 1% for jess, db, jack, avrora, bloat and sunflow. — [Shahriyar, Blackburn, Frampton, "Down for the count?", ISMM 2012](https://core.ac.uk/download/156633347.pdf)
- **Nim ARC does not collect cycles.** "RC doesn't deal with cycles by itself", so cyclic objects are not freed. Under the old `refc` model, cycles were handled by a mark-and-sweep phase. — [Nim blog, "Introduction to ARC/ORC in Nim", 2020-10-15](https://nim-lang.org/blog/2020/10/15/introduction-to-arc-orc-in-nim.html)
- **Nim ORC exists because async code creates cycles.** ORC is a cycle collector built on ARC that "combines local tracing with reference counting", and it is recommended for async code. — [Nim blog, 2020-10-15](https://nim-lang.org/blog/2020/10/15/introduction-to-arc-orc-in-nim.html)
- **ORC's algorithm.** It is "based on the pretty well known 'trial deletion' algorithm by Lins and others" (the post links Bacon's concurrent cycle collection paper). The compiler calls the cycle collector only for types it considers potentially cyclic. Cyclic root candidates are registered and unregistered in O(1). — [Nim blog, "ORC – Vorsprung durch Algorithmen", 2020-12-08](https://nim-lang.org/blog/2020/12/08/introducing-orc.html)
- **ORC's authors describe it as a GC.** ARC is called "Nim's pure reference-counting GC". The post also says "ORC can be seen as a generational and incremental GC with the additional guarantee that acyclic structures are freed as soon as they become garbage." "There is no 'stop the world' phase." "ORC only touches memory that the mutator touches, too." — [Nim blog, 2020-12-08](https://nim-lang.org/blog/2020/12/08/introducing-orc.html)
- **ORC gives up some determinism.** ORC loses ARC's "determinism (partially)" because of its adaptive cycle-collection threshold. ARC is listed as "suitable for hard realtime programming". ORC is only partially suitable. — [Nim blog, 2020-10-15](https://nim-lang.org/blog/2020/10/15/introduction-to-arc-orc-in-nim.html)
- **Avoiding ORC's cost needs annotations.** Types can be marked `{.acyclic.}` (example: `Node {.acyclic.} = ref object`). The cycle collector's overhead "can be measurable in practice", and the annotation "can be crucial" for getting ORC's performance close to ARC's. — [Nim blog, 2020-12-08](https://nim-lang.org/blog/2020/12/08/introducing-orc.html)
- **Koka/Perceus has no cycle collector.** "We currently do not supply a cycle collector." Cycles mainly arise from mutable references, so the programmer breaks them by clearing reference cells. — [Reinking, Xie, de Moura, Leijen, Perceus TR v4 (PLDI 2021)](https://microsoft.com/en-us/research/uploads/prod/2020/11/perceus-tr-v4.pdf)
- **Lobster relies on an exit-time report.** The author says a "cycle report" at program exit, which helps the programmer break cycles, is largely sufficient in practice. This comes from experience with RC in general; it is not a documented part of the compile-time RC scheme. — [Lobster memory management docs](https://aardappel.github.io/lobster/memory%5Fmanagement.html)
- **Swift has added sugar to `[weak self]` but not removed it.** SE-0365 (Swift 5.8) allows implicit `self` after `guard let self else { return }` in a `[weak self]` closure. Before 5.8, every use needed `self.`. — [Hacking with Swift, Swift 5.8 SE-0365](https://www.hackingwithswift.com/swift/5.8/implicit-self-weak-capture); [Swift Forums acceptance thread](https://forums.swift.org/t/accepted-se-0365-allow-implicit-self-for-weak-self-captures-after-self-is-unwrapped/59517)
- **Swift/ObjC reference kinds [background, not re-verified].**
  - Swift has three: `strong` (default), `weak` (optional; set to nil when the target dies, using a side-table), and `unowned` (non-optional; traps if accessed after the target dies; `unowned(unsafe)` does not check). Closures capture strongly by default; capture lists `[weak self]` / `[unowned self]` change that. — [Swift book, ARC chapter](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/automaticreferencecounting/)
  - Objective-C ARC (Clang, 2011) has `__strong`, `__weak`, `__unsafe_unretained`, `__autoreleasing`, plus the "weakSelf/strongSelf dance" for blocks. — [Clang ObjC ARC spec](https://clang.llvm.org/docs/AutomaticReferenceCounting.html)
- **CPython is RC plus a backup cycle collector [background, not re-verified].** CPython pairs refcounting with a generational cycle detector (the `gc` module) that runs periodically based on allocation thresholds. That is exactly a "GC run" in the G2 sense. — [Python docs, gc module](https://docs.python.org/3/library/gc.html)

### Inferences
- **How common is `[weak self]`?** No quantitative corpus study was found (see Gaps). The fact that Swift spent a language-evolution proposal (SE-0365) just on reducing `[weak self]` boilerplate shows the pattern is common enough to matter. Every Swift tutorial/blog result in the leak-related searches centred on closures capturing `self`. That is qualitative evidence that closure-capture cycles are the dominant leak class in Swift/UIKit code.
- **Known leak bug classes in RC languages:**
  1. Parent/back-pointer not marked weak.
  2. Delegate/observer stored strongly.
  3. Escaping closure stored on an object (button handler, timer, network completion) capturing that object.
  4. Timer/run-loop retaining its target.
  5. Async tasks/futures holding continuation closures (the reason Nim needs ORC for async).
  6. Caches/registries holding strong refs forever. This is a "logical leak"; GC does not fix it either.
- **ORC vs G2.** ORC's cycle collector is a tracing pass. It is local (it traces only from candidate roots) and incremental, not stop-the-world. But it is triggered by a runtime threshold, and its own authors call it a "generational and incremental GC". Read strictly, G2 ("doesn't require a garbage collection run like Java and Go do") excludes it. Read loosely (no global stop-the-world heap tracing), it might pass. **This is a charter interpretation question that the ADR should escalate (`needs-john`) rather than decide.** A G2-safe position that is easy to defend: pure ARC with no runtime cycle collector, plus some combination of (i) weak refs, (ii) a language design that makes most cycles hard to build, and (iii) debug-build cycle/leak reports (as in Lobster).
- **Implication for G11.** If the language's declarative layout DSL uses reference-type views with stored closures (UIKit style), users will hit closure cycles constantly and will need `weak`. The alternative is value-type view descriptions with framework-owned state (the SwiftUI style; see example (c)) or Koka-style immutable data. Those structurally avoid most self-capture cycles. **The memory model decision and the DSL design are coupled.**
- **`acyclic` and `cursor` would break G3.** Nim's `acyclic` and `cursor` pragmas are annotations. Adopting those mechanisms as-is would violate G3. If a non-owning reference is needed, it would have to be a keyword or type modifier (like Swift's `weak var`), which is borderline under G3/G1.

### Gaps
- No empirical study was found that measures how often `[weak self]` / `weak` appears in real Swift codebases, or what share of iOS memory-leak bugs are retain cycles. Searches returned only tutorials and blogs (e.g. [stablekernel](https://stablekernel.com/how-to-prevent-memory-leaks-in-swift-closures/), [hackernoon](https://hackernoon.com/memory-leaks-in-swift-the-silent-killer-of-ios-apps?source=rss)), which are not quantitative. A grep of a large open-source Swift corpus would close this gap.
- Nim ORC's exact trigger thresholds and adaptive policy were not documented in the fetched pages. The Nim `mm.html` docs could not be fetched (allowlist).

---

## 2. Runtime cost: increment/decrement overhead, atomic vs non-atomic, cache effects, cascading frees

### Takeaway
Naive RC is expensive, mostly because of atomics and memory traffic. 2018 measurements put Swift RC at roughly 32% of execution time on average, and an atomic increment costs about 2.4x a non-atomic one. Biased or ownership-aware schemes recover most of that cost. Well-optimized RC can match a tracing collector's throughput. Cascading frees are deterministic but take O(size of the freed structure) at the point of the last release. No published pause measurements were found.

### Cited Findings
- **Swift RC share of runtime [measured, 2018].** Swift programs spend 32% of execution time on RC operations on average: 42% for client programs and 15% for server programs. — [Choi, Shull, Torrellas, "Biased Reference Counting", PACT 2018](https://docs.rs/crate/biasedrc/latest/source/paper.pdf)
- **Atomic vs non-atomic increment [measured, 2018].** An increment takes 13.84 ns with atomic CAS and 5.77 ns without, a 2.40x slowdown. Removing atomics cuts overall execution time by about 25%. — [BRC paper](https://docs.rs/crate/biasedrc/latest/source/paper.pdf)
- **Most objects are thread-private [measured].** 99.98% of objects in client programs and 93.08% in server programs have all their RC updates come from a single thread. BRC reduces average client execution time by 22.5% and raises server throughput by 7.3%. — [BRC paper](https://docs.rs/crate/biasedrc/latest/source/paper.pdf)
- **Caveat on the 42% figure [opinion].** A Swift Forums participant argued it is misleading because the benchmarks are microbenchmarks, and that RC is a much smaller share in real client software. This was not a core-team statement. — [Swift Forums, "Improving reference counting performance", Nov 2019](https://forums.swift.org/t/improving-reference-counting-performance/31185)
- **Separate compilation limits Swift's optimizer [opinion].** A participant in the same thread said the compiler misses RC elimination opportunities because "Swift compiles components separately". — [Swift Forums thread](https://forums.swift.org/t/improving-reference-counting-performance/31185)
- **Modern CPUs narrow the atomic gap [opinion, not measured].** "`inc` is a handful of cycles. `lock inc` even uncontended, can be dozens." The same author says uncontended atomics on Apple Silicon and AMD Zen 3 are "almost as cheap as non-atomic". He also notes that refcounts sharing a cache line or page with other modified data penalize concurrent workloads (false sharing). — [Chad Austin, "Reference Counting Things", 2023-11](https://chadaustin.me/2023/11/reference-counting-things/)
- **Optimized RC can match tracing throughput [measured, JVM, 2012].** The baseline coalescing deferred RC was about 30% slower than tuned mark-sweep. The optimized RC was on average marginally faster than mark-sweep: at worst 22% slower (javac), at best 21% faster (hsqldb). — [Down for the count?](https://core.ac.uk/download/156633347.pdf)
- **Small counts suffice [measured].** 99.7% of objects have a max refcount of 7 or less. With 3-bit counts, 0.65% overflow, but those objects receive about 23% of all increments and decrements. An extra 32-bit header word costs about 2.5% total time. — [Down for the count?](https://core.ac.uk/download/156633347.pdf)
- **Nim ORC vs mark-and-sweep latency [vendor claim, author-built stress benchmark].**
  - With `GC_fullCollect`: ORC average latency 320.49 µs and max 6.24 ms, vs M&S 65.31 ms and 204.79 ms. ORC served 30963.96 req/s vs 282.69.
  - Without full collect (M&S in `memForSpeed` mode): ORC max latency 1.10 ms vs 46.41 ms. M&S had higher throughput, 39561.97 vs 34948.95 req/s. ORC max memory was 137 MiB vs 333 MiB.
  - The author says the benchmark "was written to stress the differences" and is "not supposed to model realistic workloads".
  — [Nim blog, 2020-12-08](https://nim-lang.org/blog/2020/12/08/introducing-orc.html)
- **Koka atomics cost [measured].** Using atomics everywhere (instead of Koka's shared-object scheme) caused slowdowns from 5% (rbtree) to 59% (nqueens). — [Perceus TR](https://microsoft.com/en-us/research/uploads/prod/2020/11/perceus-tr-v4.pdf)
- **CPython free-threading cost [measured, secondary source].** The free-threaded build is roughly 10–15% slower on single-threaded workloads, due to thread-safe RC variants and other per-object operations. It uses biased reference counting, which changes the object header (ABI-incompatible). It was experimental in 3.13 and officially supported in 3.14 under PEP 779. The GIL build is still the default. — [pydevtools, "What is PEP 703?"](https://pydevtools.com/handbook/explanation/what-is-pep-703/)
- **Large-tree deallocation matters in practice [opinion].** Watchman's refcount optimizations were a "material win" for code allocating or deallocating large trees. No numbers were given. — [Chad Austin](https://chadaustin.me/2023/11/reference-counting-things/)

### Inferences
- **Cascading frees.** Dropping the last reference to an N-node structure frees all N nodes synchronously, inside whichever operation did the last release. It is deterministic in *when* it happens, but unbounded in *how long* it takes. In a UI app, dropping a 1M-node document model on the main thread would cause a frame hitch proportional to N.
  - Mitigations: (i) deferred/incremental free queues, which reintroduce a small runtime "collector-like" component; (ii) freeing on a background thread; (iii) arena/region allocation for bulk structures.
- **Recursion depth in destructors [background, not re-verified].** A naive recursive release of a long linked list can overflow the stack. This is a known issue for Rust `Box`-linked lists and C++ `unique_ptr` chains. The runtime's release path should be iterative (a worklist).
- **Atomics: the biggest design lever.** Making counts non-atomic by default is worth roughly 25% of runtime in Swift-like code (measured above). Choosing that default requires the type system or runtime to know which objects cross threads (see section 6).
- **Header size.** Use a word-sized header holding the count. 3–5 bits would cover 99%+ of objects, but the remaining objects get many increments, and extra header words cost about 2.5%. A 32-bit count plus flags in one 64-bit word is a reasonable default.

### Gaps
- No published measurement was found of pause/latency from cascading frees in Swift, Nim ARC or ObjC.
- No 2024–2026 measurement of Swift ARC overhead was found. The 2018 BRC numbers predate OSSA and the Swift 5.9+ ownership features.
- The Shahriyar numbers are for a JVM with deferred/coalescing RC (no RC on stack/register writes). They are not directly comparable to Swift-style eager RC.

---

## 3. How much can compiler optimization (RC elision, borrow inference, Perceus) remove?

### Takeaway
A lot. Lobster reports about 95% of runtime RC operations removed by ownership inference with almost no source changes. Perceus with reuse gets a purely functional red-black tree to within 10% of C++. Both results come from the language authors on their own benchmarks, and both depend on language properties: Lobster's single-owner inference, and Koka's immutable data, explicit control flow and whole-program view. Results do not automatically carry over to a mutable OO language with separate compilation.

### Cited Findings
- **Lobster [vendor claim].** The ownership analysis "was able to remove around 95% of runtime reference count operations". Converting "several dozens of Lobster programs" from runtime to compile-time RC needed changes in "only 2 locations". — [Lobster docs](https://aardappel.github.io/lobster/memory%5Fmanagement.html)
- **Lobster mechanism.** Each allocation gets one owner (the first variable, field or vector element it is assigned to). Later uses are borrows with no RC. If a second owner is needed, the compiler inserts an increment where Rust would reject the program. Functions are specialized by caller ownership; large or dynamic-dispatch functions get one borrowing specialization. Return values are always owned. — [Lobster docs](https://aardappel.github.io/lobster/memory%5Fmanagement.html)
- **Lobster's remaining errors.** Users can still see borrow errors, described as rare: "cannot modify x while y borrows it" (e.g. `f(v[0], v.pop())`) and "cannot assign to borrowed argument". Aliasing through a reassigned owning variable is not tracked. — [Lobster docs](https://aardappel.github.io/lobster/memory%5Fmanagement.html)
- **Perceus results [measured, author benchmarks].** On rbtree (42M insertions), Koka "is within 10% of the C++ performance". Without its optimizations, Koka is "more than 2× slower" on rbtree. Java used "almost 10× the memory of Koka (1.7GiB vs. 170MiB)". The paper says Swift's RC appears "less effective than Koka". Comparators: OCaml 4.08.1, GHC 8.6.5, Swift 5.3, Java SE 15, C++. — [Perceus TR](https://microsoft.com/en-us/research/uploads/prod/2020/11/perceus-tr-v4.pdf)
- **Perceus definitions.** "Precise"/"garbage free" means an object is freed "as soon as no more references remain", so only live data is retained. Reuse analysis pairs a matched constructor with a same-size allocation and updates in place if the object is unshared. FBIP ("functional but in place") lets in-place algorithms be written functionally. Perceus builds on Lean's RC work. — [Perceus TR](https://microsoft.com/en-us/research/uploads/prod/2020/11/perceus-tr-v4.pdf)
- **Perceus caveats [author statements].** "The explicit control-flow is not zero-cost." "More experimentation in larger systems is needed." Planned selective borrowing "would make certain programs no longer be garbage free". — [Perceus TR](https://microsoft.com/en-us/research/uploads/prod/2020/11/perceus-tr-v4.pdf)
- **Nim's cursor inference.** Common traversals "do not involve RC operations". — [Nim blog, 2020-12-08](https://nim-lang.org/blog/2020/12/08/introducing-orc.html). Move semantics turn copies into moves, and copy elision reduces some copies to cursors (aliases). — [Nim blog, 2020-10-15](https://nim-lang.org/blog/2020/10/15/introduction-to-arc-orc-in-nim.html)
- **JVM RC optimizations [measured].** "Born-dead" (allocate objects as dead, so short-lived ones need no explicit free) removes over 80% of decrements. Coalescing removes about 64% of pointer-field RC updates. Combined optimizations give 24% better total time than standard RC. — [Down for the count?](https://core.ac.uk/download/156633347.pdf)
- **Lean 4 [background, not re-verified].** Lean 4 uses borrow inference plus destructive updates on unique values ("Counting Immutable Beans", Ullrich & de Moura, IFL 2019). This is the precursor to Perceus. — [arXiv 1908.05647](https://arxiv.org/abs/1908.05647)
- **Swift's path [background, not re-verified].** Swift added Ownership SSA (OSSA) in SIL to improve RC optimization, and later added explicit ownership features: `borrowing`/`consuming` parameter modifiers (SE-0377), the `consume` operator (SE-0366) and noncopyable types `~Copyable` (SE-0390), all Swift 5.9. — [swift-evolution proposals](https://github.com/swiftlang/swift-evolution)

### Inferences
- **The common pattern:** inference does most of the work; explicit ownership is the escape hatch for the rest. Lobster gets 95% with no syntax. Swift had to add user-facing ownership syntax (borrowing/consuming/consume/~Copyable) to get predictable performance. That added surface area is part of what P-SWIFT ("too many features") complains about. **An ADR adopting ARC should say up front whether it will ever expose ownership modifiers.** If not, it accepts whatever performance inference alone delivers.
- **Perceus-style reuse fits best** where the language uses value semantics or immutable data with COW. Reuse needs uniqueness checks at runtime (refcount == 1), which are cheap with non-atomic counts.
- **The 95% and within-10% numbers are on the authors' own programs.** They are evidence of what is achievable, not guarantees. No independent replications were found.

### Gaps
- No independent (non-author) evaluation of Lobster's 95% figure was found.
- No published measurement was found of how much RC traffic Swift's OSSA optimizer removes in 2024–2026 compilers.

---

## 4. Learnability: ARC/weak references vs Rust ownership vs GC

### Takeaway
No controlled studies comparing the learnability of ARC, Rust ownership and GC were found. The available evidence is indirect: Swift needed a language proposal just to make `[weak self]` easier to write; Lobster reports needing almost no source changes; Rust's community surveys repeatedly flag complexity. ARC is plausibly much easier than Rust ownership for the common case, because no annotations are needed and the program always compiles. The cost is a "silent failure" mode: cycles leak instead of failing to compile.

### Cited Findings
- **Swift weak-self ergonomics.** SE-0365 (Swift 5.8) exists to remove boilerplate in `[weak self]` closures. — [Hacking with Swift](https://www.hackingwithswift.com/swift/5.8/implicit-self-weak-capture)
- **Lobster inference [vendor claim].** Fully automatic inference meant "only 2 locations" changed across dozens of programs. Where Rust would reject a program, Lobster inserts a refcount increment instead. — [Lobster docs](https://aardappel.github.io/lobster/memory%5Fmanagement.html)
- **Rust survey coverage.** Rust's annual surveys and press coverage (2023–2025) report respondent concerns about language complexity. Pointers: [2024 State of Rust Survey results](https://blog.rust-lang.org/2025/02/13/2024-State-Of-Rust-Survey-results/), [devclass on 2023 survey](https://devclass.com/2024/02/20/rust-developers-fear-language-is-getting-too-complex-and-prefer-bug-fixes-to-new-features/), [InfoWorld 2018: "Rust language is too hard to learn and use, says user survey"](https://www.infoworld.com/article/3324488/rust-language-is-too-hard-to-learn-and-use-says-user-survey.html). Exact percentages were **not** retrieved (the fetch hit a redirect stub); see Gaps.

### Inferences
- **What ARC asks of the learner:** one concept ("objects live while something points to them") plus one exception rule ("back-pointers and self-capturing stored closures must be weak").
- **What Rust asks:** ownership, borrowing, lifetimes, `Rc`/`Arc`/`RefCell`/`Mutex` combinations, and `Send`/`Sync`, all enforced at compile time.
- **What GC asks:** nothing about lifetimes, but users must accept collection pauses (excluded by G2).
- **The main learnability risk of ARC is delayed feedback.** A missing `weak` compiles and runs, and only shows up as memory growth. Strong tooling (debug-build leak/cycle report at exit, as in Lobster; Xcode-style memory-graph debugger) would address this and fits G8 (debugging tools).
- **Swift-style capture lists add syntax and decisions.** `[weak self]`, `[unowned self]`, `guard let self` all add syntax (strain on G4) and decisions (strain on G1). A design that makes the common UI case cycle-free by construction reduces this burden more than better syntax does.

### Gaps
- No peer-reviewed study was found comparing learnability or error rates of ARC vs Rust ownership vs GC.
- Exact Rust survey percentages (e.g. share citing the learning curve or borrow checker as the top difficulty) were not retrieved in this session.

---

## 5. Implementation complexity for a small team / autonomous agent on LLVM

### Takeaway
Basic ARC is among the simplest memory models to implement on LLVM:
- inserting retain/release around assignments and scope exits;
- a destructor per type;
- a small runtime.

The difficulty is in the optimizations (ownership inference/elision, uniqueness-based reuse, cycle handling, thread-safety of counts). Nim's ARC was built by a small team. Swift's optimizer took a large Apple team many years.

### Cited Findings
- **Nim ARC's core pieces.** Destructors, move semantics and copy elision; the compiler injects destructor calls at scope end (wrapping bodies in `try`/`finally`); per-type hooks for destroy/move/copy. — [Nim blog, 2020-10-15](https://nim-lang.org/blog/2020/10/15/introduction-to-arc-orc-in-nim.html)
- **Lobster's analysis** is a single-owner-per-allocation inference with function specialization by ownership. Large or dynamic-dispatch functions get one borrowing specialization. — [Lobster docs](https://aardappel.github.io/lobster/memory%5Fmanagement.html)
- **Perceus requires** explicit control flow in the IR (which "is not zero-cost") and precise ownership tracking. Drop and reuse specialization extends Lean's approach. — [Perceus TR](https://microsoft.com/en-us/research/uploads/prod/2020/11/perceus-tr-v4.pdf)
- **ORC's complexity** comes from trial deletion with O(1) root-candidate registration, plus type analysis to skip acyclic types. — [Nim blog, 2020-12-08](https://nim-lang.org/blog/2020/12/08/introducing-orc.html)
- **Swift's ownership/optimizer evolution** (OSSA, SE-0366/0377/0390) spans several years of compiler work. [background, not re-verified] — [swift-evolution](https://github.com/swiftlang/swift-evolution)

### Inferences
- **Suggested staging for an agent-built compiler:**
  - **Stage 1** (weeks): naive non-atomic RC with retain/release emitted from a mid-level IR. Value types (structs/arrays) are copy-on-write over refcounted buffers. Iterative release worklist. Debug-mode leak/cycle report at exit.
  - **Stage 2**: last-use move inference (Nim/Lobster style) and borrow inference for parameters. This is where most of the measured gains are (95% Lobster; 80%+ decrement elimination for short-lived objects on the JVM).
  - **Stage 3**: Perceus-style reuse for unique values.
  - LLVM does not understand refcounts natively. Elision must happen in the language's own IR before LLVM lowering; LLVM's generic optimizations will not remove paired atomic RMWs. (Swift and Koka both do RC optimization in their own IR.)
- **Correctness risk.** Mistakes in RC insertion cause use-after-free or leaks that are hard to debug. A reference interpreter or sanitizer mode that checks counts (e.g. poisoning freed memory, asserting count > 0 on retain) is cheap insurance and fits G8/G10.
- **Cycle collector is optional.** Not building one (pure ARC) is the simplest option and the safest under G2. ORC-style trial deletion is a significant extra subsystem.
- **Weak references** need either side-tables (Swift) or a weak count in the header (Rust `Rc`'s weak count [background]). Both are modest work.

### Gaps
- No published effort or size figures (person-years, LOC) were found for Nim ARC, Lobster's analysis, Koka's Perceus or Swift's OSSA.

---

## 6. Interaction with concurrency and with C FFI

### Takeaway
Concurrency is RC's hardest interaction. Atomic counts everywhere (Swift, Rust `Arc`) cost roughly 2.4x per operation and about 25% of total runtime in older measurements. Non-atomic-by-default needs the language to know which objects cross threads. The options:
- types: Rust `Rc` vs `Arc`, Swift 6 `Sendable`;
- isolation/move semantics: Nim;
- a runtime "shared" bit: Koka's negative counts, BRC, CPython free-threaded.

C FFI is comparatively easy. RC objects have deterministic lifetimes, so C can hold them with explicit retain/release, and there is no GC thread registration.

### Cited Findings
- **Nim ARC is non-atomic.** It "doesn't use atomic RC", unlike Swift. Values can be moved between threads instead of copied, with isolation via an RFC. — [Nim blog, 2020-10-15](https://nim-lang.org/blog/2020/10/15/introduction-to-arc-orc-in-nim.html)
- **Koka marks thread-shared objects with a negative count.** One inlined test catches both shared objects and objects that need freeing, so the fast path avoids atomics. Atomics-everywhere costs 5–59%. — [Perceus TR](https://microsoft.com/en-us/research/uploads/prod/2020/11/perceus-tr-v4.pdf)
- **BRC.** The owner thread increments non-atomically (6.28 ns); non-owner threads use atomics (15.57 ns). 93–99.98% of objects are thread-private. — [BRC paper](https://docs.rs/crate/biasedrc/latest/source/paper.pdf)
- **CPython adopted BRC** for the free-threaded build. That changed the object header and broke ABI compatibility; the build is 10–15% slower single-threaded. — [pydevtools](https://pydevtools.com/handbook/explanation/what-is-pep-703/)
- **Nim FFI.** ARC makes FFI and embedding easier. Under `refc`, each foreign thread had to set up the GC manually, "which is not the case with ARC". Nim presents ARC as a better base for .dll/.so/Python extensions. — [Nim blog, 2020-10-15](https://nim-lang.org/blog/2020/10/15/introduction-to-arc-orc-in-nim.html)
- **Rust [background, not re-verified].** `Rc<T>` is `!Send`/`!Sync` (non-atomic, single-thread); `Arc<T>` is atomic. The compiler enforces the split. Shared mutation needs `RefCell` (single-thread) or `Mutex`/`RwLock` (multi-thread). — [std::rc docs](https://doc.rust-lang.org/std/rc/index.html), [std::sync::Arc docs](https://doc.rust-lang.org/std/sync/struct.Arc.html)
- **Swift [background, not re-verified].** Swift uses atomic RC for all class instances. Swift 6 strict concurrency (`Sendable`, actors) checks data-race safety at compile time but does not make RC non-atomic.
- **Objective-C ARC [background, not re-verified].** ObjC↔C (CoreFoundation) interop requires bridging casts: `__bridge`, `__bridge_retained`/`CFBridgingRetain`, `__bridge_transfer`/`CFBridgingRelease`. These are a known source of leaks and over-releases. — [Clang ARC spec](https://clang.llvm.org/docs/AutomaticReferenceCounting.html)

### Inferences
- **G1-friendly concurrency option:** non-atomic RC by default, with threads communicating by *moving* uniquely-owned values (checked at runtime: count == 1 at send, or at compile time by last-use analysis). Explicitly shared objects get an atomic "shared" mode (Koka/BRC-style flag). This avoids Rust's dual `Rc`/`Arc` types (P-RUST) and Swift's always-atomic cost.
- **FFI rules.** C code receiving an RC pointer must either borrow it for the call's duration (no RC traffic) or take a +1 reference and call an exported `release`. The ADR should define this ABI rule explicitly; ObjC's bridging casts show the cost of leaving it ad hoc.
- **Why RC beats tracing GC at the FFI boundary:** C never sees objects move, there is no root registration, and foreign threads need no registration.

### Gaps
- No 2024–2026 measurement of atomic RC cost on Apple Silicon or Zen 4/5 was found. Austin's "almost as cheap" claim is qualitative.
- Nim 2.x's current threading model (e.g. `Isolated[T]`, the `threading/channels` package) was not verified in this session.

---

## 7. Scenario code examples (a)–(f)

### Takeaway
RC is invisible for scenarios (a) and (d). It causes friction for (b) and (c) (cycles: weak refs or a collector). For (e), there is a hidden cost: copy-on-write can silently copy a large shared array. For (f), the cost is atomics or isolation rules. The code below was written for these notes to illustrate known semantics. It is not quoted from sources unless stated, and it has not been compiled in this session.

### Cited Findings
- The SE-0365 `[weak self]` / `guard let self` pattern in (c) is taken from [Hacking with Swift, Swift 5.8](https://www.hackingwithswift.com/swift/5.8/implicit-self-weak-capture).
- Nim `{.acyclic.}` usage follows [Nim ORC blog](https://nim-lang.org/blog/2020/12/08/introducing-orc.html).
- Koka/Perceus in-place reuse of unique data (FBIP) in (e) follows the [Perceus TR](https://microsoft.com/en-us/research/uploads/prod/2020/11/perceus-tr-v4.pdf).

### Inferences

#### (a) Read a file of unknown length into a list of lines

```swift
// Swift — ARC is invisible; [String] is a COW value type over a refcounted buffer
let lines = try String(contentsOfFile: path, encoding: .utf8)
    .split(separator: "\n", omittingEmptySubsequences: false)
    .map(String.init)
```
```nim
# Nim (ARC/ORC) — seq is uniquely owned; growth reallocs without RC traffic
import std/strutils
let ls = readFile(path).splitLines()
```
```rust
// Rust — ownership is simple here; ? propagates io errors
let lines: Vec<String> = std::fs::read_to_string(path)?.lines().map(String::from).collect();
```
- **Benefit:** with RC/ARC this is as easy as with GC. The list has one owner and is freed deterministically at scope end. Rust is also easy here.
- **Note:** in Swift, `split` returns `Substring`s that keep the whole file buffer alive until converted (`String.init`). This is a lifetime footgun that GC would share.

#### (b) Tree with parent pointers

```swift
// Swift — must mark the back-pointer weak; forgetting it leaks the whole tree, silently
final class Node {
    var children: [Node] = []
    weak var parent: Node?          // weak: optional, auto-nil when the parent dies
    func add(_ c: Node) { c.parent = self; children.append(c) }
}
```
```objc
// Objective-C ARC — same idea
@interface Node : NSObject
@property (nonatomic, strong) NSMutableArray<Node *> *children;
@property (nonatomic, weak)   Node *parent;
@end
```
```nim
# Nim — ORC collects the cycle (cost: cycle-collector run).
# Under ARC (no ORC), this leaks unless the parent field is made non-owning
# with the {.cursor.} pragma (a raw, non-zeroing alias that can dangle).
type Node = ref object
  children: seq[Node]
  parent: Node          # ORC: fine; ARC: leak. Alternative: parent {.cursor.}: Node
```
```rust
// Rust — Rc + Weak + RefCell; correct but heavy (P-RUST)
use std::{rc::{Rc, Weak}, cell::RefCell};
struct Node { parent: RefCell<Weak<Node>>, children: RefCell<Vec<Rc<Node>>> }
fn add(p: &Rc<Node>, c: Rc<Node>) {
    *c.parent.borrow_mut() = Rc::downgrade(p);
    p.children.borrow_mut().push(c);
}
// reading the parent: c.parent.borrow().upgrade()  -> Option<Rc<Node>>
```
- **Pain point:** every RC variant without a cycle collector makes the programmer identify back-edges.
  - Swift `weak` is safe (zeroing) but forces optional unwrapping at each use.
  - Nim's `cursor` is unsafe (P-C concern).
  - Rust is safe but verbose.
- **Koka-style immutable data** avoids this structurally. Parent pointers are replaced by zippers or by passing the parent down during traversal.
- **Design option for the ADR:** make `weak` a field modifier keyword, so it is not an annotation under G3.

#### (c) UI callback capturing the enclosing object (button onTap → self.save())

```swift
// Swift / UIKit-style — the canonical retain cycle: self -> button -> closure -> self
final class EditorController {
    let saveButton = Button()
    init() {
        // saveButton.onTap = { self.save() }            // LEAK: strong capture of self
        saveButton.onTap = { [weak self] in              // fix: capture list
            guard let self else { return }               // SE-0365 (Swift 5.8+) allows implicit self after this
            save()
        }
    }
    func save() { /* ... */ }
}
```
```objc
// Objective-C ARC — the "weakSelf/strongSelf dance"
__weak typeof(self) weakSelf = self;
self.saveButton.onTap = ^{
    __strong typeof(weakSelf) strongSelf = weakSelf;
    if (!strongSelf) return;
    [strongSelf save];
};
```
```swift
// Swift / SwiftUI-style — declarative DSL with value-type views: no self-cycle to break.
// The View is a struct; the closure captures a copy of the struct, and state lives in
// framework-owned storage (@State / an observable model), not in a reference graph
// that the closure closes over.
struct EditorView: View {
    @State private var text = ""
    var body: some View {
        Button("Save") { save() }          // no [weak self] needed: self is a value
    }
    func save() { /* ... */ }
}
```
```nim
# Nim — closures are refcounted environments; capturing a ref that owns the
# closure forms a cycle: leaked under ARC, collected under ORC.
type Editor = ref object
  onTap: proc () {.closure.}
proc save(e: Editor) = discard
proc newEditor(): Editor =
  let e = Editor()
  e.onTap = proc () = e.save()   # e -> onTap env -> e
  e
```
- **Pain point:** this is the scenario that matters most for G11. UIKit-style reference-type widgets with stored closures make `[weak self]` mandatory and easy to forget. The SwiftUI-style example (value-type view structs, framework-held state) shows that DSL design can remove most of these cycles. (Caveat: SwiftUI property wrappers like `@State` are annotations, which conflict with G3, so the *mechanism* would need a different surface syntax.) [background, not re-verified for SwiftUI internals]
- **Possible language-level mitigations, each with tradeoffs:**
  1. Closures stored in fields capture `self` weakly by default. Simple, but surprising when the closure outlives `self` and silently does nothing.
  2. The compiler warns when a closure stored into a field of X captures X.
  3. Value-type UI descriptions (recommended to evaluate in the DSL ADR).

#### (d) Shared mutable cache used by two components

```swift
// Swift — a class gives shared mutable identity; two strong refs, no cycle, freed when both drop
final class Cache { var entries: [String: Data] = [:] }
final class Loader   { let cache: Cache; init(_ c: Cache) { cache = c } }
final class Renderer { let cache: Cache; init(_ c: Cache) { cache = c } }
let c = Cache(); let l = Loader(c); let r = Renderer(c)
// thread-safe variant: `actor Cache { ... }` with `await` at call sites (Swift 5.5+/6)
```
```rust
// Rust — opt-in RC plus interior mutability, explicit at every type
use std::{rc::Rc, cell::RefCell, collections::HashMap};
type Cache = Rc<RefCell<HashMap<String, Vec<u8>>>>;
struct Loader { cache: Cache }
struct Renderer { cache: Cache }
let c: Cache = Rc::new(RefCell::new(HashMap::new()));
let (l, r) = (Loader { cache: c.clone() }, Renderer { cache: c.clone() });
// multithreaded: Arc<Mutex<HashMap<..>>>
```
- **Benefit:** this is RC's sweet spot. It is natural, cycle-free, and deterministic: the cache is freed exactly when its last user drops it.
- **Contrast:** in Rust, opt-in RC is explicit (`Rc<RefCell<…>>`) and generic-heavy, which conflicts with G3 (no templated types) and P-RUST.
- **Pain point:** if the cache stores callbacks or objects that point back at Loader/Renderer, it is (b)/(c) again.

#### (e) Pass a large list to a function that mutates it

```swift
// Swift — inout + copy-on-write. Fast if the buffer is uniquely referenced;
// a silent O(n) copy if anyone else holds the array.
func normalize(_ xs: inout [Double]) {
    let m = xs.max() ?? 1
    for i in xs.indices { xs[i] /= m }      // first write checks uniqueness (refcount == 1)
}
var data = loadMillionDoubles()
let snapshot = data            // shares the buffer (refcount 2)
normalize(&data)               // HIDDEN full copy here because `snapshot` exists
```
```nim
# Nim — `var` parameter mutates in place; `sink` transfers ownership (move) without copying
proc normalize(xs: var seq[float]) =
  let m = max(xs)
  for x in xs.mitems: x /= m
var data = loadMillion()
normalize(data)                # in place, no RC traffic on elements
```
```koka
// Koka (Perceus/FBIP) — written functionally; if `xs` is unique at runtime,
// map reuses each cons cell in place (no allocation)
fun normalize(xs : list<float64>, m : float64) : list<float64>
  xs.map(fn(x) x / m)
```
- **Benefit:** value semantics plus a uniqueness check (RC == 1) give "safe by default, in place when possible", with no borrow checker.
- **Pain point:** performance becomes non-local. An unrelated alias elsewhere turns an O(1)-extra-memory mutation into an O(n) copy. Swift exposes `isKnownUniquelyReferenced` and ownership modifiers to control this. That is the kind of feature creep P-SWIFT warns about.
- **For the ADR:** a debug-mode/profiler warning on large COW copies would fit G8.

#### (f) Sharing data between threads

```swift
// Swift 6 — compile-time data-race checking; RC is always atomic
actor Counter { var n = 0; func inc() { n += 1 } }
let counter = Counter()
await withTaskGroup(of: Void.self) { g in
    for _ in 0..<4 { g.addTask { await counter.inc() } }
}
// sharing a non-Sendable class across tasks is a compile error under Swift 6 strict concurrency
```
```rust
// Rust — Arc (atomic RC) + Mutex; Rc would be rejected (!Send)
use std::{sync::{Arc, Mutex}, thread};
let v = Arc::new(Mutex::new(Vec::new()));
let hs: Vec<_> = (0..4).map(|i| { let v = Arc::clone(&v);
    thread::spawn(move || v.lock().unwrap().push(i)) }).collect();
for h in hs { h.join().unwrap(); }
```
```nim
# Nim 2.x (sketch, not verified) — ARC counts are non-atomic, so a ref must be
# *moved* (isolated) to another thread rather than shared; shared state uses
# explicit locks or channels.
import std/isolation
var msg = isolate(@[1, 2, 3])   # proven to have no outside aliases
# chan.send(move msg)           # e.g. via threading/channels; sender loses access
```
- **Benefits:** RC objects can be handed between threads without stopping the world. Moving uniquely-owned data (count == 1) needs no atomics at all.
- **Pain points:**
  - Always-atomic (Swift, `Arc`) costs about 2.4x per RC op [measured 2018].
  - The non-atomic + isolation approach (Nim) needs an isolation concept the programmer must learn.
  - Rust's split needs two RC types plus `Send`/`Sync`.
- **G1-friendly candidate for the ADR:** a Koka/BRC-style runtime "shared" bit. Counts are non-atomic until an object is published to another thread, then atomic. The language surface is a single `share`/`send` operation.

### Gaps
- None of the code above was compiled in this session. The Nim threading snippet in particular is a sketch, and its API (`std/isolation`, `threading/channels`) should be checked against Nim 2.2 docs.

---

## 8. Variant summary against the charter (scoring inputs)

### Takeaway
Pure ARC with compile-time elision (Lobster/Nim-ARC style), non-atomic default counts and a "share" mode for threads is the RC variant most consistent with G1/G2/G3/P-RUST/P-SWIFT. Its main unresolved risk is closure/back-pointer cycles in G11 DSL code, which should be designed out at the DSL level. ORC-style or CPython-style cycle collectors likely conflict with G2 and need John's ruling.

### Cited Findings
- **ARC:** "fully deterministic", "suitable for hard realtime". ORC is partially deterministic because of its adaptive threshold. — [Nim blog 2020-10-15](https://nim-lang.org/blog/2020/10/15/introduction-to-arc-orc-in-nim.html)
- **ORC** is self-described as "a generational and incremental GC". — [Nim blog 2020-12-08](https://nim-lang.org/blog/2020/12/08/introducing-orc.html)
- **Lobster** gets about 95% RC op elimination without programmer annotations. — [Lobster docs](https://aardappel.github.io/lobster/memory%5Fmanagement.html)
- **Koka:** purely functional rbtree within 10% of C++, no cycle collector. — [Perceus TR](https://microsoft.com/en-us/research/uploads/prod/2020/11/perceus-tr-v4.pdf)
- **Swift:** 32% of time on RC (2018) with always-atomic counts. — [BRC paper](https://docs.rs/crate/biasedrc/latest/source/paper.pdf)

### Inferences
Per-variant fit (author's judgment, based on findings above):

| Variant | G2 (no GC run) | G1 / P-SWIFT / P-RUST burden | G3 (no annotations/templates) | G11 closure cycles | Perf notes |
|---|---|---|---|---|---|
| Swift ARC | Pass | Medium: strong/weak/unowned, capture lists, later ownership modifiers | `weak` is a keyword; Swift 5.9 ownership adds more surface | Programmer must write `[weak self]` | Always-atomic; 2018: ~32% time on RC |
| ObjC ARC | Pass | Medium-high: `__weak`, bridging casts | Qualifier keywords | weakSelf/strongSelf dance | Always-atomic |
| Nim ARC | Pass | Low-medium | `{.cursor.}`/`{.acyclic.}` are pragmas (conflict with G3 if copied) | Leaks | Non-atomic; move/cursor inference |
| Nim ORC | **Ambiguous / likely fail (escalate)** | Low | Same pragmas | Collected automatically | Sub-ms latency claimed [vendor]; cycle collector overhead "measurable" |
| Lobster compile-time RC | Pass (exit-time cycle report only) | Low: inference, rare borrow errors | Pass | Programmer breaks cycles; exit report helps | ~95% RC ops removed [vendor] |
| Koka/Lean Perceus | Pass | Low for functional style; requires immutable-first design | Pass | Mostly impossible to create with immutable data; mutable refs can cycle | rbtree within 10% of C++ [author] |
| CPython RC + cycle GC | **Fail** (has periodic cycle GC) | n/a | n/a | Collected by the cycle GC | RC tied to GIL; free-threading costs 10–15% |
| Rust Rc/Arc (opt-in) | Pass | High (P-RUST) | Fails G3 (generic wrapper types) | `Weak`, verbose | Rc non-atomic, Arc atomic, compiler-enforced split |

- **Recommended stance for ADR-0001 drafting:**
  - pure RC, no runtime cycle collector (G2-safe);
  - non-atomic default plus an explicit share/send to threads;
  - `weak` as a field/capture keyword;
  - compiler inference for moves/borrows (Lobster/Nim) from the start;
  - Perceus reuse as a later optimization;
  - debug-build cycle/leak report at exit;
  - a G11 DSL design built on value-type view descriptions, so the common UI callback does not create cycles.
- **Open escalation:** whether an opt-in, bounded, local cycle collector (ORC-like) would violate G2. Raise as a `needs-john` issue rather than decide in the ADR.

### Gaps
- No head-to-head benchmark of Swift ARC vs Nim ARC vs Lobster vs Koka on the same OO/UI-style workload was found.
- None of these RC systems publish latency data for large cascading frees.
