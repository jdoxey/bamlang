# widgets under O9-S: notes

`bash o9s-c/run.sh` passes (output matches `expected.txt`; 4 trap checks and the in-process checks pass).
ASan+UBSan+LeakSanitizer: clean on `widgets.c` with `script.txt`, and on `traps.c`.

## Counts
- `o9s-c/widgets.c`: 450 lines. Pool library 145 (lines 11-155), program ~294. `traps.c`: 88. `o9s.txt`: 280 (with comments).
- `o9s.txt`: 7 `.copy()` calls (3 strings stored in structs, 3 for closure captures or display, 1 list snapshot).
- Explicit stale `else` branches: 7. Only 2 can really fire (`notify` skip, `unsub_click`). The other 5 are "cannot happen"
  (`release_image`, `label_changed`, `remove_widget` parent, `cmd_click`, `print_tree`). Plus 6 `x.has(h)` tests.
- Trapping `[h]` lookups: 19 (`widgets[h]`, `cache[h]`). Another 6 `.get(h)` borrow blocks.

## What fires in `script.txt`
- Deferred drops, 3: the `once` subscriber (removed from inside its own notify), button `popup-close` and button
  `closeme` (each removed by its own `close` callback). The exit report says widgets=2, subscribers=1.
- Add while borrowed, 2: `click opener` creates a window while the opener button is borrowed.
- Stale handle detected: 1 (`unsubber` captured `total`, which was removed; `fresh` reused the slot, so only the
  generation told them apart). A subscriber skipped as stale: 0.
- Traps: 0 in the script (a correct run shouldn't trap). `traps.c` fires: double mutable borrow, wrong pool, stale
  `pool[h]`, `expect_empty` on a zombie. It also checks deferred drop, 1000 adds under a borrow (pointer unchanged),
  nested cascade with a borrowed grandchild, and generation-wrap retirement.

## Bugs I actually hit
- Runtime: none in `widgets.c`. `traps.c` first leaked its pool storage under LeakSanitizer (my test, not the model).
- Design bugs found before running:
  - With a literal single "borrow flag" the `close` button traps itself. `cmd_click` holds the button while the
    callback calls `enclosing_window(self)`, which reads the same button. I needed shared/mutable borrows.
  - `remove_widget` had to detach the handle from the parent's `kids` list first, or the parent holds a stale handle.

## Awkward
- Hand-kept lists next to the pool: `kids`, `windows`, `sub_order`. Each needs a matching erase on every removal path.
- Cross-pool cleanup lives in `drop Widget` (release the image, unsubscribe). Forget it and the cache entry or
  subscriber is a zombie. Nothing in the model prompts you to write it.
- Image cache: a hand-written `users` count, as the task expected. The model offers nothing better. The rules'
  alternative (cache owned above both images plus an explicit release in drop) is the same count by another name.
  No shared ownership exists, and I don't think there should be.
- `notify` copies the subscriber list (rule 4 forbids mutating a list while iterating). Correct, but it is a rule
  you learn by failing.
- Deferred drop makes output appear after `click ... done`. A drop can now run, with side effects, at a block's closing
  brace after a callback. That is correct but surprising to read (G1).
- `none`, `has`, `handles()`, `x.get(i)` on lists and `match` are all assumed. Names are found by scanning the pool.
- The many "cannot happen" `else` branches show a gap: there is `if w = pool.get(h)` and the one-expression `pool[h].x`,
  but no block form `with w = pool[h] { ... }` that traps instead of branching.

## Rules in o9s-rules.md: unclear, contradictory or insufficient
1. "A flag per entry" is under-specified. One flag makes the standard dispatcher (`get(btn)`, call, callback reads
   `btn`) trap. I modelled shared/mutable counts. The rules must say whether `get` borrows shared or mutable,
   and whether that is inferred from the body.
2. Writes through `pool[h].field = x` need the run-time check too. My `pool_at` checks reads against a mutable
   borrow only. A callback that replaces its own `onClick` frees the closure that is running (a use-after-free) and is
   not caught by anything in the rules as written. This is the F1 class again, and it was not in the review.
3. Owner cascade vs deferred drop: if the removed owner is borrowed, are its children stale at once? "remove stales h
   at once" says nothing about the subtree. My model keeps them live until the owner's release. The script doesn't
   hit it (the window is never the borrowed entry), but a real dialog would.
4. Drop order is unspecified (I chose owner first, then owned entries in creation order). Output depends on it.
   Recursion depth of a cascade on a deep tree is also unstated.
5. No `none` handle or `Handle?` is defined. Window parents and unset `sub` fields need one.
6. Rule 4 bans mutating a list during iteration. It doesn't say whether `for h in pool.handles()` may add or
   remove. Dispatch needs it constantly.
7. Typed handles: two `Pool of Widget` values share a type, so a wrong-pool use is a run-time trap only, in the model.
8. Rule 3 forces `.copy()` for closure captures of string parameters. It is cheap here but easy to forget; the
   compiler hint from F7 matters.
