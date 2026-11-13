# ADR-0003: Concurrency model

- **Status:** Proposed
- **Date:** 2026-11-13
- **Tier:** Full (see `docs/PROCESS.md`)
- **Examples:** `docs/examples/threads` (F1 crew in `f1-crew/`; rivals in `f2-scope-spawn/`, `f3-offload/`)
- **Decided by:** Claude (ruling R7). John may veto by opening an issue.

## Context

R1 puts threads in v1. ADR-0001 rule 6 already says values move into threads, shared mutable data is `Mutex of T`
reached through `lock`, and module state is main-thread only. ADR-0002 put `Channel`, `Mutex` and `Atomic` in the
built-in set. Three questions remain:
- how threads start and end;
- how errors and cancellation travel;
- what stops races, hangs and leaks.

Research (`0003-research/research.md`) found that Go's channels turned races into hangs: 58% of the blocking bugs were
message passing, and its detector caught 2 of 21. Unowned `go` statements leaked (857 at Uber). Async colouring cost
Rust, C# and Zig dearly.

## Charter

| Goal / problem | Effect | Why |
|---|---|---|
| R1 | serves | OS threads in v1 |
| G1 (R6) | serves, with a strain | One way to start threads, one error story and one cancel story, all visible in the source. About 14 rules (below). |
| G2, R3 | serves | No collector. The release thread dump reads per-thread slots, not objects. |
| G3 | serves | No `Send`, `Sync`, `@MainActor` or `@Sendable`. Thread-safety facts are inferred on the call graph. |
| G8, G10 | serves | Debug wait-for-cycle detection, a release thread dump, and deterministic tests through the handshake pattern |
| P-GO | avoids | No unowned threads; no silent re-lock hang; a closed channel is a visible result |
| P-RUST | risks | A second borrow lifetime ("until the crew's brace"), frozen containers, no mutation through shared closures |
| P-SWIFT | avoids | No actors, isolation annotations or async |

## Criteria

From `0003-research/criteria.md`, written before the options:

| Criterion | Weight |
|---|---|
| Race safety | 20 |
| Transparency | 20 |
| Simplicity | 20 |
| Deadlock and leak resistance | 10 |
| Expressiveness | 10 |
| Implementation risk | 10 |
| Performance | 5 |
| Debugging | 5 |

## Options considered

There were 14 ideas: the research's six sketches, four from a practitioner and four assumption-breaking ones
(`0003-research/ideas-*.md`, `analysis.md`).
- **Ruled out:**
  - isolated actors and home-thread pools (they drop the decided `Mutex`, and their deadlocks are invisible);
  - a full static lock graph;
  - deterministic scheduling as the release model;
  - compiler-owned threads only;
  - spawn handles in a `Locks` table;
  - the unstructured Go baseline.
- **Kernels kept from the ruled-out ideas:** the lock rule, cancelling outside locks, owned channel endpoints, the
  debug deadlock report, and no async.
- **The finalists:**
  1. **F1 Crew:** scoped threads with a cancel token, error re-raise and borrowing children.
  2. **F2 Scope plus must-join `spawn`:** cancellation by `Atomic` convention.
  3. **F3 Main loop plus `offload` Task,** with built-in `par_map` and `offload_each`.

## What the real examples taught

See `0003-research/lessons-and-scores.md`. All three were modelled in Rust and printed identical output.
- **Races** were compile errors in every model. **Hangs were not:** re-lock and a forgotten sender drop hung all
  three. This is why the lock rule (rule 11) is a trap in every build, and deadlock detection uses wait-for cycles.
- **F1** gave the only uniform error and cancel story. **F2's** generic "a scoped thread panicked" lost the cause.
  **F3** was shortest but needed 118 lines of hidden machinery, and custom pipelines fell back to raw channels.
- **F1's revised example** (loop 2) runs the main loop inside a crew, with per-job cancellation. A self-test shows
  error aggregation ("plus N more"), cancellation filtering, cancel on early exit, and the lock traps.

## Decision

**Adopt F1+: crews.** There is no `async` in v1. The rules a programmer learns:

