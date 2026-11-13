# D3 ideas, crazy lens (Sonnet inventor; condensed; unscored)

**X1 Home-thread pools** (breaks "data moves between threads").
- **Mechanism:** every pool or `Mutex` value has a home thread. Other threads send closures to it with
  `on pool { … }` (fire and forget) or `ask pool { … }` (with a result).
- **Benefits:** no locks. A dead home gives a loud error. `on main { … }` posts UI results.
- **Flaws:** chains of `ask` between two homes deadlock invisibly. A hot counter serialises through one event loop.
  It hides a scheduler.
- **Kernel:** `on main { … }` as the only way a job touches main-thread state.

**X2 Static lock graph** (breaks "deadlock is a run-time event").
- **Mechanism:** a cycle in the "held A while acquiring B" graph over the call graph is a compile error.
- **Flaws:** a soundness-critical whole-program analysis; conservative false positives through closures; and it says
  nothing about channel liveness.
- **Kernel:** a weak form: **no call that may lock while a lock is held**, checked on the call graph that the
  module-state rule already builds.

**X3 Deterministic time** (breaks "threads interleave arbitrarily").
- **Mechanism:** in test and debug builds, one baton passes only at sync points. The schedule is a replayable seed,
  and tests can explore seeds.
- **Flaw:** it prevents nothing in release builds.
- **Kernel:** an exact "all threads blocked" deadlock report in debug builds (R4: it reclaims nothing), and seed
  replay as a test feature (G8, G10).

**X4 Compiler-owned threads** (breaks "the programmer creates threads").
- **Mechanism:** only `par map`, `par each`, `par reduce`, `pipeline` and `background(job)`, all scoped.
- **Benefit:** leaks are impossible.
- **Flaws:** long-lived services don't fit, and chunk and pool sizes are hidden.
- **Kernels:** scoped parallel forms as the default surface over `scope { spawn }`; and **cancellation is honoured
  only between lock blocks**.

**Gap no idea closes:** channel-liveness deadlock beyond "the receiver is gone, so the sender traps".
