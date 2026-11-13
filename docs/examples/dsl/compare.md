# D7 benchmark comparison (numbers from each option's NOTES.md; `sh run.sh` in each directory reproduces them)

Metrics: non-blank, non-comment lines; max depth of `( [ {` (includes the fn body, a constant +2); lines holding only
closing brackets and commas; longest run of adjacent closers on a line. Whole files, same program content.

| | D1 clauses | D2 variadic | D3 pipelines |
|---|---|---|---|
| parser diff vs p3 (added/removed lines) | +39/-1 | +75/-4 | 0 |
| new AST nodes | item-if, item-for | + rest, variadic flag | none |
| todo: lines / depth / closer-only / run | 72 / 8 / 18 / 3 | 75 / 6 / 19 / 3 | 92 / 6 / 17 / 5 |
| build: lines / depth / closer-only / run | 23 / 5 / 5 / 2 | 23 / 4 / 5 / 2 | 22 / 4 / 1 / 3 |
| spec: lines / depth / closer-only / run | 45 / 10 / 13 / 3 | 48 / 7 / 14 / 3 | 37 / 7 / 3 / 5 |
| todo view() only: lines / depth / closer-only / run | 22 / 8 / 5 / 3 | 22 / 6 / 5 / 3 | 26 / 6 / 1 / 5 |
| bad-file tests | 9 | 9 | 6 |
| P3 corpus byte-identical | yes | yes | yes |
| typo'd name reported by | checker: no field | checker: no parameter | checker: no method |
| control flow | clauses, no else | clauses, no else | combinators, eager |
| forgotten structure parses silently? | no | no | yes (missing leading `.`; F9 catches) |

Reading the numbers: D3 has no grammar cost but the longest closer runs (5) and, in todo, 20 more lines (17 are setter
definitions the others keep in the library). D1 is deepest (10 in spec). D2 cuts depth by 1-3 versus D1 for +36 parser
lines. D3 has the fewest closer-only lines; D1/D2 have 5 per view().
Findings: the "first token decides" claim for `if` in D1/D2 is false (needs lookahead past the condition); `else` is
missing from every option.
