# D5 analysis (Opus coordinator)

There are 14 ideas: the research's six sketches, S1–S4 and C1–C4.

## Ruled out

| Idea | Why |
|---|---|
| Research 1, no methods (Odin) | Fails P-C ("no native OO") and P-PY |
| Research 4 / S3 structural | Errors appear far from the cause; folded into T1 as an optional `assert` |
| Research 5, sealed plus `open` | Single-level inheritance brings back the fragile base class |
| C1–C4 | Fatal flaws listed in ideas.md; only their kernels are considered |

## Kernels adopted into every finalist

- The receiver mode is written in the header (`self`, `mut self`, `take self`), and `self` is implicit in the body.
- Fields are module-private; record literals are allowed only in the type's module; constructors are `fails`
  functions.
- No inheritance, and no default methods inherited silently.
- Dynamic dispatch is visible in the type (`dyn`) at every conversion site.

## The three finalists

| | T1 records (S1, plus S3's `assert`) | T2 module = type, pools (S2) | T3 enum + `Ext` (S4) |
|---|---|---|---|
| Open extension | `dyn Shape(x)` fills a record from methods | `module X is Shape`; `Pool of dyn Shape` | the single `Ext(dyn ShapeFns)` variant |
| Closed set | sum types (ADR-0002) | sum types | the enum itself, with methods |
| Dynamic call looks like | `s.area()` with `s: dyn Shape` | `pool[h].area()` | the `Ext(d) -> d.area()` arm |

All three are modelled in Rust, std only. User code may not use generics or inheritance-like defaults, and anything
Rust forces that the design wouldn't is noted.
