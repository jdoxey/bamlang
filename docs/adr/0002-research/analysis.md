# D2 analysis of the 11 ideas (Opus coordinator; separate from the inventors)

Inventors: historian (H1–H4), teacher (T1–T3), crazy (X1–X4). That makes 7 sane and 4 crazy.

## What every idea agrees on: the base layer "B"

1. **A closed set of built-in parameterised types:** `List of T`, `Map of K to V`, `Pool of T`, `Handle of T`,
   `Optional of T`, `Mutex of T`, `Channel of T`. Users instantiate them; nobody declares a type parameter.
2. **Built-in algorithms are methods that take function values,** typed from the receiver (H1, T1–T3, X4's kernel).
3. **Derived `compare`, `equals` and `hash`** for plain data, and ordering by a field list,
   `sort_by(.dept, .salary desc, .name)` (X2, X3, T1 kernels). Inferred, so not an annotation.
4. **Closure parameter types inferred at the call site only** (X4's kernel). No inference across signatures.

So the real decision is test 2: how a **user** writes something reusable across element types.

## Ruled out before the examples

| Idea | Reason |
|---|---|
| X2 shape synthesis, H4/X3 tables as the core | A mini-language of special forms that grows without bound; hidden expansion (R6). H4's ordering-by-column kernel is already in B. |
| X4 silent inference everywhere | Signatures stop saying what they accept; errors become instantiation traces. Fails the criteria's Simplicity and Error-message rows by construction. |
| X1 stamped source as the main mechanism | A macro system by another name (G3's intent). Kept as a possible *tool* fallback. |
| T3/H2 as the *only* answer | Same mechanism (a boxed `Item`). Carried into the examples as option C to measure its cost, not ruled out. |

## Top three, to be written as real code (step 3)

- **A: "Closed set + decomposition"** (H1 + T1 + T2).
  - B, plus a stdlib that ships the common reusable shapes (`Lru`, `Set`, `Queue`, `Heap`).
  - User-written reusable logic is written over element-free data: `Int` slot ids or `Handle`s, with the typed storage
    held in a built-in container (T2).
  - No new language feature.
- **C: "Interfaces + checked box"** (B + H2/T3).
  - User-declared structural interfaces and an `Item` box with `as(T) -> Optional of T`, for user-written containers.
- **I: "Inferred generic functions"** (B + H3).
  - User functions without parameter types are inferred polymorphic and specialised per call type.
  - Struct fields stay concrete.
  - Tests G3's boundary.

The combination no inventor listed: **A with handles as the universal "element-free" currency.** ADR-0001 already
makes identity a `Handle`, so a user's generic structure (an LRU order, a graph, a priority list) can be written over
handles of *one* pool chosen by the caller... except a `Handle of T` names T. The A example will show whether `Int` slot
ids are enough.

## Modelling languages

- **A:** Go with no type parameters (Go 1.17 style).
- **C:** Go with `any` and checked type assertions.
- **I:** Go generics, with every type parameter commented "inferred, not written by the user". OCaml would be closer,
  but it isn't installed (see Blocked).

Go runs on all three CI images.
