# DSL benchmark library declarations

Machine-readable signatures (`*.names`, the NAMES.md line shape) for the stdlib libraries the benchmarks use. They are
written in the stdlib's internal generic dialect, which ADR-0002's owner answer on G3 allows in the stdlib and `extras`
only: `Node of M`, `Ui of M`, `Slot of T`. An application cannot declare type parameters, but it uses these types like
built-ins; its own `Msg` type fills `M` (`Node of Msg`, `Ui of Msg`).

- A corpus file names its libraries with `use extras.ui` (the last segment picks `lib/ui.names`); `../check_labels.py`
  checks every call it can resolve against these lines plus the file's own declarations, and counts the rest as skipped.
- List children are `List of Node of M`. Every list item, including the body of a clause, is a store site typed from the
  expected element type (here the parameter type of `kids`), so moving or copying rules apply to it (ADR-0001 rule 2):
  a borrowed `Str` read out of an element, a constant or a `for` variable needs `.copy()`; a literal, an interpolation
  and a call result are fresh values and need nothing. A `let` that holds a subtree needs an annotation
  (`let rows: List of Node of Msg = [...]`) because a list literal alone does not name its element type.
- Getters return copies (rule 3), so `slot.get()` needs no `.copy()`.
- Required parameters may follow defaulted ones (`Column(gap=, key=, kids)`); arguments stay in declaration order.
