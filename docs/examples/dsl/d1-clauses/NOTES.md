# D1 clause items (`if c => x`, `for p in xs [if g] => e` as list items): notes
`sh run.sh` prints "d1 dsl corpus OK": todo, build, spec, edge parse; 9 bad files match; the P3n corpus (5 ASTs byte-identical to `../../syntax/p3n/expected`, all 58 p3n bad files still fail) is unchanged.
**Rebased on P3n (ADR-0006 amendment 1):** `parser.py` is `../../syntax/p3n/parser.py` plus D1's additions. Every call argument in the corpus is labelled (79 labels added, 4 puns; `edge.d1` already was). Library names used (declared nowhere, the checker cannot see them): `Column/Row(key, gap, kids)`, `Text(content, style)`, `Button(label, key, active, on_click)`, `Input(key, slot, placeholder, on_enter)`, `Checkbox(checked, on_toggle)`, `Group(name, setup, before, kids)`, `Case(name, body)`, `Link(label, url)`, `A(label, href)`, `Td(text, colspan, align)`, `Th/H1/Title(text)`, `Head/Body/Nav/Table/Tr/Html(kids)`, `expect(ok)`, `expect_eq(actual, expected)`, `ui.slot(name, initial)`, `.any(test)`, `.retain(keep)`, `b.glob(pattern)`; `Msg` variants `Add(title)`, `Toggle(id)`, `Delete(id)`, `SetFilter(filter)`.
**Parser diff vs p3n:** +39/-1 lines (same as the diff vs p3 was). `Parser.item()` and `clause_arrow()` are new; the list literal calls
`item()` instead of `expr()`; two clearer errors (`if … =>` / `for` outside a list). Lexer untouched.
**AST (local addition to ../../syntax/AST.md):** `(item-if COND EXPR)`; `(item-for PAT ITER [(guard EXPR)] EXPR)`.
Only produced inside `(list ...)`. A clause yields exactly one element.
**Metrics** (non-blank, non-comment lines; depth counts `( [ {` including the fn body; metrics.py):
| file | lines | max depth | closer-only lines | longest closer run |
|---|---|---|---|---|
| todo.d1 | 72 | 8 | 18 | 3 |  (1717 -> 1869 code chars)
| build.d1 | 23 | 5 | 5 | 2 |  (785 -> 801)
| spec.d1 | 45 | 10 | 13 | 3 |  (1396 -> 1761)
(todo `view()` alone: 22 lines, depth 8, 5 closer-only lines.)
**Misspelled named argument:** `Lib(nme: "core")` parses as `(named nme ...)`; the parser cannot know parameter names.
The M2 checker would print: `build.d1:12:7: Lib has no field 'nme'; did you mean 'name'?` (same as any P3 constructor).
**Misspelled `=>`:** `[if ok -> 2]` reports `expected '=>' in the 'if' clause (a list clause is 'if … => item'), found '->'`
at the `->`. A clause outside `[ ]` reports "only allowed as an item directly inside `[ ]`".
**Grammar conflict found:** the idea said "the first token decides"; true for `for`, false for `if`. A list item
starting `if` may be an if-expression (`if c { a } else { b }`) or a clause; the parser parses the condition, then
looks at `=>` vs `{` and rewinds for the if-expression case (condition parsed twice). `if x = opt` (iflet) is never a
clause. Not LL(1) but one token of lookahead after a complete expression; no ambiguity, no corpus line changed.
**Awkward:**
- No `else` clause: the OS conditional needs two clauses (`if windows => …`, `if not windows => …`).
- A clause makes one element; a conditional group of two nodes needs two clauses repeating the condition.
- Clauses work only in `[ ]`, so every container needs `kids: [ … ]` (depth + a `]),` closer line); positional
  children are not possible.
- `for … =>` with a long body wants the body on the next line; legal only because we are inside brackets
  (outside, a line ending in `=>` is the F10 error).
- Depth is the worst of the three: spec reaches 10.
**Effect of the labelling rules (amendment 1):** layout metrics are unchanged (same lines, depth, closers); code characters
+12.4% over the four files (4291 -> 4824; spec.d1 +26%, build.d1 +2%); code lines over 100 columns 3 -> 9.
- Better: `kids: [ … ]` was already labelled in P3, so containers read exactly as before; clause items need no label
  (`for l in LINKS => A(label: l.label, href: l.url)`, spec.d1:34), so D1 loses nothing against positional children.
  Labels also make the leaf call self-describing where a bare string was ambiguous: `Td(text: …, colspan: 3)` (spec.d1:39),
  `Case(name: …, body: …)` (spec.d1:5-7).
- Better: puns come out naturally: `Project(name: "acme", version: VERSION, defaults, targets: [` (build.d1:8),
  `Todo(id: m.next_id, title, done: false)` (todo.d1:67).
- Awkward: the test spec, the label-heavy one: `expect_eq(actual: s.len(), expected: 3)` and `some(value: 3)` (spec.d1:6-7,
  10-14, 21) push single lines past 100 columns; `Group(name: "with three items", before: fn(s) { s.push(item: 1); … }, kids: [`
  (spec.d1:9) is the longest line in the corpus.
- Awkward: single-argument leaves (`Th(text: h)`, `H1(text: heading)`, `Button(label: …)`) lose their "tag with content" look
  (spec.d1:36,38, todo.d1:47); this is where F2 (one-parameter calls unlabelled) would have helped.
- `Msg.Add(title: draft.get())` (todo.d1:46-47) and `Msg.SetFilter(filter: f)` (todo.d1:51) repeat the variant's field name
  right after its name; it reads as boilerplate.
