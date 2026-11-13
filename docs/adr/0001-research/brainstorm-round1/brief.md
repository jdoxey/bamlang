# Brief: memory management for a new language

## The language

- Natively compiled (probably via LLVM) for macOS, Windows and Linux.
- Charter: `/home/claude/lang-charter/docs/CHARTER.md`. Read it.
- The goals that matter most here:
  - **G1:** much simpler than most languages.
  - **G2:** memory management that doesn't require a garbage collection run.
  - **G3:** no templated types, macros or annotations.
  - **G11:** good DSL/declarative layout support, so closures and callbacks matter.
  - **P-RUST:** Rust's learning curve is too steep.
  - **P-SWIFT:** Swift is too complicated.
  - **P-C:** C is unsafe.
  - **P-PY:** wants OO with an implicit `self`.

## The core difficulty

Lifetimes are often known to the programmer, not the compiler. Lifetimes that don't nest are the hard case: sessions, windows, cache entries, UI callbacks that fire after the scope that registered them has ended. These break simple scope-based schemes.

Every automatic scheme so far either:
- infers lifetimes, which is fragile and causes cycle problems, or
- makes programmers annotate them, which brings the Rust learning curve.

Manual schemes are simple to specify but unsafe.

## Six test scenarios

Every idea must handle all six.

- **(a)** Read a file of unknown length into a list of lines, so the list grows dynamically.
- **(b)** A tree with parent pointers.
- **(c)** A UI callback capturing enclosing state: a button's `onTap` calls `self.save()` and mutates the editor. This is the crux.
- **(d)** A shared mutable cache used by two separate components.
- **(e)** Passing a large list to a function that mutates it.
- **(f)** Sharing data between threads.

## Already covered (don't just repeat these)

- **O1:** Pure ARC with weak refs.
- **O2:** Strict mutable value semantics, Hylo-style (no references; inout/sink params; handles for graphs).
- **O3:** O2 plus copy-on-write, plus one opt-in RC identity type.
- **O4:** Move semantics plus parameter-only borrows plus a built-in RC `shared` kind.
- **O5:** Full Rust ownership with lifetimes.
- **O6:** Single ownership plus generation-checked references (Vale), or runtime-counted borrows (Inko).
- **O7:** ARC plus a backup cycle collector (Nim ORC).
- **O8:** Manual memory with explicit allocators and debug checks (Zig/Odin).
- **Region inference** (MLKit). Needs GC in practice.
- **Scope-bound regions** with move-on-return and `promote` to global. Leaks long-lived objects.
- **Arenas and slot maps** as library tools.

An idea may combine or twist these, but it must contribute something not in the list above.

## Scoring rubric

Used by analysts. Inventors may self-assess.

**Gates** (pass / fail / needs-john):
- G2: no garbage-collection run.
- G3: the model needs no templated types, macros or annotations. Built-in, compiler-known parameterised containers like `List`/`Map` are a pending question; flag if needed.

**Weighted criteria**, each scored 1–5. Total = Σ weight × score / 5, out of 100.

| Criterion | Weight |
|---|---|
| Simplicity & learnability (G1, P-RUST, P-SWIFT). Count the rules a user must learn. | 25 |
| Memory safety (P-C) | 15 |
| Expressiveness for scenarios (b), (c), (d), OO with implicit self (G11) | 15 |
| Implementation risk for a compiler written ~95% by an AI agent on LLVM | 15 |
| Performance & predictability | 10 |
| Concurrency fit | 10 |
| Tooling, debuggability & C FFI | 10 |

Reference totals under the same rubric:

| Option | Total |
|---|---|
| O1 Pure ARC | 83 |
| O4 Simplified ownership | 82 |
| O7 ARC + cycle collector (gated) | 76 |
| O3 Hybrid | 73 |
| O6 Generational / Inko | 71 |
| O2 Strict value semantics | 67 |
| O5 Full Rust (fails G3) | 65 |
| O8 Manual memory | 60 |

## Code

Pseudo-syntax is fine. Label it "illustrative only — not a syntax decision".
