# D3 builder pipelines (leading-dot chains + `take self` setters): notes
`sh run.sh` prints "d3 dsl corpus OK": todo, build, spec parse; 6 bad files match; P3 corpus unchanged.
**Parser diff vs p3:** none; `parser.py` is a byte-identical copy (`diff -q` clean). Verified nothing was needed: a leading
`.` already continues after `)`/`]`/a name, `fn(x) => …` bodies can be chains, and `take self` is already a receiver.
**AST:** unchanged; chains are `(mcall child (mcall gap (call (name Column)) …) …)`, so `lang tree` needs no new nodes.
**Metrics** (as in D1):
| file | lines | max depth | closer-only lines | longest closer run |
|---|---|---|---|---|
| todo.d3 | 92 | 6 | 17 | 5 |
| build.d3 | 22 | 4 | 1 | 3 |
| spec.d3 | 37 | 7 | 3 | 5 |
(todo `view()` alone: 26 lines, depth 6, 1 closer-only line, run 5; todo.d3 also holds a 17-line `Node` setter
library that D1/D2 do not need. spec.d3 is shortest because groups are one-line chains.)
**Misspelled named argument:** there are no named children arguments; a typo is a method: `.gpa(4)` parses as
`(mcall gpa …)`. The checker prints `error: Column has no method 'gpa'; did you mean 'gap'?` (the same quality as a field).
**Errors from the layout:** `)` piles are the failure mode. A missing `)` is reported at the right line (`unclosed '('
from line 4`) thanks to the indentation hint, an extra `)` as `mismatched ')'`. A trailing `.` is an error; a leading `.`
after `}` or `,` is an error. But a chain line that forgets its dot (`Column()⏎ child(x)`) PARSES as two statements; only
the planned unused-value check (F9, M2) catches it. `and`/`or` leading a line inside `( )` is fine.
**Grammar conflict found:** none (no grammar change).
**Awkward:**
- Control flow is not syntax: `child_if(cond, node)` and `children_of(xs, fn(x) => …)` evaluate eagerly and are library
  conventions; no `else`, no filtering guard (`for … if`) without a second combinator.
- The closing run `)))))` and `)))))` at the end of nested `.child(` calls (run 5), and lambdas inside chains need the
  `fn(t) => Row()⏎ .key(…)` layout to read well. I named subtrees (`tabs`, `nav`, `table`) to keep depth at 6-7.
- Wrapping a lambda that returns a chain makes the chain indent a second continuation level.
- Every setter is a method definition (17 lines in the todo benchmark); typos give method errors instead of field errors.
