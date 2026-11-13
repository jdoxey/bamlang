# D2 ideas, crazy lens (Sonnet inventor; condensed; unscored)

Each idea breaks one assumption. Code in the original was illustrative only.

**X1 Stamped Source** (breaks "reuse happens inside the language").
- **Mechanism:** a tool, `lang stamp file --swap UserKey=SessionId …`, writes a checked-in copy of a concrete module with
  a provenance header. CI fails if the origin changed and the copy is stale.
- **Fit:** the compiler only ever sees concrete code, so the ADR-0001 checkers stay local.
- **Flaw:** it is a macro system with a build step, which is G3's intent violated, and the number of copies explodes.
- **Kernel:** a visible, diffable copy with a staleness check is an honest fallback for the rare user-written container.

**X2 Shape Synthesis** (breaks "generic code is written by the user").
- **Mechanism:** a closed catalogue of algorithm families. You describe what you want and the compiler synthesises the
  code (`employees ordered by dept, salary desc, name`; `cache of K to V capacity 100 evict lru`).
- **Flaw:** a language of special forms (P-SWIFT), and the expansion is hidden (R6). A user-written LRU is impossible.
- **Kernel:** ordering described by a field list (a derived `compare`) removes most comparator code. A stdlib cache
  covers most hand-written ones.

**X3 Everything Is a Table** (breaks "a container holds one element type").
- **Mechanism:** one keyed relation type. List, Map and Pool are views of it, and algorithms are relational
  operators that take field names.
- **Flaw:** column-name structural typing is row polymorphism, a type-level language by another name. Query results
  must materialise as copies, because views would be stored borrows. Trees and graphs are awkward.
- **Kernel:** algorithms that take field names (`order(dept, salary desc)`, `group(dept)`); Pool and Map
  explained as one keyed-collection idea.

**X4 Silent Inference** (breaks "a function has one type").
- **Mechanism:** parameters may omit types, and each call site gets its own specialised copy, Crystal- or C++-`auto`-style.
- **G3:** literally compliant, but against its intent.
- **Flaw:** signatures no longer say what a function accepts, and errors become instantiation traces. It also breaks
  ADR-0001's function-local move check, which would have to run after specialisation.
- **Kernel:** infer lambda parameter types and element types *inside* bodies and at call sites, never across
  signatures.

**Cross-cutting:** the hard case is the user-written generic container (the LRU). Visible expansion passes R6; hidden
expansion fails it. All four ideas still need a closed set of built-in parameterised types underneath.
