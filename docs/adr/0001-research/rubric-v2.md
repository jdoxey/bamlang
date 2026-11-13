# ADR-0001 rubric, version 2 (2026-11-13)

Written before the O1/O4/O9 chatsim ports reported back, so the results can't shape the criteria.
It replaces the v1 rubric in the ADR history. Weights are set by Claude under R7 (this closes Q5).

## Changes from v1

- **New criterion R6, run-time transparency.** Can a reader of the source predict what the running
  program does: when memory is freed, what work runs at free time, whether `b = a` aliases or copies,
  and whether a callback runs or is silently skipped? Hidden work and silent outcomes score low.
- **Simplicity** now counts only the rules a programmer must remember (R6: "not too many different things to
  remember"). Hidden work moves to Transparency, so it isn't counted twice.
- **P3 is closed: memory safety is required.** R6 asks for "more helpful and safe than C". Safety stays a
  scored criterion, and an option that can't be made memory-safe outside `unsafe` is ineligible.
- **Concurrency rises,** because threads are in v1 (R1).

## Criteria and weights

| Criterion | Weight | What a 5 means | Anchor |
|---|---|---|---|
| Transparency | 20 | No hidden run-time work; aliasing, copies, frees and skipped callbacks are all visible in the source | R6, G1 |
| Simplicity | 20 | Fewest memory rules to remember; mistakes are loud (compile error or trap), not silent | R6, G1, G4, P-RUST, P-SWIFT |
| Safety | 15 | No use-after-free, double free or dangling access outside `unsafe`, prevented or trapped | R6, P-C |
| Concurrency | 15 | Data crossing threads is safe by construction, with no sendability retrofit | R1 |
| Expressiveness | 10 | chatsim's shapes (back-references, callbacks, shared cache, re-entrancy) are written directly | G11, P-PY |
| Implementation risk (5 = low) | 10 | Little soundness-critical compiler analysis; failures are loud | project constraint |
| Performance | 5 | No per-object counts or hidden copies on hot paths | P-PY, P-GO, P-JAVA |
| Tooling and C FFI | 5 | Debugger, coverage and C interop straightforward on three OSes | G8, G9 |

Total = Σ weight × score ÷ 5, out of 100. A gap under 5 points is a tie (PROCESS.md), broken by the chatsim
examples, not the scores.

## Scale

5 best in the field; 3 workable at a clear cost; 1 disqualifying.
