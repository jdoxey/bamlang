# P3n: fully labelled calls, decided design F1b (experiment)

Copy of P3 with every call argument written `name: value`. Run `bash run.sh`.

## F1b rules
1. Every call argument is `name: value`, in declaration order (defaulted parameters may be skipped), or a pun.
2. Pun: an argument that is exactly one lowercase identifier token (not `self`, not capitalised, not parenthesised;
   `f((x))` is an error) means `name: name`.
3. Labels may not repeat; neither may field-list key arguments (`.dept desc`).
4. No variadics: `print(text: Str)` takes one string (build it with `+` or interpolation).
5. Function types name their parameters; calls through function values use those names. Lambda parameter names are
   free and bind by position (like pattern binders).
6. Enum variant fields are named; patterns bind positionally, but a binder equal to the name of a *different* field of
   the same variant is an error (swap guard).
7. An `impl I for T` method's parameter names equal the interface's.
Unlabelled forms: the receiver, `.key` arguments, pattern binders, the pun, `try ... context`.

## Tools
- `same_meaning.py OLD NEW`: the labelled AST equals the P3 AST up to labels, fnt names, vfield names and lambda renames
  (injective, no capture, `(name ..)` nodes only). `sm_tests/` holds known false-accept cases; `ok_*` must pass, the rest must fail.
- `check_labels.py FILE`: labels versus declarations (rules 1, 6, 7). Declarations come from the file itself (each corpus
  file is a separate program) plus `NAMES.md` (machine-readable block). Calls it cannot resolve are counted as skipped
  (ambiguous method names, unknown receivers). `check_bad/` holds one failing file per error kind (`# expect: text`).
- `measure.py`: size of p3 vs p3n (punned corpus, no subtraction).

## Parser changes (AST differences from ../AST.md)
- Call arguments (`f(..)`, `r.m(..)`, `T(..)`): `name: expr` -> `(named NAME EXPR)`; `.key [desc|asc]` -> `(key ...)` unchanged;
  a pun (rule 2) prints `(named x (name x))`. Any other unlabelled argument is an error at the argument.
  Repeated labels and repeated `.key` arguments are errors (`appears twice`).
- Function types name their parameters: `fn(target: Handle of Widget, take ev: Event) -> Str` (modes go before the name, as in
  declarations: `mut x: T`, `take x: T`). AST: `(fnt [fails] (arg NAME [mut|take] TYPE)* [(ret TYPE)])`; the old `(mut T)`/`(take T)`
  wrappers are gone. Unnamed -> `function type parameters need names`.
- Enum variant fields must be named: `Drag(dx: Int)` -> `(vfield dx (t Int))`. Unnamed -> `variant fields need names`.
- Patterns are unchanged (positional: `Drag(d)`, `some(x)`). Lambdas are unchanged (`fn(x) => e`); a repeated lambda parameter name (except `_`) is an error.
