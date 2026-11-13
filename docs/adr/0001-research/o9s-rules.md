# O9-S: O9 with the review's fixes (loop 2 of PROCESS step 2)

These are the decisions on each finding in `review-o9.md`. They define what the second example models.

## The rules a programmer learns (6)

1. **One owner.** Every value has one owner. It is freed when the owner's scope ends, or when it is overwritten or
   removed. Freeing is a cascade proportional to what is freed (R3).
2. **`=` moves.** Assigning or passing a non-trivial value into storage moves it. Using a moved-from variable is a
   compile error, found by a check local to the function. Copies are explicit: `x.copy()`. Numbers, booleans, enums
   and handles copy implicitly.
3. **Borrows last one call.** Parameters are borrowed for the call. A borrow can't be stored, returned, or captured
   by a closure that outlives the call.
4. **Exclusivity** (fixes F1, replaces old rule 5). While a place is being mutated, nothing else may access it or
   its parts.
   - Checked at compile time for named paths in one function, including overlapping call arguments (`append_all(a, a)`
     is an error).
   - Checked at run time for list elements and pool entries, by a flag per entry. A violation traps, in debug and
     release builds.
   - Mutating a list while iterating it is an error.
5. **Identity lives in pools.** `Pool of T` holds entries, and `Handle of T` refers to one. Both are built-in
   parameterised types (D2 decides the G3 framing).
   - `if w = pool.get(h) { … } else { … }` borrows an entry, and a stale handle takes the `else`. `pool[h]` traps on
     a stale handle (fixes F9).
   - `add` never moves existing entries, because storage is segmented (fixes F2a).
   - `remove(h)` stales `h` at once. If the entry is borrowed (for example, a button's callback removes its own
     dialog), its drop runs when the borrow ends (fixes F2b). This is still proportional to what is freed.
   - `add(v, owner = h)` makes the new entry owned by entry `h` in the same pool. Removing `h` removes everything it
     owns, recursively (fixes F3). Ownership across pools is written in a type's `drop`.
   - Handles carry index, generation and pool id. A handle used on the wrong pool traps. A slot whose generation
     would wrap is retired (fixes F6).
6. **Threads share nothing implicitly.** Owned values move into threads and channels.
   - Shared mutable data is a `Mutex of T`, reached only inside `lock m { … }`. A borrow can't escape the block.
     Re-locking a mutex the thread already holds traps (F8).
   - Module-level variables, pools included, are main-thread state. A function that touches them can't be called
     from a spawned thread. The compiler infers this over the call graph; there's no annotation (fixes F5).

## Debug-only tools (R4: they reclaim nothing)

- An exit report of each pool's live entries, and `pool.expect_empty()` for tests (F4).
- Freed and stale-slot poisoning.
- A lock-order checker.

## Accepted costs

- A forgotten `remove` of a root entry is still a zombie (F4). It is mitigated by owner cascades, `expect_empty` and
  the exit report, not prevented.
- Functions can't return borrows, so getters return copies or handles (F10).
- `.copy()` will be common on strings (F7). The second example counts how common.

## Refinements after the `widgets` example (`docs/examples/widgets/NOTES.md`)

The C model and its writer found eight gaps. These are the decisions.

1. **Shared and mutable borrows.** `if w = pool.get(h)` borrows shared, unless the block writes through `w`; the compiler
   infers which from the block. Any number of shared borrows may coexist. A write to an entry while any other borrow of
   it is live traps. This is what lets the dispatcher read a button while its callback also reads it.
2. **Writes through `pool[h].f = x` are checked too.** A callback replacing its own running `onClick` therefore traps
   (it would otherwise free the running closure). The fix is to set a flag and replace it after the call.
3. **Removing a borrowed owner.** `remove(h)` stales `h` and its whole owned subtree at once. The drops run when the last
   borrow inside the subtree ends.
4. **Drop order.** The owner's `drop` runs first, then the owned entries in creation order. The cascade uses a work list,
   not recursion, so deep trees can't overflow the stack.
5. **Absent handles** are `Handle of T` inside the optional type that D4 defines. Until D4, write `none`.
6. **Iterating a pool.** `pool.handles()` returns a new `List` (a visible copy). Iterating it while adding or removing is
   allowed.
7. **Wrong pool of the same type** is a run-time trap only (the pool id check). This is accepted.
8. **`with w = pool[h] { … }`** is a block borrow that traps on a stale handle, instead of the `else` branch that can't
   happen. Five of the seven `else` branches in widgets were of that kind.

Measured in `o9s.txt` (280 lines): 7 `.copy()` calls, 7 stale branches (2 reachable), and 3 deferred drops in the script.
Cross-pool cleanup (cache release, unsubscribe) is written by hand in `drop`, and nothing prompts for it. A shared
image cache needs a hand-kept use count; the model has no shared ownership, by design.
