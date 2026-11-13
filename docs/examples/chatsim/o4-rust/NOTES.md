# chatsim in Rust, model O4 (simplified ownership)

Result: `run.sh` passes first build, no warnings. `src/main.rs`: 469 lines (`wc -l`), 430 non-blank non-comment. C reference: 359.

## Errors hit
I designed around these from the start, then re-created the naive versions in a scratch copy to get exact text:
- Naive broadcast (`for m in self.rooms[idx].members.iter() { (m.cb)(self, ..) }`):
  `error[E0502]: cannot borrow *self as mutable because it is also borrowed as immutable`.
- Moving fields out of a room on close (`let Room { name, history, .. } = room;`):
  `error[E0509]: cannot move out of type Room, which implements the Drop trait`.
- No runtime panics (no BorrowMutError): I never put a RefCell around Room, so the C-style "iterate while re-entering" had no runtime form.

## Where the model forced the escape hatch
- `User` is `Rc<User>` (13 `Rc<` mentions). Server owns users and the room's callback must also hold the user (case 17), so there are two owners. One owner is impossible.
  Its mutable fields (`room`, `last_from`, `had_contact`) became `RefCell`/`Cell` (6 RefCell), since Rc gives only `&User`.
- 6 `Weak` (2 `downgrade`): `last_from` and `Timer.user`. Weak replaces the C "MANUAL: null every pointer" loop. They go dead by themselves.
- `user.room` is a room NAME (id), not a pointer. A `&Room` can't be stored, and Rc<RefCell<Room>> would have made a real cycle (room -> callback -> user -> room).
  Every use does a linear name lookup `room_idx` plus a `String` clone (7 `.clone()` calls, plus ~8 `Rc` clones through `.cloned()`/`u.clone()`).
- `find_user` returns a cloned `Rc`. A `&User` borrowed out of `self.users` would block every following `&mut self` call (`post`, `exit_room`).
- Callback type is `Rc<dyn Fn(&mut Server, ..)>`, not `Box`: see case 20.
- Arc/Mutex/Condvar: 3 `Arc` mentions, all for the worker. Room `String`/`Vec` history are plain owned values.

## Cases
- 12, room freed on last leave: `swap_remove` hands back an owned `Room`. Move works cleanly. `impl Drop` blocked destructuring (E0509), so I `mem::take` history and name.
  `ROOMS_ALIVE` falls in `Drop`, so rooms=0 shows real freeing.
- 14, deleted user: `Weak::upgrade()` is None, so no dangling. `had_contact` still needed to tell "left" from "never had contact" (Weak can't say that).
  Timers likewise (case 15). Cheap and safe, but only because I chose Weak.
- 17, cycle: the closure `move |srv, room, from, text|` captures `me: Rc<User>`, stored in the room. Rust needed: Rc, a clone made before the closure, and `Rc<dyn Fn>`.
  There is no leak only because I broke the cycle by making `user.room` a name. If `user.room` held `Rc<RefCell<Room>>` it would leak without Weak. USERS_ALIVE hits 0 only because exit_room drops the member (and closure) before free_user.
- 20, re-entrancy: echobot's callback calls `srv.post()` while `post` is broadcasting. Rust rejects iterating members while passing `&mut Server` (E0502).
  Fix: copy `(Rc<User>, Rc<cb>)` for every member into a Vec (a snapshot) before the loop. That is an allocation plus Rc bumps per message, invisible in the source's intent.
  The snapshot also silently decides semantics: members joining mid-broadcast would be missed (C iterates live; it can't happen here).
  Box would not work (cannot clone), and `mem::take`ing the member list would hide the members from the nested post.
- 25, stats across threads: `Arc<(Mutex<Shared>, Condvar)>`. `Send` is checked by the compiler: the Job (Vec<String>) moves into the queue and is dropped by the worker, no copy. `Rc<User>` can't cross threads, which is why Shared holds only counters and strings.
  `cv.wait_while` waits for idle. The compiler caught nothing here that I got wrong, but it forced `Shared` to contain no Rc.

## Awkward / hidden work
- Counters are globals (`static AtomicI64`) because Drop has no context. Atomic is needed only to be allowed as a static.
- Hidden work: ref-count increments on every message delivery, a Vec snapshot per `post`, a name lookup per `room_idx`, Rc drop of the user at the end of `cmd_leave`.
  When the user is freed is not visible in `free_user` (the Rc count says); it depends on exit_room having dropped the closure first. Reorder those two calls and `alive` is wrong with no error.
- Shared-ownership forced by the model: User only. Everything else (Room, history, timers, rates, jobs) stayed single-owner.
