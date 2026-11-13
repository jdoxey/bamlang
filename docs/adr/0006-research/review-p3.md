# Adversarial review of P3 (Opus reviewer, 2026-11-13; condensed) and decisions

The reviewer ran every snippet through `p3/parser.py`.
- **Corrected scores:** P3 85, P1 79, P2 66. A 6-point margin, which depends on P1's Unamb being 3.
- **Tie-break fact (verified):** P3 is a strict subset of P1 with the same meaning. All 5 corpus ASTs parse
  identically under P1, so relaxing P3 later breaks nothing. P3 is the reversible choice.

| # | Severity | Finding (actual parser output) | Decision |
|---|---|---|---|
| F1 | serious | A missing comma inside brackets silently joins lines: `[⏎1,⏎2⏎-3,⏎]` is a 2-element list; `max(a⏎(b))` is `a(b)` | **Adopt.** Inside brackets, a line may not start with `(`, `[` or `-` after a complete item ("add `,` or move it up"). |
| F2 | serious | `try … or e { }` overloads boolean `or`; the operand is too wide (`try g() == 3`) | **Adopt.** The handler is spelled `try f() else e { }`. The `try` operand is one postfix chain. |
| F3 | serious | 43 reserved words block ordinary names (`tok.type`, `xs.take(3)`, `send(to: a)`, `context:`) | **Adopt.** After `.`/`?.` any word is a member name; a word followed by `:` in argument, parameter or type bodies is a name. Contextual: `desc asc to of context crew lock with drop take is dyn fails module use as`. About 26 truly reserved words remain. |
| F4 | serious | A trailing `,` in `enum`/`match` bodies gives a wrong "wrap in ( )" error | **Adopt.** A trailing `,` before a newline in `{ }` item bodies is accepted, and the formatter drops it. |
| F5 | serious | Variant versus binding decided silently by capitalisation (`red =>` is a catch-all) | **Adopt.** Type and variant names must be capitalised, which is checked at the declaration. A lowercase pattern name always binds. |
| F11 | serious | A missing `}` is reported at the enclosing `fn`; a missing `)` at the next `}` | **Adopt.** On the error path only, indentation is a hint to name the likely opener. Meaning never depends on whitespace (G5 holds). |
| F6 | minor | `a < b < c` accepted | **Adopt.** Comparisons are non-associative: "chain with `and`". |
| F7 | minor | `to` heads hardcoded and incomplete (`Lru of K to V` fails) | **Adopt.** A complete grammar-known head table (`Map`, `SortedMap`, `Lru`), legitimate because ADR-0002 froze the set; error otherwise. |
| F8 | minor | A leading `.` continues after a block's `}` | **Adopt.** A `.` line continues only after `)`, `]`, a name, a literal or `self`. |
| F9 | minor | `return⏎a + b`, `let x = a⏎-b` give silent new statements | **Adopt** (semantic check, M2): statements after `return`/`break`/`continue`/`fail` in the same block are errors, and so are unused non-call values. |
| F10 | minor | A line ending in a token that can't end an expression (`:`, `.`, `not`, `->`, `=>`) joins silently | **Adopt.** It is an error, except after `{`, `(` and `[`. The rule stays one sentence. |
| F12 | minor | Weak messages: `=>` with a statement, a missing comma in a list, `{` in strings | **Adopt** the better messages. `\{` escapes a brace in strings. |

**Not adopted:** making the parser reject non-canonical layout (C4's kernel). The mandated formatter plus
`fmt --check` in CI is enough.

There are **12 rules**, listed in the ADR.
