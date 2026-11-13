# D7 benchmark comparison (numbers from each option's NOTES.md; `sh run.sh` in each directory reproduces them)

Rebased on P3n (ADR-0006 amendment 1: every call argument labelled). D2 is **ruled out** by the amendment (variadics gone,
positional items after named arguments not allowed); its column is the old-P3 record, not comparable with the others.

Metrics: non-blank, non-comment lines; max depth of `( [ {` (includes the fn body, a constant +2); lines holding only
closing brackets and commas; longest run of adjacent closers on a line; code characters (comments and indentation dropped).
Whole files, same program content. Layout numbers are unchanged by relabelling (labels add characters, not lines).

| | D1 clauses | D2 variadic (ruled out, old P3) | D3 pipelines |
|---|---|---|---|
| parser diff vs its base (added/removed lines) | +39/-1 (vs p3n) | +75/-4 (vs p3) | 0 (identical to p3n) |
| new AST nodes | item-if, item-for | + rest, variadic flag | none |
| todo: lines / depth / closer-only / run | 72 / 8 / 18 / 3 | 75 / 6 / 19 / 3 | 92 / 6 / 17 / 5 |
| build: lines / depth / closer-only / run | 23 / 5 / 5 / 2 | 23 / 4 / 5 / 2 | 22 / 4 / 1 / 3 |
| spec: lines / depth / closer-only / run | 45 / 10 / 13 / 3 | 48 / 7 / 14 / 3 | 37 / 7 / 3 / 5 |
| todo view() only: lines / depth / closer-only / run | 22 / 8 / 5 / 3 | 22 / 6 / 5 / 3 | 26 / 6 / 1 / 5 |
| labels added by the relabelling (puns among them) | n/a (ruled out) | n/a | D1 79 (4), D3 191 (5) |
| characters before -> after relabelling (todo+build+spec+edge) | 4291 -> 4824 (+12.4%) | 4691 (unchanged, old P3) | 4436 -> 5679 (+28.0%) |
| ... todo / build / spec | 1717 -> 1869 / 785 -> 801 / 1396 -> 1761 | n/a | 2185 -> 2615 / 767 -> 952 / 1484 -> 2112 |
| code lines over 100 columns, before -> after | 3 -> 9 | n/a | 2 -> 12 |
| bad-file tests | 9 | 9 | 6 |
| P3n corpus byte-identical, all p3n bad files fail | yes | n/a (old P3 only) | yes |
| typo'd name reported by | checker: no field | checker: no parameter | checker: no method |
| control flow | clauses, no else | clauses, no else | combinators, eager |
| forgotten structure parses silently? | no | no | yes (missing leading `.`; F9 catches) |

Reading the numbers: the layout is the same as before (the amendment adds characters, not lines or depth), so the earlier
reading stands: D3 has no grammar cost but the longest closer runs (5); D1 is deepest (10 in spec) but has the cheapest
relabelling. The labelling rules hit D3 hardest (+28% characters against +12%): every chain link is a one-argument call
(`.child(node: …)`, `.gap(size: 8)`, `.key(name: …)`) whose label is pure ceremony, and D3 has 2.4 times the labels. D1 keeps
`kids: [ … ]` as it was and clause items need no label. In D3 a typo'd label on a declared combinator is now a compile
error (`check_labels.py` checks `Node`'s 26 calls). The 5-column closer run and the 100-column overflow (2 -> 12 lines) make D3
the option the labelling rules cost most; if F2 (one-parameter calls unlabelled, the ready fallback) were adopted,
most of D3's added characters would disappear.
Findings: the "first token decides" claim for `if` in D1 is false (needs lookahead past the condition); `else` is
missing from every option.
