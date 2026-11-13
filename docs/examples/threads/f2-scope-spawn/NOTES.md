# F2 Scope plus must-join spawn: NOTES (Rust 1.100, std only)

SPEC.md asks for: A parallel map of squares 1..=1_000_000 on 4 threads; B 4 workers and 20 jobs over channels with a
mutex counter; C a main loop with a cancellable 10-step job, deterministic by a tick handshake. Run `./run.sh`.

**Model.** A and B use plain `thread::scope`. C uses a detached `thread::spawn` (so `'static`, `Arc` everything)
returning `Join<T>`, a `#[must_use]` wrapper. Rust only warns when it is unused; the wrapper's `Drop` panics as a
runtime stand-in for the real language's compile error. Cancellation is an `Arc<AtomicBool>` by convention.

**Lines** (non-blank, non-comment): A 19, B 30, C 78; `main` 5. Modelling helpers ("stands in for a built-in"):
17, counted apart.

**Rules a programmer had to know:** (1) `scope` for borrowing, `spawn` for the rest; (2) a spawned closure is
`'static`: move or `Arc` everything; (3) you must join the `Join`; (4) cancellation is your own flag, polled at
checkpoints; (5) drop every unused sender; (6) never touch a mutex while holding it; (7) one flag per job.

**Bug variants** (scratch copies in /tmp/claude-1000/threads-scratch/f2-*):
- A, two threads write the same chunk (`s.spawn(|| out[0] = 1)` twice): compile error
  `error[E0499]: cannot borrow `out` as mutable more than once at a time ... argument requires that `out` is borrowed for `'1``.
- B1, re-lock inside `bump` while held: hangs (killed after 5 s with timeout, exit 124; output stops after line A).
- B2, collector stops after 5 results: usually silent. 36/40 runs printed `B: total=55 counter=20`, exit 0.
  4/40 runs a worker's `send` failed with `collector gone: SendError { .. }` and the scope panicked with the
  generic `a scoped thread panicked` (the original message only on stderr, from the hook), exit 101.
- B3, forgotten `drop(rtx)`: hangs (killed after 5 s with timeout, exit 124; output stops after line A).
- C1, job touches `static MAIN_STATE: Cell<u32>`: compile error
  `error[E0277]: `Cell<u32>` cannot be shared between threads safely ... the trait `Sync` is not implemented for `Cell<u32>``.
  C2, same with `thread_local!`: compiles, silent; main still prints `main-thread state = 0`.
- D1, forget to join (`drop(h)` at quit): Rust compiles it; my `Drop` panics: `Join dropped without being joined`,
  exit 101. D2, `spawn(..);` as a statement: rustc only warns:
  `warning: unused `Join` that must be used ... a spawned thread must be joined`, then the same `Drop` panic.
  The real language makes both a compile error.
- Extra, job panics at step 3: `job exploded at step 3`, then `job vanished: RecvError` in main (my `expect`), exit 101.

**Cancellation** is checked in `job` at the loop top, outside any lock, after the ack. **Errors:** `scope` re-panics
with a generic message; a detached job's panic shows only at `join()` (an `Err`) or never, if nobody joins.

**Kernels vs Rust.** Free: owned endpoints (drop closes; `Err` results), borrowing rules (A), module state not
shared (C1). Needs the real language: must-join as an error (D1, D2 are a warning or a runtime panic here);
no nested locking (B1); cancel-outside-lock (by hand); all-blocked detection (B1, B3 hang here; in debug builds
it prints the cycle). C2's `thread_local!` hole would be closed by the call-graph check.

**Hidden:** the flag is per-convention, so a forgotten check just means an uncancellable job; `Arc` clones for
every shared item; the generic `scope` panic message loses the child's payload.
