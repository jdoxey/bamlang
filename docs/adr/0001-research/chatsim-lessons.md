# What the chatsim ports taught (D1 step 3), and the v2 scores

All four versions in `docs/examples/chatsim/` produce byte-identical output on Linux, Windows and macOS.
Each folder's `NOTES.md` has the detail. Ports were written by Sonnet to a spec. O1 was first written in C++ `shared_ptr`, then replaced by Swift 6 (issue #1); the findings matched. None of the writers hit a
runtime bug, because each knew the hazards in advance, so "bugs hit" is weak evidence. The structure the
model forced is the strong evidence.

| | C (reference) | O1 Swift ARC | O4 Rust ownership | O9 C pools + handles |
|---|---|---|---|---|
| Lines (`wc -l`) | 359 | 292 | 469 | 392 (≈309 without the generic pool) |
| Cleanup walks on free | 3 loops ("MANUAL:") | none | none | none |
| Escape hatches needed | — | strong/weak chosen per field, unchecked | `Rc<User>`, 6 `RefCell`/`Cell`, 6 `Weak`, rooms by name | none |
| Case 12 (last leave frees room) | explicit | correct only because `user.room` is weak | owned `Room` returned by `swap_remove` | explicit `pool.remove` |
| Case 14 (deleted user) | dangles unless walk nulls it | `weak.lock()` fails | `Weak::upgrade` fails | stale handle lookup fails |
| Case 17 (cycle) | n/a | **real, silent leak** when the explicit leave path is skipped (LSan: 1012 B in 20 allocations); only the alive counters showed it | avoided by referring to rooms by name | no ownership cycle possible: handles own nothing |
| Case 20 (re-entrancy) | careful indexing | care needed (index loop, closure copied out first), unenforced | **E0502**; fixed with a per-message snapshot `Vec` of Rc clones: hidden allocation and a silent semantic choice | rule "no lookup pointer across a pool-mutating call", kept by discipline only |
| Case 25 (threads) | mutex by discipline | lifetime safe; Swift 6 demanded `@unchecked Sendable` and `nonisolated(unsafe)`, so data safety rests on discipline | compiler rejected `Rc` crossing threads (`Send`) | values move; pools stay on one thread; mutex by discipline |
| Hidden work | none | atomic retain/release on nearly every line, weak side tables; destructor timing depends on stray copies | Rc traffic, snapshot per post | pool growth relocates entries; nothing at free time |
| Forgotten cleanup | dangling pointer, UAF | silent leak | silent leak (inside `shared`) | zombie entry: handles stay valid, logic bug, bounded leak, visible in pool count |

## What each taught

- **O1:** shortest and nicest to write. But every field needs a strong-or-weak choice that nothing checks.
  A wrong choice is a silent leak that shows only on a path the tests may not run. ARC answers "is it alive?",
  never "who may touch it?". Swift 6's checker could only be satisfied by two unsafe escapes for case 25. It fails R6's "easy to reason about while
  running": when a `~User` runs depends on any stray copy anywhere.
- **O4:** the compiler's thread check is the best of the three. But chatsim needed both models at once
  (owned values *and* `Rc`/`RefCell`/`Weak`), plus names-as-references to dodge a cycle. That is the most rules,
  and it is the longest program. The re-entrancy fix added hidden work.
- **O9:** the only port where every reference is visibly a lookup that can fail, nothing happens behind the
  source, and no cycle can exist. Costs: an explicit stale branch on each lookup (~12 in chatsim), a forgotten
  `remove` makes a zombie rather than a crash, and the "don't hold a lookup across a pool mutation" rule must be
  enforced by the language, because C couldn't.

## O9 as it would be adopted (the rule set the reviewer attacks)

1. **One owner.** Every value has one owner and is freed when the owner's scope ends or it is overwritten.
2. **`=` moves non-trivial values.** Using a moved-from variable is a compile error (a local, per-function check).
   Copies are explicit: `x.copy()`. Numbers, booleans and handles copy implicitly. (Closes Q14: explicit.)
3. **Parameters are borrowed for the call.** A borrow can't be stored, returned or captured by a closure that
   outlives the call.
4. **Identity lives in pools.** `Pool of T` is a built-in container. `add` returns a `Handle` (index, generation). `get`
   returns a borrow inside `if u = users.get(h) { … } else { … }`. A stale handle takes the `else` branch.
   `remove` is explicit and bumps the generation.
5. **A borrowed pool is locked.** While a borrow from `get` is live, `add`/`remove` on that pool, or a second `get`
   of the same entry for mutation, traps (debug and release). Rejected at compile time where the compiler can see
   it in one function, trapped at run time otherwise.
6. **Threads.** Owned values move to threads and through channels. Shared mutable data lives in a `Mutex`
   and is reached only inside its lock block. Nothing is reference-counted, so nothing needs atomic counts or
   a sendability inference.

Closures capture by move or copy (handles copy), so Q11 resolves to "callbacks capture handles and handle the
stale branch explicitly". Debug builds report each pool's live entries at exit (R4: reclaims nothing).

## Scores (rubric v2; `adr0001_scores_v2.py`)

| Option | Transp 20 | Simp 20 | Safety 15 | Conc 15 | Expr 10 | Impl 10 | Perf 5 | Tool 5 | Total |
|---|---|---|---|---|---|---|---|---|---|
| O1 | 2 | 4 | 5 | 2 | 5 | 4 | 3 | 4 | 70.0 |
| O4 | 3 | 2 | 5 | 5 | 4 | 2 | 4 | 5 | 71.0 |
| O9 | 5 | 4 | 5 | 4 | 3 | 4 | 4 | 4 | **85.0** |

O9 leads in every ±10 weight variant and with equal weights (smallest margin 7.5). A drop of 2 in any single O9
cell still leaves it 6+ ahead. O1 vs O4 is a tie. The reviewer's findings follow in `review-o9.md`.
