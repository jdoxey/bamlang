# D4 ideas (Sonnet inventor, two lenses; condensed; unscored)

Common assumptions:
- A trap unwinds and runs `drop`s, and is caught only at a crew brace (re-raised as an error of kind `trap`) and by
  `expect_trap`.
- A `drop` can't fail; a trap during unwinding is appended to the chain.
- OOM traps, and `try_alloc` is the opt-in.

## Reader-at-3am lens (sane)

**S1 `fails` + `try` + one `Error`.**
- **Mechanism:** a `fails` keyword in the signature, and `try` required at every call to a failing function
  (`try f() else e { }`, `try f() with "context"`). There is one `Error` type (kind, message, context chain, trace).
  Absence is `Optional`, with no `try?`.
- **5 rules.**
- **Risk:** `fails` spreads up the call graph, like `throws` and `async`.

**S2 `Result` + statement-only `check`.**
- **Mechanism:** `check v = f(x) [with "ctx"]` binds or returns, and is never inside an expression (Go's lesson). An
  unconsumed `Result` is a compile error. Collect-all is natural, because results are values.
- **4 rules.**
- **Risk:** temporaries everywhere; the happy path gets noisy (G4).

**S3 S1 + `Txn` guard.** A guard's `drop` runs the undo unless `commit` consumes it. A failed undo is appended to the
chain.
- **6 rules.**
- **Risk:** undo closures that capture state the main path is still mutating.

**S4 S1 + `need` preconditions.** A violated precondition traps and blames the caller's line (Midori's 90% case). A
mutex poisoned by a trap is visible on its next `lock`.
- **6 rules.**
- **Risk:** it looks like an annotation, and conditions can have side effects.

## Break-an-assumption lens (crazy)

**X1 lexical `handle` + crew `on error`.**
- **Mechanism:** call sites are unmarked.
- **Flaw:** exits are invisible.
- **Kernel:** a crew-level `on error` as the visible home of the "plus N more" policy.

**X2 `Partial of T` + `Report`, always.**
- **Mechanism:** a function returns a (possibly degraded) value plus a list of problems.
- **Flaw:** half-built values leak.
- **Kernel:** `Report` as an accumulator type for collect-all.

**X3 absence as a compiler-tracked type-state.**
- **Flaw:** it can't cross a function boundary.
- **Kernel:** flow-sensitive narrowing with a precise "maybe absent here" error.

**X4 compiler-synthesised propagation.**
- **Flaw:** exits are invisible (fails R6).
- **Kernel:** tools render every error exit (debugger gutter, `explain`, coverage).
