# D1 clause items (`if c => x`, `if v = opt => x`, `for p in xs [if g] => e` as list items): notes (loop 2, after review F1-F9)
`sh run.sh` prints "d1 dsl corpus OK": todo, build, spec, edge parse; the bad files match; every corpus call is checked against `../lib/*.names`
plus the file's own declarations (`../check_labels.py`: calls checked / skipped); `timing.py` (depth-18 nesting, fails above 2 s); the P3n corpus
(5 ASTs byte-identical to `../../syntax/p3n/expected`, all 58 p3n bad files still fail) is unchanged.
**Parser diff vs p3n:** +62/-9 lines (loop 1 was +39/-1; the growth is the no-rewind `if` split, a `pending` primary, and four targeted errors).
Lexer untouched. New: `Parser.item()`, `clause_body()`, `clause_arrow()`, `if_head()`/`if_tail()` (the old `if_expr` split in two so `item()` can
share them), and `s.pending` (an if-expression already parsed by `item()` that `primary()` returns, so operators or `.abs()` can follow it).
**AST (local addition to ../../syntax/AST.md), only inside `(list ...)`:**
- `(item-if COND ITEM)`
- `(item-iflet NAME EXPR ITEM)` for `if x = opt => ITEM`
- `(item-for PAT ITER [(guard EXPR)] ITEM)`
- A clause body `ITEM` is any item: an expression or another clause. A clause yields zero or more elements (it is no longer "exactly one").
**Grammar:** `item := name ':' expr | 'for' pat 'in' expr ['if' expr] '=>' item | 'if' [name '='] expr '=>' item | expr`. After the `if` condition one
token decides: `=>` makes a clause, `{` an if-expression. The condition is parsed once (loop 1 rewound and parsed it twice per nesting level:
8.6 s at depth 18; now 0.001 s, five nesting shapes, in `timing.py`). The `for … if` guard is a plain boolean expression, not a binding; to bind
nest: `for p in xs => if v = p.opt => v` (guard-position binding was left out: it would need a second spelling for the same thing).
**Targeted errors** (bad files): `[1, if c { 2 }]` -> "an `if` without `else` is not a value in a list; write the clause `if <condition> => <item>`";
`[if a => 1 else 2]` (and the `for` form) -> "a list clause has no `else`; for one-or-other write an if-expression: `if c { a } else { b }`";
`[if ok -> 2]` -> "expected `=>` in the `if` clause…"; `[if v = o -> v]` likewise; a clause outside `[ ]` -> "only allowed as an item directly inside `[ ]`".
## Normative desugaring (review F3)
`[a, if c => b, for p in xs if g => e]` of expected element type `T` is exactly
```
var tmp: List of T = []; tmp.push(item: a); if c { tmp.push(item: b) }; for p in xs { if g { tmp.push(item: e) } }
```
- Left to right; each condition and iterable is evaluated once; a body is evaluated only when its clause includes it.
- Every `tmp.push(item: …)` is a store site typed from `T` (the parameter type of `kids:`, or the `let` annotation): a borrowed `Str` stored
  from there needs `.copy()`.
- `p` (and the `v` of `if v = opt =>`) is borrowed per iteration, so moving out of it needs `.copy()`; Int, Bool, enums copy implicitly.
- Nested clauses nest the statements: `[for r in rows => for c in r.cells => c]` pushes every `c` into the same `tmp` (flat);
  `[for r in rows => [for c in r.cells => c]]` is a list of lists. `[if a => for x in xs => x]` is `if a { for x in xs { tmp.push(item: x) } }`.
- A list holding clauses and a `let`: the `let` needs the annotation (`let rows: List of Node of Msg = [...]`); the elements of a bare literal
  are typed from context, so a literal with no context names no type.
## Library (review F1, F4)
`../lib/` declares `ui`, `build`, `html`, `test` in the stdlib generic dialect (ADR-0002 owner answer): `Node of Msg`, `Ui of Msg`, `Slot of Str`.
`use extras.ui` picks the file. The corpus stores every item from the expected element type; 3 files carry 11 `.copy()` calls, the same 11 in C1 (todo 3: `t.title`, `u.avatar`, `u.name`;
build 2: `VERSION`, `p`; spec 6: `heading` twice, link label and url, row name, header string).
## Corpus (review F9)
- `todo.d1`: a binding clause (`if u = m.user => Row(…Avatar(url: u.avatar.copy())…)`), a guard (`for t in m.items if shown(f: m.filter, t) =>`),
  an annotated subtree `let rows: List of Node of Msg`, `rows.is_empty()` tested before `rows` moves into `Column(kids: rows)`.
- `build.d1`: two clause kinds; all three targets are `Target`.
- `spec.d1`: 20 cases in nested groups (13 `Case` calls + two `for` clauses that expand to 3 and 4 cases), bodies are `fn() { … try expect_eq(…) }`
  (the lambda is `fn() fails` because its body has `try`; the lambda syntax has no `fails` marker, it is inferred from `Case.body`), shared setup
  is the plain `stack_of(count: n)`, the bodies capture only the copied `Int` loop variable. The nested clause is the nav
  (`for menu in MENUS => for l in menu.links => A(…)`).
- HTML escaping: `main()` renders a row named `<script>alert(1)</script>` under heading `Stock & Co`; `Td(text:)`/`H1(text:)` escape, only `Raw(html:)` does not:
  `<h1>Stock &amp; Co</h1>` … `<tr><td>&lt;script&gt;alert(1)&lt;/script&gt;</td><td align="right">2</td><td align="right">9.50</td></tr>`
- Expected runner output for one deliberately failing case: change the push-many body to `stack_of(count: n - 1).len()` and `run(suite:)` prints
  (the path is the group names joined by ` / `, then the case name, then the `expect_eq` error text; the runner exits non-zero)
```
FAIL Stack / push many / len after 1 pushes: expected 1, got 0
FAIL Stack / push many / len after 10 pushes: expected 10, got 9
FAIL Stack / push many / len after 1000 pushes: expected 1000, got 999
3 failed, 17 passed (20 cases)
```
## Metrics (`../metrics.py --table`; shared three files only)
| file | lines | bracket depth | tree levels | closer-only lines | longest closer run | chars |
|---|---|---|---|---|---|---|
| todo.d1 | 87 | 8 | 3 | 22 | 3 | 2142 |
| build.d1 | 24 | 5 | 2 | 5 | 2 | 847 |
| spec.d1 | 93 | 11 | 5 | 22 | 4 | 3547 |
`view()` alone: 25 lines, depth 8, tree 3, 6 closer-only lines. Lines over 100 columns: todo 4, build 3, spec 13.
## Findings (carried from loop 1, still true)
- Misspelled named argument parses; the checker now rejects it against the library: `Text(contents: …)` -> "Text has no parameter 'contents'" (`check_bad/`).
- Awkward: a clause makes one element per iteration, so a conditional group of two nodes needs two clauses repeating the condition; clauses work
  only in `[ ]`, so every container keeps `kids: [ … ]`; a `for … =>` clause with a long body wants the body on the next line (legal because
  we are inside brackets; outside, a line ending in `=>` is the F10 error). `=>` still has three meanings (lambda, match arm, clause; review F10).
- A forgotten `key:` in a `for` clause is not caught (review F12, a lint for D10).
- Single-field leaves (`Th(text: h.copy())`, `H1(text: …)`) pay amendment 1's labelling cost (review F14, evidence for its F2 fallback).
