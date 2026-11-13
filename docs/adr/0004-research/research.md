# D4 research: errors and absence (Sonnet researcher, 2026-11-13; condensed)

**[unverified]** marks claims without a fetched source. The Swift Book, P0709 and Kotlin's official docs couldn't be
fetched.

## Per language

**Midori** (the key source; https://joeduffyblog.com/2016/02/07/the-error-model/).
- **Bugs:** cause *abandonment* (fail fast, kill the isolated process). "Given that bugs are inherently not
  recoverable, we made no attempt to try."
- **Recoverable errors:** checked, with a `throws` marker on functions and `try` at every failing call, so failure is
  as visible as `return`.
- **Contracts:** preconditions replaced about 90% of the exceptions used for argument checks.
- **Ratio:** abandonment outnumbered recoverable errors about 10:1.
- **OOM:** abandoned; recoverable allocation is opt-in.
- **Rejected:** unchecked exceptions, plain error codes (easy to ignore), and Java checked exceptions.
- **Caveat:** abandonment needs isolation. Aborting one thread in a shared address space is unsafe.

**Go.**
- **Verbosity:** the top complaint in surveys (12–13%) (https://go.dev/blog/survey2024-h1-results).
- **`try` abandoned:** it hid a return "from potentially deeply nested expressions", and the team stopped pursuing
  error syntax for lack of consensus (https://go.dev/blog/error-syntax).
- **Wrapping:** makes the inner error part of your API (https://go.dev/blog/go1.13-errors).
- **Nil-interface trap:** an `error` holding a nil pointer is non-nil (https://go.dev/doc/faq#nil_error).
- **Panic/recover:** [unverified].

**Rust.**
- **Guidance:** `Result` is the default, and contract violations panic
  (https://doc.rust-lang.org/book/ch09-03-to-panic-or-not-to-panic.html).
- **Two crates for one problem:** `thiserror` for libraries and `anyhow` (context plus backtrace) for applications,
  which shows that typed errors alone don't compose (https://github.com/dtolnay/anyhow).
- **Mutex poisoning:** exists only because panics unwind; "what is important is detection, not recovery"
  (https://sunshowers.io/posts/on-poisoning/).

**Swift.**
- **Typed throws (SE-0413):** the proposal itself warns that it "constrains the evolution" of a function, and untyped
  stays the default (https://github.com/swiftlang/swift-evolution/blob/main/proposals/0413-typed-throws.md).
- **Other forms:** `try`, `try?`, `try!` and `defer` [unverified details].

**Zig** (https://ziglang.org/documentation/0.13.0/#Errors).
- **Mechanism:** errors are integer tags; error sets are inferred; `try`; `errdefer` runs only on the error path; error
  return traces.
- **The context problem:** "but not which file failed" (https://matklad.github.io/2026/05/03/zig-error-context.html).
  The fix is an `errdefer` log of context.

**Java and Kotlin.**
- **Checked exceptions** failed on versioning and scalability; most callers just propagate
  (https://www.artima.com/intv/handcuffs.html).
- **Kotlin:** dropped checked exceptions and added `T?` with `!!` [unverified against official docs].

**C++.**
- **Exceptions banned:** in about 52% of codebases (2018 survey, secondhand) [unverified].
- **P0709:** deterministic exceptions [unverified].

**Hoare.** Null was "my billion-dollar mistake"
(https://www.infoq.com/presentations/Null-References-The-Billion-Dollar-Mistake-Tony-Hoare/).

**Erlang.** "Let some other process fix the error", through supervisors (Armstrong's thesis).

## Cross-cutting

1. **Bugs and recoverable errors are separate tiers** in every serious source. Catching bugs needs isolation or
   brings poisoning. Ours: abandon the crew's thread tree and re-raise at the crew boundary.
2. **Catch traps only at named boundaries:** a crew (ADR-0003) and a test's `expect_trap`. There is no general
   `catch`.
3. **A single built-in error type crosses crews with no conversion.**
4. **Context:** a built-in error with a context chain plus a propagation trace recorded at each `?` costs nothing on
   success and one append per frame on failure.
5. **Absence:** `Optional` only, no null. The escape hatch (`unwrap`) traps.
6. **OOM:** a trap by default. `try_alloc` returns a `Result` for large or untrusted sizes.
7. **Cleanup:** `drop` covers resources. Rollback of a half-done operation needs `errdefer` or a commit pattern. A
   `drop` must not return an error. Does a trap unwind (runs drops, needed for crews and tests) or abort?

## Six sketches

- **C1 Midori-lite:** typed per-module error enums, `?` with conversion by `match`.
- **C2 One built-in `Error`** (kind, message, context chain, trace), `?`, `.context()`. Optionally a user sum-type
  payload.
- **C3 Zig-style** tags, inferred sets, `try`, `errdefer`, traces.
- **C4 A `throws` marker plus `try`,** one built-in error type, `try?` giving Optional.
- **C5 Go with teeth:** `(T, Error)`, and the compiler forces the check. No sugar.
- **C6 Trap-only plus Optional:** no recoverable errors.

## Benchmarks

1. **A config parser** with `file:line:` errors, a "collect all errors" mode, and an `Optional` lookup that must not be
   confused with a parse failure.
2. **A multi-step file operation** (read, write temp, rename, delete lock) with an injected failure at each step. Temp
   and lock are always removed, no half-written output is left, and the error names the step. Includes a failing
   `drop`.
3. **A crew of workers.** One returns an error, one traps while holding a `Mutex`, one is blocked. The first error is
   re-raised "plus N more", the mutex state is detectable, and a test asserts the trap with `expect_trap`.
