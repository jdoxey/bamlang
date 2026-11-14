# Adversarial review of H1 (Fable 5.2 reviewer, 2026-11-14; condensed)

**Verdict:** accept H1 with fixes after one clarification pass. Corrected scores: H3 71, H1 70.5, H2 69, a tie. The
examples still break it for H1:
- H3's bypass can't be fixed by the subclass author;
- H1's failures can be made loud by tooling;
- with S3, H1 has one rule everywhere.

## Fatal (fixable)

- **F1. Slicing isn't checked, and `self` breaks it.** A `Sub` was accepted for a `Base` parameter.
  - **Fix:** inside a method of `C`, `self` is a borrowed `dyn C`. A plain `Base` rejects subclass values ("write
    `dyn Base`"). A fluent `take self` method can't return plain `self`.
- **F2. A subclass in another module can't construct a base with private fields,** and the checker let
  `Sub(count: -5)` bypass `Base.new`.
  - **Fix:** `Sub(super: try Base.new(count: 3), extra: 1)`. Private means the module plus subclasses. No object
    exists until every field is set.
- **F3. `take self` and drops are unmodelled.** An inherited `Labelled.close` doesn't know about `Badge.icon`. Moving
  a field and then calling `super.close()` double-drops.
  - **Fix:**
    - a tail drop per class descriptor;
    - in a `take self` override, `super.m()` gets `self` whole, with nothing moved before and no use after;
    - drop order is subclass fields, then base fields.

## Serious

- **S1. The 3 am claim.** Calls whose bodies may live in subclasses:
  - the old T3+ corpus: 8 of 25 (32%);
  - H1 on the same portion: 15 of 24 (63%);
  - H1 on the full corpus: 23 of 44.

  Restate John's rule as "the object's *actual* class or an ancestor". The rubric:
  1. Find the class: written in the code, or from the debugger, the trace or the tool for `dyn`/`self`.
  2. Walk up.

  Supporting rules: a mandatory `override` makes overrides one grep; whole-program override listings; traces print
  the concrete class. Tell John the figures.
- **S2. Fragile base class:**
  - a base changes `close` to stop calling `self.text()`;
  - stdlib adds `insert`, bypassing a subclass's `push` invariant;
  - a `push`/`push_all` cycle;
  - an added method breaks subclasses using the name.
  - **Fix:**
    - self-call sets go in the API summary;
    - `api-diff` flags changes;
    - a warning on a self-call cycle.
- **S3. Built-ins behave closed while classes are open** (`push_all` skips the logging `push`).
  - **Fix:** a documented primitive set per built-in. For subclass instances every other method goes through the
    primitives dynamically; an exact `List` keeps the fast path.
  - **To define:** indexing, `for`, patterns and `+=`.
  - **Which built-ins are classes:** containers and Str. Int, Float, Bool, enums, Optional, tuples and Handle are
    values, not classes. Tell John.
- **S4. Exact plain types make subclasses second-class** (a `LoggedNames` can't be passed as `List of Str`).
  - Pools need `Pool of dyn Widget`.
  - **Fix:** state it; lint `pub` parameters of class type; redo a pool example.
- **S5. Whole-program checks fan out through every self-call.**
  - **Fix:** analyse per exact receiver class. Plain receivers resolve self-calls statically, and the compiler emits
    direct calls for them.
- **S6. Two roles: forwarding plus snapshot fails two cases.**
  - The role is unreachable once the value is boxed as `dyn Widget`.
  - It can't serve a `mut` role method.
- **S7. Checker false accepts.** Overrides changing the return type, a parameter type, `fails` or `pub` were accepted.
  - **Fix:** overrides match exactly and don't restate defaults.
  - **Capabilities:** copy, equals, hash and show are derived per exact class, dispatched by vtable, not overridable,
    and equal only within the same class.

## Minor

- **m1.** Lessons text wrong about the sensitivity run.
- **m2.** Fold invariants and performance into the criteria.
- **m3.** Lint forwarding of new methods.
- **m4.** Unrelated same-name methods clutter the grep.
- **m5.** Statics and empty built-in subclass literals.

## Needs-john (does not block)

"May a type have, besides its one parent, extra parents that contain only abstract methods (no bodies, no fields)?"
The reviewer recommends yes: every implementation still sits on the single parent chain. The 63%/32% figure, exact
plain types and the built-in class list go in the issue #5 closing comment.
