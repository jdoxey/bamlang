# Adversarial review of E1+ (Opus reviewer, 2026-11-13; condensed) and decisions

**Verdict:** not ready.
- **Corrected scores:** E1+ as specified 80, E2 85 (E2 had been scored on Go's tooling, not as S2); with fixes, E1+
  83.5, E2 85.5. That is a **tie**, and the examples can't break it, because neither tested its own design.
- **Recommendation:** merge them. E1's surface becomes spelling over E2's `Result` values (S1(b)), which is also the
  most reversible.

| # | Severity | Finding | Decision |
|---|---|---|---|
| F1 | fatal | A trapping child leaves mutably borrowed, non-Mutex data half-updated (`debit` then a trap) | **Adopt.** Variables a trapping child borrowed mutably are dead after the brace (dropped; a later use is a compile error, through the move checker). |
| F2 | fatal | A trap in the crew's own body makes `try crew` a general catch | **Adopt.** Only a child's trap is converted. A trap in the parent body cancels and joins, then continues as a trap. A plain `crew` (no `try`) re-traps a child's trap. |
| S1 | serious | `fails` spreads into function types and built-in algorithms (it needs `rethrows`) | **Adopt (b).** `fails` is spelling for `-> Result of T`. A bare call gives a `Result`, and an unconsumed `Result` is a compile error. `map` with a failing function gives `List of Result`. Ordering and key functions can't fail. One mechanism, no effect typing. |
| S2 | serious | One `Error`: how to tell kinds apart | **Adopt.** `kind` is a closed stdlib enum of about 12 values. Outcomes callers routinely branch on (not found, key absent) are return values (`Optional` or a sum type), not error kinds. E3's exhaustive typed matching is given up, and that is recorded. |
| S3 | serious | `else` and `with` clash with ADR-0001's grammar | **Adopt.** Working spellings are `try f() or e { … }` and `try f() context "…"`, and D6 picks the final ones. The handler block gives a value of type T or leaves the function. |
| S4 | serious | `try` inside expressions hides exits and muddles moves | **Adopt.** A propagating `try` is only the outermost operation of a statement or binding (Go's lesson). `or e { }` forms may appear in expressions. |
| S5 | serious | Unwinding cost, FFI, release builds | **Adopt.** Traps unwind with tables, the same in all builds. Outside any crew a trap aborts with the trace. A callback from C is a trap barrier that aborts. A trap inside a `drop` during unwinding is appended to the chain. The unwinder releases borrow counts. The criteria's "no unwinding tables" anchor is relaxed for traps (recorded). |
| S6 | serious | "`drop` can't fail" loses flush errors | **Adopt.** Fallible cleanup is a consuming `try x.close()`. A dirty writer dropped without `close` appears in the debug exit report (R4). A `Txn` guard (undo unless `commit`) is in the stdlib. |
| S7 | serious | Poisoning unspecified | **Adopt.** `lock` on a poisoned mutex traps. `m.is_poisoned()` and `m.clear_poison()` let a supervisor repair it. The lock is released during unwinding. |
| M1–M5 | minor | Empty handlers; eager context; trace allocation; Optional details; crew children | **Adopt.** The handler must use `e`, give a value, or be written `or _ { }`. Context is evaluated only on the error path. The trace is inline (about 8 PCs), with no allocation. `unwrap` is a long greppable name. No flattening and no narrowing of Optional. `-> Optional of T fails` is fine. `c.go` accepts failing functions. |

The honest rule count is 16 (E2 alone is about 13).

## Decisions on the gaps the loop-2 example found (`docs/examples/errors/merged/NOTES.md`)

1. **F1 is a static rule on the error path only.** In a `try crew … or e { }` handler, and after it, every variable the
   crew's children borrowed mutably counts as moved, so using it is a compile error. On the success path they are
   live. A propagating `try crew` leaves the function, so nothing remains to use. No run-time flag is needed.
2. **`crew` vs `try crew`.** A plain `crew` gives the children's `Result` (it must be consumed) and re-traps a
   child's trap. `try crew` also converts child traps into an `Error` of kind `trap`. As a statement it propagates;
   with `or e { }` it handles.
3. **`Txn` covers only non-resource undo.** A resource owns its own cleanup: a `Lock`'s `drop` removes the file and
   marks the drop as "dirty" in the debug report, and `try lock.close()` is the checked path. That avoids a borrow
   conflict between the guard and the resource.
4. **The crew adds `child N (site)` context** to every child error or trap. "First" means the lowest `c.go` order,
   with traps included.
5. **FFI callback thunks track depth** so that a trap in a callback from C aborts. This is a codegen rule for D8.
6. **Must-consume applies to each `Result` expression.** A `List of Result` counts as consumed when the list is.
7. **Atomic file replace** is a stdlib `replace` (`rename` on POSIX, `MoveFileEx` on Windows). This is for D10.
8. **Unconsumed `Result`s in frames unwound by a trap are discarded,** because the trap is the louder event.
