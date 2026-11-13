# Cross-cutting constraints on the memory-management model (ADR-0001)

Scope: criteria that hold whichever model is chosen (ARC, mutable value semantics/CoW, ownership/borrowing, regions/arenas/generational references, hybrids). Charter goals referenced: G1 simplicity, G2 no GC run, G3 no templates/macros/annotations, G8 debugging, G9 coverage, G11 DSLs; problems P-SWIFT, P-RUST, P-GO, P-JAVA. Research date: 2026-11-07. Several web pages (clang.llvm.org sanitizer docs, developer.android.com, gleam.run) were blocked by the fetch allowlist this session; claims that depend on them are marked as gaps or as unverified background knowledge.

---

## 1. Concurrency: how each model family interacts with threads, and what must be decided now

### Takeaway
The memory model fixes the object header and the cost of every reference-count operation. Atomic vs non-atomic vs "biased/flagged" RC is an ABI-level decision that ADR-0001 must make now. Swift shows the cost of adding data-race safety after the fact: years of migration pain, then a retreat to "MainActor by default". Rust and Inko show that "can this cross a thread?" can be inferred structurally from the type, or made a property of uniqueness, with no annotations. That fits G3.

### Cited Findings
- **Atomic RC is a measurable tax.** Perceus (Koka) measured atomic RC slowdowns "from 5% (rbtree) up to 59% (nqueens)" across its benchmarks. — [Reinking, Xie, de Moura, Leijen, Perceus TR](https://microsoft.com/en-us/research/uploads/prod/2020/11/perceus-tr-v4.pdf)
- **Perceus avoids atomics unless needed.** "All objects start out as unshared, and are only marked through explicit operations"; dup/drop avoid "atomic operations in the fast path by checking the thread-shared flag." — [Perceus TR](https://microsoft.com/en-us/research/uploads/prod/2020/11/perceus-tr-v4.pdf)
- **Biased reference counting (Choi, Shull, Torrellas, PACT 2018)** starts from the observation that "most objects are only accessed by a single thread". It makes RC operations "more than twice faster in the common case", reduces average execution time of Swift client programs by 22.5%, and raises server throughput by 7.3%. — [BRC paper / thesis](https://core.ac.uk/download/186334775.pdf)
- **Swift's atomic-ARC cost is anecdotal in the forums.** One user's M1 chess benchmark ran struct versions faster than class versions, "quite possibly due to ARC overhead". The author calls it "Not the most direct benchmark". This is opinion plus a weak measurement, not an official Swift team figure. — [Swift Forums, June 2023](https://forums.swift.org/t/pitch-core-team-publishes-results-of-performance-study-cooperative-scheduler-just-introduced-plus-compile-for-non-atomic-arc/65632/21)
- **Nim exposes the choice as separate modes.** ARC (non-atomic, shared heap, cycles leak), atomicArc ("Thread-safe ARC variant that pays for atomic instructions"), ORC (default, cycle collector, non-atomic), and YRC, listed in the docs as an experimental thread-safe ORC with a concurrent cycle collector. The docs also say: "On an embedded device the atomics would probably only hurt." — [Nim memory management docs](https://nim-lang.org/docs/mm.html)
- **Roc was still unsettled in late 2023.** In Roc's Zulip, Richard Feldman wrote "We might just want to always atomically refcount", possibly with a platform opt-out, and floated escape analysis to skip atomics. Brendan Hansknecht observed "Most of the time was just in the atomic read/write". No final decision appears in the thread. — [Roc Zulip, Sep–Nov 2023](https://roc-lang.github.io/zulip-export/stream/304641-ideas/topic/atomic.20refcounting.20and.20branch.20misprediction.html)
- **Rust Send/Sync are structural and inferred.** "A type is Send if it is safe to send it to another thread"; "A type is Sync if it is safe to share between threads (&T is Send)". They "are also automatically derived traits". "`Rc` isn't Send or Sync (because the refcount is shared and unsynchronized)." — [Rustonomicon](https://rust.googlesource.com/rust-lang/nomicon/+/refs/heads/drop/src/send-and-sync.md)
- **Swift's timeline:** Swift 5.7 introduced `Sendable`. Swift 5.10 (5 March 2024) "accomplishes full data isolation" under `-strict-concurrency=complete`, and added the escape hatch `nonisolated(unsafe)`. — [Swift 5.10 release blog](https://www.swift.org/blog/swift-5.10-released)
- **Swift's own vision document admits the pain.** The Language Steering Group's "Improving the approachability of data-race safety" (thread opened 26 Nov 2024) concedes that "it can be hard to make single-threaded programs". Commenters say the "progressive disclosure was, in part, neglected" and that "Swift Concurrency safety in its current form does not allow me to write a single-threaded module." These are community opinions, quoted in-thread. — [Swift Forums vision thread](https://forums.swift.org/t/prospective-vision-improving-the-approachability-of-data-race-safety/76183)
- **The remedy was a module-level default flip.** SE-0466 (Swift 6.2) lets a module set `.defaultIsolation(MainActor.self)`. Matt Massicotte calls the result a "language dialect": whether `var global = 42` compiles depends on a build setting that isn't in the source. He also argues that "For many Swift projects, `nonisolated` just isn't a great default." — [massicotte.org, 12 May 2025](https://www.massicotte.org/default-isolation-swift-6_2)
- **Inko uses uniqueness instead of a Send trait.** `recover` produces a unique (`uni`) value, used for sending between processes, "as a value being unique ensures no borrows to the data exist, and thus no race conditions can occur." — [Inko manual](https://docs.inko-lang.org/manual/latest/getting-started/memory-management)
- **Inko's runtime design:** messages "transfer ownership instead of deep-copying data", each OS thread gets its own heap, and references, closures and generators cannot be sent between processes. — [Yorick Peterse, "Friendship ended with the garbage collector"](https://yorickpeterse.com/articles/friendship-ended-with-the-garbage-collector)
- **MVS and immutability give race freedom by construction.** Mutable value semantics "bans sharing instead of mutation". References are second-class and "cannot be stored in variables or object fields. Hence, variables can never share mutable state." — [Racordon et al., "Native Implementation of Mutable Value Semantics"](https://arxiv.org/abs/2106.12678). Roc: "A reliability benefit of semantic immutability is that it rules out data races." — [roc-lang.org/functional](https://roc-lang.org/functional)

### Inferences
- **How each family interacts with threads:**
  - *ARC:* data-race freedom for the count itself needs atomics, a per-object shared flag (Perceus), or biasing (BRC). Data-race freedom for the payload is a separate type-system question; Swift needed Sendable and actors on top of ARC.
  - *MVS/CoW:* values crossing threads are race-free by construction. But the CoW buffer's refcount must be atomic (or flagged) if a buffer can be shared across threads before the copy. Uniqueness checks (`isKnownUniquelyReferenced`-style) are only sound with an atomic or acquire load.
  - *Ownership/borrowing:* a move transfers a value to another thread for free. Sharing needs a Send/Sync-like property, inferred structurally.
  - *Regions/arenas:* an arena is usually thread-local. Cross-thread use needs a transfer of the whole region, as in Inko's per-thread heaps and unique transfer. Odin-style temp arenas are not thread-safe by default (see Q6 on V's `-prealloc`).
- **G3 constraint.** Swift's model leans on attributes (`@Sendable`, `@MainActor`, `nonisolated(unsafe)`, `@unchecked Sendable`), which G3 bans. Rust's auto-derived Send/Sync and Inko's `uni`/`recover` are inference-based or ordinary keywords and type modifiers, not annotations. Any "can cross threads" property in this language must be inferred structurally from the type, or expressed as an ordinary keyword or type, never as an attribute.
- **P-SWIFT lesson.** Do not ship a single-threaded-by-default heap now and bolt on isolation checking later. Swift's 2019–2025 arc (Sendable 5.7, complete checking 5.10, Swift 6 mode, then the approachability rollback in 6.2) is the cautionary tale.
- **Decide now in ADR-0001:**
  1. Object header layout and RC op semantics: non-atomic, always atomic, or flagged/biased. This is baked into codegen and FFI.
  2. Whether shared mutable heap objects exist at all, or whether all cross-thread transfer is by move or unique value.
  3. That a "sendable" property, if any, is computed by the compiler from type structure (no annotations).
  4. That a single-threaded program pays nothing for (3).
- **Defer to a concurrency ADR:** async/await vs threads vs actors syntax, the scheduler, structured-concurrency scoping rules, channels/messages API, and main-thread/UI-thread affinity. Structured concurrency (child tasks cannot outlive the parent scope) works with every model. It is notably friendly to borrowing and arenas, because borrowed data is guaranteed to outlive the tasks.

```text
// Illustrative (pseudo-syntax): structural sendability, no annotations
type Point { x: Int, y: Int }        // all fields sendable  => Point is sendable (inferred)
type Node  { next: shared Node? }    // contains a non-atomic shared ref => not sendable (inferred)
spawn { use(p) }                     // OK: p moved into task
spawn { use(n) }                     // compile error: Node holds a thread-local shared reference
```

### Gaps
- No official Swift team measurement of atomic-ARC overhead on modern Apple Silicon was found. The forum benchmark is anecdotal.
- Roc's current (2026) atomic-RC policy could not be confirmed. The thread found ends without a decision in Nov 2023.
- Nim YRC's status and benchmarks were not found beyond "experimental".
- Current Swift 6.x adoption rates (percentage of packages in Swift 6 mode) were not found.

---

## 2. Closures and DSLs (G11) under G3: what declarative UI demands of the memory model

### Takeaway
Every mainstream declarative UI stack keeps durable UI state outside the transient view/widget value, in a framework-owned store keyed by identity. Callbacks are escaping closures that capture that state. SwiftUI and Compose use annotations, property wrappers, macros or compiler plugins, which G3 bans. Kotlin builders need only lambdas-with-receiver plus one annotation (`@DslMarker`) for scope hygiene. Flutter gets away with plain classes and closures because Dart has a GC. The memory model must therefore support cheap, non-escaping builder lambdas and safe escaping callbacks that capture shared mutable state, without forming leaks.

### Cited Findings
- **Kotlin type-safe builders:** "By using well-named functions as builders in combination with function literals with receiver, it is possible to create type-safe, statically-typed builders". The `init: HTML.() -> Unit` "is a function type with receiver". `html` "creates a new instance of `HTML`, then it initializes it by calling the function that is passed as an argument ..., and then it returns this instance." — [Kotlin docs](https://kotlinlang.org/docs/type-safe-builders.html)
- **Kotlin scope control needs an annotation.** "An annotation class is called a DSL marker if it is annotated with the `@DslMarker` annotation". With it, "Only the nearest receiver's members and extensions are accessible within a lambda". The outer receiver needs explicit `this@html`. — [Kotlin docs](https://kotlinlang.org/docs/type-safe-builders.html)
- **SwiftUI `State`** is "A property wrapper type that can read and write a value managed by SwiftUI": `@frozen @propertyWrapper struct State<Value>`. "SwiftUI manages the property's storage." "A `State` property always instantiates its default value when SwiftUI instantiates the view." Two-way access to child views goes through `Binding`, via the `$` projected value. — [Apple docs: State](https://developer.apple.com/documentation/swiftui/state.md)
- **Dated (2026):** Apple's State page now says "When you build with Xcode 27 or later, the system uses the `State()` macro instead." The Observation framework uses an `@Observable` macro. SwiftUI state therefore now relies on both property wrappers and macros. — [Apple docs: State](https://developer.apple.com/documentation/swiftui/state.md)
- **Flutter:** "StatefulWidget instances themselves are immutable and store their mutable state either in separate State objects". Resources are allocated "in State.initState and disposes of them in State.dispose". With a GlobalKey move, "the State object is reused (instead of being recreated)". — [Flutter API: StatefulWidget](https://api.flutter.dev/flutter/widgets/StatefulWidget-class.html)
- **Jetpack Compose** uses the `@Composable` annotation, processed by the Compose compiler plugin, with `remember`/`mutableStateOf` state stored in the composition and tracked by the snapshot system. — secondary sources only: [Hinchman, "Hitchhiker's guide to Compose: snapshots, compiler plugins and appliers"](https://speakerdeck.com/amanda_hinchman/hitchhikers-guide-to-compose-snapshots-compiler-plugins-and-appliers), [Compose compiler plugin overview (blog)](https://codeinsightshub.blogspot.com/2026/01/recomposition-101-how-compose-compiler.html). The official developer.android.com page was blocked this session.

### Inferences
- **G3 audit of the four frameworks:**
  - *SwiftUI:* property wrappers (`@State`, `@Binding`, `@Bindable`), macros (`@Observable`, and from Xcode 27 `State()`), result builders (`@ViewBuilder`). Fails G3 on several counts.
  - *Compose:* `@Composable` annotation plus a mandatory compiler plugin. Fails G3.
  - *Kotlin builders:* plain lambdas with receiver work without annotations. Only `@DslMarker` (scope hygiene) is an annotation, and the language could make "nearest receiver only" the default rule instead. Closest to G3-compatible.
  - *Flutter:* plain classes, constructors, named args and closures. No annotations required (`@override` is optional lint metadata). G3-compatible, but leans on Dart's tracing GC.
- **Requirements on the memory model:**
  1. **Non-escaping builder lambdas.** `column { text("hi") }` runs once, synchronously. The model should guarantee these can be stack-allocated with captured variables borrowed, at zero RC or alloc cost. All five families can do this if the language distinguishes non-escaping closures as the default, the way Swift does for non-`@escaping`. That must be a type-level rule, not an attribute.
  2. **Escaping callbacks that mutate state.** `button(onClick = { count += 1 })` outlives the build call and mutates state the view does not own. Under GC this is free (Flutter). Under ARC it creates retain cycles (view model → closure → view model); Swift needs `[weak self]` capture lists. Under strict ownership (Rust) it typically forces `Rc<RefCell<T>>` or signals/arenas, a known ergonomic pain point (P-RUST).
  3. **Framework-owned state keyed by identity.** All four frameworks store durable state outside the view value (SwiftUI attribute graph, Compose slot table, Flutter Element/State, Kotlin builder instance). This pattern maps cleanly onto handles: an index plus generation into a framework-owned store. That suits regions/generational references and MVS (views are pure values, state lives in a store, callbacks capture a handle, not a reference). It avoids both GC and RC cycles.
- **Main question for ADR-0001.** Does the language offer a first-class way to capture "a reference to mutable state owned elsewhere" in an escaping closure, without annotations and without cycles? Candidates: weak references, handles/generational references, or Inko-style runtime-checked borrows.

```text
// Illustrative: handle-based state avoids both GC and RC cycles
view Counter {
    count = state(0)                       // framework allocates slot, returns a handle (value type)
    body = column {                        // non-escaping builder lambda: stack, no RC
        text("Count: " + count.get())
        button("+1", onClick = { count.set(count.get() + 1) })  // escaping closure captures a *handle*
    }
}
// Under ARC, capturing `self` instead of a handle would form self -> body -> closure -> self.
```

### Gaps
- Official Jetpack Compose docs on `remember` and slot-table storage could not be fetched (allowlist). Compose details above rest on secondary sources.
- No primary source found quantifying RC-cycle leak frequency in SwiftUI/UIKit apps.

---

## 3. Debugging, leak detection, sanitizers and coverage (G8, G9)

### Takeaway
Tooling availability is asymmetric across the three CI platforms. Linux gets every sanitizer. macOS lacks LeakSanitizer and MemorySanitizer. Windows has essentially ASan only. A model whose correctness relies on LSan/TSan in CI will be under-tested on Windows and macOS. Models with built-in runtime checks (RC leak report at exit, generational-reference checks, Inko-style borrow counters) give the project leak and use-after-free detection on all three OSes without depending on sanitizer ports. LLVM source-based coverage works with any memory model but requires the frontend to emit coverage-mapping regions.

### Cited Findings
- **Sanitizer support by OS (as documented by JetBrains CLion; clang's own docs were blocked):**
  - *Linux:* "All the sanitizers are available on Linux x86_64 machines."
  - *macOS:* "the supported sanitizers are AddressSanitizer, ThreadSanitizer, and UndefinedBehaviorSanitizer". LSan and MSan are not listed.
  - *Windows:* ASan with clang-cl/MSVC on Windows 10; no TSan, LSan or MSan listed. "MSan is only available in Clang for Linux x86_64 targets."
  - Source: [JetBrains CLion: Google sanitizers](https://www.jetbrains.com/help/clion/google-sanitizers.html)
- **MSVC ASan limits:** "Incremental linking is unsupported", "Edit-and-Continue is unsupported", "Coroutines are incompatible with AddressSanitizer", and thread-locals "aren't protected by AddressSanitizer". The page does not mention LeakSanitizer. — [Microsoft Learn: ASan known issues](https://learn.microsoft.com/en-us/cpp/sanitizers/asan-known-issues)
- **LLVM source-based coverage workflow:** compile with `-fprofile-instr-generate -fcoverage-mapping`, run (writes `LLVM_PROFILE_FILE`), `llvm-profdata merge -sparse`, then `llvm-cov show|report|export` (export emits JSON). Coverage mappings are "emitted into instrumented binaries". Continuous mode (`%c`) "is only supported on Darwin at the moment". GNU BFD before 2.26 can't link `-fcoverage-mapping` with `--gc-sections`. — [Clang SourceBasedCodeCoverage.rst (LLVM 11 tag)](https://llvm.googlesource.com/llvm-project/+/refs/tags/llvmorg-11.0.1-rc1/clang/docs/SourceBasedCodeCoverage.rst)
- **Lobster's leak tooling:** RC does not collect cycles, so Lobster relies on "getting a "cycle report" at program exit that helps the programmer know where to break those cycles." — [Lobster memory management](https://aardappel.github.io/lobster/memory_management.html)
- **Inko's use-after-free check is built into the runtime:** dropping an owned value with live borrows produces a panic such as "can't drop a value of type 'Array' as it still has 1 reference(s)". — [Inko manual](https://docs.inko-lang.org/manual/latest/getting-started/memory-management)
- **CPython's gc module** can expose "unreachable objects that the collector found but cannot free". That is a debugging aid for cycles. — [Python docs: gc](https://docs.python.org/3/_sources/library/gc.rst.txt)
- **Swift 5.10 blog:** even with static checking, code that uses escape hatches "without correct implementation of a synchronization mechanism" may still be flagged by dynamic tools such as TSan. Static and dynamic checking are complementary. — [Swift 5.10 release blog](https://www.swift.org/blog/swift-5.10-released)

### Inferences
- **Effect of the memory model on debuggers (DWARF on Linux/macOS, CodeView/PDB on Windows):**
  - *RC/CoW:* the debugger sees a pointer to a header (refcount, maybe a flag) plus payload. The compiler must describe that layout in debug info, and ideally ship pretty-printers (lldb Python formatters, gdb printers, Visual Studio .natvis) so users see `List[3]{1,2,3}`, not a raw struct. Swift needs a Swift-aware lldb for this.
  - *Ownership/borrowing:* values are plain structs, simplest to describe. Moved-from variables must be marked dead in debug info, or the debugger shows stale data.
  - *Arenas/regions:* objects are raw memory inside a block. Use-after-reset is invisible to ASan unless the arena poisons memory with ASan's manual-poisoning interface.
  - *Generational references:* every reference is (pointer, generation), so formatters must decode the pair.
- **Recommendation shape.** Whichever model is chosen, ship a debug-build runtime mode that detects the model's characteristic bugs on all three OSes:
  - RC: leak/cycle report at exit (Lobster).
  - Ownership with runtime fallback: drop-while-borrowed panic (Inko).
  - Generational: generation-mismatch trap (Vale).
  - Arenas: poison-on-reset.
  This substitutes for missing LSan on macOS and missing LSan/TSan on Windows, and serves G8 directly.
- **Coverage (G9)** is model-independent: the frontend emits `llvm.instrprof.*` intrinsics plus coverage-mapping records and links `compiler-rt` profile. One caveat: compiler-inserted code (RC increments/decrements, drop glue, CoW copy paths) must be attributed to the right source region or excluded, or coverage reports will show phantom uncovered regions. Models with more implicit code (ARC, CoW, drop glue) need more care here.
- **Sanitizers for a non-C frontend.** ASan and TSan are LLVM IR passes plus a runtime library. A new frontend can enable them by running the passes and linking the runtimes, as other LLVM languages do. TSan only understands races if RC atomics and synchronization are emitted as real atomic IR. Hand-rolled "biased" schemes may produce false positives or need TSan annotations in the runtime.

### Gaps
- clang.llvm.org AddressSanitizer/ThreadSanitizer pages were blocked. Platform support above is from JetBrains' summary, which may lag upstream. In particular, whether LSan now works on macOS arm64 or Windows in LLVM 20+ is not verified.
- No primary source fetched on Swift's lldb fork or Rust's `-C instrument-coverage` reusing LLVM coverage mapping (background knowledge, unverified this session).
- No source found on how DWARF/CodeView represent RC headers in existing languages (e.g., Nim's gdb pretty printers).

---

## 4. C FFI, OS handles and deterministic destruction

### Takeaway
Every non-tracing model gets deterministic destruction (RAII-style drop at scope end or count zero), which is exactly what files, sockets and OS handles need. The FFI questions are the same across models:
- the object header layout visible to C;
- who frees memory that crosses the boundary;
- pinning (C may hold a raw pointer, so objects must not move);
- callbacks from C into the language (closure environment lifetime).

Tracing GC is the outlier: Flutter's explicit `dispose()` and Java's `try-with-resources` exist because finalizers are not deterministic.

### Cited Findings
- **Nim:** "ARC is fully deterministic" and "the compiler automatically injects destructors". ORC "retains most of ARC's advantages except determinism (partially)". — [Nim ARC/ORC intro](https://nim-lang.org/blog/2020/10/15/introduction-to-arc-orc-in-nim.html). ARC/ORC memory is freed roughly at scope exit, and "the runtime behavior is oblivious to the involved heap and stack sizes". — [Nim mm docs](https://nim-lang.org/docs/mm.html)
- **Inko:** C structures used for FFI are value types ("copied when they are moved"). Owned values are dropped when no longer used. — [Inko manual](https://docs.inko-lang.org/manual/latest/getting-started/memory-management)
- **Flutter (GC'd Dart) still needs explicit resource lifecycle:** allocate "in State.initState and disposes of them in State.dispose". — [Flutter API](https://api.flutter.dev/flutter/widgets/StatefulWidget-class.html)
- **Odin arenas need explicit reset.** The temp allocator is an arena where "free_all just sets the pointer to the start of the arena", and users must avoid "keeping any references to data in the arena across frame/request/whatever boundaries". (Forum users, not gingerBill.) — [Odin forum](https://forum.odin-lang.org/t/should-we-regularly-free-context-temp-allocator-even-if-unused/1601)

### Inferences
- **Per-model FFI needs:**
  - *ARC:* a stable header ABI; `retain`/`release` exported as C functions for C code that stores language objects; "unowned/borrowed" pointer passing for calls that don't retain. Callbacks from C need a retained context pointer plus a release function, the common `void* ctx` + `free_fn` C idiom.
  - *MVS/CoW:* passing a value to C means passing a pointer to a uniquely owned buffer (force the copy first) or a borrowed read-only view. Mutations by C require uniqueness.
  - *Ownership/borrowing:* the most natural fit for C. "Owned" means the callee must free, "borrowed" means the caller keeps it. Mirrors how C API docs already describe ownership.
  - *Arenas/regions:* C can't know about arena lifetime. Memory handed to C must come from a general-purpose allocator, or the arena must outlive the C use.
  - *Generational references:* C gets a raw pointer and loses the generation check. FFI is an unchecked boundary by necessity.
- **OS handles on all three platforms** (POSIX fds and sockets, Windows `HANDLE`/`SOCKET`) need close-exactly-once semantics. Destructors or `defer` provide this under all non-GC models. A move-only "owned handle" type with a destructor is the common pattern (Rust `OwnedFd`, Inko owned values). `defer` (Zig, Odin, Go, Swift) is a complement for one-off cleanup. Neither needs annotations, so both fit G3.
- **Pinning:** RC, ownership and generational-reference objects are heap-allocated at fixed addresses, so pinning is free. Only moving or compacting collectors (and Inko's earlier Immix-based design) complicate it.
- **G3 caution:** Swift and Rust lean on attributes for FFI (`@_cdecl`, `#[repr(C)]`, `extern "C"`). The language needs ordinary keywords for C layout and calling convention (`extern`, `cstruct`), not annotations.

```text
// Illustrative: deterministic resource management, no annotations
fn copy(src: Path, dst: Path) -> Result {
    in  = File.open(src)?         // owned handle; destructor closes on every exit path
    out = File.create(dst)?
    defer log("done")             // one-off cleanup
    in.copy_to(out)?
}                                 // out closed, then in closed (reverse order), even on error
```

### Gaps
- No primary sources fetched on Zig, Hare or C3 `defer`/`errdefer` semantics, or on Windows handle-inheritance pitfalls. Background knowledge only.

---

## 5. Performance predictability: GC pauses vs RC cascades vs arena reset

### Takeaway
Tracing GC pauses are the documented production pain (Discord on Go 1.9). Plain RC has deterministic but unbounded cascading-free pauses: dropping the last reference to a huge graph frees everything right then (measured in Koka at around 10 µs+ spikes). Arena reset is O(1). Every non-tracing option gives latency the programmer can reason about. "Predictable" still does not mean "bounded" for RC unless the design defers frees.

### Cited Findings
- **Discord (4 Feb 2020):**
  - "Go will force a garbage collection run every 2 minutes at minimum", producing "latency and CPU spikes roughly every 2 minutes" (Go 1.9.2).
  - The Rust rewrite "had no latency spikes!", and "Latency, CPU, and memory were all better in the Rust version."
  - Measurement is from charts only. Go's GC has improved since 1.9 (dated).
  - Source: [Discord blog](https://discord.com/blog/why-discord-is-switching-from-go-to-rust)
- **RC cascade:** "reference counting can still have unbounded pause time as a deallocation event can trigger a chain of deallocation". "unmodified Koka can occasionally get latency spikes of around 10 µs or higher". The CTRC fix defers field deallocation "until the memory is needed by further allocations", giving constant-time alloc and free at some memory cost. Preliminary benchmarks. — [Lam & Parreaux, "Being Lazy When it Counts" (HKUST, 2024 draft)](https://lptk.github.io/files/ctrc-2024-05-09.pdf)
- **Perceus throughput:** Koka's purely functional rbtree "is within 10%" of C++. Java "uses almost 10× the memory of Koka" on rbtree. Disabling Perceus optimizations made it "more than 2× slower". — [Perceus TR](https://microsoft.com/en-us/research/uploads/prod/2020/11/perceus-tr-v4.pdf)
- **Nim:** ARC is "Suitable for hard realtime programming". ORC's cycle collector has "an adaptive threshold for collecting cycles", which costs ORC its "hard realtime (partially)" status. — [Nim ARC/ORC intro](https://nim-lang.org/blog/2020/10/15/introduction-to-arc-orc-in-nim.html)
- **Vale (author's own single benchmark, terrain generator, 2023):** RC +25.29% vs unsafe, generational references +10.84%, both without regions. — [Ovadia, "Generational References"](https://verdagon.dev/blog/generational-references)
- **Arena reset:** "free_all just sets the pointer to the start of the arena". — [Odin forum](https://forum.odin-lang.org/t/should-we-regularly-free-context-temp-allocator-even-if-unused/1601)
- **BRC:** a 22.5% average execution-time reduction for Swift clients from cheaper RC ops implies RC is a large share of Swift runtime in those programs. — [BRC](https://core.ac.uk/download/186334775.pdf)
- **Inko on GC tuning:** "Such settings often lack good documentation, and are highly dependent on the infrastructure used to run the software." — [Peterse](https://yorickpeterse.com/articles/friendship-ended-with-the-garbage-collector)

### Inferences
- **Ranking by tail-latency predictability (opinion based on the above):**
  1. Arenas/regions: O(1) reset, but memory held until reset.
  2. Ownership/borrowing: frees at known points; cascades exist but are visible in code.
  3. Generational references: like ownership, plus a per-dereference check.
  4. ARC/MVS: count-zero cascades are deterministic but data-dependent; the atomic-op tax is spread across all code.
  5. RC plus cycle collector: adds an adaptive, threshold-triggered collection.
  6. Tracing GC: pauses decoupled from program points.
- **Cascade mitigation is cheap:** defer large frees to a free-list processed incrementally (CTRC-style), or let arenas own large graphs. Mention it in ADR-0001 as an optimization point, not a model choice.
- **Throughput:** RC cost is dominated by atomic ops and redundant inc/dec pairs. Perceus (2×), Lobster (about 95% of ops removed) and BRC (about 2× per op) show the optimizer matters more than the model choice.

### Gaps
- No modern (2024–2026) independent benchmark comparing Swift ARC, Rust, Go GC and arenas on tail latency was found.
- No fresh data on Go GC pause times post-1.19 (soft memory limit) was fetched.

---

## 6. Implementation cost for an AI-written compiler with a small test oracle; evidence from small-team languages

### Takeaway
The riskiest components are those whose bugs are silent (leaks, double-frees, use-after-free in generated code) and whose correctness needs a precise static analysis: borrow checking, escape analysis, aggressive RC elision. V's "autofree" is the cautionary tale: a static "insert frees automatically" scheme promised for about five years that still leaked and crashed. The tractable designs pair a simple, always-correct baseline (plain RC, or owned values with runtime-checked borrows) with optional optimizations whose failure mode is a slowdown or a loud runtime panic, never memory corruption. Inko and Lobster are the clearest examples.

### Cited Findings
- **V: the docs claim more than the code delivers.**
  - The docs say autofree "takes care of most objects (~90-100%)" and "Autofree is still WIP. Until it stabilises and becomes the default, please avoid using it." The default is "a minimal and a well performing tracing GC". — [V docs: memory management](https://docs.vlang.io/memory-management.html)
  - A 2023 independent review found leaks under `-autofree` in minimal programs; a vweb server lost about 1 KB in 10 s with no requests.
  - `-autofree` set the GC mode to none, contradicting the docs' claim that the GC frees the remainder.
  - The Ved editor and the self-compiled compiler crashed under autofree.
  - Autofree was "promised as production-ready for versions 0.3, 0.5, and 0.6". "After almost 5 years, the most interesting feature of V is still in a very early state."
  - The `-prealloc` arena uses an unsynchronized global, which is unsafe for threads; the docs now restrict it to "short lived, single-threaded, batch-like programs".
  - Opinion piece by a critic; specifics are reproducible claims. Sources: [V Language Review (2023)](https://n-skvortsov-1997.github.io/reviews), [V docs](https://docs.vlang.io/memory-management.html)
- **Inko** replaced its GC with single ownership and runtime-counted borrows. "When an owned value goes out of scope and its reference count is not zero, the program terminates with an error." Compiler analysis aims to prevent this, and because the runtime check is a fallback, the analysis doesn't need to be perfect. Trade-offs: possible runtime panics, and some types (references, closures, generators) can't be sent between processes. — [Peterse](https://yorickpeterse.com/articles/friendship-ended-with-the-garbage-collector), [Inko manual](https://docs.inko-lang.org/manual/latest/getting-started/memory-management)
- **Lobster** layers compile-time ownership analysis on runtime RC: "Using this analysis was able to remove around 95% of runtime reference count operations". The analysis is "interleaved" with type checking, to avoid duplicating logic. Migration required "minor changes in only 2 locations" across several dozen programs. — [Lobster docs](https://aardappel.github.io/lobster/memory_management.html)
- **Perceus** is formalized, with a garbage-free theorem: "only live data is retained". It is "closely based on the reference counting algorithm in the Lean theorem prover". Cycles are left "to the programmer to break". — [Perceus TR](https://microsoft.com/en-us/research/uploads/prod/2020/11/perceus-tr-v4.pdf)
- **Vale (2023):** the team "recently finished the first regions prototype"; Vale "doesn't yet support inline data". Generation tables were "not yet" available. Ambitious design, slow small-team delivery. — [verdagon.dev](https://verdagon.dev/blog/generational-references)
- **Hylo/MVS:** the paper claims MVS keeps "a simple type system" and can be "compiled to efficient native code", relying on "stack allocation for static garbage collection". The abstract reports no benchmarks. — [arXiv 2106.12678](https://arxiv.org/abs/2106.12678)
- **Nim** offers several modes (ARC, ORC, atomicArc, YRC experimental, refc, and others). Runtime diversity is itself an implementation and testing burden. — [Nim mm docs](https://nim-lang.org/docs/mm.html)

### Inferences
- **Tractability ranking for an AI-built compiler with a small oracle (opinion):**
  1. *Plain RC + scope destructors, unoptimized:* simple codegen rules (inc on copy, dec on scope exit); bugs show up as leaks or crashes that tests catch.
  2. *Owned values + runtime-counted borrows (Inko-style):* static analysis is optional; failures are loud panics.
  3. *MVS + CoW:* the semantics are simple, but implementation needs uniqueness checks and in-place-mutation (`inout`/subscript projection) machinery. Hylo has not shipped 1.0.
  4. *Generational references:* the runtime check is simple; the elision analysis (regions) is research-grade and unfinished in Vale.
  5. *Static ownership with a borrow checker:* Rust-class analysis is a multi-year effort, and it also violates P-RUST and G1.
  6. *Static "autofree"/escape-analysis-only:* V shows it fails silently.
- **Riskiest parts, ordered by blast radius:**
  1. Any analysis that removes a safety check or a free without a runtime backstop (escape analysis, borrow checking, autofree).
  2. RC elision whose bugs are double-frees, not leaks.
  3. Cycle collection (concurrency with mutators, trial-deletion correctness).
  4. Atomic/biased RC ordering bugs, which are invisible on x86 and appear on ARM (macOS arm64 CI).
- **Test-oracle strategy, model-independent:**
  - Build a debug runtime that counts allocations and frees and asserts zero live objects at exit (Lobster's cycle report generalizes this).
  - Make every optimization switchable so tests run with and without it; differential testing of opt vs no-opt output is a cheap oracle.
  - Run ASan and TSan in Linux CI on generated code.
- **Small-team precedents:**
  - Odin, Zig, Hare, C3 and Jai keep the compiler simple with manual memory, allocators and `defer`. Not memory-safe (P-C), so they probably fail this charter's implied safety expectations, though the charter does not say "memory-safe" explicitly (worth confirming with John).
  - Inko, Lobster, Koka/Lean and Roc show automatic and safe memory management is achievable by very small teams when built on RC plus static elision.
  - V shows the failure mode when marketing outruns implementation.

### Gaps
- No primary sources fetched for Odin, Zig, Jai, Hare or C3 compiler sizes and team sizes, or for Hylo's 2026 implementation status.
- **Correction to the brief's framing:** Gleam does not use Perceus-style RC. It compiles to Erlang/BEAM (per-process tracing GC) and JavaScript (host GC). This is background knowledge: gleam.run was blocked this session, so verify. Roc's RC approach is confirmed only via its 2023 Zulip; roc-lang.org/functional does not discuss memory management.
- No quantitative data on how long a borrow checker takes to implement (Rust's NLL/Polonius history not fetched).

---

## 7. Is reference counting "garbage collection"? Interpreting G2

### Takeaway
In the PL literature, yes: Bacon, Cheng and Rajan (OOPSLA 2004) treat tracing and RC as duals within garbage collection, and argue realistic high-performance collectors are hybrids. But G2's wording is operational, not taxonomic: "doesn't require a garbage collection run (like Java and Go do)". Plain, cycle-leaking ARC has no "run" and satisfies a natural reading. A backup cycle collector is a collection run, as Nim's and Python's own docs say. Whether it violates G2 hinges on "require": is it optional or load-bearing? ADR-0001 should state its interpretation explicitly and, if it relies on a cycle collector, escalate via a `needs-john` issue per the charter.

### Cited Findings
- **Bacon, Cheng & Rajan, OOPSLA 2004:**
  - "Tracing and reference counting are uniformly viewed as being fundamentally different approaches to garbage collection."
  - "We present a formulation of the two algorithms that shows that they are in fact duals of each other". Tracing operates on "matter", RC on "anti-matter".
  - "all realistic, high-performance collectors are in fact hybrids that combine tracing and reference counting."
  - The paper refers to "The reference counting garbage collection algorithm".
  - On cycles: "Tracing collects cyclic garbage while reference counting does not". Cycles must be collected "using a backup tracing collector" or "with a trial deletion algorithm".
  - Source: [Bacon, Cheng, Rajan PDF](https://web.eecs.umich.edu/~weimerw/2014-4610/reading/bacon-garbage.pdf), [IBM Research page](https://research.ibm.com/publications/a-unified-theory-of-garbage-collection)
- **Nim on ORC:** "ORC is Nim's all-new cycle collector based on ARC" and "It can be considered a full-blown GC since it includes a local tracing phase." ARC alone: "ARC is fully deterministic." — [Nim blog](https://nim-lang.org/blog/2020/10/15/introduction-to-arc-orc-in-nim.html). Nim's mm table lists ORC as not stop-the-world. — [Nim mm docs](https://nim-lang.org/docs/mm.html)
- **CPython:** "This module provides an interface to the optional garbage collector... Since the collector supplements the reference counting already used in Python, you can disable the collector if you are sure your program does not create reference cycles." — [Python gc docs](https://docs.python.org/3/_sources/library/gc.rst.txt)
- **Lobster** has no cycle collector, only a "cycle report" at exit. — [Lobster docs](https://aardappel.github.io/lobster/memory_management.html)
- **Perceus** leaves cycles "to the programmer to break" and calls cycle collection future work. It notes cycles arise only through mutable references. — [Perceus TR](https://microsoft.com/en-us/research/uploads/prod/2020/11/perceus-tr-v4.pdf)
- **Mutable value semantics** describes stack allocation as "static garbage collection". The term "GC" is stretched even for non-RC models. — [arXiv 2106.12678](https://arxiv.org/abs/2106.12678)
- **V** markets "autofree" but defaults to "a tracing GC". Branding is not semantics. — [V docs](https://docs.vlang.io/memory-management.html)

### Inferences
**Case that RC satisfies G2:**
- G2's parenthetical anchors the meaning: "a garbage collection run (like Java and Go do)". That names a discrete collection phase: a background or stop-the-world trace, decoupled from program points, with heap-size-dependent cost and tuning knobs. P-GO and P-JAVA confirm the complaint is about that GC.
- Plain ARC has no run. Frees happen inline at a known program point (count reaches zero). Nim calls it "fully deterministic" and its behavior "oblivious to the involved heap and stack sizes".
- The literature's taxonomy (Bacon et al.) answers a different question, "what algorithm reclaims memory?", not "is there a collection run?". The charter's owner chose operational wording.

**Case that RC violates G2 (or strains it):**
- In the literature RC *is* garbage collection; Bacon et al. call it "the reference counting garbage collection algorithm". A reviewer reading "No garbage collector" as the heading of G2 could reasonably object.
- Cascading frees are a deterministic but unbounded pause, a "mini-run" triggered by one decrement (Lam & Parreaux).
- RC cost is diffuse runtime overhead (atomics: Perceus 5–59%) that a "no GC" user might expect to be absent.

**Backup cycle collector (Nim ORC, CPython gc):**
- *Violates:* it is literally a collection run. Nim's own docs call ORC "a full-blown GC" with "a local tracing phase". Its adaptive threshold reintroduces non-determinism ("hard realtime (partially)"), the very property G2 targets. If the language's safety story or leak-freedom depends on it, the language "requires a garbage collection run".
- *Does not violate:* CPython's collector is "optional" and can be disabled. If the language guarantees correctness (no use-after-free) without the collector and it only reclaims leaked cycles, it is arguably not "required". It is also local and not stop-the-world in Nim's table, unlike Java/Go.
- *Middle path consistent with G2:* ship no runtime cycle collector. Make cycles impossible or rare by construction (MVS/immutability as in Roc/Koka, where cycles need mutable references), provide weak references or handles to break them, and detect leaks in debug builds (Lobster-style cycle report). Then no run exists in release builds.

**Recommendation for the ADR text:**
- Quote G2 and adopt an explicit operational definition, e.g. "No component reclaims memory by periodically scanning or tracing the heap independently of program points."
- State that RC-at-zero, scope-based drop and arena reset comply under this definition.
- State that any optional tracing/trial-deletion cycle collector would strain G2 and must be raised as a `needs-john` issue rather than decided in the ADR. The charter says decisions that "would break a goal" are escalated, not made.

### Gaps
- The charter owner's intent behind "garbage collection run" cannot be determined from sources. It needs John's confirmation.
- No authoritative PL-community survey defines "GC-free" operationally. Usage varies by community (Swift and Rust marketing vs academic taxonomy).
