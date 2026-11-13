# ADR-0003 criteria (written before the options)

The question: what crosses threads, how shared state is guarded, and whether v1 has async, given ADR-0001 rule 6
and ADR-0002.

## Gates

- **R1:** OS threads exist in v1.
- **G2/R3:** no collector, and nothing that inspects live objects (for example, no cycle-collected actor
  mailboxes).
- **G3:** no annotations (no `@Sendable`, `@MainActor` or `#[derive(Send)]`). Inferred properties are fine.
- **ADR-0001/0002:** must use owned values, moves and `take`, with no reference counting.

## Scored criteria

| Criterion | Weight | What a 5 means | Anchor |
|---|---|---|---|
| Race safety | 20 | No data race is possible outside `unsafe`, by construction, at compile time | R6 ("safer than C"), P-GO |
| Transparency | 20 | The source shows which code runs on which thread, where it can block, and when work is cancelled; no hidden scheduler | R6 |
| Simplicity | 20 | Few concepts; no function colouring; mistakes loud | G1, P-RUST, P-SWIFT |
| Deadlock and leak resistance | 10 | Deadlocks and leaked threads are prevented, or trapped and reported | R6, G8 |
| Expressiveness | 10 | The three benchmarks (parallel map, worker pool with a shared counter and a result channel, UI thread plus a cancellable background job) are written directly | G11 |
| Implementation risk (5 = low) | 10 | Fits the ADR-0001 checkers; no new soundness-critical analysis | project constraint |
| Performance | 5 | Real parallelism; no per-message deep copies forced | P-PY |
| Debugging and testing | 5 | Thread state visible in a debugger; deterministic test mode possible | G8, G10 |

Total = Σ weight × score ÷ 5, computed by script. A gap under 5 is a tie, broken by the examples, then by reversibility.
