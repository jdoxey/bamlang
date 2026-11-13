# D3 ideas, practitioner lens (Sonnet inventor; condensed; unscored)

**P1 Crew** (scoped threads that own the cancel token and channel endpoints).
- **Threads:** `crew c { … }` is the only way to start threads, and it joins all children at the closing brace.
  Children borrow the parent's locals under exclusivity; `c.each_part` hands out disjoint slices.
- **Channels:** `c.channel(cap)` gives owned `(Sender, Receiver)`. Dropping the last sender closes it, `recv` on a
  closed channel gives `none`, and `send` to a dropped receiver gives `closed`.
- **Errors and cancellation:** a child error cancels its siblings and is re-raised after the block (Trio).
  Cancellation is cooperative and seen at blocking calls.
- **Main thread:** a non-blocking "Live" crew is owned by the main loop and must be finished before exit.
- **6 rules.**
- **Risk:** borrowing across threads is a new soundness-critical analysis, and the Live crew is a second mode.

**P2 Jobs are pool handles.**
- **Threads:** `spawn` returns `Handle of Job` in a runtime registry. A forgotten join is a zombie in the exit report,
  and a trap in debug builds.
- **Sharing:** only moved values cross. Shared mutexes live in an Id-keyed `Locks` table.
- **5 rules.**
- **Risk:** parallel map is tedious, because nothing can be borrowed. The `Locks` table clashes with
  `lock m { }`.

**P3 Owned channels, scoped by default.**
- **Threads:** `crew` (join at exit, borrow allowed, no cancel token) plus a detached `spawn` returning a `Join` that
  must be consumed (dropping it is a compile error).
- **Channels:** owned endpoints. Close and `closed` results are explicit `else` arms.
- **Debug:** a wait-for graph traps with the cycle when every thread is blocked.
- **Cancellation:** by convention with `Atomic of Bool`.
- **7 rules.**
- **Risk:** convention-based cancellation is Go's leak pattern, and release builds still hang.

**P4 Main loop plus offload Task.**
- **Threads:** main thread by default. `offload(fn) -> Task of T` runs on a pool, with cancel, poll, and a progress
  `post`. Completion is a main-thread callback.
- **Parallelism:** `par { … }` is scoped compute with borrows. Worker pools are built-ins (`offload_each`), and raw
  channels are for experts.
- **5 rules.**
- **Risk:** custom pipelines fall off a cliff into raw channels, and the internal channel hides a scheduler.

**Notes:**
- Senders must not be copyable by `=` (an explicit `clone()`), so that "last sender closes" is visible.
- Every option has release-build hangs.
- A watchdog that prints thread states on request (a signal handler, not tracing) should be considered.
