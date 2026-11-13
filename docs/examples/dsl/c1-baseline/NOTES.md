# C1 baseline: no new syntax (review F2). The same three benchmarks, p3n parser unchanged
`sh run.sh` prints "c1 dsl corpus OK": `parser.py` is a byte copy of `../../syntax/p3n/parser.py`; corpus parses; 2 bad files (the D1 clause
syntax is a parse error here); every call checked against `../lib/*.names` (same lib, same 20-case spec, same copies); the P3n corpus unchanged.
## Choice per site (most readable legal form), honestly
| site | form | why |
|---|---|---|
| todo rows (`for … if shown`) | `var rows: List of Node of Msg = []` + `for` + `if` + `rows.push(item: …)` | a guard plus a multi-line body; `filter(…).map(…)` needs `filter` to copy borrowed Todos and puts the key inside a lambda |
| todo column | `var kids: List of Node of Msg = [Text(…)]` then `kids.push(item: …)` in order | seven conditional or computed children; the `+` form needs `(if c { [x] } else { [] })` around each |
| todo filter tabs | `[Filter.All, …].map(each: fn(f) => Button(…))` | a pure per-element mapping: `map` is as short as the clause |
| build `defines`, `links` | `[…] + (if windows { […] } else { [] })` and `if windows { ["ws2_32"] } else { ["pthread"] }` | one conditional per list; the second is a plain if-expression (one-or-other is better here than in D1, which needs two clauses) |
| build packages | `PLATFORMS.map(each: fn(p) => Package(…))` bound with `let`, then `[Lib, Exe, Exe] + platforms` | a map; the let keeps `targets:` short |
| spec cases | `kids: [1, 10, 1000].map(each: fn(n) => Case(…))` | a group made only of the generated cases |
| spec page | `var links` with two nested `for` loops; `let header/none_row/body_rows` then `Table(kids: [Tr(kids: header)] + none_row + body_rows)` | nested flattening has no `map` form (no `flat_map` in the library); sub-lists need names |
**Where annotations are needed:**
- Every `var kids …` and every subtree `let`: a list literal alone names no element type.
- `else { [] }` types only if the checker unifies the two operands of `+` (or the branches of the `if`) and pushes the expected type into `[]`.
  It is not annotation-free by itself; the corpus relies on that rule and spec.c1's `none_row` is annotated.
- No mixed-type problem arose, because every UI constructor returns `Node of Msg`, every build target `Target`, every HTML tag `Elem`.
  The review's "mixed children don't type in the `+`/`map` form" holds only for libraries whose constructors return different types.
**Costs seen:** `todo.c1` loses the tree look (the root `Column` is built by pushes; tree levels 2 against D1's 3); `+` chains produce a closer run of 5
(`todo.c1`); an else-less conditional item needs the two-branch form. **Gains:** zero parser change, one-or-other conditionals are natural,
`build.c1` is the shortest file (19 lines against 24), and `map` reads as well as a clause for pure mappings.
## Metrics (`../metrics.py --table`)
| file | lines | bracket depth | tree levels | closer-only lines | longest closer run | chars |
|---|---|---|---|---|---|---|
| todo.c1 | 89 | 8 | 2 | 22 | 5 | 2290 |
| build.c1 | 19 | 7 | 2 | 2 | 3 | 892 |
| spec.c1 | 90 | 11 | 4 | 19 | 4 | 3746 |
`view()` alone: 27 lines, depth 8, tree 2, 6 closer-only lines. Lines over 100 columns: todo 4, build 3, spec 16.
