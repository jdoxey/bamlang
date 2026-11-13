# ADR-0004: Errors and absence

- **Status:** Accepted
- **Date:** 2026-11-13
- **Tier:** Full (research in `0004-research/notes.md`)
- **Decided by:** Claude (ruling R7). John may veto by opening an issue.

## Context

ADR-0001: a stale handle makes `pool.get` return an optional; stack values are freed at scope end; no finalizers. ADR-0002: `Optional of T` and `Result of T,E` are built-in types. ADR-0003: a panicking thread is reported at `join`. Decide how failure and absence are represented and propagated.

## Charter

| Goal / problem | Effect | Why |
|---|---|---|
| G1, R6 | serves | Failure is a value in the signature; no hidden jumps. One mechanism plus panic for bugs. |
| G4 | serves | A one-character propagation operator keeps handling short. |
| G5 | neutral | |
| G8 | serves | Panic prints a stack trace in debug builds. |
| G10 | serves | Tests assert on `Result` values. |
| P-C | avoids | No unchecked error codes, no null. |
| P-JAVA | avoids | No null, no checked-exception ceremony. |
| P-GO | avoids | Avoids `if err != nil` boilerplate, keeps explicitness. |
| P-RUST | risks | Same shape as Rust, without `From` conversion traits or lifetimes. |

## Criteria

R6 (control flow visible in the code); one mechanism; brevity (G4); bugs vs expected failures kept apart; cost of the happy path; fit with moves (ADR-0001).

## Options considered

1. **A. `Optional of T` and `Result of T,E`, a propagation operator, `panic` for bugs (chosen).**
2. **B. Exceptions** (try/catch). Hidden control flow; cleanup needs finally or destructors; against R6.
3. **C. Go-style `(value, error)` tuples + nil.** Explicit but noisy; nil remains.
4. **D. Zig-style error unions with inferred sets.** Close to A; adds a second type-like thing (`!T`) and set inference.
5. **E. Swift-style `throws` + `Optional`.** Two mechanisms side by side.
6. **F. Null allowed, checked flow typing** (Kotlin-like). Invisible in values; adds type-narrowing rules.
7. **Crazy G. Everything returns `Optional`; error text goes to a per-thread last-error slot.** Hidden state; fails R6.
8. **Crazy H. Errors only as handles into an error pool.** Interesting under ADR-0001, but over-engineered for failures that die within one call chain.

| | R6 25 | One mechanism 20 | Brevity 20 | Bugs vs failures 15 | Impl 20 | Total |
|---|---|---|---|---|---|---|
| A | 5 | 4 | 4 | 5 | 4 | 88 |
| B | 2 | 4 | 5 | 2 | 3 | 63 |
| C | 4 | 3 | 2 | 3 | 5 | 68 |
| D | 5 | 4 | 4 | 5 | 3 | 85 |
| E | 4 | 2 | 4 | 4 | 3 | 68 |
| F | 3 | 3 | 5 | 3 | 2 | 63 |

A vs D is 3 points, a tie. Tie-break: A needs no error-set inference and uses the same `Result` type as `Optional`, so the compiler has one idea fewer.

## What the real examples taught

chatsim cases (`docs/examples/chatsim/`):
- **14, 15:** `dm` to a user who left, and a reminder whose user is gone, both came out as "get returned none" in the handle model and "map lookup returned None" in the Rust model; the "it's gone" branch was always written out, not skipped. This is exactly `Optional`.
- **Input errors:** the C reference uses `atol` on unchecked text (a bad `tick x` silently ticks 0). The Rust models call `unwrap()`, which is a panic on bad input. Both show the need for `Result` from parsing, with a short propagate.
- **10, cleanup:** pool entries and owned values vanish at scope end in both Rust and handle models; nothing needed `finally`.

## Decision

Adopt **A**.

1. **No null.** Absence is `Optional of T`. Pattern forms and `if` binding are specified in D6; `x or default` supplies a fallback; `x!` panics if none.
2. **Expected failure is `Result of T,E`.** `E` is any type; the stdlib supplies `Error` (message plus optional cause) for the common case.
3. **Propagation:** a postfix `?` returns early from the function with the `none`/`err` value if the operand is one. The function's return type must be compatible; mismatches are compile errors, not silent conversions (no implicit `From`).
4. **Panic** is for bugs: out-of-range index, `x!` on none, integer overflow in debug builds, division by zero, failed assertion. Panic unwinds nothing: it runs scope-end drops of the panicking thread only if the build is a debug build (so tests see clean pool reports), prints a message and trace, and ends the thread. In the main thread it exits with a non-zero status. A panic is reported at `join` (ADR-0003). No `catch`.
5. **Resources:** built-in resource types (files, sockets, lock guards, threads) are closed or released at scope end. User types have no destructors or finalizers (ADR-0001).
6. **Stale handles** are `none` from `get`, never panic. Using `get(h)!` is the opt-in panic.
7. **Library rule:** a function that can fail for reasons outside the caller's control returns `Result`; one that fails only on a caller bug panics.

## Consequences

- Easier: every failure path is visible in the signature; no invisible control flow; testing returns values.
- Harder: callers must handle or propagate every `Result`; wrapping errors from different sources into one `E` is manual (use `Error`).
- Rules out: exceptions, `finally`, nullable references, user destructors.

## Syntax budget impact

Postfix `?` and `!`, the word `or` for fallbacks, `panic(msg)`. `Optional`/`Result` come from ADR-0002. No annotations.
