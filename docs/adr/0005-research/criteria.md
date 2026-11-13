# ADR-0005 criteria (written before the options)

The question: how types carry behaviour. That covers methods and `self`, interfaces and dispatch, inheritance or
not, construction and invariants, and visibility. The design must fit ADR-0001 (pools, handles, moves), ADR-0002 (sum
types, records of functions, no user type parameters) and ADR-0004 (`fails`).

## Gates

- **G3:** no annotations (no `@override`, `#[derive]` or decorators). Keywords are fine.
- **P-PY:** methods must not require writing `self` as a parameter at every call or declaration.
- **R6:** a reader can tell which code a call runs, or can see that it is dynamic.

## Scored criteria

| Criterion | Weight | What a 5 means | Anchor |
|---|---|---|---|
| Transparency of dispatch | 20 | Static calls look static; dynamic calls are marked or typed visibly; no hidden overriding | R6 |
| Simplicity | 20 | Few concepts: no class, struct, protocol and extension zoo | G1, P-SWIFT, P-CPP |
| Extensibility | 15 | Third-party code adds new kinds (shapes, widgets) without editing the core; the benchmarks are written directly | G11, G7, P-C |
| Invariants and encapsulation | 15 | Constructors can enforce invariants; private state can't be reached around them | R6 ("safer than C") |
| Clean syntax | 10 | Method calls read naturally; no `self.` noise; declarations are short | G4, P-PY |
| Fit with earlier ADRs | 10 | Works with moves, pools and handles, sum types and `fails`; no new memory concepts | ADR-0001–0004 |
| Implementation risk (5 = low) | 5 | No complex resolution rules (orphan rules, overload sets, diamond) | project constraint |
| Performance | 5 | Static dispatch by default; dynamic cost only where written | P-PY |

Total = Σ weight × score ÷ 5, computed by script. A gap under 5 is a tie, broken by the examples, then by reversibility.
