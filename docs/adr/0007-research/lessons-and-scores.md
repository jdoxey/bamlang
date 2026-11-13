# D7 step 3 lessons and pre-review scores (Opus)

Examples: `docs/examples/dsl/` (`compare.md` has the numbers). D1 and D3 are rebased on the amended syntax (`p3n`).

## What the code taught

- **D2 died on the amendment.** ADR-0006 amendment 1 (issue #4) forbids positional items after named arguments, and
  D2's whole mechanism was a variadic children list. Before the amendment it had the shallowest nesting (depth 1–3
  less than D1).
- **D1 reads as the structure.**
  - `kids: [ … ]` with `for t in shown => Row(…)` and `if shown.is_empty() => Text(…)` stays close to the tree.
  - Relabelling cost +12%, mostly on leaf nodes (`Text(content: …)`).
  - The deepest nesting is in spec, at depth 10.
  - The parser change is +39/-1 lines. No P3n program changes meaning.
- **D1 `if` needs more than one token of lookahead.** A list item that starts with `if` could be a clause or an
  if-expression. The parser reads the condition, then decides on `=>` versus `{`. There is no ambiguity, but the claim
  "the first token decides" was false.
- **There is no `else` clause.** The OS conditional needs `if windows => …` and `if not windows => …`.
- **D3 costs most under labels.**
  - Size: +28%, with every link spelled `.child(node: …)` and one-argument setters like `.gap(size: 8)`.
  - Closers: the longest closing runs, 5.
  - Silent error: a chain line that forgets its leading `.` parses silently as a new statement, and only M2's
    unused-value check catches it.
  - Combinators: each library has to write its own (a 17-line `Node` setter set).
- **Typos are reported by the checker in every option**: as no field (D1), or as no method (D3).

## Scores (`scores.py`)

| Option | Read | Transp | Simple | General | Errors | Fit | Impl | Total |
|---|---|---|---|---|---|---|---|---|
| **D1 clauses** | 4 | 5 | 4 | 4 | 4 | 5 | 4 | **86** |
| D3 pipelines | 2 | 4 | 4 | 3 | 2 | 4 | 5 | 67 |
| D2 variadic | ineligible (amendment 1) | | | | | | | |

The gap is 19, and with readability weighted 10 and implementation risk 20 it is still 17. The reviewer attacks D1.
