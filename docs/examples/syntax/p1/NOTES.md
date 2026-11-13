# P1 (S1: Go lines, Kotlin joins) notes
**Size.** `parser.py`: 872 lines of Python 3, std only (lexer ~210, AST printer ~20, parser ~575). The statement-end
rule is `Lexer.newline` (8 lines) plus `continues` (15 lines); the parser only sees `nl` tokens. No backtracking;
lookahead is 1-2 tokens (`if x =`, `name :`, `fn name`). Corpus: chatsim 306, widgets 321, errors 179, types 236,
tricky 111 lines (1153 total); 10 bad files of 4-9 lines; expected ASTs 4847 lines. `sh run.sh` passes on Linux and
also checks a CRLF copy of chatsim and tricky. chatsim exceeds 250 lines because it keeps every object kind.
**The ten tricky snippets.**
1. `return` newline `x`: bare `(return)`, then the statement `(name x)`. Never an error.
2. A line starting with `(` or `[` is a new statement (`(name b)`, `(list ..)`), never a call or index.
3. A line starting `-c` is a new statement; `a -` newline `b` joins; `a -b` is binary (no spacing rule).
4. Leading `.` or `?.` continues across blank lines and comment-only lines (lexer lookahead skips both).
5. A trailing operator, `,` or opener continues; the lexer does not check the next line.
6. Leading `and`/`or` continues, including mixed `a > 0 / and b > 0 / or c > 0 {`.
7. Trailing closures do not exist: lambdas open on the call line (`c.go(fn() {`); `{` on the next line is an
   error (bad/trailing_closure_next_line, bad/brace_next_line).
8. `else` on its own line is an error with a fix hint (bad/else_own_line); `} else {` and `} else if` work.
9. Multi-line argument lists, trailing commas, named args and `.dept`/`.salary desc` keys parse.
10. Multi-line declarations parse; `a < b > (c)` is `(bin > (bin < a b) c)` (no generics, no ambiguity;
    comparison chains are left-associative and rejecting them is a later check).
Extras: CRLF and lone CR are line ends (lexer); `;;` is fine; a leading `or` lets `try f()` newline `or e {` join.
**Rules that were ambiguous to implement (my decisions).**
- Ender set: the spec list plus `self`, `fails`, `desc` (else `fn f() -> T fails` newline joins the next line).
- Only `(` and `[` suppress ends; a `{` inside them (lambda body) turns ends back on. So inside `( )` a line
  starting with `(` or `[` DOES join the previous expression as a call or index. The one residual hazard of P1.
- `try` parses its operand without `or`, so `try f() or e { }` is the handler; a boolean `or` needs parentheses.
- `to` joins only after the heads `Map` and `SortedMap` (else `Map of List of Int to Str` binds wrongly). That puts
  two stdlib names in the parser; a grammar-only rule needs a decision.
- Reserved words cost names: `to of in is as use type with lock drop take desc context crew` (corpus renamed `to`
  to `dest`, `lock` to `held`).
- Patterns: uppercase initial, a dot, or a following `(` means variant; a lowercase name is a binding.
- `fn` at statement start is a declaration iff an identifier follows, else a lambda. `fail` is statement-only
  (`fail kind, msg` or `fail msg`). `try` is accepted wherever an operand is; ADR-0004's "outermost" is a later check.
- Chosen spellings: `name: Type`, `self`/`mut self`/`take self`, parameter modes as prefixes (`mut p: T`),
  `drop(mut self) { }` in the type body, `Pool of Widget()` in expressions, `T?` not used (`Optional of T`).
**Error messages.** Good and near the cause: else on its own line, `{` on the next line (points at the end of the
header line), `&&`/`||`/`!` (names the keyword), unclosed `{`/`(` (at the opener), mismatched closer (names the
opener's line), missing separator, unterminated string, errors inside `{expr}` (exact column).
Weak: a mistaken trailing operator is silently accepted when the next line is an expression; when it is `}` the
error reads "expected an expression, found '}'" and does not mention the operator above. A missing `)` swallows
lines until EOF and is reported at the opener only at end of file.
