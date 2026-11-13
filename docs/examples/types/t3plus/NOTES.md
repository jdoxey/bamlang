# T3+ : iface + dyn for open sets, enum + one Ext(dyn) for mixed sets, provided functions

Asked by review-t3plus.md decisions F1, S1-S8. Design text: types.txt (illustrative syntax). Rust model: src/main.rs,
stdout equals ../expected.txt (run.sh passes; Tabs container, `intersects`, `show`, `collapse` run but print to stderr only).
No warnings.

## Numbers (non-blank, non-comment lines in src/main.rs)
- RUST-ONLY marked lines: 10 = 3 `Box<Self>` receivers (WidgetKind, Slider, Tabs), 3 overridable provided fns (describe,
  intersects, focus_next), 2 public enum variant fields, 1 `SliderSpec::DEFAULTS`, 1 `..DEFAULTS` use. (t1 34, t2 4, t3 6.)
- Whole file 368. builtin stand-ins 34; shape 30; widget 77 (incl. shared `route`); money 14; account 28; plugin 62; adversary 16; main 85.
- Plugin author: Hexagon 14 (t1 15, t2 13, t3 13). Slider 25 (t1 26, t2 26, t3 23), which includes a `SliderSpec` for the
  DSL literal. Tabs (container) 21, which t1/t3 cannot write at all and t2 writes only via pool handles.
- Slider vs t2: t2's trait had 5 methods and a leaf had to write 2 empty stubs (children, detach). T3+ writes 0 stubs and
  0 forwarding lines: `focus_next` is provided (t2 called it by hand in each impl; here `self.focus_next()`, 1 call, no wrapper).
  Saved: 2 stub lines per leaf, ~10 per widget in the review's estimate for a toolkit with more methods.
- Cost vs t3: +2 lines for Hexagon/Slider (Spec type, name method), +1 `impl ... for` line each; `route` shared by Panel and Tabs.

## What a reader sees at a dynamic call
- Widgets: only the `Ext(d) => d.render(..)` arm, spelled in the core. Callers of `Widget.event` see a closed enum.
- Shapes: `s.area()` / `s.describe()` on a `List of dyn Shape`: the list's type is the only marker; the call itself looks
  static. `describe` is provided so it IS static inside, but it calls `self.area()` dynamically. Reader cannot tell
  from the call site which is which (F1 makes the checker pay for this; the reader still pays).
- Borrowed `other dyn Shape` at `intersects`: the call site shows nothing at all.

## Chosen: owned tree, not `Pool of dyn Widget`
Parents own children by value; no cycles or back-references, so handles add a pool, generation checks and a dispatcher
for nothing. Tabs holds `List of Widget` directly.

## Unclear / contradictory in review-t3plus.md
1. Provided fns vs enums: Panel/Button are enum arms, not impls of WidgetKind, so they cannot use the provided
   `focus_next`; core has a separate `FOCUS` const that the provided fn returns. "All kinds share it" is true only for dyn kinds.
2. "Provided fns can never be overridden" has no Rust equivalent (3 RUST-ONLY lines): the model cannot test that rule.
3. S7 says literals are legal outside only if all fields are `pub`; but Slider itself must validate (value <= max), so the
   DSL type is a separate `SliderSpec` plus a `fails` constructor: two types per validated widget. Not stated anywhere.
4. S8 "methods live only inside the type" collides with `transfer` on a built-in `Pool of Account` (not our type): I made it a
   free function. The decisions are silent on methods for pools/containers of our type.
5. F1 "every impl in the linked program" is whole-program, which conflicts with separate compilation/incremental builds
   and with plugin loading at run time (is dynamic loading banned?). Also a false-positive risk: an impl that touches
   module state is rejected even if the crew only ever holds Circles. No escape is given beyond Atomic.
6. S2 says a `dyn` param borrows; passing `shapes[1]` borrows an element while `shapes[0]` is borrowed: fine, but for
   `mut self` methods with a dyn argument aliasing self (`s.intersects(s)`) the rule is unstated.
7. S6 trap for re-entering a pool entry is runtime; it is not exercised here (no pool of widgets), so unproven.
8. S5: `is show` on Shape forces every container of dyn to carry a type descriptor; WidgetKind omitted `is show` because Tabs
   holds Widgets, which would need Widget to derive show: the decisions don't say whether an enum with an Ext(dyn) can derive it.
9. Count of rules: the review says 16; this example needed about 12 distinct ones; fine but the choosing rule is the one a reader must memorise.

## Not demonstrated by the model (commented in types.txt): (a) take self on borrowed element, (b) shadowing bug, (c) F1 link
error, (d) private-field literal. Expected texts are proposals, not compiler output.
