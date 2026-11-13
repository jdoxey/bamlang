# ADR-0002: Generics and containers

- **Status:** Proposed
- **Date:** 2026-11-13
- **Tier:** Full (see `docs/PROCESS.md`)
- **Examples:** `docs/examples/generics` (A+ in `aplus/`; rivals in `a-closed-set/`, `c-interfaces/`, `i-inferred/`, `i-ocaml/`)
- **Decided by:** Claude (ruling R7). John may veto by opening an issue. **Depends on issue #3** (G3 reading).

## Context

G3 says the language "must not have templated types, macros or annotations". G6 asks for a good standard library
with Lists, Arrays and Maps. ADR-0001 needs `Pool of T`, `Handle of T` and typed containers. Programs also need
generic algorithms (sort, min/max, group) and occasionally a reusable container of their own. Research in
`0002-research/research.md` found that every language without user generics shipped built-in generic containers
anyway. The pain shows up in user-written reusable code and in untyped escape hatches, which fail late.

## Charter

| Goal / problem | Effect | Why |
|---|---|---|
| G3 | serves, **if issue #3 is yes** | Users and libraries never declare type parameters, templates or generic functions. A fixed set of built-in types takes an element type, like Go's `[]T` before 2022. If #3 is no, this ADR and ADR-0001 reopen. |
| G1 (R6) | serves | No type-level language to read; every cost is visible. The rules added are listed below. |
| G6 | serves | A frozen v1 set of 17 container and concurrency shapes. |
| G7 | strains | Third-party libraries can't ship their own typed containers. They write element-free logic over `Id`, or sum types. |
| G11 | strains | Mixed widget kinds are a sum type of typed handles; extension is records of functions. |
| G4 | neutral | `List of Employee` reads as English. Ordering is a field list at the call site. |
| P-GO | risks | The pre-1.18 Go ceiling. Mitigated by a larger frozen set and the `Id` pattern. |
| P-SWIFT, P-CPP | avoids | No constraints, associated types, variance or templates. |
| P-RUST | risks | Exclusivity and `take` grow (rules 7–10 below), but there are no lifetimes. |

**Why the strains are acceptable:** every option that passes G3 strains G7. The alternatives fail worse: boxing fails
static safety (option C), and inference adds templated functions (option I).

## Criteria

From `0002-research/criteria.md`, written before the options:

| Criterion | Weight |
|---|---|
| Stdlib reach | 20 |
| Simplicity | 20 |
| Transparency (R6) | 15 |
| Static safety | 15 |
| Error messages | 10 |
| Implementation risk | 10 |
| Clean syntax | 5 |
| Performance | 5 |

## Options considered

Eleven ideas came from three lenses (historian, teacher, assumption-breaking); see `0002-research/ideas-*.md` and
`analysis.md`.
- **Ruled out before the examples:** tables or SQL as the core, compiler-synthesised algorithms, silent inference
  everywhere, and stamped source files (a macro language by another name).
- **The finalists, all sharing a base** of built-in types plus algorithms taking function values:
  1. **A, closed set plus decomposition.** User-written reusable logic works over element-free data.
  2. **C, interfaces plus a checked box** (`Item`, `as(T) -> Optional of T`).
  3. **I, inferred generic functions.** Hindley-Milner style, nothing written, no generic structs.

## What the real examples taught

See `0002-research/lessons-and-scores.md` and each folder's `NOTES.md`.
- **C** (Go `any`): putting a `Profile` into the query cache compiled. It read back as a **silent miss**, or panicked
  far from the put. This is the Java 1.4 lesson repeated.
- **I** (Go generics, then OCaml 5.3 with real inference):
  - Errors were good in OCaml ("has type profile but … int list").
  - Inference did **not** check capabilities: a closure as a cache key compiled, then failed with
    `compare: functional value`.
  - Reusable state wanted a generic struct, which G3 names.
- **A** (Go, no type parameters): every mistake was a compile error at the user's line. The LRU cost about 31 lines of
  near-copy glue per key/value pair. A forgotten `delete` silently returned another entry's value: raw slot ids.
- **A+** (C model honouring ADR-0001, plus pseudo-syntax, plus a Part 4 outside the stdlib):
  - The same mistake now takes a stale `else` or traps.
  - The trap tests show S1, S5, S6 and F3 caught.
  - An event bus with a user sum type, and mixed widget kinds, work without type parameters.

## Decision

**Adopt A+.** These are the rules a programmer learns, added to ADR-0001's six:

1. **A fixed set of built-in parameterised types, frozen for v1:**
   - containers: `List`, `Array` (fixed length), `Map`, `Set`, `SortedMap`, `Deque`, `Heap`, `Lru`;
   - values: `Optional`, `Result`, tuples;
   - identity: `Pool`, `Handle`, `Id`;
   - concurrency: `Mutex`, `Channel`, `Atomic`.

   Users instantiate them (`List of Employee`, `Map of Str to Int`). Nobody outside the stdlib declares a type
   parameter. A shape is added only if two real programs need it and decomposition costs more than 20 glue lines
   per use.
2. **Algorithms are built-in methods that take function values,** typed from the receiver: `sort_by`, `min_by`,
   `max_by`, `filter`, `map`, `group_by`, `find`, `fold`.
   - Closure parameter types are inferred at the call site only, never in signatures.
   - Value forms return copies; index or key forms (`min_index_by`) don't copy.
