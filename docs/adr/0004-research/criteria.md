# ADR-0004 criteria (written before the options)

The question: how errors are reported, propagated and handled; whether anything can be null; and what a trap is.
The design must fit ADR-0001 (traps, `if x = … else`), ADR-0002 (`Optional`, `Result`, sum types, `match`) and
ADR-0003 (crews re-raise child errors).

## Gates

- **G3:** no annotations (no `throws` clauses that are annotations in disguise, no `@nullable`). Keywords and
  types are fine.
- **R6:** "safer than C", so errors can't be silently ignored.
- **G2/R3:** no unwinding machinery that inspects live objects. Cleanup is by `drop`.

## Scored criteria

| Criterion | Weight | What a 5 means | Anchor |
|---|---|---|---|
| Can't be ignored | 20 | An unhandled error or absent value is a compile error; no null | R6, P-C, P-GO (nil) |
| Transparency | 20 | Every point where control can leave a function because of an error is visible in the source; costs are visible | R6 |
| Simplicity | 15 | Few concepts; one way to report, one to propagate, one to handle | G1, P-SWIFT, P-JAVA (checked exceptions) |
| Clean syntax | 15 | The happy path reads without noise; propagation is a token, not three lines | G4, P-GO |
| Context and diagnostics | 10 | Errors carry where and why (a trace or chain) without user boilerplate | G8 |
| Fit with earlier ADRs | 10 | Works with moves, `drop` cleanup, crews and traps; tests can assert traps (G10) | ADR-0001–0003, G10 |
| Implementation risk (5 = low) | 5 | No unwinding tables or compiler-heavy machinery | project constraint |
| Performance | 5 | No cost on the happy path beyond a branch | P-PY |

Total = Σ weight × score ÷ 5, computed by script. A gap under 5 is a tie, broken by the examples, then by reversibility.
