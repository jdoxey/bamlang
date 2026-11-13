# D3: what the `threads` examples taught, and scores

All three models (Rust, std only) print the same `docs/examples/threads/expected.txt`. Each folder's `NOTES.md` has the
exact errors and panics.

| Bug variant | F1 crew | F2 scope + spawn | F3 offload | Real language under the adopted kernels |
|---|---|---|---|---|
| A: two threads write one chunk | E0499 compile error | E0499 | E0596 | compile error (exclusivity over concurrent children) |
| B1: re-lock inside a helper | **hang** | **hang** | **hang** | compile error (no call that may lock while a lock is held), or trap |
| B2: collector exits after 5 | silently wrong total in ~37/40 runs, else re-raised panic | ~36/40 wrong, else a generic panic | can't be written | `send` returns `closed` (must be handled); the total is a logic bug |
| B3: forgotten sender drop | **hang** | **hang** | can't be written | debug: all-blocked report and trap; release: hang |
| C1: job touches main-thread state | E0277 | E0277 | E0277 | compile error (call-graph rule) |
| C2: thread-local stand-in | **silent** (job bumps its own copy) | silent | silent | compile error (call-graph rule) |
| A job fails at step 3 | re-raised after siblings cancel | the main `recv` fails | the task is reported failed | F1: re-raised at the crew's closing brace |

## What each taught

- **Rust prevents races but not hangs.** Re-lock and channel-liveness bugs hang in every model. That makes the "no
  nested locking" compile rule and the debug all-blocked report the most valuable additions. Neither needs a new
  type system.
- **F1** gave the only uniform error story: one child fails, the siblings are cancelled, and the first error comes
  back at the crew's closing brace. Its "Live crew" for the main loop could only be emulated, so it needs care in the
  ADR.
- **F2:** the detached `spawn` plus convention-based cancellation recreated Go's shape. Its generic "a scoped thread
  panicked" message lost the cause.
- **F3:** built-in pools made B2 and B3 impossible to write, the shortest code (A 7 lines, B 12). But it needed
  118 lines of hidden machinery, and any custom pipeline falls back to raw channels.

## Scores (`scores.py`; weights in criteria.md)

| Option | Race | Transp | Simp | Deadlock | Expr | Impl | Perf | Debug | Total |
|---|---|---|---|---|---|---|---|---|---|
| F1 crew | 5 | 4 | 4 | 4 | 4 | 3 | 5 | 4 | **83** |
| F2 scope + spawn | 5 | 4 | 3 | 3 | 4 | 3 | 5 | 3 | 76 |
| F3 main + offload | 5 | 3 | 4 | 4 | 3 | 3 | 4 | 4 | 76 |

F1 leads in all 17 weight variants by at least 5 (the smallest margin, 7.5, is with equal weights). The combination
to attack is **F1+: F1, plus F3's `par_map` and `each_part` as stdlib conveniences built on `crew`** (no second
mechanism).
