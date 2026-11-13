# Amendment 1: ideas (Opus, 2026-11-14)

The gate (John): inheritance, no protocols or extensions, nothing final. The ideas differ on the hard cases.

## Sane

- **I1 Single inheritance.**
  - `type Button is Widget { … }`.
  - `override` is required, and an error without a base method.
  - Calling the parent is `super.m()`.
  - Abstract methods are written without a body (`fn draw(self)` in a base type), and such a base can't be built.
  - Plain `Base` values are exactly that class; `dyn Base` holds any subclass (ADR-0005 rule 8 boxing, unchanged).
  - A second role is a field plus forwarding.
- **I2 One stateful parent plus stateless parents.**
  - `type Button is Widget, Saveable`. Only one parent may have fields.
  - A method inherited from two parents is an error unless the class overrides it. The class may then call
    `super(Saveable).m()`.
  - There is no MRO, so every method has exactly one upward candidate.
- **I3 Full multiple inheritance** with C3 linearisation (Python).
- **I4 I1 with closed recursion.** Inside a class, `self.m()` calls this class's `m` statically unless `m` is marked
  `hook` (an overridable extension point). Calls from outside, on `dyn Base`, are dynamic.
- **I5 I1 with open recursion** (the classic rule). The built-ins never call their own overridable methods (no
  self-use), and the documentation states each built-in's primitive set.
- **I6 Built-in subclassing as a wrapper** (`type Names is List of Str`). The subclass gets every List method; only
  methods it overrides differ, and only through `dyn List of Str` or the subclass's own type.

## Crazy

- **X1 Prototypes** (JavaScript or Self): objects inherit from objects.
- **X2 A depth limit of 3** in the compiler.
- **X3 Every method resolved at compile time:** no `dyn` at all, with closed enums for polymorphism. This fails the
  plugin requirement.
- **X4 The implementation chosen in the call:** `x.Widget::draw()` always names the class.

## Combinations

- **I1 + I5 + I6** is the "classic and predictable" finalist.
- **I2 + I4 + I6** is the "two roles, closed recursion" finalist.
- **I1 + I4 + I6** is the third.
