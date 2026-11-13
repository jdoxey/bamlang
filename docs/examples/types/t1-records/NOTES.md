# T1 records: `dyn Shape(x)` fills an interface record from methods

Asked by SPEC.md: B1 shapes + plugin Hexagon (and misspelled-method bug), B2 widget tree + events + plugin Slider +
shared default focus without inheritance, B3 Money/Account/Pool with adversary. Output equals ../expected.txt (run.sh passes).

## Numbers (non-blank, non-comment lines in src/main.rs)
- RUST-ONLY marked lines: 34 (grep -c RUST-ONLY). 18 are shims for core types, 9 for plugin types (the compiler would
  fill the record at `dyn Shape(x)`), 6 are `dyn_*` stand-ins plus the ShapeRec bridge, 1 is the `Box<Self>` receiver.
- Whole file ~376 lines. Pool/dyn stand-in (builtin) 46; core ~100; B3 44; plugin 50; main 76.
- Plugin author, Hexagon: 15 lines (11 real + 4 shim); hand-built record version: 7 more. Slider: 26 (21 + 5 shim).
- Default focus: one plain `focus_next()` that each impl calls (1 line per impl). No inheritance, no defaults.

## What a reader sees at a dynamic call
`s.area()` on a `Box<dyn Shape>` and `root.event(..)`: nothing marks the call; the type `dyn Shape` is visible only at the
`dyn_shape(x)` conversion (grep-able), which is the only place dyn values are made (by convention here, not enforced).

## Bug variant: `area` misspelled `aera` in the plugin
Modelled design: the inherent method is misspelled, so the compiler-filled record at `dyn_shape(Hexagon)` has no `area`.
Rust cannot do that. With the explicit shim, the result is WORSE than the design: it builds (exit 0) with
`warning: function cannot return without recursing` (src/main.rs:234, the shim `Hexagon::area(self)` resolves to the trait method itself),
`warning: field `side` is never read`, `warning: method `aera` is never used`; running it dies with
`thread 'main' has overflowed its stack`. Under `deny(warnings)` it would fail at the shim, i.e. at the conversion, not at a call.
If the plugin author instead writes `impl Shape for Hexagon { fn aera.. }` directly: `error[E0407]: method `aera` is not a member of trait `Shape``
plus `error[E0046]: not all trait items implemented, missing: `area`` at the impl. Design answer: at the conversion
(`dyn Shape(Hexagon)`), a message naming the missing `area`; the structural fill must make that message good.

## Adversary (B3), scratch copies in /tmp/claude-1000/types-scratch; compiler output (note/help lines elided)
- (1) `Money(-5)`: `error[E0423]: cannot initialize a tuple struct which contains private fields` (src/main.rs:289, at the literal).
- (2) `acct.balance = ...`: `error[E0616]: field `balance` of struct `Account` is private` (at the field access).
- (3) ignore `withdraw`'s Result: default is only `warning: unused `Result` that must be used`, build exits 0.
  With `#![deny(unused_must_use)]`: `error: unused `Result` that must be used`. RUST-ONLY difference: the design's
  `fails` must be an error by default; Rust needs the deny lint.

## Rules needed / Rust vs design
- Rules: `dyn Shape(x)` is the only way to make a dyn; a record can be hand-written (ShapeRec) and bypasses `new()` checks
  (I validated by hand: an invariant leak the design must address); `take self` through a box needs a rule (`Box<Self>`).
- Rust forced: trait + shim instead of structural fill; generics in `dyn_shape`; `'static`.
