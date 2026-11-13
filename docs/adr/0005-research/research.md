# D5 research: types and OO (Sonnet researcher, 2026-11-13; condensed)

**[unverified]** marks claims without a fetched source. Recheck quotes before citing them.

## Per language

**Go.**
- **Mechanism:** methods on any named type; implicit structural interfaces; embedding, not inheritance
  (https://go.dev/doc/faq, https://go.dev/doc/effective_go).
- **Dispatch is invisible:** `x.M()` looks the same whether the call is static or dynamic.
- **The nil-in-interface trap** (Go FAQ; https://golang.org/issue/56364).
- **Every method needs a value-or-pointer receiver choice** ("If in doubt, use a pointer",
  https://go.dev/wiki/CodeReviewComments).
- **Accidental satisfaction:** the fix is an opt-in `var _ I = T{}`.

**Rust.**
- **Mechanism:** traits and `impl`; no inheritance. Static (generic) versus `dyn` dispatch is visible in the types
  (https://doc.rust-lang.org/book/ch18-02-trait-objects.html).
- **Rules:** dyn-compatibility (E0038) and the orphan rule (https://doc.rust-lang.org/book/ch10-02-traits.html).
- **Fit:** without user generics, only the `dyn` half is available. That traits are hard to learn is only weakly
  supported; the borrow checker is the documented hurdle.

**Swift.**
- **`any`:** made existentials explicit because of their cost
  (https://github.com/apple/swift-evolution/blob/main/proposals/0335-existential-any.md).
- **Silent dispatch modes:** methods added only in extensions dispatch statically, while protocol requirements dispatch
  dynamically. Behaviour depends on the static type (https://oleb.net/blog/2016/06/lily-ballard-swift-dispatch/).
- **Complexity complaints:** opinion only (https://mjtsai.com/blog/2015/05/21/which-features-overcomplicate-swift).

**Java, C# and Kotlin.**
- **Fragile base class:** Bloch's `InstrumentedHashSet`, so prefer composition or `final`
  (https://cs108.epfl.ch/c/i/EffectiveJava_Item18.pdf).
- **How inheritance is used:** mostly subtyping and reuse (Tempero et al. 2013, abstract only).
- **C# default methods:** a class doesn't inherit them.
- **Kotlin:** sealed classes with exhaustive `when`; classes need `open` to be extended
  (https://kotlinlang.org/docs/sealed-classes.html).

**C++.**
- **Slicing:** a derived value copied into a base value loses its derived part
  (https://en.wikipedia.org/wiki/Object_slicing).
- **Other problems:** the diamond; virtual calls can't be inlined.

**Python.** Explicit `self` is kept for decorators, monkeypatching and the `C.meth(foo)` equivalence
(https://neopythonic.blogspot.com/2008/10/why-explicit-self-has-to-stay.html), none of which we have. PEP 544 moved
towards structural protocols.

**Odin, Zig and C.**
- **Odin:** has no methods and no UFCS (`x.f(y)` would be ambiguous with a field named `f`); it builds vtables by
  hand (https://odin-lang.org/docs/faq/).
- **Zig:** structs act as namespaces.

**Objective-C.** Messaging nil silently returns zero, and `init` is two-phase. Both are anti-patterns for R6.

**UFCS and Julia.** UFCS (D, Nim) gives method syntax without a method system, but clashes with function-valued
fields. Julia's multiple dispatch needs generics.

## Cross-cutting

- **`self`:** declare the receiver in the header (`self`, `take self`) and use it implicitly or as `self.x` in the
  body. Relational operations are pool methods (ADR-0001).
- **Structural versus nominal:** structural is cheap but risks accidental satisfaction and poor discovery. Nominal
  shows intent. A middle path is a structural check plus one declaration site.
- **Dispatch visibility:** it is visible in Rust (`dyn`) and Swift (`any`), and invisible in Go, Java and C++.
- **Inheritance:** the harm is in implementation inheritance. Sum types already cover closed hierarchies.
- **Constructors:** private fields at module level, plus `fails` constructor functions in the type's module.
- **Ownership:** an interface value owns its data, so it is a box (a pointer, a vtable and a heap allocation).
  `take self` through a box needs a rule. Value semantics plus inheritance gives slicing.

## Six sketches

1. No methods (Odin).
2. Methods as static sugar, closed world; polymorphism only through enums and records of functions.
3. Nominal interfaces, `dyn` only (Rust-lite).
4. Go-style structural interfaces with a visible `any` at use sites.
5. Sealed hierarchy plus a single-level `open` extension point.
6. A hybrid of 2 and 3: an interface is a named record-of-functions type, filled by an `impl`. Values are an explicit
   `dyn` box. Module-level private fields; `fails` constructors.

## Benchmarks

- **B1:** shapes and their areas, with an open set of shapes from a plugin.
- **B2:** a widget tree with events and third-party widget kinds (`Pool` + `Handle` with boxes, `take self`, default
  behaviour without inheritance).
- **B3:** a `Money`/`Account` data model with private fields, a `fails` constructor, an adversary module, and a method
  on a pool entry.
