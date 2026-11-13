# P3n: fully labelled calls (experiment)

Copy of P3 with one rule: every parameter has a name and every call argument is `name: value`.
Run `bash run.sh`. `same_meaning.py OLD NEW` proves the labelled corpus means the same as `../p3` (prints every allowed difference).

## Parser changes (AST differences from ../AST.md)
- Call arguments (`f(..)`, `r.m(..)`, `T(..)`): `name: expr` -> `(named NAME EXPR)`; `.key [desc|asc]` -> `(key ...)` unchanged;
  a bare identifier is a pun for `name: name` and prints `(named x (name x))`. Any other unlabelled argument is an error
  at the argument: `argument needs a name: write 'name: value'`.
- Function types name their parameters: `fn(target: Handle of Widget, take ev: Event) -> Str` (modes go before the name, as in
  declarations: `mut x: T`, `take x: T`). AST: `(fnt [fails] (arg NAME [mut|take] TYPE)* [(ret TYPE)])`; the old `(mut T)`/`(take T)`
  wrappers are gone. Unnamed -> `function type parameters need names`.
- Enum variant fields must be named: `Drag(dx: Int)` -> `(vfield dx (t Int))`. Unnamed -> `variant fields need names`.
- Patterns are unchanged (positional: `Drag(d)`, `some(x)`). Lambdas are unchanged (`fn(x) => e`).
- Checker rules (not enforced here): lambda parameter names must equal the function type's names; a repeated label is allowed only for variadics (`print`).
