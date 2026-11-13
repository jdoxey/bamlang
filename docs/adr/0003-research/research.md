# D3 research: thread models (Sonnet researcher, 2026-11-13; condensed)

**[unverified]** marks claims without a fetched source. Several JEP, Pony and Swift pages returned 403, so Swift 6
migration and Java structured concurrency rest on search summaries.

## Per language

**Go.**
- **Model:** goroutines and channels. Nothing prevents races (https://go.dev/blog/codelab-share).
- **Race detector:** finds only races that actually happen; costs 5–10× memory and 2–20× time
  (https://go.dev/doc/articles/race_detector).
- **Tu et al. (ASPLOS 2019):** 171 real bugs, 85 of them blocking. 58% of the blocking bugs came from message
  passing. The deadlock detector caught 2 of 21 (https://blog.acolyer.org/2019/05/17/understanding-real-world-concurrency-bugs-in-go/).
- **Leaks:** an Uber study found 857 goroutine leaks; the cause is an unowned `go` (https://arxiv.org/abs/2312.12002).
  A leak profile ships in Go 1.27 (https://go.dev/blog/goroutine-leak-profiles).
- **Lesson:** channels don't remove bugs; they move them into blocking.

**Rust.**
- **Model:** `Send`/`Sync` prevent data races (https://doc.rust-lang.org/nomicon/send-and-sync.html). Deadlocks and
  logic races remain. Same-thread re-lock is unspecified (https://doc.rust-lang.org/std/sync/struct.Mutex.html).
- **`thread::scope`:** joins all children at scope end, so children may borrow locals
  (https://doc.rust-lang.org/std/thread/fn.scope.html).
- **Async:** forces `Send + 'static`, `Arc<Mutex>` and function colouring
  (https://journal.stuffwithstuff.com/2015/02/01/what-color-is-your-function/).

**Swift.**
- **Model:** actors, `Sendable` and `@MainActor`.
- **Swift 6:** strict checking hurt migration; the most common error is a non-Sendable capture.
- **6.2's fix:** a module may default to `@MainActor` (SE-0466), and async runs on the caller's actor (SE-0461)
  (https://forums.swift.org/t/has-se-0466-been-implemented-in-swift-6-2/83114).
- **Lesson:** main-thread-first should be the default from day one. ADR-0001's main-thread module state already is.

**Erlang.**
- **Model:** isolated heaps; messages are copied (https://www.erlang.org/doc/system/eff_guide_processes.html).
- **Failure model:** links and monitors (https://www.erlang.org/doc/system/ref_man_processes.html).
- **Safety:** no data races. Mailbox deadlock and unbounded mailboxes remain.

**Pony.**
- **Model:** six reference capabilities make it race-free.
- **Adoption:** "the biggest stumbling block" (https://ponylang.io/learn/reference-capabilities).

**Inko.**
- **Model:** single ownership. Isolated processes may send only unique or value data
  (https://docs.inko-lang.org/manual/main/getting-started/concurrency).
- **Fit:** the closest relative to our constraints.

**Java and C#.**
- **Java:** shared memory with nothing safe by construction. Loom virtual threads were chosen to avoid colouring;
  pinning inside `synchronized` hurts them (https://docs.oracle.com/en/java/javase/21/core/virtual-threads.html).
  `StructuredTaskScope` is in its sixth preview (https://openjdk.org/jeps/525), so the API is hard to get right.
- **C#:** blocking on a `Task` under a UI context deadlocks
  (https://learn.microsoft.com/en-us/dotnet/csharp/asynchronous-programming/async-scenarios).

**Zig.**
- **History:** async was removed. In 0.16 it returns as an explicit `Io` parameter, which avoids colouring
  (https://charlesfonseca.substack.com/p/asyncawait-is-finally-back-in-zig).
- **Safety:** none.

## Cross-cutting

- **Structured concurrency** (https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful/):
  - A nursery can't exit before its children finish. A failure cancels the siblings and is re-raised.
  - It removes leaks and gives a place where children may *borrow* the parent's data, which fits ADR-0001 rule 3.
- **Deadlock:** no surveyed language prevents it by type.
  - Options: no nested locks (static, with a call-graph check), lock ordering (Linux lockdep:
    https://kernel.org/doc/Documentation/locking/lockdep-design.txt), re-lock traps, and a debug lock-order checker.
  - Channel deadlock is not solved by any of these.
- **Async in v1:** colouring cost Rust, C# and Zig dearly; Java and Go avoided it. Recommendation: no `async` in v1;
  blocking calls on threads; keep an uncoloured path for later.
- **Cancellation:** cooperative, checked at blocking calls and loop checkpoints. A forced kill leaves locks and data
  half-written.
- **Main thread:** a background job needs a way to post results back. Likely a main-thread `Channel`.

## Candidate sketches from the research

1. Unstructured `spawn` plus channels plus `Mutex` (the Go baseline).
2. Scoped threads only.
3. Scoped threads plus a detached `spawn` whose join handle must be joined.
4. Isolated actors (this conflicts with the decided `Mutex of T`).
5. Structured tasks with built-in cancellation (Trio semantics).
6. Main-thread default plus `offload` that returns a result.

Sketches 2, 3 and 5 compose.

## Benchmarks

- **A. Parallel map** over a large list into an ordered result. Includes a bug variant where two threads write one chunk.
- **B. Worker pool** pulling jobs from a channel, bumping a shared counter and sending results to a collector. Bug
  variants: a re-lock inside a callback, and a collector that exits early, leaving senders blocked.
- **C. A UI main loop plus a cancellable background job** that posts progress back. A mutex-guarded partial result
  must be left consistent on cancel, and background code touching module state must be rejected.
