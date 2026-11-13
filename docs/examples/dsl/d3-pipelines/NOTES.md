# D3 builder pipelines (leading-dot chains + `take self` setters): notes
`sh run.sh` prints "d3 dsl corpus OK": todo, build, spec parse; 6 bad files match; the P3n corpus (5 ASTs byte-identical to `../../syntax/p3n/expected`, all 58 p3n bad files still fail) is unchanged.
**Parser diff vs p3n:** none; `parser.py` is a byte-identical copy of `../../syntax/p3n/parser.py` (`diff -q` clean). It was identical to p3's before the amendment, and the amendment changed nothing D3 needed. Nothing is needed: a leading
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
**Rebased on P3n (ADR-0006 amendment 1):** every argument in the corpus is labelled (191 labels added, 5 puns). Names chosen:
setters name what they take: `.gap(size:)`, `.key(name:)`, `.style(kind:)`, `.active(state:)`, `.checked(state:)`, `.slot(slot:)`,
`.placeholder(text:)`, `.on_click(msg:)`, `.on_enter(msg:)`, `.on_toggle(msg:)`, `.colspan(count:)`, `.align(side:)`, `.href(url:)`,
`.platform(name:)`, `.archive(kind:)`, `.srcs(files:)`, `.dep(name:)`, `.version(text:)`, `.define(flag:)`, `.link_if(cond:, lib:)`,
`.define_if(cond:, flag:)`, `.setup(run:)`, `.before(run:)`; structural combinators use fixed names: `.child(node:)`,
`.child_if(cond:, node:)`, `.add(kid:)`, `.children_of(items:, build:)` with `build: fn(item: T) -> Node` (a function type
names its parameter), `.add_each(items:, build:)`, `.targets_of(items:, build:)`, `.target(node:)`. Constructors:
`Text(content:)`, `Button(label:)`, `Group(name:)`, `Case(name:, body:)`, `Lib/Exe/Project(name:)`, `Link(label:, url:)`,
`A(label:)`, `Td/Th/H1/Title(text:)`; built-ins as in `../../syntax/p3n/NAMES.md`. `Msg` variants name their field (`Add(title: Str)`).
In `Node.children_of` the loop variable is `item` so the call through the function value is the pun `build(item)` (todo.d3:54).
**Effect of the labelling rules:** layout metrics unchanged (same lines, depth, closers); code characters +28.0% over the three
files (4436 -> 5679; build.d3 +24%, spec.d3 +42%), the largest increase of the options; code lines over 100 columns 2 -> 12.
- Worse: the chain gets noisier. Every link is `.child(node: …)`/`.add(kid: …)`, a label that repeats the method name's
  meaning (todo.d3:71-83, spec.d3:6-12). The clean `Column().child(Text("x"))` shape of the pre-amendment corpus is
  gone; `.add(kid: Case(name: "pop gives none", body: fn(s) => expect_eq(actual: s.pop(), expected: none)))` (spec.d3:7)
  carries three labels on a line.
- Worse: every setter takes exactly one argument, so the label is pure ceremony: `.gap(size: 8)`, `.key(name: "draft")`,
  `.style(kind: Style.Dim)` (todo.d3:63-79). This is the case F2 (one-parameter calls unlabelled) targets.
- Worse: building the tree from lambdas needs `build: fn(t) => Row()` (todo.d3:77), which is longer than before.
- Better: labels make terse setters self-describing where positional values were opaque: `.link_if(cond: windows, lib:
  "ws2_32")` (build.d3:12-13), `.child_if(cond: …, node: …)` (todo.d3:76), `.colspan(count: 3)` (spec.d3:32).
- Better: puns appear for free in the method-heavy build file: `.defaults(defaults)` (build.d3:16) stays as short as before.
- The static-checking claim improves: `Node` is declared in the file, so `check_labels.py` checks its setters and combinators
  (todo.d3: 26 calls checked); a wrong label name on `.child(…)` is now a compile error, not a runtime one.
