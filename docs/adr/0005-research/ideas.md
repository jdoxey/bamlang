# D5 ideas (Sonnet inventor, two lenses; condensed; unscored)

Common to all of them: the receiver mode goes in the header (`self`, `mut self`, `take self`), and `self` is
implicit in the body.

## The C-programmer-without-magic lens (sane)

**S1 An interface is a record of functions, filled by the compiler.**
- **Mechanism:** `iface Shape` is a record type of functions. `dyn Shape(x)` boxes `x` (a move) and fills the record
  from `x`'s methods. The record can also be written by hand, and it can be inspected. There is no inheritance.
  Fields are module-private, and constructors are `fails` functions.
- **5 rules.**
- **Risk:** `take self` through a box needs a rule, and a hand-written record can bypass invariants.

**S2 A module is a type, and `dyn` lives in pools.**
- **Mechanism:** privacy comes from the module boundary, and a record literal can be written only inside its module.
  `module Circle is Shape` is checked nominally. A `dyn` value is only ever a `Pool of dyn T` entry, reached through
  a handle.
- **4 rules.**
- **Risk:** many small files; a one-off `dyn` needs a pool.

**S3 Structural interfaces with a visible `dyn` conversion.**
- **Mechanism:** satisfaction matters only at the `dyn T(x)` conversion, and `assert T is I` can pin it.
- **4 rules.**
- **Risk:** a renamed method stops conformance far from the cause.

**S4 Enum methods plus one `Ext(dyn …)` variant.**
- **Mechanism:** methods on enums are an exhaustive `match self`. The only open point is a named variant.
- **3 rules.**
- **Risk:** the expression problem (every new variant edits every method); a plugin can't override a built-in variant.

## Break-an-assumption lens (crazy)

**C1 Behaviour tables keyed by type.**
- **Flaw:** a global mutable registry.
- **Kernel:** a behaviour as a first-class value.

**C2 Dispatch on a tag field.**
- **Flaw:** if the tag and the payload disagree, memory safety is lost.
- **Kernel:** data-driven kind selection for DSL files (G11).

**C3 Capabilities per handle.**
- **Flaw:** a hidden subtyping lattice.
- **Kernel:** narrowed views that hand out less authority.

**C4 Validator type-state.**
- **Flaw:** hidden re-checks at every `mut` exit.
- **Kernel:** an `invariant` block checked at construction, and at the exit of the type's own mutating methods.
