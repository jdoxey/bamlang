# ADR-0006: Core syntax

- **Status:** Accepted (v1 of the syntax; the corpus in `tests/conformance/` is the executable form)
- **Date:** 2026-11-13
- **Tier:** Full (research in `0006-research/notes.md`)
- **Decided by:** Claude (ruling R7). John may veto by opening an issue.

## Context

G4 clean syntax, G5 no significant whitespace and no mandatory semicolons. ADRs 0001-0005 used illustrative syntax; this ADR fixes it. The test is the corpus `tests/conformance/01..12`: eleven short programs and `chatsim` (12), all written in the syntax below. The corpus has not been parsed yet (no compiler); M1 is the first check.

## Charter

| Goal / problem | Effect | Why |
|---|---|---|
| G1 | serves | One expression form for blocks, `if`, `match`; few keywords. |
| G4 | serves | No parentheses on conditions, no `new`, no `return` needed for the last expression. |
| G5 | serves | Braces delimit blocks; newline ends a statement by the rule below; `;` is optional. |
| G11 | serves | Trailing-closure calls give nested declarative blocks (D7). |
| P-GO | avoids | Full-word names (`startsWith`, `handles`). |
| P-PY | avoids | No indentation, no `self` parameter. |
| P-CPP, P-RUST | avoids | No `::`, `<>`, `&`, lifetimes, macros (`!` only as postfix unwrap). |

## Criteria

G5 compliance; fewest rules to predict where a statement ends; readability of the corpus; unambiguous for a hand-written parser (implementation risk); DSL-friendliness; consistency with ADRs 0001-0005.

## Options considered

1. **A. Newline ends a statement unless the line cannot end there (chosen).**
2. **B. JS-style ASI.** Traps with leading `(` and `[`.
3. **C. Go-style lexer insertion.** Nearly A; A adds leading-`.` continuation and optional `;`.
4. **D. Mandatory semicolons.** Violates G5.
5. **E. Indentation.** Violates G5.
6. **F. Everything an s-expression.** No statements; unreadable for most (G4).
7. **Crazy G. `end`-delimited blocks (Lua/Ruby), no braces.** Same continuation rule; braces win on DSL nesting and trailing closures.
8. **Crazy H. Dot-chain operator for statements (`a. b. c`).** Novel and unfamiliar.

| | G5 30 | Predictable 25 | Familiar 20 | Parser risk 15 | DSL 10 | Total |
|---|---|---|---|---|---|---|
| A | 5 | 4 | 4 | 4 | 5 | 88 |
| B | 5 | 2 | 4 | 3 | 4 | 74 |
| C | 5 | 4 | 5 | 5 | 4 | 93 |
| D | 1 | 5 | 5 | 5 | 4 | 62 |
| G | 5 | 4 | 3 | 4 | 2 | 74 |

C and A are the same rule family; they differ by 5 (a tie). Tie-break from the corpus: program 11 has a multi-line chain with line-leading `.`, which C rejects (it would end the statement). A adopted, as C plus that one continuation case.

## What the real examples taught

Writing the corpus found these gaps, each fixed in the Decision:
- `let x = foo() else { return }` was needed ten times in `chatsim`; `if let` alone nests too deep.
- A stored callback that takes the whole server cannot be called through the server's own pool (case 20). It works because **closures that capture only copyable values (numbers, handles, strings) are themselves copyable**, so `let callback = user.onMessage` copies the closure out, the borrow of `user` ends, and `callback(self, ...)` is legal. No `mem::replace` trick (ADR-0001 mitigation 3 is thereby satisfied).
- Unscoped `spawn` cannot share a `Mutex` or `Channel` (single owner). Added `scope` (see ADR-0003 amendment).
- Field defaults in `type` bodies keep constructors short (`Server()`).
- `Pool of User()` reads awkwardly but is consistent: `Name of Args` is a type, and a type followed by `()` constructs.

## Decision

