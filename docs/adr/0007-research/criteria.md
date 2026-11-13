# ADR-0007 criteria (written before the options)

The question: how the language supports DSLs and declarative layout (G11) without macros, annotations or user type
parameters (G3), within ADR-0006's syntax and ADR-0001's memory model. This also settles Q15: whether G11 is syntax
only or includes a UI framework in v1.

## Gates

- **G3:** no macros, annotations, result-builder attributes, compiler plugins or user type parameters.
- **G5:** no indentation meaning.
- **ADR-0006 must stay a strict extension:** existing programs keep their meaning, and new syntax needs no backtracking.

## Scored criteria

| Criterion | Weight | What a 5 means | Anchor |
|---|---|---|---|
| Declarative readability | 20 | UI, config and test-spec code reads like the structure it describes; no bracket staircases; conditionals and loops fit naturally | G11, G4 |
| Transparency | 20 | A reader can tell what runs and when: no hidden receivers, no hidden state machines, no compiler-rewritten bodies | R6 |
| Simplicity | 15 | Few new rules; the DSL is ordinary code, not a second language | G1 |
| Generality | 15 | One mechanism serves UI, build files, HTML and test specs | G11, G7, G10 |
| Error messages | 10 | Mistakes in DSL code are reported in user terms at the user's line | G1 |
| Fit with earlier ADRs | 10 | Owned values, handles for state, no user generics, the crew and main-loop model | ADR-0001–0006 |
| Implementation risk (5 = low) | 10 | Small parser and compiler change; little or no runtime support | project constraint |

Total = Σ weight × score ÷ 5, computed by script. A gap under 5 is a tie, broken by the examples, then by reversibility.
