# D4: what the `errors` examples taught, and scores

All three versions print the same `docs/examples/errors/expected.txt` (Swift is skipped on Windows CI).

| | E1 Swift (`throws`/`try`, one error type) | E2 Go (`(T, *Err)`, statement checks) | E3 Rust (typed enums, `?`) |
|---|---|---|---|
| Total lines | **256** | 331 | 350 |
| Propagation | 36 `try` + 10 `ctx` | about 70 lines of `if err != nil` | 16 `?` + 6 `map_err` |
| Conversion glue | ~6 lines | 1 helper | **~65 lines** (`From`, `Display`, `Error`) |
| Forgot to handle a failing call | **compile error**: `call can throw but is not marked with 'try'` | **silent**, even with `go vet` | a warning only (`unused Result`); an error only if the value is used |
| Trap in a worker | needed a child process (Swift traps can't be caught) | `recover` plus a hand-made poison flag | real panic, real `Mutex` poisoning |

## Lessons

- **A call-site marker that the compiler requires** (`try`) is the only thing that made "forgot to handle" a hard error
  with no extra rule. Go's version needs a must-use rule that Go itself never gained. Rust's `#[must_use]` is a warning.
- **One error type** kept glue to about 6 lines. Typed per-module enums cost about 65 lines of conversions for three modules,
  and still needed `map_err`.
- **Collect-all mode** was easiest when an error is a value. In E1 it is `try f() else e { report.add(e) }`, which works as
  long as `try … else` binds the error.
- **Traps:** Rust's poisoning shows that detection is cheap and useful. A trap that unwinds and runs drops is needed
  for crews and tests.

## Scores (`scores.py`)

| Option | Ignore 20 | Transp 20 | Simp 15 | Syntax 15 | Context 10 | Fit 10 | Impl 5 | Perf 5 | Total |
|---|---|---|---|---|---|---|---|---|---|
| E1 | 5 | 5 | 4 | 3 | 4 | 4 | 4 | 5 | **86** |
| E2 | 4 | 5 | 4 | 2 | 4 | 5 | 5 | 5 | 82 |
| E3 | 4 | 4 | 2 | 4 | 3 | 3 | 4 | 5 | 71 |

E1 vs E2 is a **tie** (a 4-point gap). The examples break it towards E1: the shortest program, and the only one where
forgetting is a compile error with no extra rule. **E1+** to attack: E1, plus `try … else e { }`, `try … with "ctx"`,
`Report`, crew re-raise through `try crew`, traps caught only at crews and `expect_trap`, poisoning detection, and
`Optional` with `unwrap` trapping.
