# ADR-0006: Core syntax

- **Status:** Accepted
- **Date:** 2026-11-13; amendment 1 (named arguments, issue #4) 2026-11-14
- **Tier:** Full (see `docs/PROCESS.md`)
- **Examples:** `docs/examples/syntax` (amended P3 in `p3n/`; P3 in `p3/`; rivals in `p1/`, `p2/`; the shared AST format is in `AST.md`)
- **Decided by:** Claude (ruling R7). John may veto by opening an issue.

## Context

G5 forbids indentation-dependent meaning and mandatory semicolons. G4 asks for clean, non-verbose syntax, and P-GO
warns against over-shortening. ADRs 0001–0005 introduced constructs that all need spellings. This ADR fixes:
- where statements end;
- blocks;
- declarations;
- keywords;
- every spelling.

The winning corpus becomes the M0 conformance corpus. Research (`0006-research/research.md`) found:
- JavaScript's ASI (meaning depends on the next line) is the worst model;
- Go's token rule and Kotlin's grammar rule are good models;
- Scala's two syntaxes split its community;
- there is no evidence that braces or `end` read better.

## Charter

| Goal / problem | Effect | Why |
|---|---|---|
| G5 | serves | A newline ends a statement, and only brackets or a leading `.` continue it. Indentation is used only to improve error messages. `;` is an optional same-line separator. |
| G4 | serves | 1153 corpus lines, against 1374 for `do … end`. Construction is `Name(field: v)`, and there are no braces-as-literals. |
| G1 (R6) | serves | 12 syntax rules. Every continuation is visible at a line's edges. No silent joins remain after the fixes. |
| G3 | serves | No macro or annotation syntax. `of`/`to` apply only to the frozen built-in set. |
| G11 | neutral | Layout lives inside brackets, so P1 and P3 give identical ASTs for UI code. Trailing closures are left to D7. |
| P-GO | avoids | Words, not abbreviations (`and`, `or`, `not`); `fn` is the only short keyword |
| P-PY | avoids | No significant indentation |

## Criteria

From `0006-research/criteria.md`, written before the options:

| Criterion | Weight |
|---|---|
| Unambiguity | 20 |
| Readability | 20 |
| Brevity | 15 |
| Consistency | 15 |
| Error recovery | 10 |
| Implementation risk | 10 |
| DSL friendliness | 10 |

## Options considered

There were 14 ideas (`0006-research/ideas.md`, `analysis.md`).
- **Ruled out:**
  - JavaScript-style ASI;
  - Swift's whitespace operators;
  - optional braces;
  - spoken full-word keywords (G4);
  - a `...` marker on every continued line;
  - `endif`-style closers;
  - `=` versus `:=`;
  - a canonical tree text.
- **The finalists:**
  - **P1:** braces, Go-style line ends with Kotlin-style joins.
  - **P2:** `do … end`.
  - **P3:** braces, with only brackets or a leading `.` continuing a line.

## What the real examples taught

See `0006-research/lessons-and-scores.md` and `review-p3.md`.
- **All three parsers produce byte-identical ASTs** from their own corpora (chatsim, widgets, errors, types,
  tricky). The parsers are 872, 925 and 896 lines of Python, and run in CI on three OSes.
- **P1** silently joins a line ending in a mistaken trailing operator.
- **P2** costs 19% more lines, and reports a missing `end` at the enclosing block.
- **P3** needed parentheses on 2 real lines in 1153, and turns P1's silent join into an error at the right line.
- **The reviewer** verified that P3's corpus parses to the same ASTs under P1. So P3 is a strict subset of P1 with the
  same meaning, and relaxing it later can't break a program.
- **The loop-2 parser** (1004 lines) applies the review's fixes and adds 24 new error tests (33 in total). Common words parse as names (`tok.type`, `xs.take(3)`, `send(to: a)`, `let lock = 1`). The one AST change: a statement in a match arm needs `{ }` (F12).

## Decision

**Adopt P3 with the review fixes.** The syntax rules a programmer learns:

1. **Newlines.** A newline ends a statement. Inside `( )` or `[ ]`, newlines are spaces. A line starting with `.` or
   `?.` continues the one before it, but only after `)`, `]`, a name, a literal or `self`.
2. **Nothing else continues a line.** A line ending in an operator, `,`, `=`, `:`, `.`, `not`, `->`, `=>`, `of` or
   `to` outside brackets is an error: "wrap it in ( )".
3. **Commas.** Inside brackets, items are separated by commas. A line can't start with `(`, `[` or `-` after a complete
   item. A trailing comma is allowed in brackets and in `{ }` item bodies (`type`, `enum`, `match`, `iface`).
4. **Braces.** `{` goes on the header line, and `} else {` stays on one line. Braces are only ever blocks; values are
   built with `Name(field: v)`. `;` joins statements on one line.
5. **Declarations:**
   - variables: `let`/`var`/`const name[: T] = v`;
   - functions: `fn name(p: T, q: T = default) -> R [fails] { }`;
   - types: `type`, `enum`, `iface`, `impl I for T`;
   - `pub` as a prefix;
   - receivers: `self`, `mut self`, `take self`.
6. **Types:**
   - `T of U`;
   - `Map`, `SortedMap` and `Lru` take `of K to V`, from a grammar-known table that matches ADR-0002's frozen set;
   - `fn(T) -> R`, `dyn I`, `(A, B)`.
7. **Names.** Type, variant and interface names start with a capital letter. A lowercase name in a pattern binds.
   No shadowing.
8. **Errors:** `try f()`, `try f() context "…"`, `try f() else e { }`. A `try` operand is one postfix chain, and `try`
   is the outermost operation (ADR-0004).
9. **Binding blocks:** `if x = opt { } else { }`, `with x = e { }`, `lock a, b { }`, `crew c { }`,
   `match e { P if g => …, }`.
10. **Lambdas:** `fn(x) => expr` or `fn(x) { statements }`. Field-list arguments are `.dept desc`.
11. **Strings** stay on one line. `{expr}` and `{expr:fmt}` interpolate, and `\{` gives a literal brace.
12. **Operators and checks.** Use `and`/`or`/`not`, never symbols, and comparisons don't chain. `#` starts a comment.
    Unreachable statements and unused non-call values are errors (a semantic check in M2).

**Keywords.** 28 words are truly reserved: `pub const type enum iface impl for fn let var if else while in match return fail break continue try or and not mut self true false none`. These are contextual and usable as names elsewhere:
`desc asc to of context crew lock with drop take is dyn fails module use as`. After `.`, any word is a member name.

**Amendment 2 (ADR-0005 amendment 1, issue #5).**
- `iface` and `impl` are no longer keywords, which leaves 26 reserved words.
- `override` and `super` join the contextual words.
- `type Name is Parent {` declares a parent; `is` already introduced capabilities, and a capitalised name after `is` is the parent.
- The parser is `docs/examples/types/inherit/parser.py`.

**Tooling.**
- **Formatter:** one mandated formatter, with `fmt --check` in CI. The parser doesn't reject non-canonical layout.
- **Error recovery:** on the error path only, indentation names the likely opener of an unclosed `{` or `(`.

### Scores (`0006-research/scores.py`, corrected by the review)

| Option | Unamb | Read | Brevity | Consist | Errors | Impl | DSL | Total |
|---|---|---|---|---|---|---|---|---|
| **P3** | 4 | 4 | 5 | 4 | 4 | 5 | 4 | **85** |
| P1 | 3 | 4 | 5 | 4 | 3 | 5 | 4 | 79 |
| P2 | 3 | 4 | 3 | 3 | 3 | 4 | 3 | 66 |

The margin over P1 is 6. It rests on P1's Unambiguity score of 3; at 4, the two tie. The tie would also go to P3,
because P3 is a meaning-preserving subset of P1, so it is the reversible choice.

## Consequences

**Easier:**
- Every line's role is visible at its edges.
- One parser rule set, under 1000 lines.
- Common words (`to`, `lock`, `type`, `take`) stay usable as names.

**Harder:**
- Long boolean expressions need `( )`.
- Multi-line conditions are written `if (a⏎ and b) {`.
- A comma in a `{ }` body is optional, but the formatter removes it.

**Ruled out:**
- Trailing-operator continuation.
- `do … end`.
- Brace literals.
- Symbol operators (`&&`, `||`, `!`).

**Passed on:**
- D7: trailing closures (they would collide with `if f(x) {`) and builder-style layout.
- M0: `tests/corpus/` is created from the P3 corpus and its `bad/` files. Conformance tests are append-only.
- M2: the F9 unreachable and unused-value checks; `try` as the outermost operation.

## Amendment 1: named arguments (issue #4, 2026-11-14)

John asked for named parameters "similar to Swift, but much simpler: every parameter has a name, and there is no
difference in internal / external names". Process record: `0006-research/named/` (criteria, research, ideas, scores,
`review-f1.md`). Example: `docs/examples/syntax/p3n/`, the whole corpus relabelled, with a strict parser, a meaning
check against P3 and a label checker against declarations.

**Rules (they replace "Lambdas" in rule 10 where they differ, and add to rule 6):**

1. **Every argument is labelled.** Each call argument is `name: value`, in declaration order. Defaulted parameters may
   be skipped, and a label may not repeat. This covers functions, methods, built-ins, struct and variant construction,
   and calls through function values. A parameter has one name, used both in the body and at the call.
2. **Pun.** An argument that is exactly one lowercase identifier (not `self`, not in parentheses) means `name: name`.
   `f(count)` never means "the first parameter"; with no parameter `count` it is an error: "write `count: n`".
3. **No variadics.** `print(text: Str)` takes one string, built with interpolation.
4. **Function types name their parameters:** `fn(mut srv: Server, room: Handle of Room) -> Str`. The names are part of
   the type. A named function passes as a value only if its names match; otherwise wrap it: `fn(x) => double(n: x)`.
   **Lambda parameter names are free** and bind by position, like pattern binders.
5. **Variant fields are named** (`Rect(w: Float, h: Float)`) and never defaulted. Patterns bind by position, but a
   binder named after a *different* field of that variant is an error (`Rect(h, w) =>`).
6. **An `impl` uses its interface's parameter names.**
7. **The complete list of unlabelled forms:** the receiver, `.key` arguments (which may not repeat), pattern binders,
   puns, operators and indexing.

**What the example showed** (`p3n/measure.py`, `review-f1.md`):
- **Cost:** +8.0% characters of code (+6.0% of whole files), and the same line count. Lines over 100 columns go from
  23 to 32.
- **Puns:** 75 of 466 labels.
- **`print(text: …)`:** 83 of the labels, the largest single source of noise.
- **Checks:**
  - The meaning check proves the labelled corpus has P3's ASTs.
  - `check_labels.py` verifies 345 of 479 calls against declarations. The rest need receiver types, so they wait for
    M2.
  - 15 new bad files.

| Option | Owner fit 25 | Simple 20 | Read 20 | Brevity 15 | Evolve 10 | Impl 10 | Total |
|---|---|---|---|---|---|---|---|
| **F1b** (these rules) | 4 | 4 | 4 | 3 | 3 | 4 | **75** |
| F3: function values called positionally (Swift SE-0111) | 3 | 4 | 4 | 3 | 3 | 4 | 70 |
| F1 as first proposed (forced lambda names) | 4 | 3 | 4 | 3 | 2 | 3 | 67 |
| F2: one-parameter calls unlabelled | 2 | 3 | 4 | 5 | 2 | 4 | 65 |

The margin is 5. If Owner fit were weighted 10 and Brevity 30, F2 would win 74 to 72. So the decision rests on
following John's stated preference. **F2 is the ready fallback** if John prefers `print("hi")`.

**Traded away:**
- Brevity: +8% of code.
- Renaming or reordering a parameter breaks every caller, though always as a compile error.
- Wrapper lambdas, where a function's names differ from a callback type's.

**Library guideline (D10):** make the natural operand the receiver: `x.clamp(low: 0, high: 9)`, `a.max(other: b)`.

**Passed on:**
- D7: the D2 "variadic" option is ruled out, and D1/D3 must be rebased on `p3n`.
- D9: FFI declarations name every parameter.
- M0: the corpus comes from `p3n`.
- M2: the label, order, swap-guard and impl-name checks.

## Syntax budget impact

| Item | Count |
|---|---|
| Reserved keywords | 28 |
| Contextual words | 16 |
| Operators | arithmetic, comparison, `?.`, `=>`, `->`, `..` (no symbol booleans) |

12 syntax rules.

## Adversarial review log

| Review | Findings | Outcome |
|---|---|---|
| `0006-research/named/review-f1.md` (amendment 1, Fable 5.2) | Fatal: forced lambda names vs no shadowing; pattern swaps; loose puns; iface names; variadics; understated cost; weak meaning check | All fixed (F1b); scores corrected to 75 vs 70 |
| `0006-research/review-p3.md` | F1 a missing comma joins lines in brackets; F2 `try … or` overload; F3 reserved words block names; F4 commas in bodies; F5 capitalisation; F11 closer diagnostics; F6–F10, F12 | All adopted. `try … else e`; contextual keywords; capitalised types. Scores corrected; margin 6, backed by reversibility. |
