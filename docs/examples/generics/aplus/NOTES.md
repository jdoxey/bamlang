# A+ example: NOTES (D2 loop 2, rewritten to the A+ decisions in `a-plus.md` and `review-aplus.md`)

Files: `aplus.txt` (pseudo-syntax), `c/aplus.c` (C model), `expected-aplus.txt` (unchanged: `../expected.txt` + Part 4),
`c/run.sh` (builds with `-std=c11 -Wall -Wextra -Werror -O1 -g`, diffs, runs the trap tests; passes with `SANITIZE=1`,
address+undefined, gcc and clang on Linux; macOS and Windows not run by me).

## Counts (aplus.txt, 355 lines; "code" = non-blank, non-comment)
| Part | lines | code |
|---|---|---|
| 1 algorithms | 41 | 36 |
| 2 LRU (incl. driver) | 142 | 113 |
| 3 Optional + thread | 31 | 26 |
| 4 bus + widgets | 132 | 94 |

- `.copy()`: 12 (Part 1: 4, Part 2: 3, Part 3: 1, Part 4: 3 incl. `Ui.render`). Was 13.
- Stale `else` branches: 4 (2 in `get`, 2 for the eviction victim in `put`; the `put` ones are unreachable). Same as before.
- `take` parameters: 9 (`put` x2 = 3, closure helpers `put_p`/`put_q` = 4, `subscribe`, `publish`). `with`: 2.
- LRU generic part: **11 code lines** (was 17; Go option A: 22). Per-use glue: **32** (UserKey/Profile) and **30**
  (Str/List of Int); before 32/30; Go option A 31/31. So **still no saving, no cost**. `Pool` replaced `Table`
  and `Ids`: the `acquire` call and the key Table vanished, but the entry struct (3 lines), `pool.id(h)` (3 per use)
  and the `pool.handle(...)` victim lookup took the same lines back. The gain is safety (foreign and stale are told apart).
  The key is still stored twice (entry and Map); `QueryCache.put` now makes 1 copy of the key, not 2 (put takes `k`).

## Trap tests run by `run.sh` (all: `TRAP: ...` on stdout, exit 70, no signals)
- F3: forgotten `slots.remove` -> `get` misses via the stale `else`; `put` of that key traps (`stale Handle`).
  Slots are reused with the next generation, so the dangling Handle never sees the new tenant.
- S1: `with first = log[0] { note("b") }` where `note` (another function) pushes: traps. After the borrow, the push works.
- S7: `with x = m[k] { m.remove(k) }` traps (a block borrow holds the whole Map; inserting a NEW key traps too).
- S5: a foreign Id (`pool.handle`) and a foreign Handle (`pool[h]`) trap; a stale Id on its own pool returns "else".
- S6: `m[k].push(m[j].pop())` and `m[k].push(grow(m))` (argument inserts a key) work with arguments first. The naive
  order (place first, argument second) is shown to trap via S1: that is what the borrow count buys.

## Part 4
- 4a: the counter lives in `Stats.counts: Pool of Int`, the subscriber holds a Handle (Copy). `seen` is mutated by an
  escaping closure, so it is moved in (S4); reading it outside is a use-after-move error. The old "`n` stays 0" trap is gone.
- 4b: `enum Widget { Button(Handle of Button), ... }` plus `match`. Shorter than the record of functions, exhaustive,
  and the pools can be locals. **Record of functions dropped**: a stored `fn(Id)` escapes, so it cannot borrow the pools
  (they would be module state) and the Id would be untyped. It only fits an open set of kinds, which 4a already shows.

## Not modelled in the C
Per-entry borrow flags on Pool entries (rule 5): only List and Map carry the borrow count. Pool ids are not atomic.
## Unclear or contradictory rules (critical)
1. **"Escapes exactly when ... assigned" (S3) contradicts S2.** `put_p = fn ...` is an assignment, yet the helper must
   count as non-escaping. The rule must say "assigned to a field, global or `take` parameter", not to a local.
2. **Closure parameters and `take`.** Decision 1 forbids inferring `take` from a body, but a closure's parameter types
   are inferred. I wrote `fn take k, take vs ->`. Without it `Profile { name: name }` moves out of a borrowed parameter.
3. **Block borrow of a Pool.** S7 says a block borrow holds the whole container; ADR-0001 rule 5 says `add` during a
   borrow is fine and flags are per entry. In `get`, `self.lru.touch(self.pool.id(h))` runs inside `if e = self.pool.get(h)`,
   which only works if the borrow is shared or per entry. Pick one for `Pool`.
4. **`pool.remove(h)` returns the entry**, and `old.key` is then moved out of `old` (partial move, decision 4). Neither
   the return type nor `remove_at` returning its element is written down.
5. **Unreachable stale branches stay.** Because `pop_victim` already removed the Id from `order`, the victim can be stale
   only if code removed pool entries behind the Lru's back (a `Cache.remove(k)` that forgot `lru.forget`). Then the right
   answer is to try the next victim, not `trap`. The Lru has no `forget`, and no test exercises it. Invariants split
   between `Lru.order` and `Pool` are by hand (the same hand-kept coupling the `Ids` design had).
6. **Statement-length place borrows vs. the run-time count.** `m[k].push(e)` needs no count if nothing runs between place
   and push; the C takes one only to show S6. The spec should say whether a place expression ever bumps the count.
7. **The run-time borrow count is a cost on every container** (a counter and a branch per structural mutation, in
   release too). Cheap, but the docs must state it. A mistake via a named path is a compile error, via a function a trap.
