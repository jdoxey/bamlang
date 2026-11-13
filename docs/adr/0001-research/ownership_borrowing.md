# Ownership and Borrowing (full Rust-style and simplified variants) as the memory model for the new language

Researched 2026-11-07. Charter goals referenced: G1 (simplicity), G2 (no GC run), G3 (no templated types/macros/annotations), G11 (DSL/declarative layout, so closures and callbacks matter), P-RUST (learning curve too steep), P-C (unsafe).

Notes on evidence quality:
- "Verified" code means the researcher compiled and ran it on 2026-11-07 with `rustc 1.97.0 (2026-07-07)` or `g++ 13.3.0`. The compiler error text quoted below is real output.
- Mojo, Austral, Hylo-style and "hypothetical" code was NOT compiled (no toolchain available). Treat it as a sketch.
- docs.modular.com, verdagon.dev and doc.rust-lang.org could not be fetched in this session (allowlist). Mojo and Vale details come from secondary pages, flagged where used.

---

## Q1. Learnability evidence: what do surveys and studies measure?

### Takeaway
The measured evidence agrees across sources. Ownership, borrowing, references and lifetimes are the main beginner hurdle in Rust. Most developers get past it in roughly 2 to 4 months (Google: about a third in 2 months or less, over half within 4). Experts then report async, plus the mix of async, generics and lifetimes, as the bigger long-term pain. Better teaching gives only a modest gain (+9% on an ownership test), so the difficulty is not just poor documentation.

