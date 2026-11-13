# Merged D4 design (E1 spelling over E2 Result values): loop-2 example

`errors.txt` is illustrative pseudo-syntax only (not a syntax decision). `c/errors.c` is a C model; `c/run.sh`
diffs its output against `../expected.txt`, then runs `--selftest`. Tags F1..S7 refer to `review-e1.md`.

## Numbers
- `errors.txt`: 170 lines (140 non-comment). Header+error type 17, part 1 57, part 2 46, part 3 41, main 9.
  Vs Swift 256, Go 331, Rust 350. Not comparable: it leaves out the shared error type and stdlib (in the C model
  that is about 250 of 678 lines), and each version is annotated. The honest comparison is part by part, and
  the pseudo is shorter mainly because the stdlib (Report, Txn, TempDir, Lock, Mutex) is assumed.
- `try` tokens: 24 (3 in `main`, 1 `try crew`). `or e` handlers: 1. Context strings: 17 (11 distinct).
  Must-consume sites written by hand: 3 (two `match`, one `report.add_if_err`), plus the crew's `or e`.
- Cleanup in `replace_file`: 5 lines (Txn, on_undo, `try f.close()`, `try lock.close()`, `commit`) plus 2 stdlib
  declarations. Swift's `defer` plus its `held` flag: 6 lines. No saving; the gain is that close errors are seen.
- C model: `TRY*` macros 20 uses; must-consume check by a per-thread counter asserted at exit.

## Selftest and checks (all pass)
Main diff matches expected.txt. Selftest, 19 checks: trap in the parent body propagates (inner children joined,
inner `try crew` never returns); plain `crew` re-traps a child trap; a trap in a drop during unwinding is appended
and later drops still run; poisoning, trap on `lock`, `clear_poison`; the F1 cell is dead after the trap and use
traps; leaked Result exits non-zero with "unconsumed"; bare trap and trap in a qsort comparator inside a crew
child exit 70 with "TRAP" (re-exec via popen); dirty Lock drop counted, file removed. Also clean under
`SAN=1` (ASan+UBSan, with `detect_stack_use_after_return=0` set by run.sh; no reports seen), gcc and clang, 15
repeat runs. Not run here: Windows/macOS (MinGW paths `_open`, `_mkdir`, `remove`-then-`rename`, `_popen` are written but untested).

## Unclear or contradictory when actually written (be critical)
1. F1 vs static typing. "Dead after the brace" cannot depend on whether the child trapped. As a compile error it
   must apply to every variable a `try crew` child borrows mutably, even on success, which makes `try crew` with
   mutating children very awkward (the crew would need to hand the variables back). The model uses a run-time
   dead flag instead, which is a different rule. This needs a ruling.
2. `r = try crew c { }`: `try` here both propagates (S4) and means "convert child traps" (F2). To print the error
   and carry on I had to write `try crew … or e { }`. A plain `crew` still returns child errors but re-traps child
   traps; the asymmetry is unspecified in S1/F2 beyond one sentence.
3. S6 Txn vs consuming close: `txn.on_undo(|| lock.abandon())` borrows `lock`, and `try lock.close()` later consumes
   it: a borrow conflict in the real language. The C model hides this by sharing one struct. Needs a design
   (the Lock owning its own "dirty" drop, with Txn only for non-resource undo).
4. Who adds "worker N" to a trapped child? Nothing in the review says; the model adds it at the brace. "First
   error" now has to rank traps among errors (lowest worker number, traps included).
5. S5 "callback from C is a trap barrier" needs every FFI callback thunk to count depth; trivial in C, a real
   codegen rule. A trap in the parent body of a crew nested in a child is converted by the OUTER child (shown in selftest).
6. S1 "map with a failing function gives List of Result": unconsumed elements are legal to drop? Not shown by this benchmark.
7. Windows has no atomic replace via `rename`; the "never partial" invariant needs a stdlib `replace` (MoveFileEx).
8. Unconsumed Results held by frames killed by a trap are silently discarded in the model; the real rule must say so.
