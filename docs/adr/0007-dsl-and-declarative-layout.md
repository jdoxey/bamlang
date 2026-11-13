# ADR-0007: DSLs and declarative layout

- **Status:** Accepted
- **Date:** 2026-11-14
- **Tier:** Full (see `docs/PROCESS.md`)
- **Examples:** `docs/examples/dsl` (D1 in `d1-clauses/`; the C1 baseline in `c1-baseline/`; records in `d2-variadic/`, `d3-pipelines/`; library signatures in `lib/`)
- **Decided by:** Claude (ruling R7). John may veto by opening an issue.

## Context

G11 says the language "must have good DSL / declarative layout support". G3 forbids macros, annotations and user type
parameters. ADR-0006 (with amendment 1, every argument labelled) left trailing closures and builder layout to this
ADR. Research (`0007-research/research.md`) found that every system needs the host language's `if` and `for` inside
nested trees:
- SwiftUI uses result builders (annotations, with type-checking blow-ups);
- Kotlin uses receiver lambdas (implicit scope, plus an annotation to restrain it);
- Compose uses a compiler plugin;
- Flutter uses plain constructors with collection-`if`/`for`, and admits its staircase.

**Q15 is closed:** G11 is syntax for nested declarative data. UI, build, HTML and test frameworks are libraries.

## Charter

| Goal / problem | Effect | Why |
|---|---|---|
| G11 | serves | Trees with conditional and repeated children are written as one expression that has the tree's shape |
| G3 | serves | No macros, annotations, builders or plugins. The libraries use the stdlib generic dialect that ADR-0002's owner answer allows. |
| G1 (R6) | serves | One desugaring rule, plain left-to-right evaluation, and no hidden receiver or rewritten body |
| G4 | strains | Amendment 1's labels make leaves longer (`Text(content: …)`); the 3 shared files grow +13.7% |
| G5 | serves | No indentation meaning. Clauses live inside `[ ]`. |
| P-SWIFT | avoids | No second, builder sub-language; the list literal is ordinary code |

## Criteria

From `0007-research/criteria.md`, written before the options. The gates are G3, G5 and "ADR-0006 stays a strict
extension".

| Criterion | Weight |
|---|---|
| Declarative readability | 20 |
| Transparency | 20 |
| Simplicity | 15 |
| Generality | 15 |
| Error messages | 10 |
| Fit with earlier ADRs | 10 |
| Implementation risk | 10 |

## Options considered

There were 14 ideas (`0007-research/ideas.md`, `analysis.md`).
- **Ruled out:**
  - receiver lambdas (implicit scope);
  - trailing blocks (they collide with `if f(x) {`);
  - builder parameters;
  - spread;
  - three crazy ideas, whose kernels were kept.
- **The finalists:**
  - **D1:** `if`/`for` clause items inside list literals.
  - **D2:** variadic children after named arguments.
  - **D3:** setter and combinator pipelines.
- **Added after the review:**
  - **C1:** the no-new-syntax baseline (`map`, `+`, `if c { [x] } else { [] }`, `push` statements).

## What the real examples taught

See `0007-research/lessons-and-scores.md`, `review-d1.md` and `docs/examples/dsl/compare.md`. Every option has a
parser (a copy of the amended P3 parser plus its change) that runs in CI. Each option writes three benchmarks:
- **todo UI:** a `for` over items, an `if` placeholder, events as `Msg`, a state slot and filter tabs;
- **build file:** an OS conditional and a loop over platforms;
- **test suite and HTML page:** 20 cases in nested groups, a runner that names the failing case's path, and escaping.

The examples showed:
- **D2 died on ADR-0006 amendment 1:** no positional items after labels.
- **D3's chains grew +28% under labels.** A forgotten leading `.` parses silently, and its corpus turned out to be
  illegal: a generic `children_of`, and a field and a method sharing a name.
- **The review found D1's corpus unsound.**
  - Library types (`Msg` in a library `Button`, `ui.slot`) can't be typed without type parameters. They are now
    declared in `lib/*.names` in the stdlib dialect (`Node of Msg`).
  - About 8 `.copy()` calls were missing.
  - Clauses couldn't nest or bind.
  - The parser rewound, and went exponential when nested.
  - All of this is fixed in loop 2. Depth-18 nesting parses in 1 ms.
- **C1 is close in size:** 198 lines against D1's 204, but 6% more characters. The difference is where the tree is
  dynamic. In `view()`, C1 builds `kids` with nine `push` statements, a `for`, two `if`s and a `map`, so the order of
  statements, not the shape of the code, decides the order of children. D1 writes the same function as one
  `Column(kids: [ … ])` expression. In the static parts of `build`, C1 is as good or better.

## Decision

**Adopt D1, clause items.** The rules a programmer learns:

1. **Clauses.** Inside a `[ ]` list literal, an item may be a clause:
   - `if COND => ITEM`;
   - `if x = OPT => ITEM` (binds `x`);
   - `for PAT in ITER [if GUARD] => ITEM`.

   The ITEM may itself be a clause, so clauses nest and flatten. Clauses appear only directly inside list literals,
   never in call arguments.
