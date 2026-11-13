# A+ example: NOTES (D2 loop 2)

Files: `aplus.txt` (pseudo-syntax, illustrative only), `c/aplus.c` (C model: built-ins section, then the program),
`expected-aplus.txt` (= `../expected.txt` + Part 4). `c/run.sh` builds with `-Wall -Wextra -Werror`, diffs, and runs the F3
checks. It also passes with `SANITIZE=1` (address+undefined) under gcc and clang on Linux.

## Counts (aplus.txt, 357 lines; "code" = non-blank, non-comment)
| Part | lines | code |
|---|---|---|
| 1 algorithms | 41 | 36 |
| 2 LRU (incl. driver) | 145 | 119 |
| 3 Optional + thread | 31 | 26 |
| 4 bus + widgets | 131 | 99 |

- `.copy()` calls: 13 (Part 1: 4, Part 2: 4, Part 3: 1, Part 4: 3 incl. `render_label`). `COPY` notes also mark value-form algorithms.
- Explicit stale `else` branches: 4 (one per `get` x2, one per `put` victim-key lookup x2; the put ones are unreachable).
- `with`: 2. `m[k]` / `t[id]` place uses: about 17 (groups, vals, counts, buttons, sliders).
- LRU: generic part 17 code lines (Go option A: 22). Per-use glue: **32** (UserKey/Profile) and **30** (Str/List of Int),
  Go option A: 31 and 31. **No saving**: the typed Tables replace the Go slices, but the nested `if id` / `if p` / `else`
  and the `old = victim` lookup add what the slices removed. The gain is safety, not size.
- Two `.copy()` of the key in `QueryCache.put`: the Table and the Map each need to own a key.

## F3 (stale Id) in practice
Both `c/aplus.c --f3` and `--f3-put` deliberately forget `slots.remove(old)`. Go option A returned another entry's value.
Here: `get` finds the dangling Id, `vals.get(id)` is NULL, the stale `else` runs, output `profiles get 1/1 miss`.
A later `put` of that key traps (`stale Id (index 0, generation 1) used on a Table`) at `vals[id] = v`.
Both are checked by `run.sh`; neither shows in the Part 2 output, which has no such bug.

## Part 4
- Bus: a stored subscriber cannot borrow, so shared state is an `Id` captured by copy, with its `Table` lent as an
  argument (`Stats`) by `publish`. State that only the closure needs is owned by it (`seen`, `prefix`). The tempting
  `bus.subscribe(fn -> n += 1)` copies `n`, so the caller's `n` stays 0: silently wrong unless the compiler warns.
  **Recommendation:** error when a stored closure mutates a captured Copy variable that the outer scope later reads.
- Widgets: `render: fn(Id) -> Str` cannot borrow, so its Tables are module-level (main-thread) state. 4a's context-passing
  and 4b's module state are two different answers to one problem; the docs must teach both.

## Still awkward
- Copy-returning getters: every `get` copies the Profile or List just to print it. A visitor (`get_with(k, fn p -> ...)`
  with a non-escaping closure) avoids the copy but changes the shape of the API.
- `Map` key plus `Table` key: the key lives twice. `keys` Table exists only so eviction can find the Map key.
- The runtime borrow flags on Table entries (ADR rule 4) are not modelled in the C; `table_get` pointers are trusted.

## Unclear or contradictory rules (critical)
1. **Consuming parameters are undefined.** ADR rule 3 says parameters are borrowed for the call; rule 2 says passing into
   storage moves. `put(k, v)` must take `v`. I invented `take v`. Needs a rule (D6).
2. **Staleness is relative to what?** a-plus.md: "a stale `Id` takes `else` ... exactly as handles do". But `Ids` and
   `Table` are separate objects, and a Table cannot hold a reference to its `Ids`. In my model a Table slot stores the
   generation that wrote it, so an Id reissued by `Ids` still reads the OLD data until the new Id is inserted, and a stale
   Id can be `insert`ed into an emptied slot. `Pool` (= `Ids` + `Table`) has no such window. Either Table must be created
   from an `Ids` (a binding, not a stored borrow), or LRU-style code should use `Pool`-like pairing.
3. **`Ids.reissue` is not in a-plus.md.** Without it a full cache needs `release` then `issue`, which may reuse any slot.
   I added `reissue` (same slot, next generation). Specify it, or say what `release` recycles.
4. **`if x = m.get(k)` binds a borrow for a block**, but ADR rule 3 says borrows last one call and rule 5 allows the block
   form only for pools. a-plus.md extends it to Maps and Tables without saying so. Same for `Optional` fields (`if a = r.addr`).
5. **String literals and partial moves** are unspecified. I assumed a literal is a fresh owned `Str`, and that
   `fn u -> u.addr` may move one field out of an owned struct and drop the rest.
6. **F5 leaves stored closures with no way to share state** except Id-in-Table, argument passing or module-level state.
   That is workable but a-plus.md should say so, since "must own state or hold an Id" is not enough: the Id is useless
   without the Table.
