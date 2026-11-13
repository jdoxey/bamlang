# ADR-0004: Errors and absence

- **Status:** Accepted
- **Date:** 2026-11-13
- **Tier:** Full (see `docs/PROCESS.md`)
- **Examples:** `docs/examples/errors` (the merged design in `merged/`; rivals in `e1-swift/`, `e2-go/`, `e3-rust/`)
- **Decided by:** Claude (ruling R7). John may veto by opening an issue.

## Context

ADR-0001 introduced traps (a stale `pool[h]`, exclusivity) and the `if x = … else` form. ADR-0002 put `Optional`,
`Result` and sum types in the built-in set. ADR-0003 has crews re-raise child errors. This ADR decides:
- how failures are reported, propagated and handled;
- whether anything can be null;
- what a trap is and where it can be caught.

The research (`0004-research/research.md`) found that every serious design separates bugs (abandon) from recoverable
errors. Go's `try` died because it hid returns inside expressions. Typed errors per module need conversion glue (Rust's
two crates). Null was Hoare's "billion-dollar mistake".

## Charter

| Goal / problem | Effect | Why |
|---|---|---|
| G1 (R6) | serves | One error type and one propagation form. Every exit is marked. 16 rules, counted honestly. |
| G2, R3 | serves | No collector. Traps unwind through tables and run `drop`s; nothing inspects live objects. |
| G3 | serves | `fails` is a keyword meaning `-> Result of T`, not an annotation. No user type parameters. |
| G4 | serves | Propagation is one token, `try`. Context is one clause. |
| G8, G9, G10 | serves | An inline trace per error; tools list every error exit; tests assert traps with `expect_trap` |
| P-C | avoids | No null. Unhandled results are compile errors. A trap in a callback from C aborts instead of unwinding through C. |
| P-GO | avoids | No `if err != nil` blocks; no ignorable errors; no nil interface |
| P-JAVA | avoids | No checked exception lists: one error type, and `fails` is just a return type |
| P-SWIFT, P-RUST | avoids | No typed-throws variants and no conversion glue. The cost is less precise matching than Rust's typed enums. |

## Criteria

From `0004-research/criteria.md`, written before the options:

| Criterion | Weight |
|---|---|
| Can't be ignored | 20 |
| Transparency | 20 |
| Simplicity | 15 |
| Clean syntax | 15 |
| Context | 10 |
| Fit with earlier ADRs | 10 |
| Implementation risk | 5 |
| Performance | 5 |

The "no unwinding tables" anchor under Implementation risk is relaxed for traps (review S5), which is recorded here.

## Options considered

There were 14 ideas: six research sketches, four from a "reader at 3am" lens and four assumption-breaking
(`0004-research/ideas.md`, `analysis.md`).
- **Ruled out:** traps only (needs isolation); Zig-style tags (no context); Go without sugar (verbosity);
  handler-based and compiler-synthesised propagation (invisible exits); partial results (half-built values leak);
  absence as type-state (can't cross a function boundary).
- **The finalists:**
  - **E1** `fails` + `try`, one `Error` (Swift).
  - **E2** `Result` + a statement `check`, one `Error` (Go).
  - **E3** typed per-module enums + `?` (Rust).

## What the real examples taught

See `0004-research/lessons-and-scores.md`.
- **E1 (Swift), 256 lines:** forgetting `try` is a compile error.
- **E2 (Go), 331 lines:** forgetting the check is silent, even with `go vet`, so a must-use rule is required.
- **E3 (Rust), 350 lines:** forgetting a `?` on a statement is only a warning, and conversion glue was about 65 lines.
- **Rust's real mutex poisoning** showed that detection is cheap and useful.
- **The review** (`0004-research/review-e1.md`) showed E2 had been scored on Go's tooling, not on its design. With
  fixes, E1+ (83.5) and E2 (85.5) tie.
- **The merged design** (loop 2, `merged/`) was written in the language's pseudo-syntax plus a C model.
  - It prints the shared expected output.
  - 19 self-tests pass on three OSes:
    - a trap in the parent body propagates;
    - a plain `crew` re-traps;
    - a trap in a `drop` during unwinding is chained;
    - a poisoned lock traps, and `clear_poison` repairs it;
    - a variable is dead after a child's trap;
    - a leaked `Result` is reported;
    - a trap in a `qsort` callback aborts.

## Decision

**Adopt the merged design: E1's spelling over E2's values.** The rules a programmer learns:

1. **`fails` means "returns a `Result`".** `fn f(x) -> T fails` is spelling for `-> Result of T`, with one built-in
   `Error`. A bare call `f(x)` gives a `Result`. An unconsumed `Result` (not tried, matched or stored) is a compile
   error. A `List of Result` counts as consumed when the list is consumed.
2. **Three forms of `try`:**
   - `try f(x)` propagates.
   - `try f(x) context "…"` propagates and adds context. The string is evaluated only on the error path.
   - `v = try f(x) or e { … }` handles: the block gives a T or leaves.

   A propagating `try` is only ever the outermost operation of a statement or binding. A function containing one is
   `fails`. A handler must use `e`, give a value, or be written `or _ { }`. D6 picks the final spellings.
3. **Function values.** A non-failing function converts to a failing one. Built-in algorithms given a failing
   function return `Result`s (for example `map` gives `List of Result`). Ordering and key functions can't fail.
4. **One `Error`:** a closed `kind` enum of about 12 values (io-like categories, `parse`, `trap`, `other`), a message,
   a context chain, and an inline trace of up to 8 sites with no allocation. Callers `match e.kind`.
5. **Outcomes callers routinely branch on are return values** (`Optional` or a sum type), not error kinds. For
   example, `open_if_exists -> Optional of File`.
6. **`Report`** is a stdlib accumulator for collect-all modes.
7. **Absence is `Optional` only. There is no null.**
   - `if x = o { } else { }` and `with x = o { }` bind. There is no flow narrowing and no flattening.
   - `unwrap` (a long, greppable name) and indexing trap. `get` gives an `Optional`.
   - `-> Optional of T fails` is allowed.
8. **Traps are bugs.**
   - They unwind through tables, running `drop`s, in every build. Outside any crew a trap aborts with its trace.
   - A trap in a callback from C aborts.
   - A trap inside a `drop` during unwinding is appended to the chain, and unwinding continues.
   - Borrow counts are released during unwinding.
   - Running out of memory traps; `try_alloc` returns a `Result`.
9. **Crews and traps.** A plain `crew` gives its children's `Result`s and re-traps a child's trap. `try crew` also
   converts child traps into an `Error` of kind `trap`. A trap in the crew's own body is never converted: it cancels
   and joins the children, then continues as a trap. The crew adds `child N (site)` context. "First" means the
   lowest `c.go` order, traps included.
10. **Dead after a child trap.** In a `try crew … or e { }` handler and after it, every variable the crew's children
    borrowed mutably counts as moved. This is checked statically, through the move checker.
11. **Poisoned mutexes.** A mutex held during a trap is poisoned. `lock` on a poisoned mutex traps.
    `m.is_poisoned()` and `m.clear_poison()` let a supervisor repair it. The lock is released during unwinding.
12. **`drop` can't fail.** Fallible cleanup is a consuming `try x.close()`. A resource dropped dirty (without
    `close`) is listed in the debug exit report (R4).
