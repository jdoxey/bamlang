# ADR-0007: DSL and declarative layout

- **Status:** Accepted
- **Date:** 2026-11-13
- **Tier:** Full (research in `0007-research/notes.md`)
- **Decided by:** Claude (ruling R7). John may veto by opening an issue.

## Context

G11: good DSL / declarative layout support, with G3 forbidding macros and annotations. Q15: is G11 syntax-only for v1? Assumed yes (no GUI toolkit in v1); a toolkit built later must be expressible with what this ADR provides. ADR-0006 supplies named arguments, field defaults, trailing closures and copyable handle-only closures. ADR-0001 scenario (c): a UI callback holds a handle, not its owner.

## Charter

| Goal / problem | Effect | Why |
|---|---|---|
| G11 | serves | Nested block DSLs for trees, build files and tests, with static checking. |
| G3 | serves | One language feature, no macros, no annotations, no generics. |
| G1 | strains | Adds one concept: closures with a receiver. |
| G4 | serves | `column { text("a") }` has no builder boilerplate. |
| G7 | serves | Build files (D9) can be written in the language itself, as program 14. |
| G10 | serves | Test suites read as `test("x") { expect(...) }` (program 15). |
| P-SWIFT | avoids | No result builders, no opaque return types. |

## Criteria

Reads like the structure it describes (G11); no new meta-language (G3); statically checked names and types (P-C); one small feature (G1); works with ownership (ADR-0001); error messages point at the user's code.

## Options considered

1. **A. Plain values: constructors, named arguments, field defaults, list literals, trailing closures.** Zero new features. Flutter style.
2. **B. A plus closures with receiver (`fn with T`).** Kotlin style (chosen).
3. **C. Swift result builders / attributes.** Annotation; G3 fails.
4. **D. Macros.** G3 fails.
5. **E. Separate declarative file format** (QML-like or TOML-like). Second language.
6. **F. Dynamic dispatch on missing methods** (Ruby `method_missing`). Unchecked.
7. **Crazy G. XML-like literals in the language (JSX).** New grammar, lexical complications with `<`.
8. **Crazy H. Operator-built trees (`column / [a, b]`).** Cute; hard to read and to error-check.

| | G11 30 | G3 25 | G1 20 | Checked 15 | Impl 10 | Total |
|---|---|---|---|---|---|---|
| A | 3 | 5 | 5 | 5 | 5 | 80 |
| B | 5 | 5 | 4 | 5 | 4 | 93 |
| C | 5 | 1 | 2 | 3 | 2 | 60 |
| E | 4 | 5 | 1 | 4 | 2 | 66 |

B beats A by 13.

## What the real examples taught

`tests/conformance/13-dsl-tree.prog`, `14-dsl-build.prog`, `15-dsl-test.prog` (appended to the corpus; unparsed until M1).
- The three domains (UI tree, build file, test suite) each took one builder `type` with `mut fn`s and one receiver-closure parameter, with the same 6-line shape. A is enough only for the UI tree, and there it needs commas and nested list literals; for build files and tests it would force `Target(sources: [...], deps: [...])` with no behaviour in the middle.
- Bare-name lookup inside the closure (`text("Count")`) is just ADR-0005's implicit `self` applied to a closure.
- Nesting required the innermost-only rule: in program 13 the inner `column { text("nested") }` must call the inner receiver's `text`, never the outer one.
- No program needed state/reactivity to be a language feature. That belongs to a toolkit (Q15).

## Decision

Adopt **B**.

1. **Closure type with receiver:** `fn with T` (optionally with parameters: `fn with T (Int) Int`). A closure literal passed where such a type is expected receives a `mut` borrow of a `T` as its implicit first argument, and inside its body `T`'s fields and methods are visible by bare name, exactly as in a method of `T` (ADR-0005). The body can also use `self` for the receiver.
2. **Calling:** `content(inner)` passes the receiver explicitly as the first argument. The receiver borrow lasts for the call and cannot be stored (ADR-0001 rule 2); the closure itself cannot escape the call that receives it.
3. **Scope rule:** only the innermost receiver's members are implicitly in scope. To reach an outer receiver, name it (`let outer = self` before the nested call). Locals and ordinary functions remain visible.
4. **Name resolution order inside a receiver closure:** local, then receiver member, then module-level function. A clash between a receiver member and a local is a compile error (same no-shadowing rule as ADR-0006).
5. **Non-receiver closures** are unchanged. A callback stored in a structure stays `fn(...)` and holds handles (ADR-0001).
6. **No state or reactivity** in the language for v1 (Q15 resolved: G11 is syntax and static structure only). A toolkit may implement state as pool slots and handles (ADR-0001 scenario c).
7. Trees are plain owned values, so a DSL block can be built, inspected, copied and tested like any data.

## Consequences

- Easier: build files, test suites and view trees share one mechanism; errors are ordinary type errors.
- Harder: the receiver type must be named at each builder site; no implicit children collection (the receiver's methods do it); IDE support must know the innermost receiver.
- Rules out: macros, attribute-driven builders, implicit statement collection.
- Re-open if: a real toolkit needs a collected-statements form that `items.add` inside the receiver cannot express.

## Syntax budget impact

One new reserved word, `with`, only inside `fn with T` types. Amends ADR-0006's reserved-word list (22 -> 23).
