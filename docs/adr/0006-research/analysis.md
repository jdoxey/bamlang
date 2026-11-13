# D6 analysis (Opus coordinator)

There are 14 ideas: the research's six families, S1–S4 and C1–C4.

## Ruled out

| Idea | Why |
|---|---|
| JavaScript-style ASI (research) | Meaning depends on the next line |
| Swift whitespace operators | `a -b` and `a - b` differ |
| Scala 3 optional braces | Two syntaxes split a community |
| S4 spoken braces | Fails G4 brevity. Its `else` lookahead is kept as an option to test in S1. |
| C1 | DSL pollution |
| C2 | Doubles the keywords; its kernel (`end` naming the opener) is noted for S2 |
| C3 | Inverts `=` |
| C4 | Readers see trees; its kernel (one canonical layout) is considered for all |

## Kernels adopted into every finalist

- **Construction is a call** with named arguments and defaults: `Circle(r: 1.0)`, `Button(label: "OK")`. Braces are
  never literals (from S3; this also meets ADR-0005's DSL-literal decision).
- **Brackets suppress statement ends.**
- **No shadowing** of a visible name (C3's kernel).
- **Mandated formatter.**

## The three finalists, each with a real parser that parses the whole corpus

| | P1 = S1 | P2 = S2 | P3 = S3 |
|---|---|---|---|
| Blocks | `{ }`, same line | `do … end` | `{ }`, same line |
| Continuation | trailing operator, comma or opener; leading `.`, `and`, `or` | same as P1 | open brackets; leading `.` only |

**Corpus:** chatsim, widgets, errors and types, translated from the existing pseudo-syntax files, plus `tricky.*` for
the ten hardest snippets. Each parser prints the same S-expression AST (spec in `docs/examples/syntax/AST.md`), so
the corpora are provably equivalent. Parsers are written in Python 3 (std only) so they run on all three CI runners.
