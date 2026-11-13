# D6 ideas (Sonnet inventor, two lenses; condensed; unscored)

**Shared by all eight:** about 41 baseline keywords (from ADR-0001 to ADR-0005, plus core words); `List of T`; a
mandated formatter; `;` only as a same-line separator.

## The reading-aloud lens (sane)

**S1 Go lines, Kotlin joins.**
- **Line ends:** the lexer ends a statement at a newline after an identifier, literal, closer, `return`, `break` or
  `continue`. Nothing ends inside an open `(` or `[`.
- **Continuation:** a line ending in an operator, comma or opener; or a next line starting with `.`, `?.`, `and` or
  `or`.
- **Blocks:** braces, with `{` on the header line and `} else {`.
- **About 41 keywords.**
- **Risk:** two continuation rules, and the `{` placement papercut.

**S2 `do … end`.**
- **Mechanism:** S1's line rule, with `header do … end`. One `end` closes an `if`/`else` chain.
- **About 43 keywords.**
- **Risk:** struct literals still use braces; `end end end` in deep DSLs; the corpus needs rewriting.

**S3 Brackets continue, nothing else.**
- **Continuation:** only inside open brackets, or a next line starting with `.`. A trailing operator outside brackets
  is an error ("wrap in ( )").
- **Construction is a call:** `Circle(r: 1.0)`. Braces are only ever blocks.
- **Risk:** parentheses on long conditions.

**S4 Spoken braces.**
- **Mechanism:** a Kotlin grammar newline rule; `}⏎else` is legal; full words (`function`, `variable`, `returns`,
  `descending`).
- **Risk:** G4 brevity; it reads like Java.

## The break-an-assumption lens (crazy)

**C1 Every line is a statement, plus a trailing `...`.**
- **Flaw:** the marker pollutes DSLs.
- **Kernel:** let the next line's first token decide continuation.

**C2 `endif` / `endfunction` closers.**
- **Flaw:** about 57 keywords.
- **Kernel:** a closer can name its opener (`end if`, `end settle`) for error location.

**C3 `x = 1` declares and `x := 2` reassigns.**
- **Flaw:** it inverts the most common operation.
- **Kernel:** forbid shadowing outright, and keep `let`/`var`.

**C4 Source is a canonical tree.**
- **Flaw:** readers see S-expressions.
- **Kernel:** the parser accepts only formatter-canonical layout, so the grammar and the formatter are one spec.
