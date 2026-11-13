# chatsim under O9 (owned values + generation-checked handles), C11

Result: `run.sh` passes (output identical to expected.txt). ASan+UBSan clean, TSan clean on script.txt.

## Size
- `wc -l chatsim.c`: 392 lines; 348 non-blank, non-comment lines (the C reference is 359 `wc -l`).
- Generic pool code (lines 14-56): about 39 code lines. The program proper is about 309.
  In the real language the pool would be built in, so the program is the ~309 plus the use of the built-in.

## Bugs I actually hit
- Honest answer: only one, and it was a typo (a `*/` inside a comment broke the build). No logic bug, no
  sanitizer finding. The program passed on its first successful compile.
- That is partly because I knew the hazards and wrote around them from the start (see borrow list). I did
  not get to see what the model does to someone who is not already careful. Treat "0 bugs" as weak evidence.
- Deliberate experiment: deleting the `pool_remove(&users, ...)` call in `cmd_leave` (see "forgotten remove").

## Places the borrow rule bit (a lookup pointer could not live across a mutating call)
1. `post()` (case 20): echobot's callback calls `post()` again inside the broadcast. `post()` holds only
   handles across the loop and re-looks-up the room every iteration; `Room *r` is scoped to a block.
2. `on_message_bot`: `self`/`from` pointers are scoped to a block that ends before the nested `post()`.
3. `enter_room`: `open_room` adds to the rooms pool, which can realloc the slot array (pool starts at
   capacity 2 so growth is exercised). Lookups are done after it, not before.
4. `cmd_say`: copies `u->room` into a local handle before `post()`; `u` is not used afterwards.
5. `cmd_join`: `pool_add` returns a handle, not a pointer, so there is no tempting `User *` to keep.
Every one of these is discipline. Nothing in C stops me from writing `User *u` across `post()`; only
the habit of block-scoping the borrow stops me. A language would need to enforce it (borrows cannot cross calls).

## What was awkward
- Every access is `user_get(h)` plus a NULL branch. Many of those branches are unreachable (e.g. the
  callback's own `self` while it is a member) but still must be written. Roughly 12 explicit stale branches.
- Name lookup is a linear pool scan (`POOL_EACH`); no secondary index.
- Rate limiter: keyed by name in the C version with an explicit `rate_forget`. Here it lives inside `User`,
  so it dies with its owner and needs no cleanup. Moving shared state into its owner removed a "forget" step.
- Pool entries are moved in by memcpy; the element type needs a drop function registered at pool init.

## Work the source does not show
Very little. Removal does: drop function, `live=0`, generation bump, count--. Pool growth reallocates and
moves all entries (invisible, and what makes borrows dangerous). Lookup checks index, live flag and generation.
No hidden GC, refcounting or cleanup walk.

## Cases
- 12 (room freed when last user leaves): `exit_room` moves history out, then `pool_remove(&rooms, rh)` drops
  members array and name. Members' callbacks held only handles, so nothing needs fixing up.
- 14 (reference to deleted user): `last_from`, timers' user, and callbacks' `self` are stale handles after
  `leave alice`. `reply` and `tick` print the "left"/"dropped" paths via a visible NULL lookup. The cleanup
  walk (`free_user` loops in the C version) is gone entirely.
- 17 (cycle): user -> room (handle) and room -> member callback -> user (handle) is not a cycle of
  ownership; the pool owns both. Removing either side just stales the other's handle.
- 20 (re-entrancy): see borrow list 1-2. Safe because no pointer is held across the nested post.
- 25 (stats across threads): history moves into the job (ownership transfer); counters and archive list
  are behind one mutex; `stats` waits for `pending == 0`. Pools themselves are main-thread only, so the
  model says nothing about threads here; the mutex is plain C discipline. TSan clean.

## A forgotten `remove`
Tested: with `pool_remove(&users, ...)` removed from `cmd_leave`, the program does not crash and ASan does
not complain (shutdown `pool_free` drops everything). Instead it silently misbehaves: the user is a zombie,
handles stay valid, so `dm bob alice` succeeds, alice's reminder fires, and `users=4`/alive counts are wrong.
So the failure mode is a logic bug and a bounded leak (until pool teardown), not use-after-free. That is safer
than raw pointers, but a leak detector would not catch it, since the memory is still reachable.
