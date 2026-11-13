# E1 (Swift 6): `throws` + `try`, one `Err` type

What SPEC.md asks: part 1 config parser (fail-fast, collect-all, `Optional` lookup), part 2 `replace_file` with
cleanup and 4 injected failures, part 3 a 4-worker crew with one error and one trap. `run.sh` diffs against
`../expected.txt`; it skips on Windows (no Swift toolchain).

Design: one `struct Err: Error` (kind, message, context chain, trace). Every fallible function is `throws`.
`ctx("step 2: write temp") { ... }` adds context and appends `function:line` to the trace. Absence is `Optional`.

## Numbers
- Lines (`main.swift`, 256): shared error type + `ctx` 29, part 1 78, part 2 62, part 3 75, main 12.
- Propagation tokens: 36 `try` (plus 4 `try?` in cleanup, where a failure is deliberately dropped), 10 `ctx(...)` calls.
  Of the 36, about 10 are `try ctx(...)` pairs, so the visible call-site noise is one `try` word per fallible call.
- Conversion glue: about 6 lines: the catch-all in `ctx` (foreign `NSError` becomes `Err`) and the `posix()` helper.
  No per-module glue because there is a single error type.
- Context: part 2 steps (`step 1: create lock` ...), `worker N`, `server.port`.
  Final messages: `error: step 2: write temp: injected failure`;
  `error: worker 2: config.ini:3: missing '=' (plus 1 more)`.

## Forget to handle
- Drop `try` in front of a throwing call (including the `ctx` helper): a hard compile error.
  `error: call can throw but is not marked with 'try'` (notes: did you mean to use 'try' / handle error as optional
  value / disable error propagation). Checked on `let port = ctx("server.port") { try parseInt(s) }` and on
  `inject(failAt, 3)`.
- The closure body of `ctx` is checked too, and a function that calls a throwing function without `throws` also fails.

## Traps (model limitation)
Swift traps are not catchable in-process. Worker 3 re-execs the binary with `--trap-worker3`; the child holds an
`NSLock` and indexes out of range; the parent sees `terminationReason == .uncaughtSignal`. "Mutex poisoned" is a
flag the parent sets when the child reports the trap. This models "trap observed at the crew brace" but the
real thing (unwinding with drops, poisoned lock visible on next `lock`) is not tested here. The child process
also pays startup cost.

## Rules a programmer must know
1. Mark a function `throws` if it calls a throwing function and does not catch.
2. Write `try` at each call (one `try` may cover a whole expression).
3. `catch` must be exhaustive in a non-throwing function (`catch {}` for the foreign case).
4. Use `ctx` to add context; plain `try` adds none and no trace entry.
5. `try?` turns an error into `Optional` (silently); `defer` runs cleanup; cleanup cannot throw.
6. Swift 6: shared state across threads needs `Sendable` / `@unchecked Sendable`.

Observations: the happy path stays close to straight-line code; `ctx` closures are the main extra noise, and
`return` inside a `ctx` closure returns from the closure, a small trap. `defer` made part 2 cleanup trivial.
