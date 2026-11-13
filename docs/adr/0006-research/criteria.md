# ADR-0006 criteria (written before the options)

The question: core syntax. That covers statement endings (no mandatory semicolons, G5), blocks (no significant
indentation, G5), declarations, naming, and the spelling of every construct earlier ADRs introduced.

## Gates

- **G5:** no indentation-dependent meaning; no semicolon at the end of every statement.
- **G3:** no macro or annotation syntax.
- **Every construct from ADRs 0001–0005 has a spelling,** and the whole corpus parses with one grammar.

## Scored criteria

| Criterion | Weight | What a 5 means | Anchor |
|---|---|---|---|
| Unambiguity | 20 | Where a statement ends is never surprising; no ASI-style hazards (`return` then a newline, a line starting with `(` or `-`); the parser is LL(1)-like with no backtracking | R6, G5 |
| Readability | 20 | A newcomer reads the corpus correctly; keywords are words, not symbols; no over-shortening (P-GO) | G1, G4, P-GO |
| Brevity | 15 | Few tokens per construct; no ceremony | G4 |
| Consistency | 15 | One way to write each thing; declarations, blocks and calls share patterns | G1 |
| Error recovery and messages | 10 | A missing brace or `end` is reported near its cause; formatters are easy to write | G8 |
| Implementation risk (5 = low) | 10 | A hand-written recursive-descent parser fits in a few hundred lines | project constraint |
| DSL friendliness | 10 | Trailing closures and named arguments read as declarative layout (preparing for D7) | G11 |

Total = Σ weight × score ÷ 5, computed by script. A gap under 5 is a tie, broken by the examples (the corpus and
the parsers), then by reversibility.
