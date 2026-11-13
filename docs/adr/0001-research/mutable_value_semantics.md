# Mutable Value Semantics (MVS) with Copy-on-Write as the Memory-Management Model

Scope: Hylo (ex-Val), the "Implementation Strategies for Mutable Value Semantics" paper (Racordon, Shabalin, Zheng, Abrahams, Saeta; JOT 2022), Swift structs/arrays with COW, Mojo's ownership model, second-class references research, Lobster's compile-time RC. Assessed against charter goals G1, G2, G3, G6, G11, P-RUST, P-SWIFT, P-C, P-PY.
Research date: 2026-11-07. Notation: "[sourced]" findings carry links; "[background, unverified this session]" marks widely known facts not re-checked against a primary source here; code marked "illustrative" was written by the researcher to show the shape of a solution and has not been compiled (the Hylo compiler is pre-1.0, so even the tour's own example is marked "may not compile?" by one index site).

---

## Q1. What can and cannot be expressed? How are graphs, parent-linked trees, shared mutable state, caches and observers handled, and how painful is it?

### Takeaway
Strict MVS bans stored references: every value is a tree rooted in a variable, and references exist only briefly at call boundaries (`inout`, projections/`yield`). Anything with real sharing or back-links (graphs, parent pointers, observers, a cache shared by two components) has to be rewritten as indices or handles into an owning container (an arena), or passed explicitly as `inout`. This is safe and simple, but the compiler no longer checks the integrity of those links. Stale or dangling indices become logic bugs that the type system does not catch.

### Cited Findings
- Definition: "Mutable value semantics is a programming discipline that upholds the independence of values to support local reasoning." Values form "disjoint topological trees rooted in the program's variables." — [Racordon et al., Implementation Strategies for MVS (preprint)](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf)
- In strict MVS, "references become second-class citizens: they are only created implicitly, at function boundaries." Stored references are not allowed, so variables cannot share mutable state. — [Racordon et al.](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf)
- Acknowledged limitation on graphs: "traversing an arbitrary graph requires access to the whole graph at each step," rather than a single vertex. — [Racordon et al.](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf)
- Law of Exclusivity: overlapping `inout` paths are rejected. The paper also concedes that the conservative static index check "suffers from obvious false-positives." — [Racordon et al.](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf)
- Val object model (WG21 P2676R0, 2022-10-13; Abrahams, Parent, Racordon, Sankel):
  - Independence is "the idea that a mutation to one variable cannot affect the value of another."
  - The paper claims "Memory safety by construction" and "Thread safety by construction."
  - `&v.remove(v[2])` is rejected and must be written `v[2].copy()`.
  - `swap(&x[i], &x[j])` is rejected because the elements may overlap, while `&x.index_swap(i, j)` is accepted.
  - Val's safe subset "does not allow reseating bindings." The authors argue key paths can cover this.
  - The paper does not discuss graphs or index-based node arrays.
  — [P2676R0 The Val Object Model](https://www.open-std.org/Jtc1/sc22/wg21/docs/papers/2022/p2676r0.pdf)
- Projections: "Projections allow access to parts, including ephemeral ones, without introducing references." — [P2676R0](https://www.open-std.org/Jtc1/sc22/wg21/docs/papers/2022/p2676r0.pdf)
- Hylo subscripts:
  - "A subscript is a reusable piece of code that *yields* the value of an object, or part thereof."
  - "A subscript must have exactly one `yield` statement on every possible execution path." The caller uses the yielded value while the subscript is suspended.
  - Accessor variants are `let`, `inout`, `set` and `sink`. "The `sink` variant of a subscript can always be synthesized from the `let` variant."
  — [Hylo tour: Subscripts](https://docs.hylo-lang.org/language-tour/subscripts.md)
- Hylo example of projecting a mutable part chosen at runtime (from an index site): `subscript longer_of(_ a: inout String, _ b: inout String): String { if b.count() > a.count() { yield &b } else { yield &a } }`, used as `emphasize(&longer_of[&x, &y])`. — [Ted Neward's Hylo page](https://research.tedneward.com/languages/hylo/index.html)
- Second-class values, from the Purdue summary of Osvald et al. (OOPSLA 2016, Distinguished Artifact Award):
  - In ALGOL/Pascal, functions could be passed as arguments but could not escape their scope, so they acted as "temporary access tokens or capabilities."
  - The paper concludes that second-class values give practically relevant static guarantees, and that mixing them with first-class values enables new implementation techniques.
  - The summary gives no percentage figures.
  — [Purdue CS news](https://www.cs.purdue.edu/news/articles/2016/OOPSLA-Second-Class-Functions.html)

### Inferences
- Graphs, parent links and observers are not impossible under MVS, but they all turn into an arena plus integer handle: `struct Graph { nodes: [Node] }` with `parent: Int?`. The costs:
  - The programmer re-implements pointer integrity: stale indices after removal, generation counters, free lists.
  - Every operation on a node needs the whole container passed `inout`, which is the paper's own "access to the whole graph" point.
  - Some double borrows that would be fine are rejected (`swap(&x[i], &x[j])`), so you need helper methods like `index_swap`.
- The memory-safety failure (use-after-free) becomes a logic failure: a wrong but in-bounds index, or a bounds-check trap. Memory safety is kept and referential integrity is lost.
- Pain is concentrated in particular domains: UI trees with parent access, document models, ECS-style game state, compilers (ASTs with symbol links), and observer patterns. For data-processing code (lists, maps, records, pipelines) MVS is almost invisible.
- Rust's ecosystem converged on the same arena/index workaround (e.g. `slotmap`, `petgraph`) [background, unverified this session]. So MVS doesn't add this pain compared with Rust. It removes Rust's lifetime syntax but keeps the "no back-pointer" constraint.

### Gaps
- No measured study found of how much effort index/arena rewrites take, or how many stale-handle bugs they produce in MVS languages.
- No Hylo-specific guidance on graphs/arenas was found in the tour pages fetched.

---

## Q2. How does COW work, what hidden machinery does it need, can its refcount form cycles, and what are the performance pitfalls?

### Takeaway
COW means each heap buffer (array, string, dictionary storage) carries a reference count. Copying a value just bumps the count. Before a mutation, a uniqueness check runs: if count == 1, mutate in place; otherwise allocate a fresh copy. Under strict MVS the count cannot form cycles, because values are trees and buffers are only reachable through values. The pitfalls are:
- an invisible O(n) copy whenever a second owner exists at the moment of mutation, including spurious copies when the optimizer can't prove uniqueness;
- refcount traffic, which has to be atomic once threads exist;
- performance that depends heavily on optimizer passes that reason about uniqueness.

### Cited Findings
- Mechanism: "Heap-allocated storage is associated with a counter that keeps track of the number of references to that storage." On mutation, "If the storage is shared, the counter is decremented, the storage is duplicated and the mutation is performed on a copy." When the counter reaches zero, "the contents of the storage are destroyed and deallocated." — [Racordon et al.](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf)
- Swiftlet (the paper's research language) "applies copy-on-write on arrays only, as structures are allocated inline." — [Racordon et al.](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf)
- Pitfall named in the paper: with COW and `inout`, "the caller is compelled to copy non-unique storage defensively." — [Racordon et al.](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf)
- Measured performance:
  - Benchmark scale: 1,344 randomly generated programs × 20 runs, plus 5 micro-benchmarks (Bounce, Mandelbrot, NBody, Permute, Queens).
  - Compared: Swift 5.5.2 (-Ounchecked), C++ (Clang 11, -O3), Scala / Scala Native 0.4.2, and Swiftlet.
  - "Swift is the fastest language in the overwhelming majority of the benchmarks."
  - "Swift proved slower than C++ only for programs with extremely large number of mutating operations (> 90%)."
  - Swiftlet "is significantly slower than Swift in most benchmarks," and lags "on benchmarks that depend on heavy mutation of arrays (Bounce, NBody, Permute)." The authors attribute this to missing optimization passes that reason about refcount uniqueness, which leaves more runtime checks.
  - The study used only a single-threaded execution model.
  — [Racordon et al.](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf)
  - Note: the extracted micro-benchmark ratios (range 0.48x to 11.06x) could not be reliably mapped to language/benchmark pairs from the PDF text, so don't quote them per language.
- The paper's conclusion is that COW "offers compelling performance gain," and that in-place, part-wise mutation beats functional updates in write-heavy programs. — [Racordon et al.](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf)
- Related work cited by the paper: Perceus (Reinking et al.) uses reference counting for in-place updates. — [Racordon et al.](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf)
- Real-world spurious copy in Swift (SR-13888, Swift 5.3 / Xcode 12.2): iterating a dictionary by `.keys` makes `isKnownUniquelyReferenced` fail on the struct values, which forces COW copies even though the loop never mutates them. The report calls the cost "unnecessary copies if the values use copy on write." The excerpt doesn't show whether it was fixed. — [SR-13888](https://bugs.swift.org/browse/SR-13888)

### Inferences
- **Cycles:** in pure MVS a buffer's refcount counts only the values that hold it. Values cannot hold references, so the "holds" graph is a forest and cycles are impossible by construction. This follows from the "disjoint topological trees" definition. Cycles come back only if the language adds a reference/identity type (see Q7).
- **Accidental O(n) copies, typical shapes** (illustrative Swift):
  ```swift
  var lines = [String]()
  let snapshot = lines          // refcount 2
  lines.append("x")             // O(n) copy here, silently
  ```
  ```swift
  var model = Model()           // model.items is a COW array
  let old = model               // e.g. kept for undo/diff
  for i in 0..<n { model.items[i] += 1 }  // first write copies, the rest are in place
  ```
  ```swift
  // A closure or async task that captured the array (+1 ref) makes every later
  // mutation in the caller pay one copy.
  ```
- **Hidden machinery list** for a new compiler:
  1. a header word (refcount, plus capacity) on every growable buffer;
  2. retain/release at copy and destroy points;
  3. a uniqueness check before every mutating buffer operation;
  4. atomic refcounts if values can cross threads [background, unverified: Swift uses atomic RC];
  5. optimization passes (move-on-last-use, retain/release elimination, uniqueness propagation) to be competitive. Swiftlet's gap to Swift is evidence for item 5.
- **Pitfalls are a predictability problem more than a throughput problem.** Most code is fast, but a one-line change (keeping an extra copy) can turn an O(1) append into O(n), with nothing in the syntax to show it. Explicit `.copy()` (Mojo's choice, see Q4) trades G4 terseness for visibility.
- **Swift's COW is library-level.** Each collection implements it with `isKnownUniquelyReferenced` [background, unverified this session; the API name is confirmed by SR-13888]. A new language could build COW into the compiler for List/Map/String instead, which keeps it out of user code (helps G1) but requires compiler support.

### Gaps
- Exact per-benchmark numbers from Figure 16 could not be extracted.
- JOT volume/issue/DOI for the published paper wasn't found in the fetched text. The preprint and arXiv 2106.12678 ("Native Implementation of MVS", ICOOOLPS 2021) are related versions.
- No source found quantifying the cost of atomic vs non-atomic refcounts in Swift.

---

## Q3. How are closures that capture state handled (onTap = { save() })?

### Takeaway
This is MVS's weakest point for G11:
- **Hylo** has `let`, `inout` and `sink` captures. `inout` captures are shown only for immediately used (non-escaping) closures. An escaping closure can hold its own state (a `sink` capture) but cannot keep a live mutable link to enclosing state.
- **Swift** closures capture by reference (boxing captured vars). Once a closure captures `self` of a class, you get retain cycles and the `[weak self]` ritual.
- A UI DSL under strict MVS therefore has to use a message/update architecture (Elm/TEA-style) or a runtime-owned state store addressed by handle, not "closure mutates my fields".

### Cited Findings
- Hylo closures (from the tour):
  - Three capture kinds: "A `let` capture occurs when a function accesses a binding immutably" (`[1, 2, 3].map(fun(_ n) { n + offset })`); "An `inout` capture occurs when a function accesses a binding mutably" (`[1, 2, 3].for_each(fun(_ n) { &sum += n })`); and a `sink` capture, which must appear in an explicit capture list.
  - Example of the `sink` form: `var counter = fun[var i = 0]() inout -> Int { ... }`. The closure is marked `inout` because calling it mutates its own captured state, and calls use `&`: `print(&counter())`.
  — [Hylo tour: Functions and methods](https://docs.hylo-lang.org/language-tour/functions-and-methods.md)
- Swiftlet: "The value of each capture is then copied from the context surrounding its declaration." Because Swiftlet "captures only by copy, it guarantees statically that closures uphold the Law of Exclusivity." — [Racordon et al.](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf)
- Swift closures:
  - Closures see the current value of captured variables, so changes outside show up when the closure runs. Capture lists (`[calculator]`) take an immutable snapshot instead.
  - "By default, a closure keeps a strong reference of the variable captured."
  - A class that stores a closure using `self` creates a cycle where "`closure` and `self` are keeping a strong reference of each other."
  - Fixes: `[weak self]` plus `guard let strongSelf = self else { return }`, or `[unowned self]`, which crashes if self is gone.
  — [Marco Santarossa, Capturing values in Swift closures](https://www.marcosantadev.com/capturing-values-swift-closures/)
- Mojo docs mention "origin sets" only in passing, as tracking the lifetimes of values captured by parametric closures. No further detail was given. — [Mojo manual: Lifetimes, origins, references](https://mojolang.org/docs/manual/values/lifetimes/)

### Inferences
- **Scenario (c), button onTap calling save()** (illustrative):

  Swift (hybrid: class with ARC). Works, but carries the retain-cycle tax:
  ```swift
  final class EditorModel {
      var doc = Document()
      func save() { /* write doc */ }
  }
  final class EditorScreen {
      let model = EditorModel()
      lazy var saveButton = Button(title: "Save") { [weak self] in   // without [weak self]: cycle screen→button→closure→screen
          self?.model.save()
      }
  }
  ```
  SwiftUI hides this with `struct View` plus `@State` / `@Observable` / result builders. Those are property wrappers, macros and annotations, which directly strains G3 and P-SWIFT [background, unverified this session].

  Hylo / strict MVS: an escaping closure cannot hold `inout` to `editor`. A pattern that fits the rules is message-passing (illustrative pseudo-Hylo):
  ```hylo
  type Msg { case save; case edit(String) }           // illustrative syntax
  fun update(_ state: inout Editor, _ m: Msg) {
    match m { .save => &state.save() ; .edit(let s) => &state.text = s }
  }
  // View is a pure value; the button carries a value, not a callback that mutates.
  fun view(_ state: Editor) -> Widget {
    column { text(state.text); button("Save", on_tap: Msg.save) }
  }
  // Runtime loop owns the single mutable state:  &update(&app_state, next_event())
  ```
  Pros: no cycles, no `weak`, trivially testable, and the state is data-race-free. Cons: every interaction needs a message case. It reads less directly than `onTap = { save() }`, and component-local state needs a design (keyed state store or nested update functions).
- A design option: allow `onTap = { save() }` syntactically, but have the compiler desugar it to "closure receives `inout Self` at call time". The runtime then calls `handler(&owner)`. This is effectively a method reference plus late binding of the receiver, with no stored reference. It keeps the DSL syntax clean (G4, G11) and stays inside MVS. This is the researcher's synthesis, not a feature of any surveyed language.
- Under strict MVS, an escaping closure that captures by copy and is later run will mutate a stale copy. That is a semantic trap UI programmers coming from JS/Swift/Kotlin will hit. It can be prevented only by making escaping closures `let`-only (Swiftlet's rule), and the compiler must report it clearly.

### Gaps
- Hylo docs fetched don't state whether `inout` captures are restricted to non-escaping closures. That is inferred from the examples and the no-stored-references rule. Needs confirmation in the Hylo spec.
- No published Hylo/Mojo UI framework was found to show how real UI callbacks are built under these models.

---

## Q4. Does MVS without stored references truly eliminate lifetime annotations? What restrictions replace them?

### Takeaway
Yes for strict MVS (Hylo, Swiftlet). Lifetimes never need names because every reference is scoped to a call or a `yield` and cannot escape. Mojo is the counter-example: it keeps first-class `ref` returns, `Pointer` and `Span`, and therefore needs origin (lifetime) parameters for exactly those features. The price paid instead:
- no stored references, so no back-pointers or views stored in structs;
- no returning references, except through `yield` projections;
- exclusivity errors at call sites;
- explicit `&` markers;
- index/arena workarounds.

### Cited Findings
- Hylo parameter conventions:
  - `let` parameters are "(notionally) passed by value, and are truly immutable," and do not transfer ownership.
  - "`inout` arguments must be unique: they can only be passed to the function in one parameter position." Call sites mark them with `&`: `offset_inout(&v, by: ...)`.
  - "The `sink` convention indicates a transfer of ownership"; "the argument becomes inaccessible in the caller after the callee is invoked."
  - "The `set` convention lets a callee initialize an uninitialized value."
  - Methods have an implicit `self` that can usually be omitted. The default receiver convention is `let`; mutating methods are declared `inout` after the parameter list, and called as `&y.offset_inout(...)`.
  — [Hylo tour: Functions and methods](https://docs.hylo-lang.org/language-tour/functions-and-methods.md)
- Mojo conventions:
  - default (immutable reference), `mut`, `var` (ownership), `ref`, `out`, `deinit`.
  - Transfer uses `^`: after `take_text(message^)` the variable is uninitialized.
  - "A `mut` argument can't alias any other reference to the same value."
  - Mojo aims to "provide full value semantics by default."
  — [Mojo manual: Ownership](https://mojolang.org/docs/manual/values/ownership/)
- Mojo origins:
  - Origin annotations are required with `ref` arguments/returns and with types parameterized on origin (`Pointer`, `Span`). "A `ref` return value must have an origin specifier."
  - Example: `def as_ptr(mut self) -> Pointer[String, origin_of(self.o_ptr[])]`. Origins can also be declared as type parameters: `struct ImmutRef[origin: ImmOrigin]`.
  - The docs list "Untracked" and "Wildcard" (`MutUnsafeAnyOrigin`) origins as escape hatches, with wildcard discouraged as a last resort.
  — [Mojo manual: Lifetimes](https://mojolang.org/docs/manual/values/lifetimes/)
- Mojo 1.0 (beta in 2026): "Copies are made explicitly with `.copy()`," `^` transfers ownership, and code breaking ownership/borrowing rules won't compile, which the article compares to Rust. — [InfoWorld, First look at Mojo 1.0 (2026-05-20)](https://www.infoworld.com/article/4173158/first-look-at-mojo-1-0.html)
- Rust's mutable borrows are "operationally identical to inout arguments," but Rust relies on "a more sophisticated type system for the sake of expressiveness." — [Racordon et al.](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf)

### Inferences
- MVS's simplicity claim rests on one choice: references are never values. Once the language lets a struct hold a reference, or a function return one outside a `yield`, it needs Mojo-style origins, and with them generics over lifetimes. That collides with G3 (no templated types) and P-RUST.
- Restrictions programmers actually feel:
  1. "cannot borrow `x` twice" exclusivity errors (e.g. `swap(&a[i], &a[j])`, `&v.remove(v[2])`);
  2. `&` noise at mutating call sites (a G4 cost, small);
  3. no "view" structs (iterator holding a ref, string slice stored in a struct). Instead you get yield-scoped projections or index ranges;
  4. arena/handle patterns for any back-link;
  5. escaping closures can't mutate outside state.

  Items 1 and 2 are lighter than Rust's lifetime syntax. Items 3 to 5 are the real cost and fall heavily on UI/DSL code (G11).
- Projections (`yield`) are coroutine-like. The compiler must make sure the caller's use of the yielded value ends before the subscript resumes. This is a scoped borrow without a named lifetime, which is how Hylo avoids annotations while still giving zero-copy part access.
- Recent Swift is also adding non-escapable types and lifetime dependencies for `Span` [background, unverified this session]. That suggests even a COW language eventually wants first-class borrowed views for performance-critical code. If true, this is a warning sign for long-term G1.

### Gaps
- Swift's current `~Escapable` / lifetime-dependence status in 2026 was not verified this session.
- No user study comparing exclusivity-error frequency or confusion vs Rust borrow errors was found.

---

## Q5. Concurrency (data-race freedom by construction?) and C FFI

### Takeaway
MVS makes data-race freedom largely structural. Values are independent, so handing a value (or disjoint `inout` parts of one) to another thread cannot race. The authors claim "thread safety by construction" but give no formal proof. Hylo's concurrency is still "under design". COW buffers shared across threads need atomic refcounts or ownership transfer. C FFI is necessarily an unsafe escape hatch with raw pointers (Mojo has explicit "untracked/unsafe" origins). MVS gives no special help with FFI and adds a requirement: pin or borrow a buffer for the duration of the C call.

### Cited Findings
- P2676R0:
  - Claims "Thread safety by construction."
  - Attributes Rust's "fearless concurrency" to independence, not to a separate mechanism.
  - Says a slice pair "can be mutated in distinct threads."
  - No formal data-race freedom proof is given.
  — [P2676R0](https://www.open-std.org/Jtc1/sc22/wg21/docs/papers/2022/p2676r0.pdf)
- Hylo concurrency:
  - "The concurrency approach of Hylo is still under design. This document only presents our current plans."
  - The design is structured concurrency with `spawn`/`await`, no function colouring, no actor abstraction, and "There is no need for low-level synchronization primitives, like mutexes and semaphores."
  - The concurrent sort example: `let handle = spawn(() => my_concurrent_sort(&rhs)); my_concurrent_sort(&lhs); handle.await()`.
  - The page does not mention data-race freedom explicitly.
  — [Hylo tour: Concurrency](https://docs.hylo-lang.org/language-tour/concurrency.md)
- The JOT/preprint study is limited to a single-threaded execution model. — [Racordon et al.](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf)
- Mojo provides "Untracked" origins for memory the lifetime checker doesn't track (e.g. heap allocations), and "Wildcard" unsafe origins as a last resort. — [Mojo manual: Lifetimes](https://mojolang.org/docs/manual/values/lifetimes/)

### Inferences
- **Scenario (f), sharing data between threads** (illustrative):

  Hylo (planned design; disjoint parts, no locks):
  ```hylo
  fun parallel_sum(_ data: inout Array<Int>) -> Int {
    // split into two disjoint mutable projections (illustrative API)
    let h = spawn(() => sum(&data.left_half))
    let r = sum(&data.right_half)
    return h.await() + r
  }
  ```
  Swift (values are Sendable; reading a shared COW array from many tasks is safe because no one mutates in place):
  ```swift
  let lines: [String] = load()
  async let a = count(lines[..<mid])     // copies are O(1) refcount bumps
  async let b = count(lines[mid...])
  let total = await a + b
  ```
  Shared *mutable* state across threads, e.g. a global cache (illustrative Swift):
  ```swift
  actor Cache { var map: [String: Data] = [:]; func get(_ k: String) -> Data? { map[k] } }
  ```
  Strict MVS has no direct equivalent. You need a runtime-provided synchronized handle type (actor/channel/mutex-owned value). In other words, an opt-in identity type comes back for exactly this case.
- Atomic refcounts are needed if COW buffers can be shared between threads. An alternative is "transfer on send" (`sink`), which avoids atomics but forbids cheap shared read-only snapshots.
- FFI checklist for the ADR:
  - raw pointer type (unsafe);
  - "with buffer pointer" scoped borrow for passing a List to C;
  - C-allocated memory wrapped in an owning value with a destructor;
  - callbacks from C need a context `void*`, which strict MVS can only represent as an index/handle or an unsafe pointer.

  None of these are unique to MVS. All are compatible with G2 (no GC).

### Gaps
- No formal proof of data-race freedom for Hylo/MVS was found.
- Hylo's C interop story was not covered by the fetched tour pages.
- Mojo's thread-safety model (Send/Sync analogues) was not researched.

---

## Q6. Learnability, maturity (as of Nov 2026), and implementation complexity on LLVM

### Takeaway
- **Learnability:** no measured studies exist. The evidence is design claims and anecdote.
- **Maturity:** Hylo is pre-1.0. A maintainer targeted compiler 1.0 for Q4 2026, then "most of 2027" on bugs, performance and tooling. Mojo 1.0 was in beta by May 2026.
- **Implementation:** a basic MVS compiler is small (Swiftlet was a research prototype), but competitive performance needs uniqueness, move and retain/release optimization passes. Projections need a coroutine-style lowering.

### Cited Findings
- Hylo roadmap (GitHub discussion #1905, opened 2026-06-21): maintainer kyouko-taiga, 2026-06-22, in the accepted answer: "Our current plan is to release a 1.0 of the compiler by Q4 of this year," and "we'll probably spend most of 2027 fixing bugs, improving performance, and catching up on tooling." Self-hosting will come "Once our ecosystem is somewhat stable." — [hylo-lang discussion #1905](https://github.com/orgs/hylo-lang/discussions/1905)
- A `hylo-lang/hylo-old` repository exists, with releases and a Swift Package Registry listing. — [hylo-old releases](https://github.com/hylo-lang/hylo-old/releases); [Swift Package Registry](https://swiftpackageregistry.com/hylo-lang/hylo-old)
- Hylo concurrency is "still under design." — [Hylo tour: Concurrency](https://docs.hylo-lang.org/language-tour/concurrency.md)
- Mojo:
  - "Now in 2026, the first beta version of Mojo 1.0 is out" (article dated 2026-05-20).
  - Named obstacles: "finding an audience" and "no automatic migration path from Rust or Python."
  - The article doesn't state open-source status or platforms.
  — [InfoWorld](https://www.infoworld.com/article/4173158/first-look-at-mojo-1-0.html)
- P2676R0 claims value semantics gives "a simpler programming model" but presents Val as a research model ("Adopting this model may not be the right thing for C++"). — [P2676R0](https://www.open-std.org/Jtc1/sc22/wg21/docs/papers/2022/p2676r0.pdf)
- Swiftlet trails Swift mainly because it lacks uniqueness-reasoning optimizations, and it omits protocols. — [Racordon et al.](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf)
- Lobster (compile-time RC plus ownership analysis): "Using this analysis was able to remove around 95% of runtime reference count operations." It is "a fully automatic algorithm that mostly does not require programmer intervention." Cycles are not collected; a "cycle report" at program exit "helps the programmer know where to break those cycles." — [Lobster memory management](https://aardappel.github.io/lobster/memory_management.html)

### Inferences
- The `hylo-old` repo, together with a fresh 1.0 target, suggests the original Swift-hosted compiler was archived and replaced by a new implementation. This is an inference from repo naming only and was not confirmed.
- **Hylo as a reference point:** it is the closest existing design to what the charter wants. It has implicit `self` (P-PY ✔), no lifetime syntax (P-RUST ✔), no GC (G2 ✔) and no first-class references. But it has no production users, no stable compiler and its concurrency is undecided as of Nov 2026. It is a design reference, not a dependency.
- **Implementation components** on LLVM (rough order of difficulty, researcher's estimate):
  1. ownership/initialization dataflow (definite init, `sink` = move, last-use analysis). Moderate; Swift SIL and Mojo do this at IR level.
  2. exclusivity checking for `inout` (static plus some dynamic checks). Moderate.
  3. projections/`yield` lowering, either as LLVM coroutines or by inlining/CPS. Hard-ish; the simplest approach is to inline accessors and restrict yields to one per path.
  4. COW runtime (refcount header, uniqueness check, copy). Easy.
  5. retain/release and uniqueness optimizations. Ongoing work and where performance lives; Lobster's 95% figure shows the ceiling.

  The compiler stays simpler than a Rust-style borrow checker because there are no lifetime variables to solve.
- **Learnability (opinion):** most programmers already understand value semantics from ints/strings and "pass by value vs by reference". `inout` + `&` matches Swift/C# habits. The learning curve shows up when someone tries to build a linked structure or a mutating callback, and the language must have a documented idiom ready for that moment.

### Gaps
- Whether Hylo actually shipped 1.0 by Nov 2026 could not be verified (the GitHub repo page was not fetchable this session).
- No empirical learnability studies (classroom, user studies) were found for Hylo, Swift value types or Mojo ownership.
- Mojo platform support (Windows) and open-source status in 2026 were not verified.
- Austral (linear types + borrows/regions) was not researched this session.

---

## Q7. Hybrid: values by default plus an opt-in reference-counted class/identity type (Swift model). What problems return, and how much?

### Takeaway
Adding an RC class type brings back every pure-RC problem, but only inside the class subset:
- retain cycles, and with them `weak`/`unowned`, optional unwrapping and capture lists;
- aliasing (shared mutation, so local reasoning is lost);
- data races, which need Sendable/actors;
- atomic RC cost.

How much code is affected depends on the domain. Data and algorithm code barely touches classes. UI, observer, cache and graph code (the G11 core) is where classes concentrate. No measured "% of code" figure was found.

### Cited Findings
- Swift closure/class cycle and the `[weak self]`/`[unowned self]` remedies, including crash risk with `unowned`. — [Marco Santarossa](https://www.marcosantadev.com/capturing-values-swift-closures/)
- Swift implements different copy behaviours for reference and value types via value witnesses. — [Racordon et al.](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf)
- C# supports mutable value types, but "its interaction with interfaces can produce counter-intuitive results" (a hybrid pitfall). — [Racordon et al.](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf)
- Lobster shows RC plus ownership analysis can remove ~95% of RC ops, and handles cycles by reporting them at exit rather than collecting them. — [Lobster](https://aardappel.github.io/lobster/memory_management.html)

### Inferences
- **Problems that return with a class type, and mitigations that keep G2 (no GC run):**

  | Problem | Mitigation options (no GC) | Charter tension |
  |---|---|---|
  | Retain cycles / leaks | `weak` refs; Lobster-style cycle report at exit/in debug builds (G8); forbid class fields of class type except `weak` (strong) | `weak` adds optionals and syntax (G1/G4) |
  | Closure capturing `self` | Default escaping closures to capture class `self` weakly, or desugar to receiver-passed handlers (Q3) | Hidden semantics vs boilerplate |
  | Aliased mutation (spooky action at a distance) | Keep classes rare by idiom; immutable-by-default fields | Local reasoning lost inside class graph |
  | Data races | Classes non-sendable by default; a `shared`/actor type for cross-thread | Extra concept (P-SWIFT risk: Swift 6's Sendable migration is widely seen as painful [background, unverified]) |
  | Atomic RC cost | Non-atomic RC for non-sendable classes; ownership analysis à la Lobster | Compiler complexity |
  | Two copy semantics (`a = b` means copy for struct, alias for class) | Distinct syntax or naming convention | Classic Swift/C# confusion (G1) |

- **Scenario (d), shared mutable cache used by two components** (illustrative):

  Strict MVS (Hylo-like). The cache is owned by a common parent and passed explicitly:
  ```hylo
  type App { var cache: Cache; var search: SearchPane; var detail: DetailPane }
  fun on_query(_ app: inout App, _ q: String) {
    &app.search.run(q, cache: &app.cache)    // explicit inout
    &app.detail.refresh(cache: &app.cache)   // sequential, never overlapping
  }
  ```
  Pros: no aliasing, and the data flow is visible. Cons: "prop-drilling" through every layer, and components can't hold the cache themselves.

  Hybrid (Swift):
  ```swift
  final class Cache { var map: [String: Data] = [:] }
  struct SearchPane { let cache: Cache }   // both hold the same instance
  struct DetailPane { let cache: Cache }
  ```
  Pros: direct. Cons: aliasing, and thread safety becomes the programmer's problem. Usually harmless (cache entries don't point back to their owners).
- **Scenario (b), tree with parent pointers:**

  Swift hybrid:
  ```swift
  final class Node { var children: [Node] = []; weak var parent: Node? }
  ```
  `weak` is needed, otherwise parent↔child forms a cycle. Each access is `node.parent?.x`.

  Strict MVS arena (Hylo-like, illustrative):
  ```hylo
  type Tree { var nodes: Array<Node> }
  type Node { var value: Int; var parent: Optional<Int>; var children: Array<Int> }
  fun reparent(_ t: inout Tree, _ n: Int, to p: Int) { &t.nodes[n].parent = p; &t.nodes[p].children.append(n) }
  ```
  Pros: no cycles, cache-friendly, and the whole tree copies as one value (undo/redo is trivial). Cons: index validity is unchecked, and deletion needs tombstones or generations.
- **Scenario (a), read a file of unknown length into a list** (dynamic growth works naturally under MVS):

  Swift:
  ```swift
  var lines: [String] = []
  while let line = readLine() { lines.append(line) }   // unique buffer → amortized O(1), no COW copy
  ```
  Hylo-like:
  ```hylo
  var lines = Array<String>()
  while let line = file.read_line() { &lines.append(line) }   // illustrative API
  ```
  Mojo:
  ```mojo
  var lines = List[String]()
  for line in f.read().splitlines(): lines.append(String(line))
  ```
  Pitfall: return `lines` by value (move) and never keep a second copy during the loop. Otherwise each append that hits shared storage pays an O(n) copy.
- **Scenario (e), pass a large list to a mutating function:**

  Swift `func normalize(_ xs: inout [Double])`, call `normalize(&data)`. No copy if `data` is unique.

  Hylo `fun normalize(_ xs: inout Array<Float64>)`, call `normalize(&data)`.

  Mojo:
  ```mojo
  def normalize(mut xs: List[Float64]): ...
  normalize(data)       # no & marker at call site
  ```
  All three avoid copies. Swift/Hylo make mutation visible at the call site with `&`. Mojo's `mut` is invisible at the call site, which is a readability drawback.

  If the caller still holds another copy (Swift/Hylo with COW), the first write copies "defensively" (paper's term). Mojo avoids this because its `List` copies are explicit (`.copy()`).
- **Overall estimate (opinion, not measured):**
  - In a CLI/data/service codebase, perhaps a small minority of types would need identity: resources, caches, connections.
  - In a UI app, the view-model layer, which is most of the stateful code, would.

  So a hybrid keeps MVS's guarantees for most code by volume, but not for the code G11 targets. Unless the DSL is designed around value/state-store semantics (Elm/TEA, or the receiver-passed handler desugaring from Q3), the hybrid will in practice bring back Swift's UIKit/SwiftUI-era problems: `[weak self]`, ObservableObject/`@Published`-style annotations. That pulls against P-SWIFT and G3.

### Gaps
- No measured data was found on the proportion of Swift code using `class` vs `struct`, or on how often retain-cycle bugs occur in Swift apps. This would be the key empirical input for the hybrid decision.
- Swift's documentation on ARC (Swift Book "Automatic Reference Counting" chapter) could not be fetched in this session (allowlist). The closure-cycle facts are from a secondary tutorial source.
