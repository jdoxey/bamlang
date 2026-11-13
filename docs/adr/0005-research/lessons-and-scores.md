# D5: what the `types` examples taught, and scores

All three versions (Rust, std only, designs modelled with `RUST-ONLY` lines marked) print the same
`docs/examples/types/expected.txt`.

| | T1 records | T2 module + pools | T3 enum + `Ext` |
|---|---|---|---|
| RUST-ONLY lines | 34 (shims Rust needs to fill a record) | 4 | 6 |
| Plugin author: Hexagon / Slider | 11 / 21 (+ shims) | 13 / 26 | 13 / 23 |
| Misspelled `aera` | in the model, compiled, then **overflowed the stack**; the design must report it at `dyn Shape(x)` | E0407/E0046 at the `impl` | E0407/E0046 at the `impl` |
| Invariant leak | **hand-built records bypass `new()` checks** | none | variant fields must be module-private |
| Dynamic call visible as | the `dyn Shape` type | the `Pool of dyn` type | **the single `Ext(d) -> d.area()` arm** |
| Adversary: `Money(-5)`, set balance | E0423, E0616 | same | same |
| Adversary: ignore a `withdraw` failure | only a warning in Rust; ADR-0004 makes it an error | same | same |

## Lessons

- **Report a missing method at the declaration.** Conformance must be declared (`impl Shape for Hexagon`) and checked
  there, as in T2 and T3. T1's fill-at-conversion produced the worst failure.
- **No hand-built interface records.** They break module privacy and invariants.
- **Pools-only `dyn` (T2) makes `close` and every call need the pool,** which is noisy for one-off values.
- **T3's closed enum is the clearest to read,** but its `Ext` must be able to hold containers. Its interface needs
  `children`, which works only if the interface may declare any methods.

## Scores (`scores.py`)

| Option | Transp 20 | Simp 20 | Ext 15 | Invar 15 | Syntax 10 | Fit 10 | Impl 5 | Perf 5 | Total |
|---|---|---|---|---|---|---|---|---|---|
| T3 | 5 | 5 | 2 | 4 | 4 | 5 | 5 | 5 | **86** |
| T1 | 4 | 4 | 5 | 3 | 4 | 4 | 3 | 4 | 79 |
| T2 | 4 | 3 | 4 | 5 | 3 | 5 | 4 | 4 | 79 |

T3 leads by 7, but not robustly (Extensibility +10 makes it a 0.9-point tie). **T3+** to attack: methods on structs
and enums, receiver modes in headers; **nominal interfaces** declared with `impl I for T` in T's module or the
interface's module, checked at the declaration; `dyn I` boxes visible in types, usable directly in containers and as
an enum variant's payload; no hand-built records, no inheritance, no default methods (shared behaviour is a plain
function); module-private fields; `fails` constructors.
