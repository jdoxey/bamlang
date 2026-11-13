# ADR-0002 criteria (written before the options)

The question: how do typed containers and generic algorithms exist when G3 says the language "must not have templated
types, macros or annotations"? ADR-0001 needs `List of T`, `Map of K to V`, `Pool of T`, `Handle of T`,
`Mutex of T`, `Channel of T` and an optional type.

## Gate: G3, read literally

An option fails if a **user** can declare a type parameter, write a template or macro, or attach an annotation.
Compiler-provided parameterised types that users *instantiate* (`List of Employee`) pass if the language has a closed
set of them (P2 is decided here; reasoning in the ADR). Inferred behaviour (for example, a derived `compare`) is not an
annotation.

## Scored criteria

| Criterion | Weight | What a 5 means | Anchor |
|---|---|---|---|
| Stdlib reach | 20 | The three test programs (sort with a comparator, an LRU cache reused for two key/value pairs, an `Optional` pipeline) are written once, typed, with no copy-paste per type | G6, P-GO (pre-1.18 pain) |
| Simplicity | 20 | Few concepts; a reader understands any signature without learning a type-level language | G1, G3, P-SWIFT, P-CPP |
| Run-time transparency | 15 | No hidden boxing, dynamic dispatch or code bloat that the source doesn't show; costs predictable | R6 |
| Static safety | 15 | Type errors are compile errors; no casts that can fail at run time | R6, P-C (Java 1.4 lesson) |
| Error messages | 10 | Errors point at the user's line in user terms, not inside instantiated library code (Zig and C++ lesson) | G1 |
| Implementation risk (5 = low) | 10 | Little compiler machinery; fits the ADR-0001 checkers | project constraint |
| Clean syntax | 5 | Container and algorithm use reads without brackets or noise | G4 |
| Performance | 5 | No boxing on hot paths; specialised code where it matters | P-PY |

Total = Σ weight × score ÷ 5. A gap under 5 is a tie, broken by the examples.
