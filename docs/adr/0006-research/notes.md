# ADR-0006 research notes (core syntax)

URLs from memory of primary sources; not re-fetched this session.

| Language | Statement ending | Lesson |
|---|---|---|
| Go | Lexer inserts `;` after a line ending in an identifier, literal, `)`, `]`, `}`, `return`, etc. https://go.dev/ref/spec#Semicolons | Simple rule, few surprises; forces `{` on the same line and operators at line ends. |
| JavaScript | Automatic semicolon insertion (ASI) with exceptions | Well-known traps (`return\nvalue`, lines starting with `(` or `[`). https://262.ecma-international.org/#sec-automatic-semicolon-insertion |
| Kotlin / Swift | Newline ends a statement unless the expression cannot end there; semicolons optional | Works well; line-leading `.` continues chains. https://kotlinlang.org/spec/syntax-and-grammar.html |
| Python | Newline ends; indentation makes blocks (banned by G5) | |
| Lua | Semicolons optional, whitespace ignored | Ambiguity `f\n(g)` parses as a call. https://www.lua.org/manual/5.4/manual.html#3.3.1 |
| Ruby | Newline ends; trailing operator or `\` continues | |
| Rust | Semicolons required, last expression without `;` is the value | Expression-oriented blocks are pleasant; the required `;` violates G5. |
| Zig / C | Semicolons required | G5. |

Block forms: braces everywhere (Go, Rust, Swift, Kotlin) vs `end` (Lua, Ruby). Naming: Go over-shortens (`fmt`, `Sprintf`, `len`), which P-GO calls out; Swift favours full words (`removeAll(where:)`). Trailing closures from Swift/Kotlin make DSLs read declaratively (G11).
