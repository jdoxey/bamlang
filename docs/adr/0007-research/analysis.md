# D7 analysis (Opus coordinator)

**Q15 is closed:** G11 is syntax for nested declarative data. UI, build and test frameworks are libraries; v1 ships a
small UI library only as a stress test (D10 decides its scope).

There are 14 ideas: the research's C1–C6, S1–S4 and X1–X4.

## Ruled out

| Idea | Why |
|---|---|
| Receiver lambdas (C5) | Implicit scope (R6); Kotlin needed an annotation to restrain it |
| Trailing blocks (C3) | The Swift header collision; braces are blocks only (ADR-0006) |
| Explicit builder parameter (C4) | Noisy; the tree shape disappears |
| S3 spread | Hides fields' origins; may return later as a separate convenience |
| X1, X2, X3 | Fatal flaws; their kernels are kept below |

## Kernels adopted into every finalist

- Events are `Msg` values; `update(mut m, msg)` is the only writer; state lives in handle slots (`ui.slot`).
- An explicit `key:` for list children.
- `lang tree` (G8).
- A formatter hint to name subtrees deeper than about 4.
- `take self` setter chains are allowed for attributes of one node.

The S2 pure-view check is treated as a separate, cheap add-on, to be weighed by the reviewer.

## The three finalists, each a real extension of the P3 parser

| | D1 = S1 clause items | D2 = S4 variadic + clauses | D3 = X4 pipelines |
|---|---|---|---|
| Grammar change | `if c => x` and `for p in xs [if g] => e` as list items | a variadic last parameter (positional items after named arguments) plus the same clauses as arguments | none |
| Children | `name: [ … ]` | positional, after the named arguments | `.child(…)` / `.children_of(…)` |

**Benchmarks** (each written in every option): `todo.*` (UI), `build.*` (build file) and `spec.*` (a test suite plus
an HTML page).