### Cited Findings
**Google internal (2022 data, published June 2023), over 1,000 Google developers who committed Rust code in 2022**
- "a third of respondents become as productive using Rust as other languages in two months or less". Within four months that rose to over 50%. — [Google Open Source Blog, "Rust fact vs. fiction"](https://opensource.googleblog.com/2023/06/rust-fact-vs-fiction-5-insights-from-googles-rust-journey-2022.html)
- "more than 2/3 of respondents are confident in contributing to a Rust codebase within two months or less". — [same](https://opensource.googleblog.com/2023/06/rust-fact-vs-fiction-5-insights-from-googles-rust-journey-2022.html)
- The top three hardest areas, in the order the post lists them: **macros, ownership and borrowing, async programming**. — [same](https://opensource.googleblog.com/2023/06/rust-fact-vs-fiction-5-insights-from-googles-rust-journey-2022.html)
- Slow builds were "by far the #1 reported challenge". Only a little over 40% found build speed acceptable. — [same](https://opensource.googleblog.com/2023/06/rust-fact-vs-fiction-5-insights-from-googles-rust-journey-2022.html)
- Caveat: the sample is Google engineers with mentoring and internal training. It is not a random developer population.

**Crichton, Gray, Krishnamurthi, "A Grounded Conceptual Model for Ownership Types in Rust", OOPSLA 2023 (also a CACM Research Highlight)**
- Main finding: learners struggle to connect Rust's static semantics (what the borrow checker rejects) with its dynamic semantics (what would actually go wrong at run time). For example, they could not tell whether a rejected program would really have undefined behaviour. — [Brown CEL paper page](https://cel.cs.brown.edu/paper/ownership-conceptual-model/)
- The authors propose a model that explains borrow checking as flow-sensitive permissions on paths into memory. They built the "Ownership Inventory" test, a compiler plugin that visualises the model, and a new ownership chapter for the Rust Book. — [same](https://cel.cs.brown.edu/paper/ownership-conceptual-model/)
- The new teaching raised Ownership Inventory scores by an average of **9% (N = 342, d = 0.56)**. — [same](https://cel.cs.brown.edu/paper/ownership-conceptual-model/)

**Coblenz et al., randomized controlled trial of the Bronze garbage collector for Rust (arXiv 2110.01098; the researcher believes this is the ICSE 2022 paper, but the title and venue were not confirmed in this session)**
- 428 students took part in some way. 333 were randomly assigned (139 Bronze GC, 194 traditional Rust). 1,120 surveys were completed. — [arXiv 2110.01098](https://arxiv.org/pdf/2110.01098)
- On the aliasing task, the **median time was 4 h with GC vs 12 h without (p < .001)**. GC users were also significantly more likely to finish it (p ≈ .006). There was no significant difference on the ownership task completion rate or on total time. — [same](https://arxiv.org/pdf/2110.01098)
- Of 1,143 coded "challenge" comments, 340 were about references (204 of them about **lifetimes**), 199 about ownership (76 about borrowing), 100 about interior mutability, 83 about dynamic borrowing and 70 about mutability. — [same](https://arxiv.org/pdf/2110.01098)
- Traits and async were not discussed as challenges. — [same](https://arxiv.org/pdf/2110.01098)

**Fulton et al., "Benefits and Drawbacks of Adopting a Secure Programming Language: Rust as a Case Study", SOUPS 2021 (16 interviews, 178 survey responses)**
- 59% of surveyed participants found Rust harder to learn than other languages. One interviewee described "a near-vertical learning curve". Seven interviewees named the borrow checker and the shift in programming paradigm as the biggest learning challenges. — [NSF PAR copy](https://par.nsf.gov//servlets/purl/10357735)
- Time to write programs that compile without frequent `unsafe`: 27% under 1 week, 41% 1 week to 1 month, 25% 1 to 6 months. — [same](https://par.nsf.gov//servlets/purl/10357735)
- 55% said they spend longer getting Rust code to compile than code in a language they know well. 89% said they spend less time debugging compiled Rust code. 92% rated Rust's error messages good or very good. 99% would use Rust again. — [same](https://par.nsf.gov//servlets/purl/10357735)
- 72% had used `unsafe`, but only 28% reported an `unsafe`-review process at their employer. — [same](https://par.nsf.gov//servlets/purl/10357735)
- The authors recommend teaching ownership and borrowing step by step, and suggest a garbage-collected Rust variant as a learning tool. — [same](https://par.nsf.gov//servlets/purl/10357735)

**Rust annual surveys (self-selected respondents, mostly existing users)**
- 2025 survey (run Nov 17 to Dec 17 2025, published Mar 2 2026): 7,156 completed. — [Rust Blog, 2025 State of Rust Survey](https://blog.rust-lang.org/2026/03/02/2025-State-Of-Rust-Survey-results)
- 2025 worries: "Rust may become too complex" **41.6%** (45.2% in 2024). Not enough industry usage 42.1%. 56.8% said they were productive with Rust (53.5% in 2024). — [InfoWorld](https://www.infoworld.com/article/4139528/rust-developers-have-three-big-worries-survey.html)
- 2024 survey, via secondary coverage: **31%** of non-users (n = 327) said Rust is "too difficult". **24%** of people who stopped using Rust (n = 348) said it was "too difficult to learn". — [i-programmer](https://i-programmer.info/news/98-languages/17840-state-of-rust-survey-2024-results.html). The primary page was not readable in this session.
- The text of the 2025 results post contains no breakdown of difficulty by feature (borrow checker, lifetimes, traits, async). Those charts are images. — [Rust Blog 2025](https://blog.rust-lang.org/2026/03/02/2025-State-Of-Rust-Survey-results)

**Rust Vision Doc team, "Rust's challenges don't disappear with experience: they evolve" (Jack Huey, path dated 2026-03-20; qualitative interviews)**
- Beginners struggle with ownership. Experienced developers "basically never cite the borrow checker itself as a frustration". — [HackMD, Rust Vision Doc](https://hackmd.io/@rust-vision-doc/rJKYOjIrWx)
- Async is the most-cited expert pain point. One developer described "a significant learning gap between basic Rust and async programming", which the post calls a "chasm of sadness". — [same](https://hackmd.io/@rust-vision-doc/rJKYOjIrWx)
- Combining async, generics and lifetimes makes the types "so complicated that you basically have to be some sort of Rust god". — [same](https://hackmd.io/@rust-vision-doc/rJKYOjIrWx)
- No sample size is reported. — [same](https://hackmd.io/@rust-vision-doc/rJKYOjIrWx)

### Inferences
- **The learning cost is front-loaded.** Most people get through it in about 2 to 4 months (Google, SOUPS). It is not permanent: experts stop citing the borrow checker. Steelman framing: P-RUST is mostly a ramp-up cost, not a daily-use cost.
- **The cost is still real, and better teaching only trims it.** +9% (d = 0.56) is a medium effect. It does not flatten the curve.
- **Shared mutable state (aliasing) is where most of the time goes.** In the Bronze trial, a GC cut the aliasing task from 12 h to 4 h. G2 rules out a GC, but this points to where the cost sits.
- **The numbers conflict somewhat.** Google says a third were productive in 2 months or less. SOUPS says 68% could write mostly-safe compiling code within a month. These are different measures: "as productive as in other languages" versus "compiles without much `unsafe`". Both samples are self-selected.

### Gaps
- The ICSE 2022 paper "Learning and Programming Challenges of Rust: A Mixed-Methods Study" (Zhu et al., Penn State) was found, but its numbers were not. The artifact repository only describes method and categories: lifetime violations split into intra-procedural, inter-procedural and syntax errors, and ownership violations split into move and borrow violations. — [GitHub artifact](https://github.com/system-pclub/rust-programming-challenges), [ICSE page](https://conf.researchr.org/details/icse-2022/icse-2022-papers/127/Learning-and-Programming-Challenges-of-Rust-A-Mixed-Methods-Study). A likely full-text copy is at [par.nsf.gov 10321050](https://par.nsf.gov/servlets/purl/10321050) (not read).
- No 2024 or 2025 Rust-survey breakdown by feature was readable as text. The 2020 survey post (which reportedly ranked lifetimes as hardest) could not be read: the redirect was not followed.
- No newer Google figures (2024 to 2026) on ramp-up time were found. The widely reported 2024 claim that Rust teams are "twice as productive as C++ teams" exists ([The Register, 2024](https://www.theregister.com/2024/03/31/rust_google_c/?td=rt-3a)) but was not read in this session.

---

## Q2. Which parts of Rust's difficulty come from ownership and borrowing, and which from lifetimes in structs, traits/generics/macros or async?

### Takeaway
If you remove what the charter already bans (macros, generics, traits, annotations) and what is a separate decision (async), a large core remains that is ownership itself: moves, aliasing-XOR-mutation, reference lifetimes, interior mutability. In the Bronze trial, references, lifetimes, ownership and interior mutability make up most of the coded challenges. Rust's lifetimes are also *type parameters* (`Parser<'a>`), and its escape hatches (`Rc<T>`, `RefCell<T>`, `Arc<Mutex<T>>`) and thread-safety markers (`Send`/`Sync` traits) are generic types and traits. So copying Rust's ownership design literally would clash with G3 in several places.

### Cited Findings
- Google's top three hardest areas mix the two kinds: macros (banned by G3), ownership and borrowing (the core of this option), async (a separate decision). — [Google OSS blog](https://opensource.googleblog.com/2023/06/rust-fact-vs-fiction-5-insights-from-googles-rust-journey-2022.html)
- In the Bronze trial, 340 of 1,143 challenge comments were about references (204 lifetimes), 199 about ownership, 100 interior mutability, 83 dynamic borrowing, 70 mutability. Traits and async were not raised. — [arXiv 2110.01098](https://arxiv.org/pdf/2110.01098)
- For experts, async is the main pain point. Lifetimes become a problem mainly in combination with async and generics. — [Rust Vision Doc](https://hackmd.io/@rust-vision-doc/rJKYOjIrWx)
- Rust's own 2026 roadmap lists the borrow-checker pain points it is still fixing:
  - conditional borrows (Polonius),
  - partial and disjoint borrows of struct fields ("calling `&mut self` methods while borrowing other fields"),
  - self-referential structs,
  - workarounds that cost "restructuring code into free functions, introducing indices instead of references, or adding runtime checks like `RefCell`". — [Rust Project Goals 2026, "The Borrow Checker Within"](https://goals.rust-lang.org/2026/roadmap-borrow-checker-within.html)
- The same roadmap argues that more explicit lifetime syntax (place-based lifetimes like `'self.text`) would make Rust *easier* to learn, because today's errors "force explanations of compiler internals". — [same](https://goals.rust-lang.org/2026/roadmap-borrow-checker-within.html). This is the Rust project's opinion, not a measured result.
- Verified with rustc 1.97.0: lifetime rules leak into closures through defaults. `Box<dyn FnMut()>` silently means `'static`, and the compiler says so: `note: due to object lifetime defaults, Box<dyn FnMut()> actually means Box<(dyn FnMut() + 'static)>` (E0597). — researcher compile test (code in the scenario section, item c).
- Verified: thread safety is expressed through a trait. Sending an `Rc` to a thread fails with `E0277: Rc<i32> cannot be sent between threads safely … the trait Send is not implemented`. — researcher compile test (scenario f).

### Inferences
**What disappears under this charter anyway** (so it should not count against "ownership"):
- macros (G3)
- user-defined generics and trait bounds (G3)
- trait-object lifetime defaults (only exist because of `dyn Trait`)
- async, `Pin`, `Future` (a separate ADR)
- most "lifetimes + generics" combination complexity

**What remains if Rust-style ownership is adopted:**
1. **Move semantics.** Use-after-move errors, and when to clone.
2. **Aliasing XOR mutation.** E0502/E0499 errors, including the "borrow `self` while iterating a field" case (verified, see `bad_partial` below).
3. **Reference lifetimes**, including returning a reference to a local (E0515).
4. **References stored in structs**, which need named lifetime parameters.
5. **Interior mutability** (`RefCell`/`Cell`) and shared ownership (`Rc`/`Arc`/`Weak`) for graphs, caches and callbacks.
6. **Thread-safety rules** (`Send`/`Sync`).

Items 1 to 3 are what the Bronze data and Google's "ownership and borrowing" category measure. Item 4 is where lifetime syntax becomes visible to users. Item 5 is what G11 (callbacks) will hit constantly.

**G3 conflicts.** A Rust-faithful design needs at least one of:
- lifetime parameters on user types (`struct View<'a>`), which are arguably "templated types";
- generic wrapper types (`Rc<RefCell<T>>`);
- trait-based marker types (`Send`).

A G3-compliant variant would have to:
- make borrows second-class, so no lifetimes appear in types (see Q3);
- build shared/interior-mutable ownership into the language as a construct, not a library generic;
- make thread-transferability a built-in property the compiler infers, not a user trait.

**Rough split (researcher estimate, not measured).** For the code this charter targets (UI/DSL, apps, tools, no user generics, no async yet), most remaining Rust-style difficulty would be items 2, 4 and 5. Item 4 can be removed entirely by design (second-class borrows). Items 2 and 5 cannot.

### Gaps
- No study found gives a quantitative percentage split of Rust difficulty across ownership, struct lifetimes, traits/generics and async within one population. The Bronze trial's coding scheme is the closest. It shows references, lifetimes and ownership dominating, but in a course setting with no async.

---

## Q3. Can a language get Rust's guarantees with only second-class borrows (no lifetimes in types)? What is lost?

### Takeaway
Yes, for memory safety without GC. The design pattern is "mutable value semantics": borrows exist only as function parameters and cannot be stored or returned, and sharing is banned instead of mutation. It has been formalised (Hylo/Val) and runs at scale (Swift `inout`). The cost is expressiveness:
- no references stored in structs, no returned slices or views, no borrowing iterators, no self-referential structs;
- any longer-lived sharing (graphs, caches, escaping callbacks) needs reference counting, indices or copy-on-write.

Swift, which started with second-class `inout`, is now adding lifetime dependencies (`@lifetime`, non-escapable `Span`) because views were too limited. That is the main warning sign.

### Cited Findings
- Mutable value semantics "bans sharing instead of mutation". Values form disjoint trees rooted at variables. It allows in-place partial mutation and local reasoning "without a complex type system". — [Racordon, Shabalin, Zheng, Abrahams, Saeta, "Native Implementation of Mutable Value Semantics", ICOOOLPS 2021 (arXiv 2106.12678)](https://ar5iv.labs.arxiv.org/html/2106.12678)
- In that design, references are created implicitly only at function boundaries for `inout` arguments, and only when uniqueness can be proven. They "cannot be stored in variables or object fields". — [same](https://ar5iv.labs.arxiv.org/html/2106.12678)
- How safety is achieved without GC or lifetimes:
  - stack allocation as "static garbage collection";
  - compiler-synthesised destructors for heap-backed arrays and closures;
  - non-escaping, exclusive `inout`;
  - copy-on-write (reference counting) and moves to avoid copies. — [same](https://ar5iv.labs.arxiv.org/html/2106.12678)
- The paper argues that flow-sensitive systems (ownership, capabilities, regions) raise the entry barrier, citing a Rust survey. It contains **no benchmarks**. — [same](https://ar5iv.labs.arxiv.org/html/2106.12678)
- **Austral** keeps references nearly second-class through lexical regions:
  - `&[T, R]` and `&![T, R]` are references tied to a region `R` created by a `borrow … in R do … end` block or anonymously by `&x`;
  - references can't outlive the borrow because the region name can't be written outside its scope, which "avoids the need for sophisticated control-flow analysis". — [Borretti, "How Austral's Linear Type Checker Works"](https://borretti.me/article/how-australs-linear-type-checker-works)
  - Note that Austral's signatures still carry a region parameter (`generic [R: Region]`). — [same](https://borretti.me/article/how-australs-linear-type-checker-works)
- **Swift:**
  - SE-0446 added non-escapable types but deliberately left out returning them from functions and properties.
  - SE-0456 added stdlib properties returning `Span`, using a not-yet-official `@lifetime` attribute.
  - The Language Steering Group worried adoption would be "very limited" without lifetime-dependency support, and in March 2025 considered `@lifetime` a "supported experimental feature" in Swift 6.2. — [Swift Forums, "Experimental support for lifetime dependencies in Swift 6.2 and beyond"](https://forums.swift.org/t/experimental-support-for-lifetime-dependencies-in-swift-6-2-and-beyond/78638); later pitch: [Pitch #3 compile-time lifetime dependency annotations](https://forums.swift.org/t/pitch-3-compile-time-lifetime-dependency-annotations/84968)
- **Mojo** is not purely second-class (secondary source; docs.modular.com not fetched). Escaping references carry lifetime/provenance ("origin") parameters. The lifetimes/provenance proposal describes them as second-class, capability-style markers rather than full Rust regions, which Lattner says makes inference simpler. — [tamnd notes, Mojo 2026 (secondary)](https://tamnd.github.io/brain/research/memory-management/ownership/04_mojo_2026/), citing [modular/modular discussion #338](https://github.com/modular/modular/discussions/338)
- **Rust's view:** its 2026 roadmap says lending iterators "are simply inexpressible without Polonius", and wants *more* expressive lifetimes (internal references, place-based lifetimes). This is the opposite direction from second-class borrows. — [Rust Project Goals 2026](https://goals.rust-lang.org/2026/roadmap-borrow-checker-within.html)

### Inferences
**What second-class borrows keep:**
- no use-after-free or dangling references from borrows;
- no data races on borrowed data (exclusive `inout`);
- deterministic destruction;
- no lifetime syntax anywhere (fits G1, G3).

**What is lost, with what replaces it:**
| Lost capability | Replacement |
|---|---|
| `struct Parser { src: &str }` (borrowed data inside a struct) | own a copy, or store an index/offset |
| Functions returning `&T` / `&mut T` into an argument (`map.get_mut(k)`, `first(list)`) | callbacks or "projections"/subscripts (Hylo-style yield), or return copies or indices |
| Zero-copy views/slices/iterators that outlive a call | indices or language-built-in slice types with compiler-known rules |
| Borrowed data captured in escaping closures (UI callbacks) | escaping closures must own (move) or share (RC) what they capture |

**Swift is the clearest evidence of the limit.** A mainstream language with only second-class `inout` needed first-class-ish lifetimes after about a decade, specifically for safe zero-copy views (`Span`). A charter-compliant design should plan for this from the start: one built-in non-escaping view type with compiler-known rules, rather than user-written lifetimes.

**Hybrid option** (researcher proposal, not found implemented anywhere exactly):
- second-class borrows for parameters;
- a single built-in "view" kind that may be returned only when tied to exactly one parameter (similar to Rust's elision rule "one input lifetime → output gets it" and Swift's `@lifetime(borrow x)`), with that dependency inferred, never written;
- built-in RC with weak references for everything longer-lived.

### Gaps
- No empirical learnability study of Hylo, Austral or Mojo ownership was found. Their simplicity claims are design opinions.
- Hylo's current status in 2026 (release, adoption) was not checked.
- Rust's function lifetime-elision rules could not be fetched from doc.rust-lang.org in this session. Researcher knowledge, unverified here:
  - each elided input reference gets its own lifetime;
  - if there is exactly one input lifetime, it is assigned to all elided outputs;
  - if there is a `&self`/`&mut self`, its lifetime is assigned to elided outputs.
- No corpus measurement ("lifetime elision coverage": what fraction of real Rust signatures need explicit lifetimes) was found. That would be the key number for sizing what second-class borrows lose.

---

## Q4. Performance and predictability: does "zero runtime overhead" hold?

### Takeaway
Borrow checking itself costs nothing at run time and gives deterministic destruction with no GC pauses (fits G2). Real programs pay small, *visible* costs for the escape hatches: refcount updates for `Rc`/`Arc`, atomics for `Arc`, borrow flags and possible panics for `RefCell`, bounds checks for index-based graphs. Approaches that move checks to run time (Vale's generational references) measured about 11% overhead against unsafe code, versus about 25% for naive RC, on one benchmark. The main cost is compile time, not run time.

### Cited Findings
- Verified (rustc 1.97.0): `RefCell` moves the aliasing check to run time. This program compiles with 0 errors and then panics with `RefCell already borrowed`:
  ```rust
  let r = c.borrow(); c.borrow_mut().push(2);
  ```
  — researcher compile test
- Vale generational references, BenchmarkRL terrain generator (secondary summary of verdagon.dev; benchmark date not stated):
  | Mode | Time | Overhead vs unsafe |
  |---|---|---|
  | `unsafe-fast` | 43.82 s | baseline |
  | `naive-rc` | 54.90 s | **+25.29%** |
  | generational refs | 48.57 s | **+10.84%** |

  Newer write-ups summarise "2–10.84% overhead" depending on access patterns. — [tamnd notes on Vale (secondary)](https://tamnd.github.io/brain/research/memory-management/ownership/02_vale_generational_references/), citing [verdagon.dev/blog/generational-references](https://verdagon.dev/blog/generational-references)
- Vale's regions prototype claims to remove checks in tight loops, approaching zero overhead. — same secondary source, citing [Zero-Cost Borrowing with Vale Regions, Part 1](https://vale.dev/blog/zero-cost-borrowing-regions-part-1-immutable-borrowing)
- Compile-time cost: Google's #1 complaint was slow builds (only about 40% found speed acceptable). In 2025, 27.9% of survey respondents called slow compilation a big problem. — [Google OSS blog](https://opensource.googleblog.com/2023/06/rust-fact-vs-fiction-5-insights-from-googles-rust-journey-2022.html); [InfoWorld 2025 survey](https://www.infoworld.com/article/4139528/rust-developers-have-three-big-worries-survey.html)
- Polonius alpha (the next Rust borrow checker) does at least as much work as NLL. The worst regression seen on borrow-heavy crates was "2-3x" in borrow-check time. — [Rust Blog, 2026-08-04](https://blog.rust-lang.org/2026/08/04/enabling-polonius-alpha-on-nightly)
- Austral claims memory and resource safety "without runtime checks or garbage collection", with performance comparable to C. — [Borretti](https://borretti.me/article/how-australs-linear-type-checker-works). This is a design claim; no benchmark was found.

### Inferences
- Rust's build-time problem comes mostly from monomorphised generics, macros and LLVM, not the borrow checker. Under G3 (no generics or macros), a borrow-checked language would probably compile much faster than Rust. This is an inference; no measurement of how build time splits between borrow checking and other phases was found.
- **Predictability favours ownership over tracing GC** (G2): frees happen at known points. RC adds cost proportional to pointer copies. RC cycles leak unless weak references are used.
- Mojo is reported to destroy values "ASAP" (after last use) rather than at end of scope. That is researcher knowledge, not verified this session. It affects how predictable destructor timing feels.

### Gaps
- No primary benchmark comparing Rust `Rc<RefCell>`-heavy code with equivalent GC or arena code was found.
- Vale's numbers come through a secondary source, and the benchmark date is unknown.

---

## Q5. Graphs, parent pointers, shared caches, callbacks: which escape hatches are needed?

### Takeaway
Every ownership-based language needs at least two escape hatches beyond plain ownership and borrows:
1. **Shared ownership with weak references.** Rust `Rc`/`Weak`/`Arc`; C++ `shared_ptr`/`weak_ptr`.
2. **Either interior mutability with runtime checks or an arena/index pattern.**

Rust's own roadmap admits that the workarounds (free functions, indices, `RefCell`) are a cost. For G11, escaping UI callbacks that capture and mutate enclosing state are the worst case. In Rust they require the `Rc<RefCell<…>>` + clone-before-move pattern, or the `'static` default bites.

### Cited Findings
- Rust 2026 roadmap: the current workarounds are "restructuring code into free functions, introducing indices instead of references, or adding runtime checks like `RefCell`". Self-referential structs are not supported yet. — [Rust Project Goals 2026](https://goals.rust-lang.org/2026/roadmap-borrow-checker-within.html)
- Verified compiler errors, rustc 1.97.0 (full code in the next section):
  - Callback capturing `&mut doc`, then reading `doc`: `E0502 cannot borrow doc.saved as immutable because it is also borrowed as mutable`.
  - Registering a boxed callback that borrows a local: `E0597 doc does not live long enough` plus a note that `Box<dyn FnMut()>` means `'static`.
  - Iterating `e.lines` while calling `e.record(...)` (`&mut self`): `E0502 cannot borrow e as mutable because it is also borrowed as immutable`. This is the partial-borrow problem Rust plans to fix with "view types".
  - Spawning a thread that borrows a local: `E0373 closure may outlive the current function`.
  - Sending `Rc` to a thread: `E0277 … Send is not implemented`.
- Bronze trial: aliasing-heavy work took a median of 12 h without GC versus 4 h with GC. — [arXiv 2110.01098](https://arxiv.org/pdf/2110.01098)
- Austral's linear rules are "very onerous" by the author's own words. A `length` function must either consume a linear list or return it along with the length. The checker rejects some safe loops instead of adding special cases. — [Borretti](https://borretti.me/article/how-australs-linear-type-checker-works)
- C++ baseline (verified, g++ 13.3 with `-Wall -Wextra`): a lambda capturing a local by reference, returned inside `std::function`, and use-after-move of `unique_ptr` both compile with **zero warnings**. AddressSanitizer catches it only at run time: `stack-use-after-return`. — researcher compile test

### Inferences
**Minimal escape-hatch set for a charter-compliant ownership language** (G3 means these must be built-in language constructs, not generic library types):
| Need | Construct |
|---|---|
| Graphs, parent pointers, caches, escaping callbacks | a built-in shared reference kind with refcounting and weak references |
| Rust's `RefCell` | a rule for mutating through shared references: either runtime-checked exclusivity like Swift's dynamic exclusivity enforcement, or single-threaded "shared mutable" objects |
| Large graphs | arenas/indices (library-level, but indices are unchecked against stale use unless generations are added, as in Vale) |

**For G11 specifically.** Declarative UI code is mostly escaping closures over shared mutable state, which is exactly where borrow checking helps least. In practice a Rust-style UI DSL becomes an `Rc<RefCell>` (or signal/arena) DSL. So even if ownership is chosen, the UI layer will in practice run on RC. That points to "ownership + built-in RC" as the realistic design, not "pure borrow checking".

### Gaps
- No user study on closures and callbacks in Rust UI frameworks was found.
- Vale's "group borrowing" (reportedly what its author is exploring in 2026, per a secondary source) was not examined.

---

## Q6. How hard is a borrow checker for a small team or an autonomous agent to implement?

### Takeaway
The range is wide:
- **Austral-style linear checking:** about 600 lines of OCaml.
- **Second-class/MVS exclusivity checking:** small (scope-based, no lifetime inference).
- **Rust-grade flow-sensitive borrow checking with lifetime inference:** a decade-long research and engineering effort for a large team. Polonius alpha reached nightly in August 2026 and is targeted to stabilise before the end of 2026, still not a superset of the original Polonius design.

For a project built about 95% by an AI agent, only the simpler end is realistic to get correct.

### Cited Findings
- Austral's linearity checker is "600 lines of OCaml", with the core algorithm "a page of text" and the code "less than 1k lines". The author deliberately rejects special-case heuristics to keep it maintainable. — [Borretti](https://borretti.me/article/how-australs-linear-type-checker-works)
- Polonius alpha:
  - Status: enabled on nightly only (stable still uses NLL), stabilisation targeted for before end of 2026.
  - It adds "flow-sensitive borrow checking of lifetime outlives relationships".
  - It is not a full superset of original Polonius: a linked-list traversal compiles under the old Polonius but not under alpha.
  - Worst observed borrow-check regression: 2 to 3x.

  — [Rust Blog, "Enabling the next iteration of the borrow checker on nightly", 2026-08-04](https://blog.rust-lang.org/2026/08/04/enabling-polonius-alpha-on-nightly)
- Polonius is called Rust's next-generation borrow checker that "lands on nightly after ten years". — [besthub.dev (secondary, headline only)](https://www.besthub.dev/articles/polonius-alpha-rust-s-next-gen-borrow-checker-lands-on-nightly-after-ten-years-c1edc733e330)
- Code that NLL (stable Rust) rejects but Polonius accepts, a conditional return of a borrow:
  ```rust
  fn get_mut_or_default<'r, K: Hash + Eq + Copy, V: Default>(
      map: &'r mut HashMap<K, V>, key: K) -> &'r mut V {
      match map.get_mut(&key) {
          Some(value) => value,
          None => { map.insert(key, V::default()); map.get_mut(&key).unwrap() }
      }
  }
  ```
  — [Rust Blog 2026-08-04](https://blog.rust-lang.org/2026/08/04/enabling-polonius-alpha-on-nightly)
- Carbon (Google's C++ successor) had not designed its memory-safety model as of its 2025 roadmap:
  - It said it "haven't been focused on the safe side of Carbon for several years".
  - The plan is to follow Rust's direction, "using the type system to ensure compile-time guarantees of safety", with no GC or RC.
  - Adding safety pushes 0.1 out "by at least a year": 2026 at the earliest, called "very ambitious".
  - 1.0 is beyond 2028.

  — [Carbon roadmap](https://docs.carbon-lang.dev/docs/project/roadmap.html); [Proposal p4880, Safety milestones and a 2025 roadmap](https://docs.carbon-lang.dev/proposals/p4880.html)
- Mojo uses a flow-sensitive last-use analysis enforcing aliasing-XOR-mutation per stack slot (secondary). The compiler was closed source as of May 2026, with open-sourcing committed for fall 2026 (secondary; not verified). — [tamnd Mojo 2026 notes](https://tamnd.github.io/brain/research/memory-management/ownership/04_mojo_2026/)
- Vale development is reported paused as of May 2026 (secondary). Its author worked on Mojo at Modular from July 2024 to December 2025. — [tamnd Vale notes](https://tamnd.github.io/brain/research/memory-management/ownership/02_vale_generational_references/)

### Inferences
- **Carbon is a strong signal.** A well-funded Google team with a C++-expert design lead treated compile-time memory safety as a multi-year design problem it had not solved by 2025.
- **What an autonomous agent can realistically build:**
  - moves and use-after-move detection (straightforward dataflow);
  - second-class borrows with scope-based exclusivity (simple, no inference);
  - built-in RC with weak references;
  - optionally a single inferred "returned view tied to one parameter" rule.
- **Rust-level NLL/Polonius-style lifetime inference is a soundness-critical research artifact.** Bugs in it are memory-safety holes, so it is a poor fit for agent-written code without a formal model and a large test corpus.
- **Error message quality is a separate, large cost.** 92% of SOUPS respondents praised Rust's errors ([SOUPS 2021](https://par.nsf.gov//servlets/purl/10357735)). That quality represents years of work, and the Crichton study shows learners need to be told *why* a program is rejected, not just *that* it is.

### Gaps
- No public numbers were found for the size of rustc's borrow checker (`rustc_borrowck`), Hylo's checker, or Mojo's checker. A line count of `compiler/rustc_borrowck` in the rust-lang/rust repo would answer this cheaply.
- Carbon's 2026 roadmap, if published, was not found. The roadmap page fetched still described 2025 objectives.

---

## Variant survey: how each design works

### Takeaway
The designs sit on one spectrum, from checked-and-expressive to unchecked:
- **Rust:** full lifetimes, most expressive, steepest.
- **Mojo:** argument conventions plus inferred origins; lifetimes mostly hidden.
- **Austral:** linear types plus lexical regions; tiny checker, onerous to write.
- **Hylo/MVS:** second-class only; simplest rules, least expressive.
- **Vale:** runtime generational checks plus optional regions; flexible, but about 2 to 11% overhead and paused.
- **Carbon:** undecided.
- **C++ RAII:** ownership by convention, unchecked (P-C, P-CPP).

### Cited Findings
- **Rust.**
  - Single owner, moves by default, `&T` (shared) and `&mut T` (exclusive) borrows with lifetimes inferred inside functions and elided or annotated in signatures.
  - Escape hatches: `Rc`/`Weak`/`RefCell` (single-thread), `Arc`/`Mutex` (multi-thread), `unsafe`.
  - All verified by compiling the scenario code below (rustc 1.97.0).
  - The stable checker is NLL. Polonius alpha is on nightly. — [Rust Blog 2026-08-04](https://blog.rust-lang.org/2026/08/04/enabling-polonius-alpha-on-nightly)
- **Mojo** (secondary source; docs.modular.com not fetchable).
  - Argument conventions: `read` (formerly `borrowed`, immutable borrow, default for `fn`), `mut` (formerly `inout`), `var` (formerly `owned`; callee takes ownership).
  - `x^` explicitly transfers ownership. Moves can also be inserted implicitly at last use.
  - The borrow checker enforces aliasing-XOR-mutation.
  - Example: `matmul(a, b, out)` needs no `&` sigil at the call site.

  — [tamnd Mojo 2026 notes](https://tamnd.github.io/brain/research/memory-management/ownership/04_mojo_2026/)
  - Researcher knowledge, unverified: `out` is used for initialisers, `deinit` for destructors, and "origins" (renamed from "lifetimes" in 2024) appear as `ref [origin]` on returned references and in `Pointer[T, origin]`. They are usually inferred.
- **Austral.**
  - Linear types: each value used "once and exactly once".
  - 11 rules, including: no consumption inside loops of outer variables; branches must agree; everything consumed before `return`.
  - Borrows `&x` / `&!x` scoped by regions.
  - Goals: no leaks, no GC, no runtime checks, capability-based security, "fits-in-head simplicity".

  — [Borretti](https://borretti.me/article/how-australs-linear-type-checker-works)
- **Hylo/Val (mutable value semantics).** Second-class `inout`, no storable references, copy-on-write for efficient value types. — [Racordon et al. 2021](https://ar5iv.labs.arxiv.org/html/2106.12678)
- **Vale.** Single ownership plus non-owning "generational references" checked at dereference: about 10.84% overhead vs unsafe, compared with +25.29% for naive RC. Region borrowing is meant to remove those checks. — [tamnd Vale notes (secondary)](https://tamnd.github.io/brain/research/memory-management/ownership/02_vale_generational_references/); [Vale regions part 1](https://vale.dev/blog/zero-cost-borrowing-regions-part-1-immutable-borrowing)
- **Carbon.** Intends a Rust-like type-system approach. Design not done as of the 2025 roadmap. — [Carbon roadmap](https://docs.carbon-lang.dev/docs/project/roadmap.html)
- **C++ `unique_ptr`/RAII.** Same ownership shape as Rust, with no checking. Dangling lambda captures and use-after-move compile without warnings (verified: g++ 13.3 `-Wall -Wextra`; caught only by ASan at run time). — researcher compile test

### Inferences
- **Charter fit.**
  - Rust: fails G1 and P-RUST, and strains G3 (lifetime parameters, generic wrappers, `Send`/`Sync` traits).
  - Mojo: closer, since conventions are keywords on parameters, not types. But origins are a form of lifetime parameter.
  - Austral: G1 for the *compiler*, not for the *user*.
  - Hylo/MVS: the best G1/G3 fit on paper, but the least proven at scale.
  - Vale: closest to "simple for the user", but has runtime cost and an inactive project.
  - C++ RAII: fails P-C, and P-CPP for unchecked safety.
- **Mojo's renaming history** (`borrowed`/`inout`/`owned` → `read`/`mut`/`var`) is itself evidence that naming ownership concepts so they are easy to learn takes iteration.

### Gaps
- Primary Mojo manual text was not read. Keyword names (`var` vs `owned`, `out`, `deinit`) and the origin syntax should be checked against https://docs.modular.com/mojo/manual/values/ownership before quoting them in the ADR.
- Primary Vale (verdagon.dev) pages were not readable.

---

## Scenario code examples (a)–(f)

### Takeaway
Rust handles (a), (e) and (f) well: plain ownership and borrows, zero-cost, and the compiler catches real data races. It is painful for (b), (c) and (d), which need `Rc`/`Weak`/`RefCell` or arenas, clone-before-move closures and runtime-checked borrows. Scenario (c), the UI callback, is the one G11 will hit most often. C++ writes all six more briefly but checks none of them.

### Cited Findings
All Rust below **compiles and runs** (rustc 1.97.0, edition 2021, verified 2026-11-07). Output, in order:
```
1 lines | kid's parent is root (1 children) | arena: kid -> root | saved=true text=hi | b sees Some("v") | [0.25, 0.5, 1.0] | counter=4 | [10, 20, 300, 400]
```
Failing variants show the real compiler error codes. — researcher compile tests in `/tmp/ob/*.rs`, `/tmp/ob/cpp.cpp`.

**(a) Read a file of unknown length into a list of lines**
```rust
// Rust (verified)
fn read_lines(path: &str) -> io::Result<Vec<String>> {
    let f = fs::File::open(path)?;
    io::BufReader::new(f).lines().collect()
}
```
```cpp
// C++ (verified)
std::vector<std::string> read_lines(const std::string& p){
  std::ifstream f(p); std::vector<std::string> out; std::string l;
  while (std::getline(f, l)) out.push_back(l);
  return out; }
```
Ownership notes:
- Ownership is invisible here. The `Vec` is returned by move, with no lifetimes. This is the case where ownership costs nothing.
- The Rust version relies on traits and generics (`collect()` into `io::Result<Vec<_>>` via `FromIterator`) and on the `?` operator. Under G3 the equivalent needs built-in list types and a non-generic API.

**(b) Tree with parent pointers**
```rust
// Rust option 1 (verified): Rc children, Weak parent, RefCell for mutation
struct Node {
    name: String,
    parent: RefCell<Weak<Node>>,
    children: RefCell<Vec<Rc<Node>>>,
}
fn add_child(parent: &Rc<Node>, name: &str) -> Rc<Node> {
    let child = Rc::new(Node { name: name.to_string(),
        parent: RefCell::new(Rc::downgrade(parent)),
        children: RefCell::new(Vec::new()) });
    parent.children.borrow_mut().push(Rc::clone(&child));
    child
}
// read parent: kid.parent.borrow().upgrade().unwrap()

// Rust option 2 (verified): arena + indices
struct Tree { nodes: Vec<ANode> }
struct ANode { name: String, parent: Option<usize>, children: Vec<usize> }
```
```cpp
// C++ (verified): unique_ptr children, raw non-owning parent; nothing stops a dangling parent
struct Node { std::string name; Node* parent = nullptr;
  std::vector<std::unique_ptr<Node>> children; };
```
Pain points:
- **Rust option 1** stacks three generic wrappers (`RefCell<Weak<…>>`, `RefCell<Vec<Rc<…>>>`) plus `upgrade().unwrap()`. Runtime borrow flags and refcounts make this not zero-cost, and it is G3-hostile as written.
- **Rust option 2** is simple and fast, but indices can go stale (the "logical dangling" problem). This is why Vale adds generations.
- **C++** is shortest, but has no safety at all.

**(c) UI callback capturing enclosing state (button `onTap` calls `save()`)**
```rust
// Rust naive (FAILS): E0502 cannot borrow `doc.saved` as immutable because it is also borrowed as mutable
let mut doc = Document { saved: false };
let mut button = Button { on_tap: Box::new(|| doc.save()) };
println!("{}", doc.saved);
(button.on_tap)();

// Rust naive, 'static registration (FAILS): E0597 `doc` does not live long enough
// note: due to object lifetime defaults, `Box<dyn FnMut()>` actually means `Box<(dyn FnMut() + 'static)>`
fn register(_f: Box<dyn FnMut()>) {}
register(Box::new(|| doc.save()));

// Rust working (verified): shared ownership + interior mutability + clone-before-move
let doc = Rc::new(RefCell::new(Document { text: "hi".into(), saved: false }));
let doc_for_button = Rc::clone(&doc);
let button = Button { on_tap: Box::new(move || doc_for_button.borrow_mut().save()) };
(button.on_tap)();
```
```cpp
// C++ (verified): compiles with zero warnings under -Wall -Wextra; ASan reports stack-use-after-return at runtime
Button makeButton(){ Document doc; return Button{ [&doc]{ doc.save(); } }; }
```
```text
// Hypothetical second-class-borrow language (NOT a real language; illustrative)
doc := shared Document()           // built-in RC kind, no generic wrapper
button := Button(onTap: { doc.save() })   // escaping closure may capture `shared` values, never borrows
```
Pain points:
- This is the G11 core case. In Rust it costs three concepts at once: `Rc`, `RefCell` and `move` plus clone.
- A second-class-borrow language must *forbid* capturing borrows in escaping closures. It then needs a built-in shared kind for this, which is effectively RC.

**(d) Shared mutable cache used by two components**
```rust
// Rust (verified)
struct Cache { map: HashMap<String, String> }
struct ComponentA { cache: Rc<RefCell<Cache>> }
struct ComponentB { cache: Rc<RefCell<Cache>> }
let cache = Rc::new(RefCell::new(Cache { map: HashMap::new() }));
let a = ComponentA { cache: Rc::clone(&cache) };
let b = ComponentB { cache: Rc::clone(&cache) };
a.cache.borrow_mut().map.insert("k".into(), "v".into());
b.cache.borrow().map.get("k");
```
```rust
// Rust runtime failure mode (verified: compiles with 0 errors, panics "RefCell already borrowed")
let r = c.borrow(); c.borrow_mut().push(2);
```
Pain points:
- A shared mutable cache is inherently outside aliasing-XOR-mutation, so the static check gives up and becomes a runtime check that can panic.
- The alternative is threading `&mut Cache` through every call (context passing), which works only if the components don't store the cache.

**(e) Passing a large list to a function that mutates it**
```rust
// Rust (verified): zero-copy exclusive borrow
fn normalise(v: &mut Vec<f64>) {
    let max = v.iter().cloned().fold(f64::MIN, f64::max);
    for x in v.iter_mut() { *x /= max; }
}
normalise(&mut big);
```
```mojo
# Mojo (UNVERIFIED sketch, keyword per secondary source): no sigil at call site
fn normalise(mut v: List[Float64]): ...
normalise(big)
```
```text
// Hylo/Swift-style second-class inout (illustrative): same guarantee, no lifetimes needed
fun normalise(_ v: inout Array<Float64>) { ... }
normalise(&big)
```
Ownership notes:
- This is ownership and borrowing's best case: no copy, no RC, and the compiler proves no aliasing.
- Second-class borrows handle it fully, so nothing is lost versus Rust here.

**(f) Sharing data between threads**
```rust
// Rust (verified): shared counter
let counter = Arc::new(Mutex::new(0));
let handles: Vec<_> = (0..4).map(|_| { let c = Arc::clone(&counter);
    thread::spawn(move || { *c.lock().unwrap() += 1; }) }).collect();
for h in handles { h.join().unwrap(); }

// Rust (verified): scoped threads mutate disjoint halves with no Arc/Mutex
thread::scope(|s| {
    let (left, right) = data.split_at_mut(2);
    s.spawn(move || for x in left.iter_mut() { *x *= 10 });
    s.spawn(move || for x in right.iter_mut() { *x *= 100 });
});

// FAILS: E0373 closure may outlive the current function, but it borrows `v`
let h = thread::spawn(|| v.push(4));
// FAILS: E0277 `Rc<i32>` cannot be sent between threads safely ... `Send` is not implemented
thread::spawn(move || println!("{}", r));
```
Pain points and benefits:
- **Benefit:** Rust's strongest selling point. Data races become compile errors, and scoped threads give zero-cost parallel mutation of disjoint data.
- **Pain:** `Arc<Mutex<T>>` and `Send`/`Sync` are generic types and traits (G3 conflict).
- A charter-compliant design would need built-in "sendable" inference plus a built-in lock/actor construct.

### Inferences
**Where Rust-style ownership pays off and where it costs:**
| Scenarios | Fit |
|---|---|
| (a), (e), (f) | Ownership pays for itself |
| (b), (c), (d) | Costs most: always resolved with RC, interior mutability or indices, never by borrowing |

**Implication for the ADR.** The fair way to score this option is a hybrid of:
- moves plus second-class borrows (covers a, e, and scoped f);
- built-in RC/weak for b, c, d;
- built-in thread-transfer rules for f.

Pure Rust-style borrow checking with lifetimes adds expressiveness mainly for zero-copy views and borrowed iterators. Those features have the steepest learning cost and the greatest G3 friction.

### Gaps
- Mojo, Austral and Hylo versions of (b), (c), (d) and (f) were not compiled. Mojo's thread-safety story (whether it has `Send`-like checks) was not researched.
- No real-world Rust UI framework (Dioxus, Leptos, Slint, iced) was examined to see how its signals/arena designs avoid the `Rc<RefCell>` problem in (c). That would be the most relevant prior work for G11.
