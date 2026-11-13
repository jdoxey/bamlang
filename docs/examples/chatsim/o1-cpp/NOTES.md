# chatsim under O1 (pure ARC), C++17

Files: `chatsim.cpp`, `run.sh`. `run.sh` passes (output matches expected.txt byte for byte).
Sanitizers (g++ 14, Linux): `-fsanitize=address,undefined` clean; `-fsanitize=thread` clean.
Not tested: Windows/macOS. The MinGW `-static` + `std::thread` path needs the posix threading model of MinGW (win32 model has no std::thread/std::mutex); CI will tell.

## Size
`wc -l`: 332 lines. Non-blank, non-`//`-comment lines: 303. (C reference is ~300 plus ~100 of `thread_compat.h`-style plumbing; this is not shorter, because std::string/map work is offset by `shared_ptr`/`weak_ptr`/`lock()` ceremony.)

## Choices
- `user->room` is a `weak_ptr<Room>`. The server's `rooms` map owns rooms. A strong one makes User -> Room -> callback -> User a cycle.
- `last_from`, `Timer::user`, `Member::user` and the callback capture are all `weak_ptr<User>`. `had_contact` flag kept for the "last contact has left" message.
- The server's `users` map is the only strong owner of a User. Leaving = `users.erase()`.
- No pointer-nulling walk. `free_user` in the C version (3 loops) has no counterpart; `rate->forget(name)` stays because the limiter is keyed by name, not by object.

## Bugs actually hit
Honestly: none at runtime. It compiled with `-Wall -Wextra -Werror` and matched on the first run, and ASan/UBSan/TSan were clean first time. I know the model well enough that the traps were avoided on purpose (see "care needed").

## The naive capture (build with `-DNAIVE`, still in the source)
Naive = callback captures `shared_ptr<User>`, and `user->room` is a strong `shared_ptr<Room>`.
- On the full script.txt it does NOT leak: output matches, `exit: alive users=0 rooms=0`. Every user leaves through `exit_room`, which erases the member (destroying the closure and its strong capture) and moves `u->room` out. The cycle only exists while the user is a member, and `leave`/`move` break it by hand.
- On the script with the last 4 lines cut (no `leave bob`, `leave carol`, `stats`), naive ends `exit: alive users=2 rooms=2` and ASan/LSan reports 1620 bytes leaked in 18 allocations (the closure state in `make_callback`). The fixed build ends `users=0 rooms=0`. So the cycle is real but only bites when something skips the explicit leave path: shutdown, an exception, or a future "kick" command. Nothing in the compiler warns about it. The alive counters are what exposed it; without them it is silent, and without LSan it never shows.
- The weak version needs `weak.lock()` plus a null check inside every callback (3 lines of boilerplate per closure).

## Awkward
- Every access to a related object is `lock()`, then a null check, then use: `room.lock()`, `last_from.lock()`, `Member::user.lock() == from` (used just to test "is this member the sender"). `Member` could hold a raw `User*` for identity but that is what the model is meant to avoid.
- Choosing strong vs weak per field is a design decision made by hand at each field; nothing checks it.
- Closure state is hidden: `std::function` allocates, copies share/duplicate captures.
- `make_shared<Timer>`, `Job`, `RateLimiter` as shared_ptr objects is ceremony; none of them is actually shared.

## Hidden work the source does not show
- Refcount traffic: `find_user` returns a copy (atomic inc/dec) on every command; `post()` copies each `OnMessage` per recipient (copying a `weak_ptr` capture = atomic weak-count inc/dec, plus maybe a heap clone of the closure state); `lock()` is a CAS loop. shared_ptr counts are atomic even though only the main thread touches Users and Rooms.
- Destructor cascades: `rooms.erase` + last `shared_ptr<Room>` falling off the end of `exit_room` runs `~Room`, which frees the member vector, closures, remaining strings and its `shared_ptr<Shared>` ref. `users.erase` + end of `leave` runs `~User`. When these run depends on who else holds a copy (a stray `shared_ptr<User>` in a local would delay "alive" counts).
- The history vector is moved (a pointer swap), and then freed on the worker thread when `j.reset()` drops the Job; the room's destructor frees nothing of it.
- Server shutdown order is implicit: dtor joins the worker, then members are destroyed in reverse declaration order.

## Memory cases
- 12 room freed when last user leaves: the server's map and the local `r` in `exit_room` are the only strong refs, so it dies at function end (the `}` marked in source). Correct only because `user->room` is weak: a strong one would be a second owner. Alive counters confirm it (`rooms=2` then `0`).
- 14 reference to deleted user: handled by a failed `lock()` on `last_from`; `dm` goes through the by-name map, which fails cleanly. No dangling pointer is possible, and no nulling walk exists. `had_contact` is the only extra state.
- 17 cycle: described above. Real, silent, fixed by weak capture.
- 20 re-entrancy: echobot calls `post()` from inside a callback inside `post()`. Care was needed: loop by index (the vector is not resized by nested posts here, but `history` is), and copy the `std::function` out of the member before calling it so the callable cannot be destroyed or moved mid-call. The model does not enforce either; I added them knowing the case. `Room&` is safe only because the caller holds a `shared_ptr<Room>` for the duration.
- 25 stats across threads: the counters and archive list live in one `Shared` behind a mutex + condvar. The worker holds its own `shared_ptr<Shared>`, so its lifetime is safe; but the model gives no help with races: the `messages++` and every access need the lock by discipline (TSan is clean because I took it). ARC protects lifetime, not data. User/Room counts are plain longs touched only by the main thread.
