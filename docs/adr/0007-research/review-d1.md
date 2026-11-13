# Adversarial review of D1 clause items (Fable 5.2 reviewer, 2026-11-14; condensed)

**Verdict:** the clause grammar is sound, but the corpus is not. Fix F1–F9 and loop back on the examples. The C1 baseline
was never built and may tie D1.

## Fatal

- **F1.** The corpus uses library types that can't be typed without type parameters (ADR-0002):
  - `Button(on_click: Msg.Toggle(…))` with a user `Msg`;
  - `ui.slot(initial: "")`;
  - test `Case.body: fn(s: Stack)`.

  **Coordinator's resolution:** ADR-0002's owner answer lets the stdlib and `extras` use the internal generic dialect
  (`Node of Msg`, `Slot of Str`). The UI and test libraries live there, and D10 designs them. The corpus must declare
  their signatures.
- **F2.** The baseline C1 (plain constructors plus `map` and `+`, or statements) was never built. On `view()` it is
  within 5–11% of D1's size, but mixed children don't type in the `+`/`map` form.
  - **Fix:** build `c1/` and score it.

## Serious

- **F3.** Ownership inside clauses is unspecified, and about 8 `.copy()` calls are missing (`Text(content: t.title)`).
  - **Fix:** make the desugaring normative: left to right, the condition evaluated once, `p` borrowed per iteration.
- **F4.** The list element type is unstated.
  - **Fix:** list items, including clause bodies, are store sites typed from the expected element type. `let` of a
    subtree needs an annotation.
- **F5.** Clauses don't nest or bind (`[if a => for x in xs => x]`, `[if u = m.user => …]`).
  - **Fix:** the body is an item, and `if x = opt =>` is allowed.
- **F6.** No `else` clause is needed: one-or-other is the if-expression.
  - **Fix:** targeted errors for `[if c { a }]` and `[if a => 1 else 2]`.
- **F7.** The parser rewinds, and it is exponential when nested (8.6 s at depth 18).
  - **Fix:** parse the condition once.
- **F8.** The D3 corpus breaks ADR-0002 rule 1 (`children_of` is generic) and ADR-0005 rule 7 (field `gap` and method
  `gap`).
  - **Fix:** drop the setter-chain kernel.
- **F9.** The benchmarks under-deliver: 9 cases, not 20; no runner naming the failing case; no HTML escaping; no
  compile-error demo.
  - **Fix:** use `fn() fails` bodies with `try expect…`, and a runner that names the path.

## Minor

- **F10.** `=>` has three meanings; the formatter breaks after a clause `=>` that contains a lambda.
- **F11.** Depth: hint on tree levels (about 6), not brackets.
- **F12.** Lint a missing `key:` in `for` clauses.
- **F13.** Numbers: the sensitivity gap is 13, not 17; +13.7% on the shared files.
- **F14.** Single-field leaves (`Th(text: h)`) are amendment 1's cost, and evidence for its F2 fallback.

## Reviewer's scores

| Option | Total | Readability 10 / implementation 20 |
|---|---|---|
| D1 with fixes | 78.5 | 79.5 |
| C1 baseline (estimate) | 82 | 88 |
| D1 as built | 70.5 | 71.5 |
| D3 | 60 | 66 |

The reviewer breaks the D1-versus-C1 tie for D1:
- G11 is a "must";
- only clauses type mixed children without annotations;
- D1 is about 39 parser lines.

Reversibility favours C1, because clauses can be added later.