13. **`Txn`** (undo unless `commit`) is a stdlib guard for non-resource undo. Resources own their own cleanup.
14. **Tests** catch traps only through `expect_trap { … }`. There is no general `catch`.
15. **Unconsumed `Result`s** in frames that a trap unwinds are discarded; the trap is the louder event.
16. **Tools** (debugger, coverage, `explain`) list every error exit in a function.

### Scores (`0004-research/scores.py`)

| Option | Ignore | Transp | Simp | Syntax | Context | Fit | Impl | Perf | Total |
|---|---|---|---|---|---|---|---|---|---|
| **Merged** | 5 | 5 | 3.5 | 3.5 | 4 | 4.5 | 3 | 5 | **86** |
| E2 fixed | 5 | 5 | 4 | 2.5 | 4 | 4.5 | 4 | 5 | 85.5 |
| E1+ fixed | 5 | 5 | 3.5 | 3 | 4 | 4 | 3 | 5 | 83.5 |
| E3 | 4 | 4 | 2 | 4 | 3 | 3 | 4 | 5 | 71 |

**The merged design and E2 tie.** The merged design is E2's semantics with a one-token propagation spelling. So
choosing it gives up nothing of E2, and it is the most reversible choice: the spelling can be changed in D6 without
changing any semantics. E1's effect-typed `fails` is not adopted.

## Consequences

**Easier:**
- Every error exit is visible.
- One error type crosses crews with no conversion.
- Collect-all is natural, because errors are values.
- Traps can be tested.
- Data left half-updated by a trap is statically unreachable.

**Harder:**
- Matching on error kinds is coarser than Rust's typed enums.
- Unwind tables on three OSes are a codegen cost (D8).
- Fallible cleanup needs an explicit `close`.
- 16 rules.

**Ruled out:**
- `catch` for bugs.
- Null.
- Typed throws.
- Exceptions without a call-site mark.

**Changes to earlier ADRs:**
- ADR-0003: crews give `Result`s, and `try crew` converts traps.
- ADR-0001 rule 6: a poisoned lock traps.

**Passed on:**
- D5: methods returning `fails`.
- D6: spellings of `try`, `or`, `context` and `fails`.
- D8: unwind tables, FFI thunks.
- D10: the `kind` enum, `Report`, `Txn`, `replace`, `try_alloc`.
- M4/M5: the conformance tests take the 19 self-tests.

## Syntax budget impact

| Item | Count |
|---|---|
| Keywords | `fails`, `try`, `or` (handler), `context` |
| Library | `Error`, `Report`, `Txn`, `expect_trap`, `unwrap`, `is_poisoned`, `clear_poison` |
| Grammar | `try` as the outermost operation; the `or e { }` handler clause |

16 rules, counted by the reviewer.

## Adversarial review log

| Review | Findings | Outcome |
|---|---|---|
| `0004-research/review-e1.md` | F1 data half-updated after a child trap; F2 `try crew` as a general catch; S1–S7 (`fails` spreading, kinds, grammar clashes, `try` inside expressions, unwinding, `drop` failures, poisoning); M1–M5 | All adopted; merged design chosen (E1 spelling over E2 values) |
| Merged example notes | 8 gaps (static F1, `crew` vs `try crew`, `Txn` vs resources, child context, FFI depth, `List of Result`, atomic replace, discarded results) | Decided in `review-e1.md` and rules 1–15 |
