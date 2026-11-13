# F1 Crew: NOTES (Rust 1.100, std only)

SPEC.md asks for: A parallel map of squares 1..=1_000_000 on 4 threads; B 4 workers and 20 jobs over channels with a
mutex counter; C a main loop with a cancellable 10-step job, deterministic by a tick handshake. Run `./run.sh`.

**Model.** `Crew` wraps `thread::scope` (token, `go`, `channel`, `each_part`, `crew()`); it re-raises the first child
panic after cancelling siblings. C wraps the whole event loop in one `crew` (Rust cannot express a non-blocking
"Live crew" safely). Quit cancels the token, drops the ack sender, and the crew join ends the loop.

**Lines** (non-blank, non-comment): A 16, B 31, C 75 (C includes job, message enum and pump); `main` 5.
Modelling helpers ("stands in for a built-in"): 61, counted apart.

**Rules a programmer had to know:** (1) threads start only via `c.go`; (2) children borrow parent data, but the data
must be declared before `crew(..)` (a local made inside the body does not live long enough); (3) `each_part` gives
disjoint slices; (4) the token is cooperative, so check it at checkpoints; (5) drop every sender you do not hand
off; (6) never touch a mutex while holding it. In real Rust the `Send`/`'scope` rules are extra.

**Bug variants** (scratch copies in /tmp/claude-1000/threads-scratch/f1-*):
- A, two threads write the same chunk (`c.go(|_| out[0] = ..)` twice): compile error
  `error[E0499]: cannot borrow `out` as mutable more than once at a time ... first mutable borrow occurs here`.
- B1, re-lock inside `bump` while held: hangs (killed after 5 s with timeout, exit 124; output stops after line A).
- B2, collector stops after 5 results (`take(5)` then drop receiver): usually silent. 37/40 runs printed
  `B: total=55 counter=20` with exit 0. 3/40 runs a worker's `send` failed: `collector gone: SendError { .. }`,
  re-raised by the crew after cancelling siblings, exit 101.
- B3, forgotten `drop(rtx)`: hangs (killed after 5 s with timeout, exit 124; output stops after line A).
- C1, job touches `static MAIN_STATE: Cell<u32>`: compile error
  `error[E0277]: `Cell<u32>` cannot be shared between threads safely ... the trait `Sync` is not implemented for `Cell<u32>``.
  C2, same with `thread_local!`: compiles, silent; the job bumps its own copy, main still prints 0.
- Extra, job panics at step 3: stderr `job exploded at step 3`, then main's `recv` fails:
  `job vanished: RecvError` (my pump's `expect`), exit 101. The crew would re-raise the job's own payload if the
  body had not panicked first.

**Cancellation** is checked in `job` at the loop top, outside any lock, after the ack. `cancel` sets the token, then
acks. **Errors:** a panic in a child is caught, cancels the token, and is re-raised at the crew's end (first wins).

**Kernels vs Rust.** Free: owned endpoints (move semantics; `drop` closes), `recv` gives `Err` and `send` gives
`Err` as visible results, borrowing and disjoint writes (A is a compile error), module state not shared (C1).
Needs the real language: no nested locking (B1 hangs here; the call-graph check would be a compile error);
cancel-outside-lock (only by hand here); all-blocked detection (B1 and B3 hang here; the debug build would
print the wait-for cycle: main blocked in `recv`, workers gone for B3). Rust's `thread_local!` hole (C2) would
be closed by the call-graph check. B2 would still be a silent short total; only the `send` failure shows it.

**Hidden:** the `Mutex<Receiver>` job queue (std mpsc has one consumer); `thread::scope` needs captured data
declared outside; the crew's token is shared by all children, so `cancel` stops every child, not one.
