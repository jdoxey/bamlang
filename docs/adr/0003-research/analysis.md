# D3 analysis (Opus coordinator)

There are 14 ideas: 6 sketches from the research, P1–P4 (sane) and X1–X4 (crazy). Below, R2 means research
sketch 2, scoped threads only.

## Ruled out

| Idea | Why |
|---|---|
| Research 4, isolated actors; X1 home-thread pools | Drops the decided `Mutex of T`. Invisible `ask` deadlocks. A hidden scheduler (R6). |
| X2 full static lock graph | A soundness-critical whole-program analysis with false positives. Its weak form is kept (below). |
| X3 as a release model | It prevents nothing in release builds. Its debug form is kept (below). |
| X4 compiler-owned threads only | Long-lived services don't fit. Kept as library forms on top of scopes. |
| P2 jobs as pool handles | Nothing can be borrowed, and a separate `Locks` table clashes with `lock m { }`. |
| Research 1, the unstructured Go baseline | Leaks and silent hangs. Measured only through P3's detached `spawn`. |

## Kernels adopted into every finalist

- **No nested locking:** a call that may lock while a lock is held is a compile error, checked on the call graph that
  ADR-0001's main-thread rule already builds (X2's weak form).
- **Cancellation is honoured only at blocking calls and checkpoints outside `lock` blocks,** so data is never left
  half-written (X4).
- **Owned channel endpoints:** an explicit `clone()` for senders; the last sender closes; `recv` gives `none` and
  `send` gives `closed` as visible results (P1, P3).
- **Debug and test builds detect "all threads blocked"** and print the wait-for cycle, with a replayable schedule
  in tests (X3, P3). Under R4 this reclaims nothing and never ships.
- **No `async` in v1** (research).

## The three finalists, to be written as real code

| | F1 Crew (P1) | F2 Scope plus must-join spawn (P3) | F3 Main loop plus offload (P4) |
|---|---|---|---|
| Thread start | `crew c { c.go(…) }` only; a Live crew for the main loop | `crew { go(…) }` plus `spawn` returning a must-consume `Join` | `par { }` for compute; `offload(fn) -> Task` |
| Borrowing into threads | yes, under exclusivity | yes, inside `crew` only | yes, inside `par` only |
| Cancellation | built-in token, sticky, re-raise | `Atomic of Bool` by convention | `Task.cancel()`, and the closure gets `me` |
| Posting to main | a channel held by the main loop | a channel plus `select` | `app.on(task, fn)` |

Modelled in Rust (std only): `thread::scope`, `mpsc` channels (dropping closes), `Mutex`, `AtomicBool`.
