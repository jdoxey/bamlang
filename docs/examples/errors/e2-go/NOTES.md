# E2 (Go): `(T, *Err)` + statement-level check, one `Err` type

What SPEC.md asks: part 1 config parser (fail-fast, collect-all, absence), part 2 `replace_file` with cleanup and 4
injected failures, part 3 a 4-worker crew with one error and one trap. `run.sh` runs `go vet`, builds, and diffs
against `../expected.txt`.

Design: fallible functions return `(T, *Err)`; `*Err` is a concrete pointer, never the `error` interface (so no
typed-nil trap). Each propagation is written as `if err != nil { return zero, err.with("ctx") }`, exactly what a
statement-level `check v = f() with "ctx"` would expand to. `with` copies the error, appends context and a
`file:line` trace entry. Absence is `(string, bool)` (the Go form of `Optional`).

## Numbers
- Lines (`main.go`, 331): shared error type 41, part 1 106, part 2 95, part 3 89 (incl. `main`).
- Propagation statements: 14 `if err != nil` on `*Err` values (of which 1 is the fail-fast print and 2 are plain
  `return err` with no context) plus 9 `if e != nil` on stdlib `error` values that are converted. 15 `.with(` calls.
  Each is 3 lines, so about 70 lines (a fifth of the file) are propagation.
- Conversion glue: `ioErr` (1 line) used at 8 call sites (the stdlib error needs its own `if` first).
- Context: same strings as E1. Final messages: `error: step 3: rename temp: injected failure`;
  `error: worker 2: config.ini:3: missing '=' (plus 1 more)`.

## Forget to handle
- Call a `*Err`-returning function as a bare statement (`inject(failAt, 3)`): `go build` succeeds and
  `go vet ./...` is silent. Nothing is reported; the step-3 injection is silently ignored at run time.
- Same for `cfg, _ := parseFailFast(...)` (explicit discard is legal and also silent).
- Assigning a two-value call to one variable is a compile error, but ignoring the whole result is not.
- Conclusion: E2 needs the language-level must-use rule (S2's "unconsumed `Result` is a compile error"); `go vet`
  does not provide it for user functions.

## Traps
`recover()` in a deferred function in the worker goroutine models "trap caught at the crew brace". The deferred
function runs while the lock is still held (it is registered after the `defer Unlock`, so it runs first) and sets
the `poisoned` flag, then the result becomes an `Err` of kind `trap`. Poisoning is hand-built (`poisonMutex`
wrapper), not a property of `sync.Mutex`. The out-of-range index is a real Go runtime panic.

## Rules a programmer must know
1. Return `(T, *Err)`; the last value is the error, `nil` means success.
2. After every call, check `err != nil` before using `T` (nothing enforces it).
3. Propagate with `err.with("context")`; a bare `return err` loses context and trace.
4. Stdlib `error` must be converted (`ioErr`) before returning.
5. `defer` for cleanup; `recover()` only inside a deferred function.
6. Do not return `*Err` as `error` (typed nil).

Observations: collect-all is the most natural here (errors are plain values in a slice). Happy-path code is noisy
(G4): part 2's `replaceFile` is 40 lines for 4 operations.
