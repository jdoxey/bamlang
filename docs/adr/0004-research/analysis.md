# D4 analysis (Opus coordinator)

There are 14 ideas: the research's C1–C6, S1–S4 and X1–X4.

## Ruled out

| Idea | Why |
|---|---|
| C6 trap-only | Midori's model needs process isolation, and the file and parse cases lose detail |
| C3 Zig tags | Can't say which file failed; inferred sets hide the signature |
| C5 Go with teeth, no sugar | Go's own top complaint (G4) |
| X1, X4 | Invisible exits (Transparency is 20) |
| X2 | Half-built values leak |
| X3 | Absence can't cross a function boundary |

## Kernels adopted into every finalist

- Traps unwind with drops and are caught only at crew braces and `expect_trap`.
- `drop` can't fail.
- A mutex poisoned by a trap is visible on its next `lock` (detection only).
- `Optional` only, no null, and `unwrap` traps.
- OOM traps.
- `Report` as a stdlib accumulator for collect-all modes.
- Tools list every error exit (G8, G9).
- `Txn`-style guards as a stdlib pattern.

## The three finalists, to be written as real code

| | E1 `fails` + `try`, one `Error` (S1/C4) | E2 `Result` + statement `check`, one `Error` (S2/C2) | E3 typed error enums per module + expression `?` (C1) |
|---|---|---|---|
| Model language | Swift 6 (`throws`/`try`, with one error type used everywhere) | Go (`(T, error)` with the check written out as a statement; `go vet` must-use) | Rust std (`enum ParseError`, `?`, `From` conversions, no crates) |
| What it tests | marker spread, call-site noise | statement-only noise, collect-all naturalness | conversion glue, typed matching, versioning |

The `errors` benchmark spec is `docs/examples/errors/SPEC.md`. Swift is skipped on Windows CI, as for chatsim.
