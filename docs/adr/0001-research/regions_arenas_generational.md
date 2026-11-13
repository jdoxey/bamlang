# Regions, Arenas, Generational References, Checked-Manual and Handle-Based Memory Management (for ADR-0001)

Scope: generational references (Vale/Valen), region-based memory management (MLKit, Cyclone, Rust-style arenas, Zig/Odin allocators and temp allocators), manual memory with safety tooling (Zig, Odin, C + sanitizers, C++ profiles), handle/index designs (slot maps), and hardware assistance (CHERI, Arm MTE / Apple MIE). Research date: 2026-11-07. Charter goals referenced: G1 (simplicity), G2 (no GC run), G3 (no templates/macros/annotations), G6 (stdlib with growable Lists), G11 (DSL/declarative layout, so closures/callbacks), P-RUST (learning curve), P-C (unsafety).

Convention in this file: "Cited Findings" are sourced facts or sourced opinions (opinion is labelled). "Inferences" are this researcher's analysis. All code is **illustrative, written for this report, not compiled**; APIs are approximate where noted (Zig and Odin standard libraries change between releases).

---

## Q0. What is the state and mechanism of each variant as of November 2026?

### Takeaway
Vale's generational references are a real, measured design, but Vale itself has been stuck at v0.2 (roadmap last dated July 2023). In September–October 2026 its author moved to a new language, "Valen", built on compile-time "group borrowing", with generational references "temporarily disabled". Zig (0.17 docs exist) and Odin (dev-2026-02) are active manual-memory languages. MLKit region inference is still maintained, but it relies on a tracing GC to perform well. CHERI and MTE ship only on niche or mobile hardware.

