# chatsim findings (D1 step 3)

All four programs produce byte-identical output on `docs/examples/chatsim/c/script.txt` (`expected.txt`). The C reference ran clean under ASan+UBSan and TSan.

| Program | Where | Lines | Model |
|---|---|---|---|
| Reference | `c/chatsim.c` | 224 | Raw C; users by id, rooms by pointer |
| O1 | `rust-o1/chatsim.rs` | 185 | `Rc<RefCell>` + `Weak` standing in for Swift ARC (**Swift is not installed**) |
| O4 | `rust-o4/chatsim.rs` | 181 | Moves; ids for back-references; no `Rc` needed at all |
| O9 | `c-o9/chatsim.c` | 168 | Fixed pools, generation-checked handles, no stored pointers |

Caveat: O1 is a proxy. Rust's `RefCell` traps at run time where Swift would silently allow the aliasing, so O1's "loud" failures below are louder than real ARC.

## By case

| # | O1 (ARC) | O4 (moves) | O9 (handles) |
|---|---|---|---|
| 11 back-reference | `Weak` needed, else leak | plain id | handle |
| 12 freed with last user | automatic, but only because every other holder was weak | explicit `remove` from map | explicit `FREE`; must remember |
| 14 deleted target | `upgrade()` -> None | map lookup -> None | `GET` -> NULL |
| 15 callback, `self` gone | `Weak` capture mandatory, compiler never says so | callback captures nothing; gets `&mut Server` and an id | handle in closure; `GET` fails visibly |
| 17 cycle | room->cb->user->room leaks silently if capture is strong | cannot form | cannot form |
| 20 re-entrancy | **naive loop panics `RefCell already borrowed`** on the first bot reply; fix is hand-snapshotting members | rustc rejects calling a stored callback with `&mut Server` (E0502). Fix: `mem::replace` the box out and back (hidden, easy to forget) | needs a handle snapshot **and** a copy of any `char*` read from a pool before calling out; one missed copy is a use-after-free in C |
| 23 move to worker | `mem::take` history | plain move into channel | pointer handed over under mutex |
| 25 shared stats | `Arc<Mutex>` | `Arc<Mutex>` | mutex around plain struct |
| 26 owner dies while worker runs | name reuse is harmless: job owns its data | same | same; reused slot gets a new generation |

## What it taught

1. **Case 20 is the discriminator.** Every model needed a deliberate workaround. O1 fails at run time, O4 fails at compile time with an odd fix, O9 relies on discipline plus checks. A language-level answer is needed: *callbacks receive the world as a parameter and hold only ids/handles*. That is O9's shape expressed in O4's checker.
2. **O1's good result hides work.** It passed only because I wrote `Weak` in four places and a snapshot in one. Nothing told me to. R6 (reason about the running program) is weakest here: whether the room is freed depends on every other holder having remembered `Weak`.
3. **O4 needed no reference counts for chatsim.** Ids for back-references plus `&mut Server` in callbacks removed every `Rc`. That is O9 with a hash map as the pool; Rust's borrow checker just did not need to be involved except in case 20.
4. **O9 in C is the shortest and the least checked.** Stale handles are caught, but dangling `char*` obtained from a live handle are not. A language version would make `get` return a borrow that cannot outlive the call, which is O4's rule 2.
5. **No model used cycles, `weak` keywords or shared ownership once identity lived in a table.** Two of three programs needed no reference counts at all.
6. **Cost of free**: the O1 free cascade (user -> callbacks) is invisible in code; O4/O9 free exactly what `remove` names.

## Verdict for the rubric

R6 run-time transparency: O9 5, O4 4, O1 2. The winning shape is O4's static rules with O9's pools as the only identity mechanism (see ADR-0001).
