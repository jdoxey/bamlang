# D2 variadic last parameter + clauses as arguments: notes
**RULED OUT by ADR-0006 amendment 1 (named arguments).** Variadics are gone and positional items after named arguments are not allowed, so D2 cannot exist under the amended syntax. This directory is frozen on old P3 (its parser, corpus and numbers are the record); `run.sh` still passes against `../../syntax/p3`. Do not rebase it.
`sh run.sh` prints "d2 dsl corpus OK": todo, build, spec, edge parse; 9 bad files match; P3 corpus unchanged.
**Parser diff vs p3:** +75/-4 lines (1004 -> 1075); +36 over D1. Lexer: a `...` token. `param()`/`params()`: `name: T...`
(flag `variadic`; must be last, no default, needs a type). `args()` rewritten to collect items; `item_arg()` new.
**AST (local addition to ../../syntax/AST.md):** D1's `item-if`/`item-for` (now also directly in call args), plus
`(param NAME [mut|take] variadic TYPE)` and, as the LAST child of `call`/`mcall`, `(rest ITEM*)`. Rule: a positional
argument that follows a named one, and every clause, goes to `rest` in source order; earlier positionals and all named
stay as in P3. `f(1, x: 2)` is unchanged (strict extension); a named argument after any item is an error.
**Metrics** (as in D1):
| file | lines | max depth | closer-only lines | longest closer run |
|---|---|---|---|---|
| todo.d2 | 75 | 6 | 19 | 3 |
| build.d2 | 23 | 4 | 5 | 2 |
| spec.d2 | 48 | 7 | 14 | 3 |
(todo `view()` alone: 22 lines, depth 6, 5 closer-only lines; todo.d2 includes a 3-line `column` declaration.)
**Misspelled named argument:** `column(gpa: 4, text("x"))` parses as `(named gpa ...)` then `(rest ...)`. The checker would
print `error: column has no parameter 'gpa'; did you mean 'gap'? (its variadic 'kids' takes positional items only)`.
Worse case: `row(gap: 4, gpa: 2)` where the variadic is last: same message, never silently treated as an item.
**Misspelled `=>`:** as D1 (`expected '=>' in the 'if' clause`). A named argument after items:
"named argument `gap:` after positional items: named arguments must come first, then the items".
**Grammar conflict found:** same `if` lookahead as D1 (clause vs if-expression), now also in argument position, plus
`f(if: 1)` (a keyword before `:` is a name; handled by `name_colon()` first). No new ambiguity from `...`: `T...` only
follows a parameter type, and `x...` at a call is "expected ',' or ')'" (no spread).
**Awkward:**
- The reader cannot tell a named argument from a trailing item by position alone once clauses are mixed in.
- Argument order is a rule to learn (named, then items); `rest` after `named` in the AST differs from source order for
  `f(a, x: 1)` vs `f(x: 1, a)` only in that the latter lands in `rest`.
- Every container needs a variadic fn; nodes with their own struct constructor (`Column(...)`) cannot take items, so a
  library must expose fns (`column`) beside types. Calls with many named args before the items push the items right.
- Trailing `),` lines remain (5 closer-only lines in view()), but nesting depth drops by 2 vs D1.
- No else-clause either (two clauses for the OS conditional).