### Cited Findings
**Vale / generational references (GR)**
- Mechanism (v1, Jan 2021): every allocation has a generation number at its top. Freeing increments it. A generational reference is a pointer plus an 8-byte "target generation". Each dereference compares the two, and a mismatch halts the program. Creating or discarding references costs nothing generation-related. Only dereferencing costs. — [Generational References v1 (verdagon.dev, 2021-01-05)](https://verdagon.dev/blog/generational-references-v1)
- v1 allocator constraints: `genFree` puts the slot on a per-size-class free list (16b, 24b, 32b, ≤48b, ≤64b, ≤128b…) instead of calling `free`. The experimental version "never returns memory to the OS until exit". A slot whose generation can't be incremented further is not reused. — [GR v1](https://verdagon.dev/blog/generational-references-v1)
- Current design (updated 2023-07-09): Vale's default is "random generations". Each object gets a pseudo-random number, which is zeroed on destruction. This works with regular `malloc`, allows stack, embedded and array placement, and lets memory return to the OS. The author gives the chance of an undetected invalid access as 1/2^64 per access. A failed check brings down the whole process. The author also notes a theoretical Spectre + existing-UAF exploitation concern. — [Vale's Memory Safety Strategy: Generational References and Regions (verdagon.dev, updated 2023-07-09)](https://verdagon.dev/blog/generational-references)
- Owning references skip checks. "Linear style" (move ownership in and out) and `pure` functions (immutable region borrowing) remove checks. Vale replaces `unsafe` with a "skip-check dereference" operator, which the compiler ignores in dependencies by default. — [verdagon.dev/blog/generational-references](https://verdagon.dev/blog/generational-references)
- Verbatim Vale examples from that article:
  ```vale
  pure func PrintFuel(ship_ref &Ship) {
    // No __check needed!
    println(ship_ref.fuel);
  }
  func PrintFuel(ship Ship) Ship {
    // No __check needed!
    println(ship.fuel);
    return ship;
  }
  ```
  — [verdagon.dev/blog/generational-references](https://verdagon.dev/blog/generational-references)
- "Hybrid-generational memory" (Jan 2021) is a design, not shipped. It plans generational stacks per size class, static analysis to skip liveness checks, and "scope tethering". The author *expects* it "could be as fast as Rust and almost as fast as C++". That is a projection, not a measurement. — [vale.dev/vision/safety-generational-references](https://vale.dev/vision/safety-generational-references)
- Vale roadmap: "Vale is currently version 0.2, and we're currently working on version 0.3". 0.2 shipped May 2022, and 0.2.2 in early 2023. Planned milestones 0.3 (Summer 2023) through 0.6.1 (Early 2025) cover region borrow checking, the stdlib, structured concurrency, and isolates. The last dated progress entry is 2023-07-11. — [vale.dev/roadmap](https://vale.dev/roadmap)
- On 2026-09-17 Ovadia announced "Valen", a new systems language similar to Vale. Its aim is Rust interop, and it uses "group borrowing" ("purely compile-time memory safety") and has `unsafe` like Rust. In his words, "Generational references are temporarily disabled, hopefully coming back soon." He calls it "extremely experimental", and the Vale compiler was migrated to Rust. — [The Golden Spike, and Resurrecting the Vale(n) Programming Language (verdagon.dev, 2026-09-17)](https://verdagon.dev/blog/golden-spike-reviving-vale-valen)
- Group borrowing (2026-10-11) relaxes shared-xor-mutable to "no use-after-free". The compiler tracks the path each reference points into and invalidates references into an object when it is modified. Multiple read-write references to one list are allowed. Arbitrary graphs and closures are deferred to later posts. Some parts are "not implemented in Valen yet". — [Valen's Memory Safety: A New Kind of Borrow Checking (verdagon.dev, 2026-10-11)](https://verdagon.dev/blog/valen-group-borrowing)
- Secondary (aggregator, lower confidence): Ovadia worked on Modular's Mojo from July 2024 to December 2025, and "no widely deployed language uses the bare generational reference design in production". — [tamnd brain notes: Vale GR](https://tamnd.github.io/brain/research/memory-management/ownership/02_vale_generational_references/)

**Regions**
- MLKit is based on Tofte–Talpin region inference ("Region-Based Memory Management", Inf. & Comp. 1997; "A Region Inference Algorithm", TOPLAS 1998). Since 2002 the MLKit work has combined region inference with tracing GC (PLDI 2002, PADL 2020, JFP 2021, PLDI 2023). The manual was revised for v4.7.16 in December 2025. — [MLKit papers (elsman.com)](https://elsman.com/mlkit/papers)
- Cyclone (PLDI 2002) is a "type-safe programming language derived from C". It has static region typing, region subtyping, and stack allocation integrated with a garbage collector for the heap region. Default annotations plus local inference cut the annotation burden. — [Grossman et al., Region-Based Memory Management in Cyclone](https://www.cs.umd.edu/~mwh/papers/GrossmanMJHWC02.html)

**Zig / Odin**
- Zig docs (master; releases listed up to 0.17.0): "by convention, there is no default allocator in Zig". `ArenaAllocator` "is a great candidate" when allocations in a cyclical pattern can be freed together. `DebugAllocator` is for debug builds, and `smp_allocator` "is a solid choice" in fast mode. — [Zig documentation (master)](https://ziglang.org/documentation/master/)
- Zig 0.14.0 rewrote `GeneralPurposeAllocator` and renamed it `DebugAllocator`. It added `SmpAllocator`, which is "competitive with glibc performance", is designed for ReleaseFast with threads, and is a singleton. The release-notes example uses DebugAllocator in Debug/ReleaseSafe and smp_allocator in ReleaseFast/ReleaseSmall. — [Zig 0.14.0 release notes](https://ziglang.org/download/0.14.0/release-notes.html)
- Odin's implicit `Context` struct holds `allocator`, `temp_allocator`, a logger, and more. `Allocator` is `{procedure, data}`, and its modes include `Free_All`. The default temp allocator is arena-based and is "typically" reset with `free_all(context.temp_allocator)` once per frame loop. — [Odin base:runtime package docs](https://pkg.odin-lang.org/base/runtime/)
- Odin uses manual memory management with no GC. The latest stable release is dev-2026-02 (2026-02-04), and the project is still pre-1.0. — [Wikipedia: Odin](https://en.wikipedia.org/wiki/Odin_(programming_language))

**C++ / hardware**
- C++26 ships a hardened standard library (opt-in, with unstandardized flags), makes uninitialized reads "erroneous behavior", and adds contracts. Profiles did not make C++26 and target C++29 with no promised date. ISO discontinued Safe C++ (P3390) after a vote of 19 for profiles, 9 for Safe C++, and 11 for both. No shipped C++26 feature gives lifetime/UAF guarantees. — [Whole Tomato blog, 2026-07-26 (vendor blog)](https://www.wholetomato.com/blog/c26-memory-safety-what-actually-ships-for-existing-code/)
- CHERI (March 2026 slides) claims "referential, spatial, and temporal memory safety" that is "deterministic and secret-free", with typical memory-protection overhead of "0%-5%". It needs recompilation and gives "strong source-level compatibility". Hardware: Arm Morello (2022 prototype), Microsoft CHERIoT Ibex (MCU, test chips), plus Codasip X730 and CVA6-CHERI cores. The RISC-V "RV64Y" standard is in development. — [Robert Watson, CHERI crash course, CHERI Blossoms 2026](https://cheri-alliance.org/wp-content/uploads/2026/04/D1-0.2-Robert-Watson-CHERI-crash-course-high-level-introduction-CHERI-Blossoms-2026.pdf)
- Apple Memory Integrity Enforcement (Sept 2025, A19/A19 Pro, iPhone 17/Air) combines secure allocators, EMTE in synchronous mode, and Tag Confidentiality Enforcement. It covers the kernel and 70+ userland processes, and it blocks adjacent-overflow and stale-tag (UAF) accesses. Pixel offers MTE as a developer option from Android 13. — [The Hacker News, 2025-09-10](https://thehackernews.com/2025/09/apple-iphone-air-and-iphone-17-feature.html)

### Inferences
- Vale is not a dependable reference implementation to copy in 2026. The mechanism is well documented, but its region borrow checker never shipped as a release, and the author has moved on to a different safety model. Any "Vale proves it works" argument in the ADR should be limited to the measured benchmarks below.
- None of the hardware options can be assumed on the charter's targets (macOS, Windows, Linux desktop/server x86-64 and arm64). MTE/MIE is limited to some phones, and CHERI to prototypes and MCUs. They are a backstop, not a model.

### Gaps
- Carbon's memory-safety design status in 2026 was not researched in this session.
- I couldn't confirm whether Valen's generational references have been re-enabled since 2026-09-17.
- I found no primary source dating Ovadia's Modular tenure (it comes only from an aggregator).

---

## Q1. Which approaches are memory-safe, which detect errors at runtime, and which are unsafe?

### Takeaway
Only static region systems (MLKit, Cyclone, Rust-lifetimed arenas) give compile-time UAF freedom, and MLKit and Cyclone need a GC for some of the heap. Generational references, slot maps and CHERI give **runtime-checked safety**: a stale access becomes a deterministic or probabilistic trap or a `None`, never silent corruption. Zig DebugAllocator, Odin's tracking allocator and ASan are **test-time detectors**. Zig ReleaseFast, Odin and C remain **unsafe** for temporal errors, and Zig is unchecked for stack UAF even in safe modes.

### Cited Findings
- Vale GR is memory-safe "if we always call __check before dereferencing". With random generations, detection is probabilistic: there is a 1/2^64 chance per access of missing an invalid access. A failed check halts the process. — [verdagon.dev/blog/generational-references](https://verdagon.dev/blog/generational-references)
- Slot maps: "Only when the stored version and version in a key match is a key valid." After removal a key stays invalid even if its slot is reused, which avoids the ABA problem of `Vec` indices or `slab`. Versions wrap after 2^31 insert/remove cycles on one slot. A spurious match then becomes possible ("incredibly unlikely"), but behaviour stays memory-safe. — [slotmap 1.1.1 docs](https://docs.rs/slotmap/)
- Zig: "It is the Zig programmer's responsibility to ensure that a pointer is not accessed" after its memory is gone. Dereferencing pointers into a returned stack frame is *unchecked* Illegal Behavior. Safety-checked Illegal Behavior covers bounds, integer overflow, null/error unwrap, bad casts, inactive union fields, alignment and so on, in Debug and ReleaseSafe. "Safety checks are disabled by default in the fast and small optimization modes". — [Zig documentation (master)](https://ziglang.org/documentation/master/)
- Zig GPA (now DebugAllocator) goals: leak detection with allocation stack traces, double-free detection with three stack traces, and UAF detection by keeping freed memory "mapped with no permissions … so that it causes page faults when used". It is POSIX-only and "Not well tested yet" (README of the pre-merge repo, now in std). — [zig-general-purpose-allocator README](https://github.com/andrewrk/zig-general-purpose-allocator/blob/master/README.md)
- Disputed, and from community comments rather than primary docs: in ReleaseSafe the GPA "reuses object addresses in many cases" (so UAF can go undetected), and Zig has "*nothing at all* to detect stack UAF". Another commenter disputes the heap claim. — [LWN comments, 2024-08-31](https://lwn.net/Articles/988006)
- Odin temp allocator: after `free_all(context.temp_allocator)` the next allocation reuses the same address. The temp arena "does **not** auto-free" and grows without bound if never wiped (tutorial page, not official docs). — [Odin lessons: context & allocators](https://odin-lessons.pages.dev/08-context-and-allocators.html)
- AddressSanitizer finds heap/stack/global out-of-bounds and use-after-free bugs, with an "average slowdown … just 73%". — [Serebryany et al., USENIX ATC 2012](https://research.google/pubs/addresssanitizer-a-fast-address-sanity-checker/)
- Cyclone uses a static typing discipline for regions and is type-safe. — [Grossman et al. PLDI 2002](https://www.cs.umd.edu/~mwh/papers/GrossmanMJHWC02.html)
- CHERI protection is described as deterministic. — [Watson 2026](https://cheri-alliance.org/wp-content/uploads/2026/04/D1-0.2-Robert-Watson-CHERI-crash-course-high-level-introduction-CHERI-Blossoms-2026.pdf)
- C++26 offers no lifetime/UAF guarantee, and lifetime profiles are deferred to C++29. — [Whole Tomato 2026](https://www.wholetomato.com/blog/c26-memory-safety-what-actually-ships-for-existing-code/)

### Inferences
Classification table (researcher's synthesis of the sources above):

| Approach | UAF / dangling | Leaks | Classification |
|---|---|---|---|
| MLKit region inference (+GC) | Statically prevented | GC needed to bound space | Safe (but G2 violated by the GC) |
| Cyclone regions | Statically prevented for region pointers; heap region GC'd | GC | Safe (GC for the heap) |
| Rust arena (`bumpalo`/`typed-arena`) | Statically prevented by lifetimes | Arena memory retained until drop | Safe, at the P-RUST cost |
| Vale GR (incrementing gens) | Deterministic runtime trap | Owner-scoped free (RAII) | Runtime-checked safe |
| Vale GR (random gens, default) | Probabilistic trap, 1/2^64 miss per access | RAII | Runtime-checked, probabilistic |
| Valen group borrowing | Claimed compile-time, unbenchmarked, partly unimplemented | n/a | Unproven |
| Slot map / generational handles | Stale handle gives "invalid"/None, memory-safe; 2^31-wrap spurious hit possible | Never shrinks (SlotMap) | Safe *within the store*; logic errors possible |
| Zig Debug/ReleaseSafe + DebugAllocator | Heap UAF often caught (page-protected); stack UAF unchecked | Leak report at deinit | Detect-at-test-time |
| Zig ReleaseFast/Small | Unchecked | None | Unsafe |
| Odin (+ Tracking_Allocator in dev) | Unchecked (bounds checks exist, see Gaps) | Tracking allocator reports | Unsafe, with leak tooling |
| C + ASan/Valgrind | Detected in instrumented test runs only | LSan | Unsafe in production |
| C++26 | Bounds hardening opt-in; no lifetime safety | — | Unsafe |
| CHERI | Deterministic (with revocation support) | — | Safe on CHERI hardware only |
| MTE/EMTE | Tag-mismatch trap | — | Probabilistic; mobile only |

- P-C ("C is unsafe — safety matters") is not met by any of the "checked-manual" options unless the checks run in production. Zig ReleaseSafe plus DebugAllocator is the closest, but production allocators are recommended for speed, and stack UAF stays open.
- A slot map converts memory-safety bugs into logic bugs (a stale handle returns "missing"). That is strictly better than C, but it is not a guarantee that the right object is referenced.

### Gaps
- I didn't fetch the official Odin docs on bounds checking or `#no_bounds_check`. The exact Odin runtime checks are not verified here.
- MTE tag width and the probabilistic detection rate (commonly cited as 4-bit tags, about 1/16 miss) were not verified from a primary source this session.
- I didn't verify whether Zig's current DebugAllocator (0.14+) still never reuses freed slots. The README describes the pre-merge GPA, and the LWN claims are disputed.

---

## Q2. What is the measured runtime overhead, and how predictable are latency and fragmentation?

### Takeaway
The only primary GR numbers are **+10.84% vs unsafe (BenchmarkRL, 2021, naive GR without regions)** and **"no observable overhead" (2023, a single cellular-automata benchmark, regions + linear style, compared against Vale's own bounds-checked unsafe mode)**. The "2.3% overhead" figure in the brief **could not be verified**. The closest primary text is "2.3x faster than reference counting, unoptimized!", which is a multiplier against RC, not a percentage overhead. Arenas and regions give the fastest allocation but can waste a lot of memory: MLKit region-only runs used up to about 100× the memory of region+GC on some benchmarks.

### Cited Findings
- BenchmarkRL terrain generator (2021): Unsafe 43.82 s; naive RC 54.90 s (+25.29%); GR 48.57 s (+10.84%). Heap-only, no regions or static analysis, compared only against other Vale modes. — [GR v1](https://verdagon.dev/blog/generational-references-v1); repeated in [GR current article](https://verdagon.dev/blog/generational-references), which has **no "2.3%" figure**.
- "2.3x faster than reference counting, unoptimized!" — [vale.dev/vision/safety-generational-references (2021-01-05)](https://vale.dev/vision/safety-generational-references). **Conflict:** the BenchmarkRL table implies GR is only about 1.13× faster than RC (54.90/48.57). The two numbers presumably come from different benchmarks or builds, and the vision page gives no benchmark details.
- Regions prototype (2023-07-11), CellularAutomata.vale measured with hyperfine: unsafe-no-bounds was "1.18 ± 0.01 times faster" than *both* unsafe-with-bounds and safe_fastest. The author concludes "this approach has no observable overhead" beyond bounds checks. Caveats he gives: comparison only against Vale's own modes, results on larger programs "seemed rather fragile", LLVM missed obvious optimizations and a Vale-specific pre-optimizer "may be needed", all structs still on the heap, and the prototype had verbose errors and firing assertions. — [Vale's First Prototype for Immutable Region Borrowing](https://verdagon.dev/blog/first-regions-prototype)
- Aggregator summary "2–10.84% overhead depending on access patterns" (secondary, no primary link for the 2% end). — [tamnd notes](https://tamnd.github.io/brain/research/memory-management/ownership/02_vale_generational_references/)
- Ovadia (opinion): zero-overhead memory safety "doesn't actually exist, and never has". He measured bounds checking at 18% in his cellular automata program and 74% in an interpreter, and cites an external 1–15% figure for safe Rust. Rust workarounds (indices, arenas) cost "more cloning, bounds checking, and hashing", but that last point is not quantified. — [Chasing the Myth of Zero-Overhead Memory Safety (2023-06-19)](https://verdagon.dev/blog/myth-zero-overhead-memory-safety)
- Memory cost of GR: 8 bytes per allocation plus 8 bytes per non-owning reference (fat pointer). — [GR v1](https://verdagon.dev/blog/generational-references-v1); [verdagon GR](https://verdagon.dev/blog/generational-references)
- Valen group borrowing: "I still have to implement it to benchmark it, so take it with a grain of salt." — [Golden Spike post](https://verdagon.dev/blog/golden-spike-reviving-vale-valen)
- MLKit (JFP 2021, Fig. 15): a non-region-friendly mergesort under regions-only took 0.46 s and 410 MB, against 1.14 s and 139 MB with regions + generational GC. Region-friendly mergesort under regions-only took 0.44 s and 103 MB (best). Region-only used far more memory elsewhere: barnes-hut 185 MB vs 2.3 MB, logic 277 MB vs 2.5 MB, nucleic 266 MB vs 2.6 MB. The authors conclude that "in general, a combination with reference-tracing garbage collection is necessary to make region inference perform well in practice", and they note fragmentation overhead with generational GC. — [Elsman & Hallenberg, JFP 2021](https://www.cambridge.org/core/services/aop-cambridge-core/content/view/782D317A9B811CD99FA0E924A35B6A58/S0956796821000010a.pdf/integrating_region_memory_management_and_tagfree_generational_garbage_collection.pdf)
- Zig DebugAllocator rewrite: `zig ast-check` wall time went from about 22.8 s to 20.5 s and peak RSS fell 6.2%. SmpAllocator matched glibc malloc (12.2 s) with about 3.9% fewer instructions when building the Zig compiler. — [Zig 0.14.0 release notes](https://ziglang.org/download/0.14.0/release-notes.html)
- ASan average slowdown is 73%. — [USENIX ATC 2012](https://research.google/pubs/addresssanitizer-a-fast-address-sanity-checker/)
- CHERI memory protection costs "0%-5%", with some pointer-dense workloads higher. — [Watson 2026](https://cheri-alliance.org/wp-content/uploads/2026/04/D1-0.2-Robert-Watson-CHERI-crash-course-high-level-introduction-CHERI-Blossoms-2026.pdf)
- Slot map memory: SlotMap costs 4 + max(sizeof(T),4) bytes per slot, never shrinks, and iteration may pass many empty slots. HopSlotMap (deprecated) iterates faster but inserts and removes about 2× slower. DenseSlotMap needs two indirections for access but iterates at Vec speed. — [slotmap docs](https://docs.rs/slotmap/)

### Inferences
- **Predictability:** all of these models avoid GC pauses (G2). GR adds a branch per non-owning dereference, which is predictable but not free in tight loops. Arena reset is O(1) (the Odin page shows `free_all` as a cursor reset). The worst case is memory, not time: regions and arenas hold dead data until reset, and the MLKit numbers show this can run to orders of magnitude for programs not written in a region-friendly style.
- **Fragmentation:** GR v1's per-size-class free lists that never return memory to the OS fragment by design. Random generations fix this by working with ordinary malloc. Slot maps never shrink. Arenas don't fragment internally but keep peak memory alive.
- The ADR should not quote "2.3% overhead". The defensible range is "about 11% for naive GR on one benchmark (2021). One 2023 benchmark showed no overhead beyond bounds checks after region and linear-style annotations, with the author calling larger-program results fragile."

### Gaps
- There are no independent (non-author) benchmarks of generational references. The Cal Poly thesis (2021, DOI 10.15368/theses.2021.99) appeared in search results ([digitalcommons.calpoly.edu/theses/2348](https://digitalcommons.calpoly.edu/theses/2348)) but was not read.
- There are no measurements of GR against C or Rust directly. The author explicitly deferred these.
- I didn't fetch any measured overhead for Zig ReleaseSafe or Odin bounds checks.

---

## Q3. How much must the programmer think about allocators and regions, and how learnable is each?

### Takeaway
There is a spectrum. GR as a default (Vale-style) asks the least: write single-ownership code, and `&` references are checked automatically, with regions and `pure` as opt-in optimizations. Handles ask for a moderate "store + ID" discipline. Odin's implicit context allocator is low-friction but hides allocation. Zig's explicit allocator parameters are maximally visible but add noise to every allocating API. Static region systems (Cyclone, Rust arena lifetimes) need annotations, which strains G3 and P-RUST.

### Cited Findings
- Vale region borrowing is opt-in: developers apply it only to code they want to optimize. — [first-regions-prototype](https://verdagon.dev/blog/first-regions-prototype)
- Ovadia suggests starting with GR, then adding regions and linear style where profiling justifies it, noting that the stdlib already uses these techniques. — [verdagon GR](https://verdagon.dev/blog/generational-references)
- The regions prototype produced "very verbose" compile errors. — [first-regions-prototype](https://verdagon.dev/blog/first-regions-prototype)
- Cyclone: porting legacy C meant changing about 8% of the code, with about 6% of total code being region annotations. — [Grossman et al. 2002](https://www.cs.umd.edu/~mwh/papers/GrossmanMJHWC02.html)
- MLKit: good space behaviour from regions alone depends on region-friendly code (for example copying list tails so intermediates land in local regions). Region inference "does not always capture object lifetimes precisely". — [JFP 2021](https://www.cambridge.org/core/services/aop-cambridge-core/content/view/782D317A9B811CD99FA0E924A35B6A58/S0956796821000010a.pdf/integrating_region_memory_management_and_tagfree_generational_garbage_collection.pdf)
- Zig: there is no default allocator by convention, so allocators are passed explicitly. — [Zig docs](https://ziglang.org/documentation/master/)
- Odin: implicit `context.allocator` reads can hide allocation, so a reader "can't tell it allocates, or from where" from the signature alone. An explicit allocator argument overrides the context. — [Odin lessons page (non-official)](https://odin-lessons.pages.dev/08-context-and-allocators.html)
- Zig has no simple closures because they need allocation, which conflicts with its "no hidden allocation" policy. — [openmymind: Closures in Zig (2024-09-10)](https://www.openmymind.net/Closures-in-Zig/)
- Valen argues (opinion, not measured) that it is simpler than Rust for patterns where Rust must re-fetch `&mut` or use GhostCell. — [Valen group borrowing](https://verdagon.dev/blog/valen-group-borrowing)

### Inferences
- **G1/P-RUST fit ranking (researcher's judgement):** (1) GR-by-default with ownership/RAII, then (2) handles for graph-shaped data, then (3) Odin-style context allocator, then (4) Zig explicit allocators, then (5) annotated regions/lifetimes. Annotated regions in the Cyclone `` `r `` or Rust `'a` style look like the type parameters G3 bans, so they would arguably conflict with G3.
- The learnability cost of GR is mostly *conceptual*. Programmers must know owning vs non-owning references, and that a non-owning reference may trap. That is close to Swift/ObjC "strong vs weak" and C++ `unique_ptr` plus raw pointer, which is a familiar mental model.
- Zig's explicit-allocator style adds an allocator parameter to every growable `List` operation. In Zig 0.15+ the default `ArrayList` is "unmanaged": you pass the allocator to `append`/`deinit` (background knowledge, not verified this session). That is visible noise against G4 (clean syntax) and G1.

### Gaps
- I found no learnability studies (user studies or teaching data) for Vale, Zig or Odin memory models.

---

## Q4. How do graphs, parent pointers, shared caches, callbacks, large mutable lists and threads look in each? (code scenarios a–f)

### Takeaway
Arenas and explicit allocators make (a) easy and (b) easy *only if the whole structure dies together*. Dangling remains unchecked for (c) callbacks and (e) "slice held across append". GR handles (b)–(e) with ordinary pointer-shaped code and turns misuse into a trap. Handles handle (b)/(d)/(f) well but make (c) awkward, because the closure needs access to the store. No variant here has a *shipped*, safe, simple threading story except Rust-with-arenas, which pays the P-RUST cost.

### Cited Findings
- Zig closures: the pattern is a `{ptr: *anyopaque, runFn: *const fn(*anyopaque) void}` struct, with captured state heap-allocated through an allocator. — [openmymind 2024](https://www.openmymind.net/Closures-in-Zig/)
  ```zig
  const Runnable = struct {
      ptr: *anyopaque,
      runFn: *const fn(ptr: *anyopaque) void,
  };
  ```
- Odin: a `proc "c"` callback has no context, so it must set `context = runtime.default_context()` before allocating. Allocating without a context is a compile error. — [Odin lessons page](https://odin-lessons.pages.dev/08-context-and-allocators.html)
- Valen allows two mutable references to the same list. Verbatim:
  ```valen
  let ref_a = &list;
  let ref_b = &list;
  ref_a.push(42);
  ref_b.push(73);
  ```
  Graphs and closures are not yet covered, and "closures don't yet support group borrowing". — [Valen group borrowing](https://verdagon.dev/blog/valen-group-borrowing); [Golden Spike](https://verdagon.dev/blog/golden-spike-reviving-vale-valen)
- Slot maps suit "objects that need stable references but have no other clear owner, such as game entities or graph nodes". `SecondaryMap` attaches extra data per key. — [slotmap docs](https://docs.rs/slotmap/)
- Vale concurrency (structured concurrency, isolates, threads, mutexes) is listed on the roadmap for versions never released (0.4.1/0.6). — [vale.dev/roadmap](https://vale.dev/roadmap)
- The GPA/DebugAllocator has a compile-time thread-safety option. — [GPA README](https://github.com/andrewrk/zig-general-purpose-allocator/blob/master/README.md)
- Zig: pointers into a returned function's stack frame are invalid, and dereferencing them is unchecked. — [Zig docs](https://ziglang.org/documentation/master/)

### Inferences — illustrative code (not compiled; APIs approximate)

#### (a) Read a file of unknown length into a list of lines
**Zig (approx. 0.15 API):** the arena makes ownership trivial. Without it, `lines` would alias `data`, which is a dangling hazard.
```zig
fn readLines(a: std.mem.Allocator, path: []const u8) !std.ArrayList([]const u8) {
    const data = try std.fs.cwd().readFileAlloc(a, path, std.math.maxInt(usize));
    var lines: std.ArrayList([]const u8) = .empty;
    var it = std.mem.splitScalar(u8, data, '\n');
    while (it.next()) |line| try lines.append(a, line); // slices point INTO data
    return lines;
}
pub fn main() !void {
    var dbg: std.heap.DebugAllocator(.{}) = .init;
    defer _ = dbg.deinit();                       // leak report in Debug/ReleaseSafe
    var arena = std.heap.ArenaAllocator.init(dbg.allocator());
    defer arena.deinit();                         // frees buffer + list together
    const lines = try readLines(arena.allocator(), "input.txt");
    std.debug.print("{d}\n", .{lines.items.len});
}
```
Benefit: zero per-line frees, and leaks are reported. Pain: an allocator is threaded through every call, and `try` appears on every append.

**Odin (approx.; `core:os` API changed in 2025–26):**
```odin
read_lines :: proc(path: string, allocator := context.allocator) -> []string {
    data, ok := os.read_entire_file(path, allocator)
    if !ok do return nil
    lines, _ := strings.split_lines(string(data), allocator) // aliases data
    return lines
}
main :: proc() {
    lines := read_lines("input.txt", context.temp_allocator)
    defer free_all(context.temp_allocator)
    fmt.println(len(lines))
}
```
Benefit: very little ceremony. Pain: any `lines` kept past `free_all` dangle silently, because the address is reused.

**C:**
```c
char **read_lines(const char *path, size_t *n) {
    FILE *f = fopen(path, "r"); if (!f) return NULL;
    char **v = NULL, *line = NULL; size_t cap = 0, len = 0; *n = 0;
    while (getline(&line, &len, f) != -1) {          // POSIX only; not MSVC
        if (*n == cap) { cap = cap ? cap * 2 : 16; v = realloc(v, cap * sizeof *v); } // unchecked
        v[(*n)++] = strdup(line);
    }
    free(line); fclose(f); return v;                 // caller frees each line and v
}
```

**Rust + bumpalo arena:**
```rust
fn read_lines<'a>(arena: &'a bumpalo::Bump, path: &str) -> std::io::Result<Vec<&'a str>> {
    let text: &'a str = arena.alloc_str(&std::fs::read_to_string(path)?);
    Ok(text.lines().collect())   // 'a ties every line to the arena; compiler-checked
}
```
Benefit: compile-time safe. Pain: the lifetime parameter `'a` appears in the signature (P-RUST, and arguably G3).

**Vale (syntax approximate):**
```vale
func readLines(path str) List<str> {
  contents = readFileAsString(path);  // stdlib name approximate
  return contents.split("\n");        // owned list; freed when owner's scope ends; no gen checks
}
```

#### (b) Tree with parent pointers
**Vale (approx.):** the owning `children` and non-owning checked `parent` match the natural model.
```vale
struct Node {
  name str;
  parent ?&Node;          // non-owning: generation-checked on deref
  children List<Node>;    // owning
}
// Deref of parent after the parent is destroyed -> deterministic halt, not UAF.
```

**Zig (arena):**
```zig
const Node = struct { name: []const u8, parent: ?*Node, children: std.ArrayList(*Node) = .empty };
fn addChild(a: std.mem.Allocator, p: *Node, name: []const u8) !*Node {
    const n = try a.create(Node);
    n.* = .{ .name = name, .parent = p };
    try p.children.append(a, n);
    return n;
}
// Freeing one subtree is impossible with an arena (it leaks until reset); with a general
// allocator, a.destroy(n) leaves p.children / child.parent dangling, unchecked in ReleaseFast.
```

**Rust + typed_arena:** safe, but needs interior mutability plus lifetimes.
```rust
struct Node<'a> {
    name: String,
    parent: Cell<Option<&'a Node<'a>>>,
    children: RefCell<Vec<&'a Node<'a>>>,
}
let arena = typed_arena::Arena::new();
let root = arena.alloc(Node { name: "root".into(), parent: Cell::new(None), children: RefCell::new(vec![]) });
let kid  = arena.alloc(Node { name: "kid".into(),  parent: Cell::new(Some(root)), children: RefCell::new(vec![]) });
root.children.borrow_mut().push(kid);
```

**Handles (Rust slotmap):**
```rust
new_key_type! { struct NodeId; }
struct Node { name: String, parent: Option<NodeId>, children: Vec<NodeId> }
let mut tree: SlotMap<NodeId, Node> = SlotMap::with_key();
let root = tree.insert(Node { name: "root".into(), parent: None, children: vec![] });
let kid  = tree.insert(Node { name: "kid".into(), parent: Some(root), children: vec![] });
tree[root].children.push(kid);
tree.remove(root);
assert!(tree.get(tree[kid].parent.unwrap()).is_none()); // stale handle -> None, no UAF
```
Pain: every access goes through `tree`, and `tree[x]` panics on a stale key while `get` returns Option.

**C:** plain `struct Node *parent;`. ASan catches UAF only in instrumented test runs.

#### (c) UI callback capturing enclosing state (button onTap calls save()) — the key G11 scenario
**Vale (approx. lambda syntax):**
```vale
button.onTap = { doc.save(); };  // captures &Document (non-owning); if doc is gone when tapped -> halt
```
Benefit: it reads like Swift or Kotlin, and a lifetime bug becomes a loud trap.

**Zig:** no closures, so you hand-roll a context pointer.
```zig
const Button = struct {
    ctx: *anyopaque,
    onTap: *const fn (ctx: *anyopaque) void,
    fn tap(self: Button) void { self.onTap(self.ctx); }
};
const Editor = struct {
    doc: Document,
    fn onSave(ctx: *anyopaque) void {
        const self: *Editor = @ptrCast(@alignCast(ctx));
        self.doc.save();
    }
};
var editor = Editor{ .doc = loadDoc() };
const btn = Button{ .ctx = &editor, .onTap = Editor.onSave }; // if editor dies first: dangling, unchecked
```
Pain: verbose type erasure and unchecked casts. That is hostile to declarative layout DSLs (G11).

**C:** `void (*on_tap)(void *user); void *user;`, the same as Zig with fewer checks.

**Rust:** `Box<dyn Fn() + 'a>` borrowing `&'a RefCell<Document>`, or more commonly `Rc<RefCell<Document>>` (RC, not an arena). An arena alone forces the doc to outlive every button.

**Handles:**
```text
button.onTap = { if let doc = docs.get(docId) { doc.save() } }  // pseudocode
```
The closure needs `docs` (a global, context, or captured store reference), so the store becomes the shared-state problem again.

#### (d) Shared mutable cache used by two components
- **Vale:** the app owns `Cache`, and both components hold `&Cache`, which is checked on use. Valen's group borrowing explicitly permits multiple mutable references (see the verbatim example above).
- **Zig/Odin/C:** both hold `*Cache` / `^Cache`. Aliasing is unrestricted and the lifetime is manual. Simple, unchecked.
- **Rust arena:** `struct A<'a> { cache: &'a RefCell<Cache> }` in both. Mutable sharing needs `RefCell` (runtime borrow panics), plus lifetime parameters on both component types.
- **Handles:** components hold `CacheId`. Mutation goes through the store, which also needs to be shared.

#### (e) Pass a large list to a function that mutates it
**Zig, the classic hazard:**
```zig
fn normalize(gpa: std.mem.Allocator, list: *std.ArrayList(f64)) !void {
    const first = &list.items[0];
    try list.append(gpa, 0);   // may realloc
    first.* = 1.0;             // dangling write: unchecked even in ReleaseSafe (no bounds violation)
}
```
- **Vale:** `func normalize(list &List<float>)`. This is a non-owning mutable reference, checked on access. The Vale docs I read don't say whether element pointers held across growth are protected (see Gaps).
- **Rust arena:** `fn normalize(v: &mut bumpalo::collections::Vec<'_, f64>)`. The borrow checker rejects the hazard above at compile time.
- **Odin:** `normalize :: proc(list: ^[dynamic]f64)`. The dynamic array carries its own allocator (background knowledge, not verified this session), and the same dangling-element hazard as Zig applies.

#### (f) Share data between threads
- **Zig:** `std.Thread.spawn(.{}, worker, .{&shared})` plus `std.Thread.Mutex`. The language has no data-race prevention, and allocator thread-safety varies per allocator (DebugAllocator has a thread-safe option).
- **C:** pthreads/Win32 plus a mutex. TSan works only in test builds.
- **Rust arena:** `bumpalo::Bump` is not `Sync` (background knowledge), so arenas are usually per-thread. Sharing uses `Arc<Mutex<T>>` or `std::thread::scope`. Safe, but it pays the P-RUST cost.
- **Vale:** no shipped threading model. Generation counters are non-atomic (the author noted the theoretical counter overhead in the regions post), and isolates and structured concurrency were never released.
- **Handles:** IDs are plain integers and trivially sendable, but the store needs a lock or per-thread ownership.

### Gaps
- I didn't confirm Vale's closure and lambda syntax, or how Vale handles references into a growing `List` (whether element references are generation-checked).
- I couldn't verify from a primary source that Odin lacks capturing closures. Search didn't surface Odin docs on this.
- The `bumpalo`/`typed_arena` APIs and `Sync` status were not fetched this session (background knowledge).

---

## Q5. Should these be the primary model or a complementary stdlib facility?

### Takeaway
The evidence favours **arenas and handle stores as complementary stdlib facilities** rather than the primary model. MLKit's 25 years of results show regions alone leak space without a GC (which G2 forbids), and arenas can't free individual objects. **Single ownership + generational-checked non-owning references** is the only candidate here that works as a *primary* model meeting G1 + G2 + "safety matters" without a borrow checker. Its weak points are unverified independent performance, no shipped threading story, and 16-byte non-owning references.

### Cited Findings
- Region inference alone: "in general, a combination with reference-tracing garbage collection is necessary to make region inference perform well in practice." — [JFP 2021](https://www.cambridge.org/core/services/aop-cambridge-core/content/view/782D317A9B811CD99FA0E924A35B6A58/S0956796821000010a.pdf/integrating_region_memory_management_and_tagfree_generational_garbage_collection.pdf)
- Zig itself frames `ArenaAllocator` as a choice for "cyclical patterns" where allocations are freed together, alongside a general-purpose allocator. — [Zig docs](https://ziglang.org/documentation/master/)
- Odin's temp allocator is a per-frame arena next to the main allocator. — [Odin runtime docs](https://pkg.odin-lang.org/base/runtime/)
- Vale layers optional regions and linear style on top of default GR. — [verdagon GR](https://verdagon.dev/blog/generational-references)
- Slot maps target entities and graph nodes with "no other clear owner". — [slotmap docs](https://docs.rs/slotmap/)

### Inferences
- A candidate architecture for the ADR to score: single ownership (RAII, no RC by default) for the common case; generational-checked non-owning references (`&T`) for parent pointers, callbacks and caches; a stdlib `Arena` for compilers, parsers and per-request work; and a stdlib `Handles`/slot-map store for graphs and ECS-like data. Then score each piece against G1 (number of concepts: owner, reference, optionally arena/handle).
- **G3 tension (important):** a generic `SlotMap<T>`, `Arena<T>` or `List<T>` normally needs templated types, which G3 forbids. To satisfy G3 and G6, these must be **compiler-built-in parameterised types** (like Go's pre-1.18 `[]T`/`map[K]V`), not user-definable generics. That makes the set of built-in containers a language-design decision in this ADR, or a dependency on a separate ADR.
- **G11:** declarative UI needs capturing closures stored beyond the creating scope. Explicit-allocator languages (Zig) refuse to hide the closure allocation and have no closures. GR lets closures capture non-owning references with checked use. That is the strongest argument for GR as primary.
- Hardware options (CHERI/MTE) should be at most a "use when available" hardening note.

### Gaps
- I found no production language that uses GR as its primary model, so there is no field evidence on large codebases. That claim comes from an aggregator and is unverified.

---

## Q6. How complex is each to implement for a small team or an autonomous agent on LLVM?

### Takeaway
Explicit allocators, arenas and slot maps are almost entirely library work and cheap to build. Basic generational references are a moderate compiler and runtime change: an object header, fat references, check insertion at dereference, and an allocator policy. The *optimizations* that make GR fast (region borrow checking, pure-function immutability) consumed years of a skilled designer's effort without a shipped release. Region *inference* (MLKit) is research-grade and still needs a GC. Static lifetime checking at Rust or Cyclone level is the most expensive option.

### Cited Findings
- The Vale regions prototype hit LLVM missing obvious optimizations, and the author said a Vale-specific pre-optimizer "may be needed". It had verbose compile errors, firing compiler assertions and tech debt, and was described as a prototype in July 2023. — [first-regions-prototype](https://verdagon.dev/blog/first-regions-prototype)
- Vale's roadmap milestones from Summer 2023 onward (0.3 to 0.6.1) were never marked released. — [vale.dev/roadmap](https://vale.dev/roadmap)
- The Valen re-architecture "took most of 2026", the rustc patches are "not upstreamable", and Ovadia says it needs "a glorious few months of cleaning, rewriting, and solidifying". — [Golden Spike](https://verdagon.dev/blog/golden-spike-reviving-vale-valen)
- Random generations work with regular `malloc`, while incrementing generations need a custom size-class allocator. — [verdagon GR](https://verdagon.dev/blog/generational-references); [GR v1](https://verdagon.dev/blog/generational-references-v1)
- ASan's design "is simple enough to be implemented in any compiler", and it is available in LLVM/Clang. — [ASan paper](https://research.google/pubs/addresssanitizer-a-fast-address-sanity-checker/)
- The Zig allocator interface and the Odin `Allocator {procedure, data}` pattern are plain library-level abstractions. — [Zig docs](https://ziglang.org/documentation/master/); [Odin runtime](https://pkg.odin-lang.org/base/runtime/)

### Inferences
- **Effort ranking for an LLVM front end (researcher's estimate):**
  1. Explicit or context allocators plus arena: low (library work plus a calling convention).
  2. Slot-map/handle store: low, if containers are compiler built-ins (see the G3 note).
  3. Basic GR (random generations, check on every non-owning dereference, owning references unchecked): moderate. It needs a header word per allocation, 16-byte references, a check-and-trap sequence, and correct handling of inline or embedded structs. Vale itself had not finished inline data.
  4. GR check elision through `pure`/region borrowing: high, as Vale's history shows.
  5. Region inference or a full lifetime borrow checker: very high.
- A practical path for an agent-built compiler: ship basic GR plus RAII (correct, about 11% worst-case on the one known benchmark), then rely on LLVM's redundancy elimination plus simple intra-procedural elision. Defer region borrowing. Debug builds could add an ASan-style mode cheaply via LLVM sanitizer passes.
- Interop risk: GR fat references and object headers complicate C FFI (Vale built "Fearless FFI" for this; that post was listed but not read). If the stdlib wraps C APIs for Time/Calendar (G6), the FFI boundary needs design.

### Gaps
- I found no public estimate (lines of code or person-months) of the effort to implement GR in a compiler.
- I didn't read the Vale "Fearless FFI" post ([verdagon.dev/blog/fearless-ffi](https://verdagon.dev/blog/fearless-ffi)), so the FFI implications are inferred, not sourced.
