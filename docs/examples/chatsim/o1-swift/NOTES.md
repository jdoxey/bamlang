# chatsim under O1 (pure ARC), Swift 6.0.3

Files: `chatsim.swift`, `run.sh`. `run.sh` passes (byte-identical to expected.txt), built with `-swift-version 6`, zero warnings.
Sanitizers (Linux): `-sanitize=address` (incl. LSan) clean, `-sanitize=thread` clean, both with identical output.
Windows CI skips this example: the CI image has no Swift toolchain (run.sh prints SKIP, exits 0). macOS/Linux untested in CI yet.

## Size
`wc -l`: 292. Non-blank, non-`//`-comment lines: 261 (C++ port: 303). Foundation `Thread`+`NSCondition`, String interpolation and Dictionary make it shorter than C++.

## Choices
- Every identity object is a `final class`: User, Room, Job, Timer, Shared, RateLimiter, Server.
- Server's `users`/`rooms` dictionaries are the only strong owners. `user.room`, `user.lastFrom`, `Timer.user`, `Member.user` are `weak var`; the callback captures `[weak u]`.
- Liveness = weak ref reads nil; no pointer-nulling walk. `rate.forget` stays (limiter keyed by name). `hadContact` flag kept.
- Worker: `Thread { Server.worker(sh) }`. `Thread` has no join, so a `finished` flag under the NSCondition is waited on in `Server.deinit`.
- Counters are global `nonisolated(unsafe) var`, touched in init/deinit. `runServer()` is a function so the Server dies before the `exit:` line prints.

## Diagnostics and runtime problems (exact)
- `error: expected '}' at end of closure`: `#if` cannot switch a capture list inside a closure body; split the body into `onMessage()` and `#if` around two one-line closures.
- No compiler diagnostic at all in the final version, but only because of two escapes. Removing them gives:
  - `error: main actor-isolated var 'usersAlive' can not be mutated from a nonisolated context` (4 sites, plus 2 reads) -> `nonisolated(unsafe)`.
  - `error: capture of 'sh' with non-sendable type 'Shared' in a `@Sendable` closure` -> `final class Shared: @unchecked Sendable`.
  So `-swift-version 6` works, but the compiler only checks that the class is *claimed* Sendable. Every field of `Shared` is guarded by `cond` by discipline; the compiler cannot verify it. `Job` (non-Sendable) crosses threads inside `Shared.queue` unflagged because `Shared` is unchecked.
- Runtime: none. ASan, TSan clean first time.

## Naive capture (`-DNAIVE`: strong closure capture + strong `user.room`)
- Full script: no leak, `exit: alive users=0 rooms=0` (leave/move break the cycle by hand via `u.room = nil` + member removal).
- Script minus last 3 lines (`leave bob`, `leave carol`, `stats`): naive ends `exit: alive users=2 rooms=2`, ASan: `SUMMARY: AddressSanitizer: 1012 byte(s) leaked in 20 allocation(s).` Weak version ends `users=0 rooms=0`. Silent, no warning; found only by the counters/LSan. Same as C++.

## Awkward
- Strong vs weak chosen by hand per field; nothing checks it. A weak capture needs `[weak u]` and an optional unwrap in every callback.
- `#if NAIVE` can't be spliced inside a closure (see above).
- No `Thread.join`; hand-rolled flag. `Thread`/NSCondition are Foundation (corelibs on Linux), not stdlib.
- "Move" of the history is not a language move: `Job(r.name, r.history)` shares the COW buffer, then `r.history = []`. The worker frees it by `j.history = []`. Correct, but nothing stops reuse of `r.history` before the reset.
- Swift 6 isolation for plain global counters needs an unsafe annotation.

## Hidden work
- Retain/release on nearly every line: `users[name]` returns +1; `post` copies each `Member` (closure context retain + weak-ref load, which goes through the object's side table and is atomic); `weak` loads retain the target. Refcounts are atomic even though only the main thread touches Users/Rooms.
- First `weak` reference to an object allocates a side table; it lives until the object's weak count drops.
- Deinit cascades: `rooms[r.name] = nil` plus the end of `exitRoom` frees the Room (members, closures); `users[name] = nil` plus end of `leave` frees the User. A stray local `let u` delays it (e.g. `leave` holds `u` to the closing brace).
- Server shutdown order is implicit: `deinit` joins the worker, then stored properties are released in declaration order.

## Cases
- 12 Room freed when the last user leaves: dies at the `}` of `exitRoom` because `user.room` is weak; alive counters show `rooms=2` then `0`.
- 14 Deleted user: `lastFrom` reads nil -> "last contact has left"; `dm` goes through the dictionary and fails cleanly. No dangling pointer possible.
- 17 Cycle: real with strong capture, silent, fixed by `[weak u]` (see leak result).
- 20 Re-entrancy: echobot's callback calls `post` mid-broadcast. Index loop and closure copied out of the array first, by discipline (Swift's exclusivity checker would trap if `room.members` were mutated while iterated in place; arrays are value types, so a `for in` over a snapshot would also be safe).
- 25 Cross-thread stats: counters live in `Shared` under NSCondition; the model protects lifetime only, the lock is by discipline (TSan clean because it is taken). `@unchecked Sendable` is the price.
