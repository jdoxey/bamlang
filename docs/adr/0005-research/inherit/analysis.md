# Amendment 1 analysis (Opus)

## Ruled out

| Idea | Why |
|---|---|
| I3 C3 MRO | The reader has to compute a linearisation; fails the 3 am test |
| X1 prototypes | Not classes; dynamic shape; fails ADR-0001's owned layouts |
| X2 hard depth limit | Not supported by the data; a lint instead |
| X3 no `dyn` | Fails G11 and ADR-0005's plugin containers |
| X4 qualified calls everywhere | Noisy; fails G4 |

## What changes in ADR-0005 under every finalist

- `iface` and `impl I for T` are removed. Their job (a set others extend) is done by an abstract base type, and
  `dyn I` becomes `dyn Base`.
- Rule 15's choosing rule becomes:
  - a closed set you own is an `enum`;
  - a set others extend is a base type plus `dyn Base`;
  - a single callback is a closure field.
- Kept:
  - methods live in types;
  - receiver modes;
  - `self.x`;
  - visibility;
  - no overloading;
  - `dyn` boxing at store sites;
  - type descriptors;
  - the whole-program `dyn` check, which now counts every override.
- Built-ins (`List of T` and so on) can be subclassed. A plain built-in value is exactly the built-in.
- `is copy, equals, show` capabilities move to the base type (`type Shape is copy, equals { … }`).

## Finalists

| | **H1 = I1 + I5 + I6** | **H2 = I2 + I4 + I6** | **H3 = I1 + I4 + I6** |
|---|---|---|---|
| Parents | one | one with fields, plus stateless ones | one |
| `self.m()` inside a class | dynamic (open) | static unless `hook` | static unless `hook` |
| Second role | field plus forwarding | stateless parent | field plus forwarding |
| Built-in self-use | none; primitive set documented | static by rule | static by rule |

**Examples (step 3):**
- The ADR-0005 benchmark (`docs/examples/types`: widgets with a plugin container `Tabs`, shapes, accounts), plus a
  serialisable widget (the two-roles case) and a `List of Str` subclass with logging, written under each finalist and
  parsed by an extension of the `p3n` parser.
- A **3 am resolver** that, for every call in the corpus, lists the bodies that can run and the number of steps to
  reach them.
- A C model of each option's dispatch (vtables, `dyn` boxes, `super`, hooks), run on three OSes.
