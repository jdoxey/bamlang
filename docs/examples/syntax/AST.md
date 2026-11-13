# Syntax-corpus AST (D6)

Every candidate parser prints this tree for the same program, so the corpora are provably equivalent. Parsers must
reproduce `expected/*.ast` byte for byte.

## Printing

- A node is `(kind atom* child*)`. Atoms (identifiers, flags, numbers, quoted strings) follow the kind on the first
  line; children are nodes.
- One node per line, children on the following lines indented two spaces more than the parent.
- A node with no children is one line: `(name x)`. A node with children has no closing line: the `)` is appended
  to the last line of its last descendant.
- No source positions. Lines end in `\n`, no trailing spaces, file ends with one `\n`.
- Strings are printed as JSON strings (`"` `\` and control characters escaped as `\" \\ \n \r \t \b \f \u00XX`;
  non-ASCII characters raw, UTF-8). Escapes in source are decoded first (`\n \t \r \0 \\ \" \{ \}`).
- Numbers: the literal text with `_` removed (`1_000` -> `1000`, `2.50` stays `2.50`). A negative literal appears
  only inside a pattern (`-1`); in expressions it is `(un - (int 1))`.
- Parentheses around an expression leave no node. `()` is `(tuple)`.
- Atoms never contain spaces. `pub`, `fails`, `mut`, `take`, `desc`, `asc` are the only flag atoms.

## Top level

| Node | Meaning |
|---|---|
| `(file item*)` | whole source file |
| `(module NAME item*)` | `module NAME { ... }` |
| `(use PATH)` / `(use PATH as ALIAS)` | PATH is dotted, one atom: `std.sync` |
| `(const NAME [pub] [TYPE] EXPR)` | `pub` flag follows NAME |
| `(let NAME [TYPE] EXPR)`, `(var NAME [pub] [TYPE] EXPR)` | `let` has no flags |

## Declarations

| Node | Children |
|---|---|
| `(type NAME [pub] member*)` | `(field NAME [pub] TYPE [(default EXPR)])`, `(fn ...)`, `(drop ...)` |
| `(enum NAME [pub] member*)` | `(variant NAME vfield*)`, `(fn ...)`, `(drop ...)`. A vfield is `(vfield TYPE)` or `(vfield NAME TYPE)` |
| `(iface NAME [pub] [(is CAP+)] fn*)` | required signatures are `fn` without a body |
| `(impl IFACE TYPE)` | `impl I for T` |
| `(fn NAME [pub] [fails] recv? param* [(ret TYPE)] [block])` | `fails` follows `->` Type in source |
| `(recv self)`, `(recv mut)`, `(recv take)` | receiver mode (`self`, `mut self`, `take self`) |
| `(param NAME [mut\|take] [TYPE] [(default EXPR)])` | type is absent only on lambdas |
| `(drop recv param* block)` | `drop(mut self) { }` |

## Types

| Node | Source |
|---|---|
| `(t NAME TYPE*)` | `Int`, `List of T`, `Handle of T`, `Optional of T`, `Mutex of T`, `Map of K to V` (`to` joins only after the heads `Map` and `SortedMap`; `of` is right-nested: `List of Handle of W` = `(t List (t Handle (t W)))`) |
| `(dyn I)` | `dyn I` |
| `(fnt [fails] argtype* [(ret TYPE)])` | `fn(take Event, Int) -> Str fails`; an argument is TYPE, `(mut TYPE)` or `(take TYPE)` |
| `(ttuple TYPE+)` | `(A, B)` |

In expression position a type expression (`Pool of Widget`) is the callee node: `(call (t Pool (t Widget)))`.

## Statements

| Node | Source |
|---|---|
| `(block stmt*)` | `{ ... }` |
| `(assign TARGET EXPR)`, `(opassign OP TARGET EXPR)` | `=`; `+=` has OP `+`. TARGET is `name`, `field` or `index` |
| `(if COND block [(else block\|if\|iflet)])` | `else if` nests an `if` inside `else` |
| `(iflet NAME EXPR block [(else ...)])` | `if x = expr { }` |
| `(while COND block)`, `(for PAT EXPR block)` | |
| `(match EXPR arm*)` | `(arm PAT [(guard EXPR)] BODY)`; BODY is a `block` or one statement/expression node |
| `(return [EXPR])`, `(break)`, `(continue)` | |
| `(fail EXPR+)` | `fail "msg"` or `fail kind, "msg"` |
| `(crew NAME block)` | `crew c { }` (also an expression) |
| `(lock EXPR+ block)` | `lock a, b { }` |
| `(with NAME EXPR block)` | `with w = pool[h] { }` |

Any expression is also a statement (no wrapper). `if`, `match`, `crew` and lambdas can be expressions.

## Try

`(try EXPR)`, `(try-context EXPR CTX)`, `(try-or NAME EXPR block)`. `NAME` is the error binding or `_`.
`try crew c { } or e { }` is `(try-or e (crew c ...) block)`.

## Patterns

`(pwild)` `_`; `(pbind NAME)` lowercase name; `(pvariant NAME pat*)` for `Click`, `Drag(d)`, `some(x)`, `Shape.Ext(d)`
(an uppercase initial, a dot, or a following `(` makes a variant); `(plit LIT)` literals incl. `none` and `-1`;
`(ptuple pat*)`; `(plist pat*)` with `(prest [NAME])` for `..rest`; `(por pat+)` for `a | b`.

## Expressions

| Node | Source |
|---|---|
| `(int N)` `(float N)` `(str "text")` `(bool true)` `(none)` | literals |
| `(interp part*)` | string with `{expr}`: `(s "text")`, `(part EXPR)`, `(partf "fmt" EXPR)` for `{x:.2}` |
| `(name X)` | identifier; `self` is `(name self)` |
| `(tuple EXPR*)`, `(list EXPR*)` | `(a, b)`, `[a, b]` |
| `(call CALLEE arg*)` | `f(x)`, `Circle(r: 1.0)` |
| `(mcall NAME RECV arg*)`, `(mcall? NAME RECV arg*)` | `recv.m(x)`, `recv?.m(x)` |
| `(field NAME EXPR)`, `(field? NAME EXPR)` | `e.f` (also `e.0`), `e?.f` |
| `(index EXPR EXPR)` | `e[i]` |
| `(bin OP L R)` | OP: `+ - * / % == != < <= > >= and or ?? .. ..=`, all left-associative |
| `(un OP EXPR)` | OP: `-` or `not` |
| `(lambda param* BODY)` | `fn(x) => e` (BODY an expression) or `fn(x) { }` (BODY a `block`) |
| `(named NAME EXPR)` | argument `name: expr` |
| `(key PATH [desc\|asc])` | field-list argument `.dept`, `.salary desc`, `.a.b` |
| `(if ...)` `(iflet ...)` `(match ...)` `(crew ...)` `(try ...)` | as above |

Binding strength, low to high: `or`, `and`, `not`, comparison, `??`, `..`/`..=`, `+ -`, `* / %`, unary `-`
(and `try`), postfix.
