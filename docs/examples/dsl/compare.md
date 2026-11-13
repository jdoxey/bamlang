# D7 benchmark comparison, loop 2 (`sh run.sh` in each directory reproduces its numbers; `python3 metrics.py --table` prints all)

Rebased on P3n (ADR-0006 amendment 1). Loop 2 applies review F1-F13 to D1 and adds the C1 baseline. The library is declared
(`lib/*.names`, checked by `check_labels.py`), `.copy()` is explicit, the test spec has 20 cases, the HTML page shows escaping.
**D3 is the record** (review F8: illegal under ADR-0002 rule 1 and ADR-0005 rule 7; not rebuilt, old corpus and numbers).
**D2 is ruled out** by amendment 1 (old P3 corpus). D3 and D2 numbers are not comparable with D1/C1: older programs, no library
declarations, no `.copy()`, a 9-case spec, no escaping.

Metrics: the three shared files only (todo, build, spec; edge files excluded). Lines: non-blank, non-comment. Bracket depth: max nesting of
`( [ {` (includes the fn body, +2). **Tree levels**: max nested constructor calls `Name(` (D3/D2 chains and variadics score 1).
Closer-only: lines of only closing brackets and commas. Run: longest run of adjacent closers. Chars: code characters.

| | D1 (fixed) | C1 baseline | D3 (record, old numbers) | D2 (ruled out, old P3) |
|---|---|---|---|---|
| parser diff vs its base | +62/-9 (vs p3n) | 0 (byte copy of p3n) | 0 | +75/-4 (vs p3) |
| new AST nodes | item-if, item-iflet, item-for | none | none | rest, variadic flag |
| todo: lines / bracket depth / tree / closer-only / run | 87 / 8 / 3 / 22 / 3 | 89 / 8 / 2 / 22 / 5 | 92 / 6 / 1 / 17 / 5 | 75 / 6 / 1 / 19 / 3 |
| build: lines / depth / tree / closer-only / run | 24 / 5 / 2 / 5 / 2 | 19 / 7 / 2 / 2 / 3 | 22 / 4 / 1 / 1 / 3 | 23 / 4 / 1 / 5 / 2 |
| spec: lines / depth / tree / closer-only / run | 93 / 11 / 5 / 22 / 4 | 90 / 11 / 4 / 19 / 4 | 37 / 7 / 1 / 3 / 5 | 48 / 7 / 1 / 14 / 3 |
| three files: lines / chars | 204 / 6536 | 198 / 6928 | 151 / 5679 | 146 / 4032 |
| todo `view()` only: lines / depth / tree / closer-only / run | 25 / 8 / 3 / 6 / 3 | 27 / 8 / 2 / 6 / 5 | 26 / 6 / 1 / 1 / 5 | 22 / 6 / 0 / 5 / 3 |
| spec cases / escaping demo / library declared | 20 / yes / yes | 20 / yes / yes | 9 / no / no | 9 / no / no |
| `.copy()` calls (todo + build + spec) | 11 | 11 | none (missing) | none (missing) |
| lines over 100 columns (todo / build / spec) | 4 / 3 / 13 | 4 / 3 / 16 | n/a | n/a |
| bad-file tests (parser) + label-check bad files | 13 + 2 | 2 + 2 | 6 | 9 |
| calls checked / skipped by check_labels | 142 / 26 (4 files) | 154 / 24 (3 files) | not run (undeclared lib) | n/a |
| P3n corpus byte-identical, all p3n bad files fail | yes | yes (same parser) | yes | n/a |
| control flow | clauses (`=>`), binding, nesting, no else | if-expressions, `map`, `+`, `push` | combinators, eager | clauses, no else |

Reading the numbers (honest):
- D1 and C1 are within 3% on lines (204 against 198) and C1 is 6% larger in characters (6928 against 6536). The review's estimate (5-11%)
  holds for `view()` (C1 27 lines against 25, 1295 against 1147 characters).
- C1 is not worse everywhere: `build` is 5 lines shorter in C1 (a one-or-other `links` is an if-expression, and `map` builds the
  packages), and no mixed-type problem arose because each library's constructors share one result type. D1 wins on `todo` (tree
  levels 3 against 2, closer run 3 against 5) and on the generated cases and nested nav in `spec`.
- D1's cost is the parser: +62/-9 lines against 0, three AST nodes, and the second reading of `=>`. Its benefit is that the tree stays
  one expression; C1's `todo` is built by statements, so the root `Column` is no longer visible as a tree.
- Bracket depth is not the readable measure: C1 build has depth 7 from `[ … ] + platforms` yet tree levels 2.
- D3 and D2 are included for the record only. D3's longest closer runs (5) and D2's removal remain true; neither is rebuilt.
