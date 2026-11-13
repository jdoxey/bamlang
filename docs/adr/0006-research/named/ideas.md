# Amendment 1: ideas (Opus, 2026-11-14)

Every option keeps the gate: one name per parameter. They differ on the hard cases: one-parameter calls, punning,
function values and lambdas, argument order, enum payloads, and built-ins.

## Sane

- **S1 Strict.** Every argument in every call is `name: value`: functions, methods, built-ins (`print(text: s)`),
  enum payloads (`Drag(dx: 3)`, `some(value: x)`), and calls through function values. Function types name their
  parameters (`fn(target: Handle of Widget)`); a lambda lists the type's names, or `_`.
- **S2 Strict plus punning.** S1, but a bare name argument `f(count)` means `f(count: count)`. It is an error if `f` has
  no parameter `count`. Rust's `Point { x, y }` and OCaml's `~x` are the precedents. Patterns use the same shorthand.
- **S3 S2 plus a one-parameter exemption.** A function with exactly one parameter is called without the label:
  `print("hi")`, `xs.push(3)`, `some(x)`. Adding a second parameter to it breaks every caller.
- **S4 S2 with positional function values.** Function types carry no names (Swift's SE-0111 route). A call through a
  function value is positional, and lambda parameters are free names. Everything else is as in S2.
- **S5 S2 with free order.** Labelled arguments may come in any order and are evaluated as written. The formatter
  doesn't reorder (that would change evaluation order).
- **S6 Swift-2 style.** The first argument is unlabelled and the rest are labelled. Fails the spirit of the gate
  ("every parameter has a name" at the call site) but is measured for comparison.

## Crazy

- **C1 One record per function.** Every function takes one struct, and `f(a: 1)` is sugar for `f(F.Args(a: 1))`.
  Arguments become ordinary values and can be built ahead, stored and reused.
- **C2 Type-directed labels.** An argument whose type matches exactly one parameter may omit the label.
- **C3 Path punning.** `send(msg.to)` fills parameter `to` because the path ends in `to`; `f(self.count)` fills `count`.
- **C4 Smalltalk selectors.** The labels are part of the function's name: `copy(src) to(dst)` is one call to
  `copy_to`. Overloading by label becomes natural.

## Combinations considered

- **S2 + S5 order.** Free order helps DSL literals but gives two spellings of one call; rejected unless the review
  finds a case.
- **S2 + C3.** Path punning would remove many labels in chatsim (`self.name`), but the label then depends on a field
  name far away; renaming a field silently changes nothing (still compiles) but changes the reading. Kept as a
  measurement only.

## Ruled out

- **S6:** fails the gate as John phrased it.
- **C1:** every function gets a hidden type; argument records interact badly with borrows (ADR-0001 call-length
  borrows would have to live in a struct).
- **C2:** a reader can't see the mapping without the declaration; fails Readability and R6.
- **C4:** names split around arguments are hard to grep and can't be called through a function value.

## Finalists

- **F1 = S2** (strict, punning, named function types).
- **F2 = S3** (F1 plus the one-parameter exemption).
- **F3 = S4** (F1 with positional function values).

Step 3 rewrites the P3 corpus fully labelled (F1 written out with no puns), then derives F1, F2 and F3 by script,
so the three are measured on the same 1200 lines.
