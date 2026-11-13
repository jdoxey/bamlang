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
