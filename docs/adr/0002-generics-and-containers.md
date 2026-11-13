# ADR-0002: Generics and containers

- **Status:** Accepted
- **Date:** 2026-11-13
- **Tier:** Full (research in `0002-research/notes.md`)
- **Decided by:** Claude (ruling R7). John may veto by opening an issue.

## Context

ADR-0001 needs typed `List`, `Map`, `Pool`, `Handle`, `Optional`, `Mutex`. G3 says the language "must not have templated types, macros or annotations". G6 wants a good standard library. This ADR answers charter problem P2: can built-in parameterised types exist, and can users write their own?

## Charter

| Goal / problem | Effect | Why |
|---|---|---|
| G1, R6 | serves | One kind of generic thing, all built in; no constraint language, no instantiation to reason about. |
| G3 | serves, with a reading | "Templated types" is read as *user-definable* parameterised types. Built-in `List of T` is a type constructor like an array type, not a template. This reading is the only one under which G6 is possible without `void *` (P-C), so it is recorded and John may veto. |
| G6 | strains | Users cannot write a `Stack of T` or `Cache of K,V`. The stdlib covers the common ones. |
| G4 | serves | `List of Name` is the whole syntax. |
| P-CPP | avoids | No templates. |
| P-GO | risks | Go lived 12 years with built-ins only and added generics late. We take the cheap half of Go's history on purpose. |

## Criteria

R6 transparency (no instantiation you cannot see); G1/G3 (fewest user-facing concepts); G6 (can the stdlib be good); type safety (P-C); implementation risk (the compiler is mostly agent-written, so monomorphisation and constraint solving are risk); reversibility (can generics be added later without breaking code).

## Options considered

1. **A. Built-in parameterised types only; no user generics.** Compiler knows `List of T` etc. Users write concrete types; polymorphism over behaviour comes from interfaces (D5).
2. **B. Full user generics** (Go/Rust-style type parameters with constraints). Fails G3's plain reading and adds constraints.
3. **C. Dynamic containers** (`List` of `Any`, checked casts). Simple, but moves type errors to run time and boxes everything (P-C safety, P-PY speed).
4. **D. Zig-style `comptime` type functions.** One mechanism but a second language at compile time; G1 strain, large implementation risk.
5. **E. Built-ins plus a fixed set of "kind" parameters users can opt into** (e.g. user container declares `of T`). This is B restricted; no principled stopping point.
6. **F. Code generation** (user tool stamps out `IntStack`, `NameStack`). Honest but a macro by another name (G3).
7. **Crazy G. Containers are only `Pool of T` and everything else is a library over pools.** Elegant, but `List` order and `Map` hashing are not pool concerns.
8. **Crazy H. Type erasure with compiler-inserted checks at the container boundary.** C with hidden work: fails R6.

| | Simplicity 25 | G3 25 | Stdlib 20 | Safety 15 | Impl 15 | Total |
|---|---|---|---|---|---|---|
| A | 5 | 4 | 3 | 5 | 5 | 88 |
| B | 2 | 1 | 5 | 5 | 2 | 56 |
| C | 4 | 4 | 3 | 1 | 4 | 66 |
| D | 2 | 2 | 5 | 5 | 1 | 53 |
| E | 3 | 2 | 4 | 5 | 3 | 63 |

A wins by more than 5 points. The score is not the real evidence, the corpus check below is.

## What the real examples taught

`docs/examples/chatsim/` uses, across all four programs, exactly: a list of members, a map from name to user, a queue of jobs, a queue of timers, a pool of users and rooms, a mutex, a channel. No program defined a generic type of its own. Under A every one is a built-in; the one thing that must be hand-written is the job queue wrapper, as `List of Job` with push/pop, which is 6 lines.

The cost shows in `list.sort_by(f)`, `map`, `filter`: they must be compiler-known methods on built-in types, not library functions users can imitate.

## Decision

Adopt **A**.

1. **Built-in parameterised types (closed set):** `List of T`, `Array of T` (fixed length), `Map of K,V`, `Set of T`, `Deque of T`, `Pool of T`, `Handle of T`, `Optional of T`, `Result of T,E` (D4 confirms), `Channel of T`, `Mutex of T`, function types. Users cannot declare a type or function with type parameters.
2. **Polymorphism over behaviour** is by interface (D5), not by type parameter. `sort_by`, `map`, `filter`, `fold`, `find` are built-in methods whose function arguments are checked against the element type.
3. **Constraints** are built in: `Map` keys must be hashable and comparable by value; this is inferred from the key type, not annotated.
4. **Reversibility:** the closed set can be extended by John-visible ADRs. User generics would be additive (new syntax, old code still valid); the chosen type syntax `X of T` leaves room for it. Re-open trigger: three stdlib or sample modules that duplicate a container for different element types.
5. **G3 reading** ("templated types" means user-definable) is recorded here and reported in STATE; John's veto reopens this ADR.

## Consequences

- Easier: one mental model, fast compiles, readable errors, no monomorphisation blow-up (still need per-type code for built-ins; the backend may specialise, not user-visible).
- Harder: no user `Stack of T`; duplicated wrapper types; third-party libraries (G7) cannot ship generic containers.
- Rules out: generic user functions such as `fn max(a: T, b: T)`; use interface parameters or write per type.

## Syntax budget impact

One type constructor form `Name of Type[, Type]` in type position. No new keywords beyond `of`. No angle brackets.
