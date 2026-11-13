# F1 Crew: NOTES (Rust 1.100, std only), loop 2

SPEC.md asks for: A parallel map of squares on 4 threads; B 4 workers and 20 jobs with a mutex counter; C a main
loop with a cancellable 10-step job. Run `./run.sh` (main diff, then `--selftest`). `crew.txt` shows A, B, C in the
real language's pseudo-syntax, with decisions 1-3, 5-7 marked and every bug variant's expected report.

**Changed in loop 2 (review-f1 decisions).** C is now `crew(|c| app_run(c, ..))`: the event loop is the crew body;
handlers get `&Crew` for one call; `start` uses a moving `c.go` that returns a `JobHandle` (`cancel()` is per job);
progress comes back on a channel drained with `try_recv` (D4, D6). Errors (D7): first real error re-raised as
"<msg> (plus N more)", the parent's error wins, a `Cancelled` exit is filtered, early exit cancels then joins.
Locks (D5): `Lock<T>` records a per-thread "holding" site; a second lock, `Rx::recv` or `sleep` while holding
panics `TRAP: blocking call while holding lock at <site>` (`#[track_caller]`). The Part B job queue is now a clonable
`Rx`, so the old `Mutex<Receiver>` hack is hidden inside the model as a stdlib leaf lock.

**Lines** (non-blank, non-comment): A 16, B 33, C 90 (job, enum, App, pump, run), selftest 126, main 16.
Model 188 ("stands in for a built-in"), counted apart. C grew from 75: the App struct and the handle.

**Selftest** (all pass, 20/20 runs, exit 0):
- two failing children: `"bang (plus 1 more)"`.
- a child that leaves by `check()` after a sibling fails is not reported: message is exactly `"real"`.
- `crew_try` body returns Err: sibling sees the cancel and has finished when the crew returns.
- `h1.cancel()` stops job 1 only; job 2 is untouched until `h2.cancel()`.
- re-lock in a helper (child process): stdout has `TRAP: blocking call while holding lock at src/main.rs:258:14
  (lock taken at ...)`, exit 101, no hang. `recv` while holding: same TRAP.

**Rules the programmer must know (honest list, 14):** (1) threads start only via `c.go`; (2) a child may borrow only
variables declared above the crew block in the crew-opening function; elsewhere use a moving closure; (3) a container
borrowed shared into a crew is frozen until the join, borrowed mutably it goes to one child; (4) closures passed to
crew-reaching parameters may not mutate captures; (5) no module state through such parameters; (6) `each_part` gives
`Part` views that cannot be stored; (7) drop every sender you do not hand off; (8) never take a lock, or make a
blocking call, while holding a lock (traps at run time); (9) cancellation is cooperative: only blocking calls and
`c.check()` are points, CPU loops need `check`; (10) no cancellation inside `drop`; (11) `go` returns a handle for
per-job cancel, `cancel_all` for everything; (12) the first error wins, "plus N more", cancelled exits are not errors;
(13) early exit cancels then joins; (14) handlers get `c` for the call only.

**Bug variants** (Rust results from the loop-1 scratch copies; the real language's reports are in `crew.txt`):
- A same chunk: Rust `E0499` cannot borrow `out` as mutable more than once. Real: compile error (D1).
- B1 re-lock: Rust hung. Now the model traps (selftest). B2 collector exits after 5: Rust usually silent (37/40),
  3/40 `collector gone`; real language: early exit cancels, workers fail, re-raised. B3 forgotten drop: hangs
  (timeout 5 s, exit 124); real: debug wait-for cycle, release thread dump.
- C1 `static Cell`: Rust `E0277` not `Sync`. C2 `thread_local!`: compiles, silent. Real: compile error for both (D3).
- D1 par_map mutates capture, D2 child borrows loop-local, D3 child pushes to a frozen list: rustc and `crew.txt`
  agree only on D2/D3 in spirit (E0373/E0502); D1-style freezing is NOT checked by this model, `crew.txt` only.

**Not checked by the Rust model:** decisions 1, 2, 3 (partial), 8; blocking `send` (the channel is unbounded);
lock-while-`join` (scope joins implicitly); recv returning closed on cancel (job still needs the ack);
non-`Cancelled` errors caused by cancellation (a failed `send`) are still reported.
**Hidden:** `try_recv` pumping spins with a 1 ms sleep (deterministic because of the tick handshake, not a real
event loop); `thread::scope` needs captured data declared outside.