**Lexical**
1. Source is UTF-8. Comments: `//` to end of line; `/* */` nests.
2. **Statement ending.** A newline ends a statement unless (a) the line ends with a binary operator, `,`, `.`, `->`, `=`, or an opening `(`, `[`, `{`; or (b) the next non-blank line begins with `.` (a call chain) or a closing `)`, `]`, `}`. A line beginning with `(`, `[`, `-` or `+` starts a new statement. `;` may separate statements on one line and is never required.
3. **Names.** Types, enum variants and interfaces are `UpperCamel`. Values, fields, functions and methods are `lowerCamel`. Enforced by the compiler (the capital letter distinguishes a type from a value for the parser). Full words, no abbreviations in the stdlib beyond `len`, `max`, `min`.
4. Literals: `42`, `1_000`, `0xff`, `3.5`, `true`, `false`, `"text"` with escapes `\n \t \" \\ \{`, and interpolation `{expr}`. No character type in v1; `chars()` yields one-letter strings. `[a, b]` is a `List`; `[]` with a declared type is empty. `a..b` is a half-open range, `a..=b` closed.

**Declarations**
5. `let x = e` immutable binding; `var x = e` mutable; `let x Type = e` annotates. `x = e` assigns (only to `var`). Bindings may not shadow in the same function.
6. `fn name(a Int, b String) Result of Int, Error { ... }`. Type follows name. The body's last expression is its value; `return` exits early. `fn` types: `fn(Int, Int) Int`. Argument labels are optional at call sites and must match the parameter name when given.
7. Methods live in `type` bodies (ADR-0005): `fn` reads the receiver, `mut fn` may change it; fields are visible by bare name; `self` names the whole value. Fields may have defaults (`x Int = 0`). Fields on one line separate with `,`.
8. `enum E { A, B(x Int, y Int) }`, `interface I { fn m(a Int) Int }`, as in ADR-0005.
9. Type syntax: `Name`, `Name of A`, `Name of A, B`. `of` is right-associative and a comma binds to the nearest enclosing `of`; use parentheses otherwise.

**Expressions and control flow**
10. `if c { } else if c { } else { }` is an expression. No parentheses around conditions; braces required. Also `while c { }`, `loop { }`, `for x in list { }`, `break`, `continue`. `_` is the wildcard.
11. `match v { Pattern -> expr }` is exhaustive; patterns: literals, variants with bindings, `_`, `Some(x)`. Arms are separated by newlines.
12. Boolean operators are the words `and`, `or`, `not`. Comparison `== != < <= > >=`; arithmetic `+ - * / %` (integer `/` truncates). `x or default` also works on `Optional` and `Result` (it yields the default on `None`/`Err`), distinguished by the left operand's type.
13. Absence and errors (ADR-0004): variants `Some`, `None`, `Ok`, `Err`. Postfix `?` propagates; postfix `!` unwraps or panics. Bindings: `if let p = e { } else { }` and `let p = e else { diverge }` (the else block must `return`, `break`, `continue` or `panic`).
14. Closures: `{ a, b -> body }` or `{ -> body }` when no parameters; a closure as the last argument may follow the call's parentheses (`xs.map { x -> x * 2 }`), and parentheses may be omitted if it is the only argument. Closure bodies are blocks.
15. Borrows (ADR-0001) end at the last use of the borrowed name, not at the end of the scope. Assigning to a `mut` borrow parameter writes through it (`lock total { t -> t = t + n }`).
16. Concurrency forms (ADR-0003): `spawn { }`, `scope { s -> s.spawn { } }`, `lock m { guard -> }`.
17. Entry point: `fn main()`. The stdlib supplies `print` (adds a newline), `stdin.lines()`, and the container methods used in the corpus. Their exact set belongs to D10.

**Reserved words (22):** `fn let var mut type enum interface match if else for in while loop break continue return and or not true false scope lock spawn of take`.

## Consequences

- Easier: the corpus reads like the examples in all earlier ADRs; DSL layouts are nested trailing closures.
- Harder: rule 2 is unusual enough to need good error messages; capitalisation is semantic; the `else` clause of `let ... else` needs a divergence check.
- Rules out: `new`, `self` parameters, semicolon-required code, parenthesised conditions, `!`/`&&`/`||` as boolean operators.
- Risk: nothing is parsed yet. If M1 finds a grammar conflict, fix the grammar by amending this ADR and appending corpus files.

## Syntax budget impact

This ADR is the syntax budget: 22 reserved words, no sigils beyond `? !` postfix and `->`.
