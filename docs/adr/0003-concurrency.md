# ADR-0003: Concurrency

- **Status:** Accepted
- **Date:** 2026-11-13
- **Tier:** Full (research in `0003-research/notes.md`)
- **Decided by:** Claude (ruling R7). John may veto by opening an issue.

## Context

R1: threads are in v1. ADR-0001: values have one owner and move; borrows cannot escape; identity lives in pools; pools shared between threads sit behind a mutex; handles are sendable. ADR-0002: `Channel of T` and `Mutex of T` are built-in. Decide the thread API and the rules that keep races impossible outside `unsafe`.

## Charter

| Goal / problem | Effect | Why |
|---|---|---|
| G1, R6 | serves | One way to start work (`spawn`), two ways to talk (channel, mutex). No colours, no actors, no marker traits. |
| G3 | neutral | `Mutex of T`, `Channel of T` are built-ins (ADR-0002). |
| G4 | serves | Few new words. |
| G8 | strains | Debuggers must show threads; a debug lock-order checker is wanted (R4: reclaims nothing). |
| G10 | neutral | Tests can join threads. |
| P-PY | avoids | Real parallel threads. |
| P-GO | risks | Shared mutable memory is not possible, unlike Go. |
| P-RUST | risks | The rule "what crosses threads" is checked by the compiler, but inferred, not annotated. |

## Criteria

R6 (you can see what is shared and when it is locked); race-freedom (ADR-0001 safety); G1 (concepts to learn); fit with moves and pools; implementation risk; blocking-I/O ergonomics.

## Options considered

1. **A. OS threads + move-only channels + `Mutex of T` that owns its data (chosen).**
2. **B. Actors** (Swift/Pony): isolated objects with mailboxes. Needs a second kind of object next to pools.
3. **C. async/await + executor.** Function colouring; two APIs.
4. **D. Shared memory + locks by convention** (Java/Go). Races possible; fails safety.
5. **E. Processes with copied messages** (Erlang). Safe, but copies large values that moves already hand over free.
6. **F. Structured-only** (`scope { spawn }`, children cannot outlive the block). Lets children borrow, but borrows are call-scoped in ADR-0001, so it adds nothing yet.
7. **Crazy G. Pool-per-thread with handle passing.** Each thread owns a pool; only handles and moved values cross. This is already how A works if each pool lives in one thread.
8. **Crazy H. Deterministic single-writer scheduler.** Simple to reason about, loses parallelism.

| | R6 25 | Race-free 25 | G1 20 | Fits ADR-0001 15 | Impl 15 | Total |
|---|---|---|---|---|---|---|
| A | 5 | 5 | 4 | 5 | 4 | 93 |
| B | 4 | 5 | 3 | 3 | 3 | 77 |
| C | 3 | 4 | 2 | 3 | 2 | 61 |
| D | 3 | 1 | 4 | 4 | 5 | 63 |
| E | 5 | 5 | 4 | 3 | 3 | 82 |

A leads E by 11. F and G are folded into A.

## What the real examples taught

chatsim (`docs/examples/chatsim/`) has a worker thread in all four programs, covering case 23 (history moved to a worker), 25 (stats shared mutable), 26 (room reused while the archive is written).
- The C reference, the Rust O4 model and the C handle model run clean under TSan/ASan. The only shared state is one mutex-guarded structure; everything else is moved.
- Case 26 is harmless because the job *owns* the moved history and a copy of the room name; a reused slot gets a new generation.
- Both Rust models used `Arc<Mutex<Stats>>`; in our language `Mutex of Stats` is the owner and the only way to reach `Stats`.
- The deterministic script needed a gate (flush) to hold the worker; real tests need a test hook to pause workers (G10).

## Decision

Adopt **A**.

1. `spawn { ... }` starts an OS thread and returns a `Thread` value; `t.join()` returns the closure's result. The closure captures by move or copy only; a captured borrow is a compile error. Everything captured must be *sendable*: owned values whose parts are sendable, handles, channels, mutexes. Borrows and values that contain a borrow are not sendable. Sendability is inferred, never annotated.
2. `Channel of T` is multi-producer, multi-consumer, blocking, optionally bounded. `send(x)` moves `x`. `recv()` returns `Optional of T` (none when closed and drained).
3. `Mutex of T` owns its value. `m.lock()` gives a guard that is a mutable borrow valid only to the end of its block; it cannot be stored or returned. Pools shared across threads are `Mutex of Pool of X`.
4. `Atomic of Int` and `Atomic of Bool` for counters and flags. Nothing else is atomic.
5. No shared immutable references in v1. Read-only data shared by threads is copied or put behind a `Mutex`. (Revisit with an `RwLock`-style reader guard if profiling shows contention; case 24.)
6. No async/await, no actors, no thread pool in the language; a thread pool is a stdlib module (D10). Blocking I/O blocks its thread.
7. Debug builds: a lock-order checker reports cycles (R4); lock held across `recv` is reported.
8. Deadlock is not prevented. A thread panic is reported at `join`.

## Amendment (2026-11-13, found while writing the D6 corpus)

As written, rule 1 let a thread own a `Mutex` or `Channel` only by moving it in, so main and the worker could not share one. Corrected:
1. **`scope { s -> s.spawn { ... } }`** runs threads that are all joined when the scope ends. Scoped threads may *borrow* values of the internally synchronised built-ins (`Mutex`, `Channel`, `Atomic`) from the enclosing function, and may also take moved values. No other borrow may be captured.
2. Plain `spawn` keeps rule 1: moved captures only. A plain-spawned thread therefore cannot share a mutex or channel with its parent; use `scope` for that. A split sender/receiver pair for long-lived unscoped threads is deferred (re-open if D11 or M5 needs it).
3. `Channel of T` is a single value (not split) and `close()` ends `recv` with `None` once drained.

## Consequences

- Easier: races are compile errors with no annotations; forgotten locks are impossible.
- Harder: no cheap shared read-only data; fan-in/fan-out through channels needs copies for shared inputs; lock-order deadlocks remain.
- Rules out: cross-thread borrows, `async` functions, actor syntax.

## Syntax budget impact

Keywords/words: `spawn`, `lock` (method). Block form for the guard. Built-ins from ADR-0002. No annotations.
