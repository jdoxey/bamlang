# D7 ideas (Sonnet inventor, two lenses; condensed; unscored)

**Shared:**
- Events are `Msg` values (or capture-free functions), and only `update(mut m, msg)` writes.
- Local widget state is a framework-owned slot addressed by a handle.
- The runtime loop (an arena per frame, diff, dispatch) is library code.

## The maintainer lens (sane)

**S1 Clause items in lists plus a one-child-per-line formatter.**
- **Grammar:** `item := expr | if c => x | for p in xs [if g] => e`, legal only inside `[ ]`. The first token decides, so
  it is a strict LL(1) extension. The `=>` avoids the `if x = opt {` collision.
- **3 rules.**
- **Risk:** deep screens still stair-step, though less.

**S2 Elm shape with a compiler-checked pure view.**
- **Mechanism:** `if`/`match` become expressions (`else` mandatory; `Empty()`). Functions returning `Node`, `Build` or
  `Spec` may not write (the same call-graph pass as ADR-0001 rule 6). `ui.slot(key, init)` is the only intrinsic.
- **4 rules.**
- **Risk:** a new analysis; a `dyn` call can cause a false rejection.

**S3 Typed records with spread `..base`, and table-driven specs.**
- **2 rules.**
- **Risk:** the spread hides which fields came from `base` (R6).

**S4 Variadic last parameter (`kids: Node...`) and explicit `key:`.**
- **Mechanism:** items follow the named arguments positionally, so `[ ]` disappears. Clauses are allowed as variadic
  arguments.
- **3 rules.**
- **Risk:** named arguments must come before the items.

## The break-an-assumption lens (crazy)

**X1 A flat node table with parent ids.**
- **Flaw:** parent pointers and string ids.
- **Kernel:** `lang tree` prints any `Node`, `Build` or `Spec` value as a tree (G8).

**X2 Leaves first, with named lets and a depth limit.**
- **Flaw:** naming noise; imperative `push`.
- **Kernel:** a "name this subtree" depth hint in the formatter.

**X3 `.view`, `.build` and `.spec` files containing one expression.**
- **Flaw:** a function in disguise.
- **Kernel:** a constructs-only check that proves a build file does no I/O.

**X4 Builder pipelines with leading-dot chains and `take self` setters.**
- **Flaw:** control flow needs combinators (`child_if`, `children_of`); `)))` piles up.
- **Kernel:** dot-chains for the attributes of a single node. No grammar change.
