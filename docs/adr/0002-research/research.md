# D2 research: typed containers without user-defined generics

Gathered by a Sonnet research agent, 2026-11-13, by web search and fetch. **[unverified]** marks claims the agent
could not source in-session.

## Case studies

**Go before 1.18.**
- **Mechanism:** built-in slice, map and chan were the only typed containers. Everything else used `interface{}`
  plus type assertions, `sort.Interface` method sets, or `go generate`.
- **Motivation for generics:** duplicated per-type code and type assertions
  (https://go.googlesource.com/proposal/+/master/design/go2draft-generics-overview.md).
- **The interface route's limits:** it needs interface values, which aren't always efficient, and method signatures
  must use specific types (https://go.googlesource.com/proposal/+/master/design/15292-generics.md).
- **Evidence of pain:** generics were "one of the most commonly requested" features from 2009
  (https://go.dev/blog/generics-proposal). In the 2020 survey, 88% of those missing a feature named generics
  (https://go.dev/blog/survey2020-results).
- **Restricted generics kept growing:** generic methods arrive in 2026 (https://go.dev/blog/generic-methods).
- **Lesson:** the built-ins were generic all along. The pain is the gap between built-ins and user code, mostly
  generic *algorithms*.

**Java 1.4 raw collections.**
- **Failure:** casts on the way out fail at run time, far from the bad insert
  (https://docs.oracle.com/javase/1.5.0/docs/guide/language/generics.html).
- **After the retrofit:** erasure kept raw types alive.

**C.**
- **Mechanism:** `void*` or macro-instantiated containers.
- **Failures in stb stretchy_buffer:** no type safety, macro arguments evaluated more than once, relocation, no bounds
  checks (https://sources.debian.org/src/libstb/0.0%7Egit20200713.b42009b+ds-1/stretchy_buffer.h/).
- **Lesson:** type safety in C costs macros, which G3 bans. klib works the same way **[unverified]**.

**Zig comptime.**
- **Mechanism:** a type parameter is an ordinary function argument.
- **Failure:** no declared constraints, and template-like errors
  (https://ziggit.dev/t/discussion-a-potential-solution-to-the-anytype-problem/16259).
- **Fit:** the most powerful option and the worst fit for G3.

**Odin.**
- **Mechanism:** `$T` parameters stamp a copy per type. Constraints are `where` clauses calling compiler intrinsics
  (https://odin-lang.org/docs/overview).
- **Fit:** small and readable, but still user-written type parameters.

**Hare.**
- **Mechanism:** no generics by design and no stdlib data structures; users write their own hash table
  (https://harelang.org/documentation/faq.html, https://harelang.org/blog/2021-03-26-high-level-data-structures/).
- **Criticism:** a hash table is "not a simple data structure", and the consequences "are dire"
  (https://ayende.com/blog/197185-B/criticizing-hare-language-approach-for-generic-data-structures).
- **Fit:** conflicts with G6.

**C3 generic modules.**
- **Mechanism:** `module m <Type>` parameterises a whole module. Contracts are checked only when invoked
  (https://c3-lang.org/generic-programming/generics/).

**Lua.**
- **Mechanism:** one dynamic table type.
- **Failure:** `#` is ill-defined with holes and changed between 5.4 and 5.5
  (https://groups.google.com/g/lua-l/c/pOH68GYtDgw).

**Objective-C lightweight generics.**
- **Mechanism:** advisory, erased, and mismatches are mostly warnings
  (https://useyourloaf.com/blog/using-objective-c-lightweight-generics/).
- **Lesson:** advisory typing is worse than none.

**Swift.**
- **Failure:** associated types and existentials confused users, and `any` became mandatory in 5.7
  (https://forums.swift.org/t/se-0309-unlock-existential-types-for-all-protocols/47515?page=3).
- **Lesson:** generics accrete. This is P-SWIFT. Kotlin variance has the same problem **[unverified]**.

## Cross-cutting findings

1. Every language without generics shipped built-in generic containers anyway.
2. The recurring demand is generic *algorithms* (sort, map/filter, min/max), more than containers.
3. Untyped escape hatches (`interface{}`, `Object`, `void*`, `id`) fail late and far from the cause.
4. Advisory typing creates false confidence.
5. No built-ins at all gives Hare's outcome: weaker per-program copies.
6. Restricted generics grow over time (Go).

## Options that respect G3 literally (from the research; the ideas step adds more)

- **A.** Closed set of built-in parameterised types (`List of T`, `Map of K to V`, `Pool of T`, `Optional of T`,
  `Channel of T`, `Mutex of T`). Users instantiate them but never declare type parameters.
- **B.** A, plus interface (dynamic-dispatch) generic algorithms.
- **C.** One implicit element type per module (type holes). This is a type parameter in disguise.
- **D.** Structural capabilities (compare, equals, hash) derived for user structs, accepted by built-in algorithms.
- **E.** Code generation as a build step. This is a macro language by another name.
- **F.** Built-in container methods taking function values (`sort_by`, `map`, `filter`). The element type is inferred
  from the receiver.

The researcher's opinion: A + D + F is the strongest literal reading.

## Test programs for D2

1. Sort `List of Employee` by (dept, salary descending, name), then `min_by`, `max_by` and `group_by` into
   `Map of K to List of V`.
2. An LRU cache keyed by a user struct, written once in user code and used for two different key/value pairs.
3. `find_user(id)` returning `Optional of User`, mapped to `Optional of Address`, with an error path, sent through
   `Channel of Optional of Address`.
