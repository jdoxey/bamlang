# D2 ideas, historian lens (Sonnet inventor; condensed; unscored)

All four keep a closed set of compiler-known parameterised types (`List`, `Map`, `Pool`, `Handle`, `Mutex`,
`Channel`, `Optional`). They differ on how user code gets generality.

**H1 Go 1.0 done right: the closed set, with algorithms as methods that take function values.**
- **Mechanism:** `sort_by`, `min_by`, `max_by`, `map`, `filter`, `group_by`, `find` and `fold` are built-in methods.
  The element type comes from the receiver. `compare`, `equals` and `hash` are derived structurally. The stdlib
  ships `Lru`, `Set`, `Deque` and `Heap` as members of the closed set.
- **Can't write:** user generic functions or containers. Test 2 fails by design; you copy-paste.
- **Precedent:** Go 1.0–1.17. 88% of those missing a feature named generics; Go now has generics, and generic
  methods since 2026.
- **Risk:** the closed set keeps growing under demand.

**H2 Open interfaces, checked narrowing.**
- **Mechanism:** user-declared method-set interfaces, satisfied structurally. User containers hold `Item`, a tagged
  owned box. `x.as(T)` returns `Optional of T`. The built-in typed set stays.
- **Risk:** the Java 1.4 experience, softened. A wrong type shows up as a silent `none`. Boxing and dispatch are
  hidden costs (R6).

**H3 ML inference: polymorphism with nothing written.**
- **Mechanism:** user functions are inferred polymorphic (Hindley-Milner style) and specialised per type. Capabilities
  are inferred from the operators used. Struct fields stay concrete, so an LRU is generic *functions* over a
  per-use state struct.
- **Risk:** arguably G3's "templated" with the brackets removed. Errors land inside generic bodies, and signatures
  show no types (ML programmers write signatures anyway).

**H4 Row types as tables (SQL, APL).**
- **Mechanism:** every struct gets a companion table with relational operators by column name. Indexes and eviction
  are declared clauses. An LRU is a row struct plus `evict_by oldest tick`.
- **Risk:** the operator set is a mini-language that grows without bound (LINQ, pandas). A heavier concept than a list.

**Combinations they suggested:** H1 as the base for everything; H2 or H3 layered on for test 2; H4 as a stdlib feature
built on H1.
