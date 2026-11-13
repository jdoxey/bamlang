# T2 module = type, dyn only in pools

Asked by SPEC.md: B1 shapes + plugin Hexagon (and misspelled-method bug), B2 widget tree + events + plugin Slider +
shared default focus without inheritance, B3 Money/Account/Pool with adversary. Output equals ../expected.txt (run.sh passes).

## Numbers (non-blank, non-comment lines in src/main.rs)
- RUST-ONLY marked lines: 4 (all the `Box<Self>` receiver of `take self`). Rust does not force anything else here.
- Whole file ~364 lines. Pool stand-in (builtin, with generics) 38; core ~108 (incl. dispatch/render); B3 44; plugin 41; main 78.
- Plugin author, Hexagon: 13 lines. Slider: 26 lines (the trait has 5 methods, none defaulted: children, detach, render_line,
  event, close; a leaf must write the two empty ones). Default focus: plain `focus_next()` called from each impl.
- Widgets are `Handle`s in a `Pool of dyn Widget`; trees are handle lists; Rust-side `dispatch` walks them.

## What a reader sees at a dynamic call
`pool.get(h).unwrap().area()`: the pool's type `ShapePool = Pool of dyn Shape` is the marker; `dispatch(pool, root, path, ev)`
hides one. There is no `dyn` conversion expression: `pool.insert(Box::new(x))` coerces silently (design: insert checks `is Shape`).

## Bug variant: `area` misspelled `aera` in the plugin's `impl Shape for Hexagon`
Reported AT THE TYPE'S IMPLEMENTS DECLARATION (the module/impl), not at a call or conversion; builds nothing:
`error[E0407]: method `aera` is not a member of trait `Shape`` (src/main.rs:231)
`error[E0046]: not all trait items implemented, missing: `area`` (src/main.rs:229, `impl Shape for Hexagon`, suggests `area`)

## Adversary (B3), scratch copies in /tmp/claude-1000/types-scratch; compiler output (note/help lines elided)
- (1) `Money(-5)`: `error[E0423]: cannot initialize a tuple struct which contains private fields` (src/main.rs:275, at the literal).
- (2) `acct.balance = ...`: `error[E0616]: field `balance` of struct `Account` is private` (at the field access).
- (3) ignore `withdraw`'s Result: default is only `warning: unused `Result` that must be used`, build exits 0.
  With `#![deny(unused_must_use)]`: `error: unused `Result` that must be used`. RUST-ONLY difference: the design's
  `fails` must be an error by default; Rust needs the deny lint.

## Rules needed / Rust vs design
- Rules: dyn only inside a pool; handles are generation-checked (assert in B2 shows stale handles after `close`);
  `take self` = remove from pool, then consume. Parents hold handles, so close needs the pool (`close(self, pool)`).
- Cost: widget trees need a pool and a dispatcher; a one-off dyn also needs a pool. Rust matched the design otherwise.
