# D6 research: statement endings and core syntax (Sonnet researcher, 2026-11-13; condensed)

**[unverified]** marks claims without a fetched source. The Swift book, the ECMAScript ASI text and the Stefik
paper body couldn't be fetched.

## Where statements end

- **Go:** the lexer inserts `;` after an identifier, a literal, `return`, `break`, `continue`, `fallthrough`, `++`,
  `--` or a closing bracket at the end of a line (https://go.dev/ref/spec#Semicolons). Consequences: `{` must go on
  the same line (the FAQ rejects lookahead: https://go.dev/doc/faq#semicolons), a continuation line needs a trailing
  operator, and gofmt is mandated. Simple and predictable.
- **JavaScript ASI** is an error-correction rule, which makes it the worst model. The hazards:
  - `return` then a newline returns `undefined` [unverified details];
  - a line starting with `(`, `[` or a backtick joins the previous line (https://2ality.com/2011/05/semicolon-insertion.html,
    https://feross.org/never-use-semicolons, https://eslint.org/docs/rules/no-unexpected-multiline).
- **Kotlin** handles newlines in its grammar (https://kotlinlang.org/spec/syntax-and-grammar.html):
  - **Allowed before:** `||`, `&&`, `?:`, `as`, and probably a leading `.` [unverified].
  - **Allowed only after:** `+ - * / %` and comparisons (`1⏎+ 2` is two statements).
  - **Never allowed before:** a call's `(` or an index's `[`.
  - **A trailing lambda** may start on the next line.

  This is the best precedent.
- **Swift:** a whitespace-sensitive operator rule, where `a -b` and `a - b` differ [unverified]. That is a novice
  hazard.
- **Scala 3:** optional braces plus semicolon inference. Its "most controversial feature" split the community
  (https://contributors.scala-lang.org/t/feedback-sought-optional-braces/4702). It has `end if` / `end match` markers
  (https://docs.scala-lang.org/scala3/reference/other-new-features/indentation.html). Lessons: offer one syntax, not
  two; labelled `end` markers help locate errors.
- **Lua** is free-form with no terminators. Its one ambiguity is a line starting with `(` (it becomes a call), so the
  manual advises a leading `;` (https://www.lua.org/manual/5.4/manual.html §3.3.1).
- **Ruby:** a newline ends an expression unless the line ends with an operator, `(` or `,`
  (https://docs.ruby-lang.org/en/master/syntax/miscellaneous_rdoc.html). Blocks close with `end`.
- **Julia:** `end` blocks; `try … catch x end` on one line has a quirk (https://docs.julialang.org/en/v1/manual/control-flow/).
- **Odin:** `x: int = 1`, `x := 1`, `x :: const`, and same-line braces (https://odin-lang.org/docs/overview/).

## Braces versus `end`

- **Evidence:** Stefik and Siebert (2013) found Java- and Perl-style syntax no better for novices than random symbols,
  while Python, Ruby and Quorum did better (https://neverworkintheory.org/2014/01/29/stefik-siebert-syntax.html).
- **Limits:** that isn't a controlled braces-versus-`end` study, and none was found.
- **Choose on parse robustness and error locality:** a labelled `end` locates errors better, and braces are more
  familiar.

## Declarations and keywords

- `name: Type` is the most widely recognised form; `Type name` is hard to grep.
- `fn`, `func`, `fun`, `def` and `function` are untested for novices. P-GO (over-shortening) argues against `fn`.
- `List<T>` collides with comparison, `[]T` is terse, and `List of T` reads as words.

## Six families

1. Kotlin-like: braces with grammar-level newline rules.
2. Go-like: token-based insertion, same-line braces.
3. Lua/Ruby-like: `end` blocks.
4. Scala-like labelled `end if`.
5. Braces plus Swift's whitespace operator rule.
6. Odin/Julia-like `name: T = v` with `::` and `:=`.

**Common to all:** an optional `;` separator, a mandated formatter, and rejecting a call or index whose `(` or `[`
starts a new line.

## The ten hardest corpus snippets

1. `return`, then a newline, then a value.
2. A line starting with `(` or `[`.
3. Unary minus at the start of a line.
4. Leading-dot chains, with blank lines or comments between the lines.
5. A trailing operator before a continuation line.
6. A leading `&&` or `||` in a multi-line condition.
7. A trailing closure on the next line, and `if cond` then `{` on the next line.
8. `else` on its own line.
9. Multi-line argument lists with trailing commas.
10. Multi-line declarations, and `a < b > (c)`.

Also: postfix operators at line start, empty statements, and CRLF line endings.
