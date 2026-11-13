# F3 Main loop plus offload: NOTES (Rust 1.100, std only)

SPEC.md asks for: A parallel map of squares 1..=1_000_000 on 4 threads; B 4 workers and 20 jobs over channels with a
mutex counter; C a main loop with a cancellable 10-step job, deterministic by a tick handshake. Run `./run.sh`.

**Model.** A uses `par_map(&items, 4, f)` (thread::scope inside). B uses `offload_each(items, 4, f)`: the pool
and its channels are hidden, results come back in a Vec. C uses `app.offload(fn(me: &TaskCtx) -> T) -> Task`;
the task has `me.cancelled()`, `me.post(k)`, and the App queue runs the progress/done callbacks on the main
thread (`app.next()`). The determinism handshake (`me.wait_tick()` / `task.tick()`) is an extra, test-only API.

**Lines** (non-blank, non-comment): A 7, B 12, C 71; `main` 5. Modelling helpers ("stands in for a built-in"):
118, counted apart (par_map, offload_each, App, Task, TaskCtx). The helpers are the largest of the three options.

**Rules a programmer had to know:** (1) `par_map` for compute with borrows; (2) `offload_each` for pools, no
channels; (3) `offload` closures are `'static`; (4) the closure polls `me.cancelled()` at checkpoints;
(5) results and progress arrive as main-thread callbacks; (6) never touch a mutex while holding it.

**Bug variants** (scratch copies in /tmp/claude-1000/threads-scratch/f3-*):
- A, two threads write the same chunk: not expressible, `par_map` takes an `Fn` closure and a mutation of a
  captured vec is rejected: `error[E0596]: cannot borrow `out2` as mutable, as it is a captured variable in a
  `Fn` closure`. (The real language would reject it by the same borrow rule.)
- B1, re-lock inside `bump` while held, in the `offload_each` closure: hangs (killed after 5 s with timeout,
  exit 124; output stops after line A). User mutexes remain.
- B2 (collector exits after 5) and B3 (forgotten sender drop): not expressible. The channels are inside
  `offload_each`, which always collects all results. The bugs cannot happen, but custom pipelines would need raw
  channels, which this option does not offer in the sketch.
- C1, job touches `static MAIN_STATE: Cell<u32>`: compile error
  `error[E0277]: `Cell<u32>` cannot be shared between threads safely ... the trait `Sync` is not implemented for `Cell<u32>``.
  C2, same with `thread_local!`: compiles, silent; main still prints `main-thread state = 0`.
- Extra, job panics at step 3: `job exploded at step 3`, then the task reports `Failed` and `app.next()` panics
  `task failed`, exit 101.

**Cancellation** is checked in `job` at the loop top, outside any lock, after the tick. `task.cancel()` is
per task, not per scope. **Errors:** a panic inside a task becomes a Failed event on the main loop.

**Kernels vs Rust.** Free: ownership of channel ends (nothing visible to leak: they are hidden), borrow rules (A),
module state not shared (C1). Needs the real language: no nested locking (B1); cancel-outside-lock (by hand);
all-blocked detection (B1 hangs here; debug builds would print the cycle, and the main loop blocked in `next`
with no live task would be reported). The `thread_local!` hole (C2) is closed by the call-graph check.

**Hidden:** a scheduler and its channels inside `offload`/`offload_each`; callbacks only run when the loop calls
`next`, so a loop that forgets it never sees progress; the Failed event is easy to ignore.
