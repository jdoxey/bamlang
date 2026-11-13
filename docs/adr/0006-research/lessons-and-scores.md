# D6: what the three real parsers taught, and scores

All three parsers (Python 3, std only) turn their own corpus (chatsim, widgets, errors, types, tricky) into the
**byte-identical** ASTs in `docs/examples/syntax/expected/`, so the corpora say the same thing.

| | P1 braces, Go lines + Kotlin joins | P2 `do … end` | P3 braces, brackets-only continue |
|---|---|---|---|
| Parser lines | 872 | 925 (+99/−46) | 896 (+30/−6) |
| Corpus lines | 1153 | **1374 (+19%)** | 1153 (2 real lines needed parentheses) |
| Error tests | 10 | 21 | 18 |
| Trailing operator by mistake | **silently joins the next line**; or "expected an expression, found `}`" | as P1 | **an error at the operator's line**: "wrap the whole expression in ( )" |
| Missing closer | reported at the opener at end of file | reported at the **enclosing** opener (one word closes everything) | as P1 |
| Special cases | none | `else do` lexer case; an inline mode for blocks inside string interpolations | none |
| Continuation rules to learn | trailing operator, comma or opener; leading `.`, `and`, `or` | as P1 | open brackets; leading `.` |

## Lessons

- **P3's single continuation rule** removed P1's one silent hazard at almost no cost: 2 real lines in 1153 needed
  parentheses, and they read naturally (`while (a⏎ and b) {`).
- **`do … end` costs lines** (one-line blocks become three) and gives worse missing-closer errors. There is no
  evidence that it reads better.
- **One hazard is shared by all three:** inside `( )`, a line starting with `(` joins as a call. That is for the
  reviewer.

## Scores (`scores.py`)

| Option | Unamb 20 | Read 20 | Brevity 15 | Consist 15 | Errors 10 | Impl 10 | DSL 10 | Total |
|---|---|---|---|---|---|---|---|---|
| P3 | 5 | 4 | 5 | 5 | 5 | 5 | 4 | **94** |
| P1 | 4 | 4 | 5 | 4 | 4 | 5 | 4 | 85 |
| P2 | 4 | 4 | 3 | 3 | 3 | 4 | 3 | 70 |

P3 leads in every weight variant.
