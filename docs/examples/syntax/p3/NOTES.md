# P3 (S3: brackets continue, nothing else) notes, loop 2 (review fixes F1-F12)
Rule kept: a newline is dropped inside `( )`/`[ ]` or when the next line starts with `.`/`?.`; otherwise it ends the
statement. `sh run.sh` prints "p3 syntax corpus OK" (5 ASTs, CRLF variants, 33 bad files). p1/run.sh, p2/run.sh pass.
`parser.py` is 1004 lines (was 896). P3 now has its own `expected/` (copied from ../expected); only types.ast and
tricky.ast differ from the shared files.
**What changed**
- F1: in `( )`/`[ ]` a line starting `(`, `[` or `-` after a complete item is an error ("add `,`").
- F2: handler is `try f() else e { }`. Operand is one postfix chain; `try g() == 3` is `(try g()) == 3`. The
  try-or-next-line special case is gone (a next-line `else` is the generic else error). Same AST node `try-or`.
- F3: word after `.`/`?.` is a member (lexer makes it an id); any word before `:` is a name in args, params, fields,
  variant fields. Contextual (plain ids, parser gives meaning by position): desc asc to of context crew lock with
  drop take is dyn fails module use as. Truly reserved (28): pub const type enum iface impl for fn let var if else
  while in match return fail break continue try or and not mut self true false none.
- F4: trailing `,` before a newline in `{ }` is accepted (lexer emits the newline); in a block it stays an error.
- F5: type/enum/iface/variant names must be capitalised (error at the declaration); lowercase patterns bind.
- F6: comparisons are non-associative. F7: `to` only after Map, SortedMap, Lru (nested `Map of List of Int to B` ok).
- F8: a leading `.` continues only after `)`, `]`, a name, a literal or `self`. F9: later semantic check (noted).
- F10: a line ending in `: . ?. not -> => of to`, a binary op, `=`, `,` outside brackets is an error.
- F11: error path only. When a `{`/`(` is unclosed or mismatched, the innermost opener whose body dedents to or below
  its own indentation is named: "unclosed `{` from line N (the line after it dedents at line M)". Parsing never reads
  indentation.
- F12: `=>` with an assignment (arm or lambda) errors; missing `,` in list/args says so; `{` in a string says `\{`.
**Corpus edits.** `or e {` became `else e {` (chatsim, errors, widgets, tricky; AST unchanged). tricky `a < b > (c)`
became `(a < b) > (c)` (same AST). types.p3: `some(b) => self.balance = b` is now `=> { self.balance = b }`, so
p3/expected/types.ast has a `(block ...)` around that assign. tricky gained t11-t13 (tok.type, xs.take(3),
send(to: a), let lock = 1, fn f(context: Ctx), trailing commas, leading dots, Lru, `\{`); tricky.ast regenerated.
**New bad tests (line: message part).** paren_line_in_args 4 `(`; minus_line_in_list 5 `-`; bracket_line_in_list 4 `[`;
try_else_next_line 4 else; try_or_handler 3 old `or e {`; reserved_as_name 3; lowercase_type/iface 2,
lowercase_variant 3; chained_compare, chained_equal 3; to_after_list 2; dot_after_brace 5; ends_with_colon/dot/not 3,
ends_with_arrow 2, ends_with_fat_arrow 4, ends_with_of 3; unclosed_inner_brace 4; unclosed_paren_hint 3;
mismatched_same_line 2; arm_assign 4; lambda_assign 3; list_missing_comma 2; string_open_brace 3.
Updated: call_with_missing_comma (new text), mismatched_close (now the hint), try_or_next_line renamed.