3. **No derived ordering.** Ordering is a field list or a function at the call site: `sort_by(.dept, .salary desc,
   .name)`.
   - Derived `equals`/`hash` exist only when every field supports them. Otherwise the use site gets an error naming
     the field (Float, closure or `Mutex`).
   - Floats offer `total_order`.
4. **Untyped `Id`** for element-free reusable logic.
   - `pool.id(h)` erases the type, and `pool.handle(id)` restores it.
   - A stale `Id` takes `else`. A foreign `Id` traps.
   - `pool[id]` traps when stale.
   - Pool ids are 64-bit and never reused. Generations retire on wrap.
5. **User sum types** (enums with payloads) with exhaustive `match`. D4 and D5 refine them.
   - Heterogeneous collections are a sum type of typed handles, taught first.
   - Records of functions are the extension pattern.
6. **Places and block borrows.**
   - `m[k]` is a place, borrowed for one operation, with its arguments evaluated first.
   - `m[k] = v` inserts. Compound updates or field writes on a missing key trap. `m.entry(k, make)` upserts.
   - `if x = c.get(k) { … } else { … }` and `with x = c[k] { … }` work on every container and `Optional`. They
     borrow the whole container for the block. A Copy-typed binding copies.
   - Every container keeps a run-time borrow count, and structural mutation while it is borrowed traps.
7. **`take` parameters.** A parameter that moves out of the caller is marked `take`, including in function types
   (`fn(take Event)`) and as `take self`. Built-in `push`, `insert` and `send` take.
8. **Closures.**
   - A closure escapes exactly when it is passed to a `take` parameter, returned or assigned. Then it captures by
     move or copy, and a captured Copy variable it mutates counts as moved.
   - A closure that doesn't escape acts as a nested function and borrows its captures per call, under exclusivity
     and the overlapping-argument check.
   - Stored closures share state by owning it, by holding an `Id` into a pool passed as an argument, or through
     module-level state.

**Third-party libraries can't ship typed containers.** JSON or ORM mapping is written per struct until D10 decides a
derived encode/decode to a built-in `Value`.

### Scores (`0002-research/review-aplus.md`; cells after both reviews)

| Option | Reach | Simp | Transp | Safety | Errors | Impl | Syntax | Perf | Total |
|---|---|---|---|---|---|---|---|---|---|
| A+ (fixes adopted) | 2 | 3.5 | 4 | 5 | 5 | 3.5 | 4 | 4 | **74** |
| I (same memory rules) | 4 | 2.5 | 3 | 5 | 3 | 2.5 | 5 | 4 | 70 |
| C | 4 | 3 | 2 | 2 | 2 | 4 | 3 | 2 | 57 |

**This is a tie under PROCESS (a 4-point gap), after two loops.**
- **Broken by the examples:** A+ is the only option whose example honours ADR-0001. I needs generic structs (named by
  G3) and capability inference. C fails silently.
- **Reversibility:** adding inferred generic functions later would extend A+ without breaking programs. Removing
  them after shipping I would break programs. PROCESS asks for the most reversible option after two loops.

## Consequences

**Easier:**
- Signatures always say what they hold.
- Errors name the user's types at the user's line.
- No instantiation traces.
- A small compiler: no type-variable inference across signatures.

**Harder:**
- Reusable user containers are element-free logic plus glue (about 30 lines per use).
- Library authors can't publish typed containers.
- 17 built-in shapes, each with compiler-known borrow behaviour.
- Rules 6–8 add borrow-checker-like reasoning (P-RUST risk).

**Ruled out:**
- User type parameters, constraints, variance and templates.
- Untyped `any` boxes.
- Derived ordering.

**Changes to ADR-0001 (refinements, not reversals):**
- `take` parameters.
- Non-escaping closures borrow.
- Block borrows on every container.
- Container borrow counts.

**Passed on:**
- D4: `Result` and `Optional` details, and trap vs error.
- D5: sum types and methods, and `take self`.
- D6: spellings of `of`, `take`, `with` and `match`.
- D10: derived encode/decode and the stdlib API.
- M4: the conformance tests take the A+ trap cases.

## Syntax budget impact

| Item | Count |
|---|---|
| Keywords | `of` (type application), `take`, `enum`, `match` (D4/D5 may share them) |
| Operators | `.field` shorthand in field lists, `desc` |
| Grammar | type application `T of U` and `K to V`; field-list arguments |

Rules to remember: ADR-0001's 6, plus 8 here.

## Adversarial review log

| Review | Findings | Outcome |
|---|---|---|
| `0002-research/review-a.md` (option A) | F1 G3 reading; F2 example in a GC language; F3 raw slot ids; F4 ceiling; F5 closure capture; F6 copies; F7 the closed set; F8 derived ordering; F9 benchmark; F10 per-field exclusivity; F11 hidden costs | F1 asked as issue #3; all others adopted as A+ (`a-plus.md`) |
| A+ example notes | `take`, Ids/Table window, block borrows, literals, closure state | Decided in `a-plus.md` |
| `0002-research/review-aplus.md` (A+) | S1–S7, M1–M4; review-a's arithmetic wrong | All adopted; scores corrected; recorded as a tie broken by examples and reversibility |
