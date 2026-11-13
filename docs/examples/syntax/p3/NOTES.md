# P3 (S3: brackets continue, nothing else) notes
**Parser diff vs P1.** `parser.py` 896 lines (P1 872): 30 lines added, 6 removed, all in `Lexer.newline`/`continues`
(+ a `BINOPS` tuple, +1 `dangling`). Parser proper untouched. Rule: a newline is dropped inside `( )`/`[ ]` (as P1) or
when the next line starts with `.`/`?.`; otherwise it ends the statement. Outside brackets, a last token that is a
binary op, `=`/`+=`.., `,`, `and`, `or` is an error; so is a next line starting with `and`/`or`. A `{` inside
brackets (lambda body) turns ends back on, as in P1. Grouping parens leave no node in either parser (AST.md), so
`expected/*.ast` is reproduced byte for byte; `sh run.sh` passes (5 ASTs, CRLF variants, 18 bad files).
**Corpus vs P1 lines.** chatsim 306/306, widgets 321/321, errors 179/179, types 236/236, tricky 110/111 (two snippets
merged to one line). Lines changed: chatsim 2, errors 2, tricky 14 (comments included), widgets 0, types 0.
**Places parens had to be added: 6 (4 in tricky, 1 in chatsim, 1 in errors); 2 of them in real programs.** Reads:
- `while (self.timers.len() > 0` / `and self.timers[0].due <= self.clock) {` (chatsim; condition-in-parens, `{` after `)`)
- `const BAD_TEXT = ("[server]\n" +` ... `"name\n")` (errors; a 5-line string concatenation)
- tricky: `let d = (a -`/`b)`, `let s = (a +`/`b *`/`2)`, `if (a > 0`/`and b > 0`/`or c > 0) {`, `return (a > 0 and`/`b > 0)`.
Everything else in the real programs (argument lists, list literals, `.method()` chains, params) already sat inside
brackets or used leading dots. Cost is low; the trailing `{` after `)` reads fine; a one-line `try ... or e {` is forced.
**Tricky snippets (same ten).** 1 `return` newline `x`: bare return then `x` (unchanged). 2 line starting `(`/`[`
is a new statement (unchanged). 3 `-c` new statement; `a -` newline `b` is now an ERROR outside parens, so the corpus
wraps it; `a -b` binary (unchanged). 4 leading `.`/`?.` across blank/comment lines (unchanged). 5 trailing op
continues only inside `( )`; trailing comma/opener only inside brackets. 6 leading and/or are whitespace inside parens,
an error outside. 7 braces on the header line (unchanged). 8 `try f(2)` newline `or _ {}` is now an error
(bad/try_or_next_line); the handler must share the line. 9, 10 unchanged (all bracketed).
Residual hazard kept from P1: inside `( )` a line starting `(`/`[` joins as a call/index (`(f` newline `(1))` is a call).
**Errors vs P1.** P1's weak case is fixed: `let x = 1 +` then `}` or then `b` both report at the operator, line of
the operator: "line ends with `+`: wrap the whole expression in ( ) (only brackets and a leading '.' continue a line)".
Leading `and`/`or` and trailing `,`/`and`/`=` give the same shape of message at the right line and column; the `or`
variant adds the `try ... or e {` hint. All other P1 messages are identical. New cost: a forgotten `)` is still found
only at EOF (as P1), but now a missed continuation never silently changes meaning.
