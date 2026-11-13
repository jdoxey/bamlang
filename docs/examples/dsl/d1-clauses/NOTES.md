# D1 clause items (`if c => x`, `for p in xs [if g] => e` as list items): notes
`sh run.sh` prints "d1 dsl corpus OK": todo, build, spec, edge parse; 9 bad files match; P3 corpus (5 ASTs, all bad) unchanged.
**Parser diff vs p3:** +39/-1 lines (1004 -> 1042). `Parser.item()` and `clause_arrow()` are new; the list literal calls
`item()` instead of `expr()`; two clearer errors (`if … =>` / `for` outside a list). Lexer untouched.
**AST (local addition to ../../syntax/AST.md):** `(item-if COND EXPR)`; `(item-for PAT ITER [(guard EXPR)] EXPR)`.
Only produced inside `(list ...)`. A clause yields exactly one element.
**Metrics** (non-blank, non-comment lines; depth counts `( [ {` including the fn body; metrics.py):
| file | lines | max depth | closer-only lines | longest closer run |
|---|---|---|---|---|
| todo.d1 | 72 | 8 | 18 | 3 |
| build.d1 | 23 | 5 | 5 | 2 |
| spec.d1 | 45 | 10 | 13 | 3 |
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
