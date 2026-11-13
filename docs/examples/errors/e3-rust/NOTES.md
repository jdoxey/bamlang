# E3 (Rust, std only): typed error enums per module + `?`

What SPEC.md asks: part 1 config parser (fail-fast, collect-all, absence), part 2 `replace_file` with cleanup and 4
injected failures, part 3 a 4-worker crew with one error and one trap. `run.sh` builds with cargo and diffs
against `../expected.txt`. Package name `errors`; runs on Windows too (`fs::rename` replaces).

Design: `config::ParseError` and `files::FileError` (one enum per module), a top-level `AppError` with
`From<ParseError>`, `From<FileError>`, `From<io::Error>`, plus `Worker { n, source }` and `Trap { n }`. `?` is used
in every fallible function. Absence is `Option`. Cleanup is a `Drop` guard.

## Numbers
- Lines (`main.rs`, 350): config module + part 1 driver 134, files module + part 2 driver 110, part 3 59,
  top-level `AppError` and glue 42 (rest: header and `main`).
- Propagation: 16 `?`, 6 `map_err` (they carry the context: step number and what). Context for a step is a
  variant field, not a free-form string.
- Conversion glue: about 15 lines of `From` impls, ~31 lines of `AppError` enum/`Display`/`Error`, ~18 lines of
  `Display` for the two module enums, 3-line `io_at` helper. Roughly 65 lines (19%) before any
  context. Adding a worker-level context needed a new variant (`Worker`) and a `Box`.
- Final messages: `error: step 4: remove lock: injected failure`;
  `error: worker 2: config.ini:3: missing '=' (plus 1 more)`.

## Forget to handle
- Drop the `?` on a `Result` statement (`fs::write(..).map_err(..);`): only a warning, the build succeeds:
  warning: unused `Result` that must be used
     = note: this `Result` may be an `Err` variant, which should be handled
  It becomes an error only with `#![deny(unused_must_use)]` or `-D warnings` (CI's "no warnings" rule).
- Drop `?` where the value is used (`let cfg = config::parse(..);` then `cfg.get(..)`): hard type error,
  `error[E0599]: no method named 'get' found for enum 'Result<T, E>'`, with help "use the `?` operator to extract
  the `Config` value, propagating a `Result::Err` value to the caller".
## Traps
Real: the worker thread panics on `keys[idx]` while holding a `std::sync::Mutex` guard; `JoinHandle::join`
returns `Err` (mapped to `AppError::Trap`), and `Mutex::is_poisoned()` is true. The panic hook is silenced for
clean output. Worker 3 is the only user of the shared mutex (so no other worker needs to handle a poisoned lock);
`.lock().unwrap()` would trap in another worker if it ran after worker 3.

## Rules a programmer must know
1. Each module defines an error enum, `Display`, and `Error`.
2. `?` needs `From<Inner> for Outer` for every inner type, or an explicit `map_err`.
3. `?` is allowed in an expression, anywhere (`e?.file_name()`).
4. `Result` is `#[must_use]` (warning, not error, by default).
5. Context must be a variant or a wrapper type; there is no free-form `with("...")`.
6. `Drop` cleanup cannot return errors; thread panics are seen only through `join`.

Strength: typed variants can be matched in tests. Cost: glue and no uniform context mechanism.
