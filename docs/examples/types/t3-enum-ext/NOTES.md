# T3 enum + one `Ext(dyn ..)` variant

Asked by SPEC.md: B1 shapes + plugin Hexagon (and misspelled-method bug), B2 widget tree + events + plugin Slider +
shared default focus without inheritance, B3 Money/Account/Pool with adversary. Output equals ../expected.txt (run.sh passes).

## Numbers (non-blank, non-comment lines in src/main.rs)
- RUST-ONLY marked lines: 6 (`Box<Self>` receiver x2; 4 for enum variant fields being public in Rust, where the design
  keeps them module-private; the plugin could build `Shape::Circle{r:-1.0}` if it could see the enum, which it can).
- Whole file ~340 lines. Pool stand-in (builtin) 38; core ~99; B3 44; plugin 38; main 72.
- Plugin author, Hexagon: 13 lines. Slider: 23 lines (3 trait methods). Default focus: plain `focus_next()` called in each arm.
- Every new core kind edits every method (`match self`); a plugin can only fill `Ext`, so it cannot be a container
  (Slider is a leaf) nor override a built-in kind.

## What a reader sees at a dynamic call
The `Ext(d) => d.area()` arm is the only dynamic call, written in the core; user code calls `s.area()` on a closed enum
and sees nothing dynamic. The conversion `Shape::Ext(Box::new(x))` is visible at construction.

## Bug variant: `area` misspelled `aera` in the plugin's `impl ShapeExt for Hexagon`
Reported AT THE IMPL (the type's declaration of the extension), not at the `Ext(..)` conversion or a call:
`error[E0407]: method `aera` is not a member of trait `ShapeExt`` (src/main.rs:216)
`error[E0046]: not all trait items implemented, missing: `area`` (src/main.rs:214, `impl ShapeExt for Hexagon`)

## Adversary (B3), scratch copies in /tmp/claude-1000/types-scratch; compiler output (note/help lines elided)
- (1) `Money(-5)`: `error[E0423]: cannot initialize a tuple struct which contains private fields` (src/main.rs:257, at the literal).
- (2) `acct.balance = ...`: `error[E0616]: field `balance` of struct `Account` is private` (at the field access).
- (3) ignore `withdraw`'s Result: default is only `warning: unused `Result` that must be used`, build exits 0.
  With `#![deny(unused_must_use)]`: `error: unused `Result` that must be used`. RUST-ONLY difference: the design's
  `fails` must be an error by default; Rust needs the deny lint.

## Rules needed / Rust vs design
- Rules: methods are exhaustive matches; extensions only through `Ext`; `take self` through Ext needs `Box<Self>`.
- Rust forced: public variant fields (design: private), `Box<Self>`.