2. **Desugaring (normative).** `[a, if c => b, for p in xs if g => e]` is exactly:
   ```
   var tmp: List of T = []
   tmp.push(item: a)
   if c { tmp.push(item: b) }
   for p in xs { if g { tmp.push(item: e) } }
   ```
   It runs left to right, evaluates each condition once, and evaluates an item only when it is included. `p` borrows
   each element, so storing a field read out of `p` needs `.copy()` (ADR-0001).
3. **List items are store sites,** typed from the expected element type (ADR-0005 rule 8). A `let` that names a subtree
   needs a type: `let rows: List of Node of Msg = [ … ]`.
4. **There is no `else` clause.** One item or the other is the if-expression `if c { a } else { b }`. Targeted errors
   catch `[if c { a }]` ("write `if c => a`") and `[if c => a else b]`.
5. **Children are labelled list fields:** `Column(gap: 8, kids: [ … ])`. Attributes are labelled fields with defaults
   (ADR-0005). There are no setter chains.
6. **DSL libraries.** UI, HTML, build and test libraries live in the stdlib or `extras`, written in the generic
   dialect. The application's message type fills `M` (`Node of M`), and state lives in handle slots
   (`ui.text_slot(name:, initial:)`). Events are `Msg` values, and `update(mut m, msg)` is the only writer. List
   children take an explicit `key:`. Test cases are `Case(name:, body: fn() fails)` with `try expect_eq(…)`, and the
   runner reports the path `Group / Group / case`.
7. **Tooling.**
   - The formatter breaks after a clause's `=>` when its condition contains a lambda.
   - A lint flags a `for` clause whose items lack `key:` in a UI tree, and trees deeper than about 6 constructor
     levels.

### Scores (`0007-research/scores.py`)

| Option | Read | Transp | Simple | General | Errors | Fit | Impl | Total |
|---|---|---|---|---|---|---|---|---|
| C1 baseline (built) | 2.5 | 5 | 5 | 3.5 | 4.5 | 4 | 5 | 82.5 |
| **D1, loop 2** | 4 | 4.5 | 4 | 4 | 4 | 4 | 4 | **82** |
| D3 (as corrected by the review) | 2 | 3.5 | 3 | 3 | 2 | 3 | 5 | 60 |
| D2 | ineligible (ADR-0006 amendment 1) | | | | | | | |

**The scores tie (a gap of 0.5).** With readability at 10 and implementation risk at 20, C1 leads 87.5 to 82. PROCESS
breaks ties with the examples, and they favour D1:
- the layout benchmark is exactly where C1 stops looking like the tree;
- G11 asks for *good* declarative layout, and C1 is what the research classes as "no DSL support" (Zig, Odin);
- the clause form is about 60 parser lines with no runtime support.

**Traded away: reversibility.** C1 is the more reversible choice, because clauses could be added later without
breaking programs, while removing them later would break programs. This is recorded as the main cost. If M-phase UI
code shows clauses unused or confusing, a later ADR can deprecate them, with the formatter rewriting them to the
desugaring.

## Consequences

**Easier:**
- UI trees, HTML, build files and test suites are single expressions with the data's shape.
- A test runner gets case paths from the data tree, without annotations.
- Field typos are checker errors in user terms.

**Harder:**
- `=>` has three meanings: lambdas, match arms and clauses.
- A list item starting with `if` needs the condition parsed before the parser knows the form; it is parsed once, with
  no rewinding.
- Subtree `let`s need type annotations.
- Every UI string read from the model needs `.copy()`.

**Ruled out:**
- result builders;
- receiver lambdas;
- trailing blocks;
- variadic children;
- setter-chain DSLs;
- map and set literals for now (conditional maps use lists of tuples).

**Passed on:**
- **D8:** lowering clauses with the desugaring; per-frame allocation (an arena is not yet in any ADR).
- **D10:**
  - the UI library's scope (`Node of M`, slots, keys);
  - the test runner;
  - HTML escaping by default (`Text` escapes, `Raw` doesn't);
  - the generic-dialect signatures in `docs/examples/dsl/lib/`.
- **D11:** `lang test` finds suites without annotations: a `pub fn spec()` by convention, decided there.
- **M2:** store-site typing of list items; the copy checks inside clauses.

## Syntax budget impact

| Item | Count |
|---|---|
| Keywords | none (reuses `if`, `for`, `in`, `=>`) |
| Grammar | one production: the list item may be a clause |
| Operators | none |

7 rules.

## Adversarial review log

| Review | Findings | Outcome |
|---|---|---|
| `0007-research/review-d1.md` (Fable 5.2) | F1 library types untypeable (fatal); F2 baseline never built; F3 ownership in clauses; F4 element type; F5 no nesting or binding; F6 `else` errors; F7 exponential rewind; F8 D3 illegal; F9 thin benchmarks; F10–F14 minor | All adopted in loop 2. C1 built and scored; tie broken by examples and G11, with reversibility recorded as the trade-off. |
