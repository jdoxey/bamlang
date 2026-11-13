# P2 (S2: P1 statement rules, blocks are `header do ... end`) notes
**Parser diff vs P1.** `parser.py` 925 lines vs 872: 99 lines added, 46 removed (about 145 changed, 16%). Lexer: `do`/`end`
are keywords and enders; `do` is pushed on the bracket stack and `end` pops it (so newlines inside `f(fn() do`
count again, as `{` did); `{ }` are now lexer errors; an `else` lets its following `do` skip the push (one `end` per
chain). Parser: `body` takes `do` + `end`; `if_expr` loops the chain; statement ends before `end`/`else` are required.
Balance errors (extra/missing/mismatched `end`, bracket) are deferred: the parser runs on the tokens before the
fault and reports its own error first if it fails earlier, otherwise the lexer's (needed so a missing `do` is
reported at the header, not at the later stray `end`). `sh run.sh` passes; all five ASTs are byte-identical
(`cmp`), CRLF variants too, 21 bad files check their error line and text.
**Corpus.** chatsim 346 (P1 306), widgets 398 (321), errors 204 (179), types 314 (236), tricky 112 (111); total 1374 vs
1153 (+19%). Growth is all one-line blocks (`if c { return }`, `type T { a: Int, b: Int }`, `match` arms) that must
now take 3 lines. Translated mechanically (script), then checked by AST equality.
**Cost found only by translating.** A block inside a string interpolation (`"{if p() { "y" } else { "n" }}"`,
`fn(c) { c.close() }`) cannot satisfy "`do` ends the line" (interpolations are single-line). To keep the ASTs equal
the parser has an `inline` mode for interpolations only: `{if p() do "y" else do "n" end}`. Without it these two
corpus lines need a hoisted `let` (a different AST). A grammar decision is needed: allow or ban.
**Tricky snippets (same behaviour as P1 for 1-6, 9, 10).** 1 bare `return` then `x`; 2 `(`/`[` line starts a statement;
3 `-c` new statement, `a -`/`b` joins; 4 leading `.`/`?.` continues over blanks/comments; 5 trailing operator, comma,
opener continue; 6 leading `and`/`or` continue; 9 multi-line args, trailing commas; 10 `a < b > (c)` two comparisons.
7 (changed): lambdas are `c.go(fn() do` ... `end)`; `do` on the next line is "unexpected `do`" (bad/trailing_closure_next_line);
`else`/`else if` stand alone in one chain with one `end`; `else` after a `for ... end` or after `end` of its if is
an error (bad/else_after_for, end_before_else) and a second `else` is too (else_if_after_else). 8: `try f(1) or e do` ...
`end` and the leading-`or` join work; a handler after a block operand reads `end or e do` (one line).
**Errors for missing/extra `end` vs P1 braces (where reported).**
- Missing `do`: at the header line end ("expected `do` to open the if body", 3:11): as good as P1's `{` message.
- `do` on next line / body after `do` on the same line: same quality, at the header end / the first body token.
- Missing `end`: always "unclosed `do` (missing `end`)" at the OPENER, at end of file. Same as P1's unclosed `{`, but
  worse in practice: `end` is a word, every block closes with the same word, nothing says which block lacks it
  (a missing end of an inner `if` is reported at the enclosing `fn`, bad/end_missing_in_chain: line 2, fault at line 8).
  With a following `fn` the nested decl is parsed happily (bad/missing_end_then_fn). A column-1 heuristic could fix it.
- Extra `end`: reported at the extra token, but it is the LAST `end` that is flagged, not the misplaced one, as with `}`.
- `end` inside open `(`: "mismatched `end`: the '(' opened at line 3" (like P1's mismatched `}`).
**Awkward.** Closer runs: max 4 `end` lines in a row (chatsim, P1 max 3 `}`), 3 in widgets/errors/types, 2 in tricky.
Every closer is the identical word (92 `end` lines in widgets, no `})`-style visual variety; lambda closers are
`end)`). Interpolation limit above. Reserved words cost two more names (`do`, `end`; no clashes in the corpus).
`else do` costs a lexer special case (the `else`'s `do` must not push), which P1 did not need.