1. **Threads start only inside `crew c { … }`, through `c.go(fn)`.** The closing brace joins every child. The parent
   body runs concurrently with the children and is inside the crew's cancel scope. `par_map` and `c.each_part(list,
   n, fn(part))` are stdlib conveniences built on crews.
2. **Children may borrow** only variables declared in the function that opens the crew, at or above the crew
   block's level. Elsewhere, and in handlers given `c` by a framework, `c.go` takes a moving closure.
3. **Frozen while shared.** A container borrowed shared into a crew is frozen until the brace: any write or structural
   change traps, and borrows skip the count. A container borrowed mutably goes to exactly one child.
4. **Closures that reach crew children** (an inferred flag per parameter, on the call graph) may not mutate their
   captures. The error suggests `Mutex` or `Atomic`.
5. **Module state is unreachable from children,** either directly or through a parameter that reaches a child.
6. **`Part of T`** is a borrow-only view for `each_part`. It is added to ADR-0002's built-in set.
7. **Errors.** A child error cancels the crew. The first error is re-raised after the brace with "plus N more" (all are
   printed in debug builds). The parent's own error wins. Cancellation-caused exits are not reported. How an error is
   represented is D4's decision.
8. **Early exit** (return, break, error) cancels, then joins. Falling off the end only joins.
9. **Cancellation is cooperative and sticky.**
   - Cancellation points: `recv`, a blocking `send`, `sleep`, `join`, stdlib I/O built on poll plus a wake handle,
     and `c.check()`.
   - Lock acquisition is never a cancellation point. A cancelled call returns its closed result.
   - CPU loops call `c.check()`; nothing is inserted silently.
   - Not cancellable: regular-file reads, DNS and FFI. The stdlib documents this per OS.
   - Blocking calls inside `drop` ignore cancellation.
   - `c.go` returns a handle with `cancel()`. Inner crews' tokens are children of outer ones.
10. **Channels have owned endpoints.**
    - Senders are copied with `clone()` only.
    - When the last sender is dropped, the channel closes. `recv` gives `none` when closed, and `send` gives `closed`
      when the receiver is gone. Both are handled explicitly.
    - `send` takes its value, so sending a borrow is a compile error.
11. **Locks.** `lock m { … }`. Holding a user lock while acquiring another, or while making any blocking call, traps
    with both sites, in every build. Re-lock is a special case. A lexically nested `lock` is a compile error.
    `lock a, b { … }` acquires several locks in a fixed order. Stdlib leaf locks are exempt.
12. **The main loop runs as `crew c { app.run(c) }`.** Handlers get `c` for the call, start jobs with moving closures,
    and drain results with `try_recv`.
13. **Deadlock and hang reporting.**
    - Debug builds detect cycles in the wait-for graph (channel endpoints record their holder) and trap with the
      cycle.
    - Release builds record "waiting on X at S" per thread. A dump on SIGQUIT or Ctrl+Break prints it.
    - A debug lint flags sending inside a crew whose receiver is drained only after the brace.
14. **No `async`.** Blocking calls on OS threads. A future uncoloured path, such as an `Io` parameter or lightweight
    threads, stays open.

### Scores (`0003-research/scores.py`, then the review's corrections)

| Option | Race | Transp | Simp | Deadlock | Expr | Impl | Perf | Debug | Total |
|---|---|---|---|---|---|---|---|---|---|
| F1+ with fixes | 5 | 4 | 3.5 | 3.5 | 3.5 | 2.5 | 5 | 4 | **78** |
| F2 with the race fixes | 5 | 4 | 3 | 2.5 | 4 | 2.5 | 5 | 3 | 74 |
| F3 with the race fixes | 5 | 3 | 3.5 | 4 | 3 | 2.5 | 4 | 4 | 73 |

- **This is a tie under PROCESS:** a 4-point gap after the review.
- **The tie is broken by the examples:** F1 had the only uniform error and cancel story.
- **It is also broken by reversibility:** a crew-only language can add a detached `spawn` later without breaking
  programs, but F2's `spawn` could never be removed.

## Consequences

**Easier:**
- No leaked threads.
- One error and cancel story.
- Parallel loops borrow their input without copies.
- Re-lock and lock-while-blocking are traps, not hangs.
- Closed channels are visible results.

**Harder:**
- Long-lived services live inside a crew opened near `main`.
- CPU loops must call `c.check()` to be cancellable.
- A second borrow lifetime (until the brace) and frozen containers are new rules.
- Cancellable I/O is a large stdlib commitment on three OSes. Implementation risk is the weakest cell.
- Release builds can still hang on a channel cycle; the thread dump shows where.

**Ruled out:**
- Unscoped spawn in v1.
- Async and await.
- Actors.
- Thread-safety annotations.

**Changes to earlier ADRs:**
- ADR-0002 gains `Part of T`.
- ADR-0001 rule 6's "re-locking traps" widens to "locking or blocking while holding a lock traps".

**Passed on:**
- D4: the error value that crews re-raise.
- D7 and D10: the UI framework's `app.run(c)` and the cancellable I/O list.
- M5: conformance tests from the F1 self-test and `crew.txt`.

## Syntax budget impact

| Item | Count |
|---|---|
| Keywords | `crew`, `lock` (from ADR-0001) |
| Library, not syntax | `c.go`, `c.check`, `each_part`, `par_map`, `channel`, `clone`, `try_recv` |
| Grammar | the `crew name { }` block; `lock a, b { }` |

Rules to remember: 14, the honest count from the review.

## Adversarial review log

| Review | Findings | Outcome |
|---|---|---|
| `0003-research/review-f1.md` | 3 fatal (borrow counts across threads, mutation through shared closures, borrows outliving their owner); 6 serious (Live crew, lock-analysis false positives, cancellation, error re-raise, deadlock detector, slice type); 4 minor | All adopted as rules 1–13; the Live crew dropped; recorded as a tie broken by the examples and reversibility |
