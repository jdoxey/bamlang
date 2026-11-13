# `types`: the benchmark for D5

Deterministic output; every option prints the same `expected.txt`.

## B1. Shapes from a plugin

- The core defines `Circle(r)` and `Rect(w, h)`.
- A separate "plugin" module, which may not edit the core, adds `Hexagon(side)`.
- Build a list of 5 shapes (including 2 hexagons). Print each shape's name and area (2 decimals), then the total.
- Bug variant (NOTES): the plugin's `area` is misspelled `aera`. Record when and where the error appears.

## B2. A widget tree with events and third-party kinds

- The core has `Panel` (children) and `Button(label)`. A plugin adds `Slider(value, max)`.
- Build the tree: a root Panel holding Button "OK", a Slider (3 of 10) and a Panel holding Button "Cancel".
- Events, in order: `click OK`, `drag Slider +4`, `click Cancel`, then `close` of the inner panel, which consumes it
  and its children (`take self`).
- Print a line per event handled, and the tree (indented) after each. Default focus behaviour ("focus moves to
  next") must be shared by all kinds without inheritance.

## B3. A data model with invariants

- `Money(cents)` can't be negative. `Account(owner, balance)` lives in a `Pool of Account`.
- `deposit` and `withdraw` keep `balance >= 0` (`withdraw` `fails` on insufficient funds), and `transfer(a, b, m)`
  is a pool method.
- An "adversary" module tries to (1) build `Money(-5)` directly, (2) set `balance` directly, and (3) call `withdraw`
  ignoring failure. Each attempt is in a scratch copy, and the compiler output goes in NOTES.
- The program runs a valid sequence and prints balances, plus one failed withdrawal message.

## NOTES.md per option

- Lines per part, separating what the plugin author writes.
- What a reader sees at each dynamic call.
- The bug-variant and adversary results (pasted compiler output).
- Rules a programmer needed, and what Rust forced that the design wouldn't (or vice versa).
