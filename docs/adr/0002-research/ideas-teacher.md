# D2 ideas, teacher-of-beginners lens (Sonnet inventor; condensed; unscored)

## Shared base for all three

- **Built-in types:** a closed family (`List of T`, `Map of K to V`, `Pool of T`, `Handle of T`, `Mutex of T`,
  `Channel of T`, `Optional of T`).
- **Element types:** inferred from the receiver, so no `of` appears at call sites.
- **Algorithms:** methods that take function values.
- **Field shorthand:** `.field` means `fn x -> x.field`.
- **Derived operations:** `compare`, `equals` and `hash` are derived field by field.

The beginner test: `emps.sort_by(.dept, .salary desc, .name)` can be read and predicted, while a declared `K` can't.

## Options

**T1 Batteries, not blueprints.**
- **Mechanism:** the stdlib ships the shapes people reuse (`Cache of K to V` (LRU), `Set`, `Queue`, `Deque`,
  `Counter`). Users instantiate them but never write their own reusable containers.
- **Fit:** the best fit for ADR-0001, since every method has known borrow behaviour. Errors are in user terms.
- **Risk:** the stdlib becomes the ceiling (Go 2009–2022). Test 2 ("written once in user code") is met only by
  vendor fiat.

**T2 Split the logic from the type.**
- **Mechanism:** an LRU is ordering bookkeeping over `Int` slot ids (written once, a user struct `Recency`) plus storage
  in a built-in `Map`. A five-line wrapper per use, or an `ordered_by = Recency` hook that calls `touch` and `evict`
  structurally.
- **Fit:** strong; only `Int`s are tracked.
- **Risk:** it is a pattern, not a feature. Forgetting `touch` gives a silently wrong eviction order. The hook is
  close to an interface.

**T3 Plain value box with a checked view.**
- **Mechanism:** one built-in `Item` type tags any value. `item.as(T)` returns `Optional of T`. A user-written
  `LruCache` holds `Item`s.
- **Precedent:** Go `interface{}`, Swift `Any`.
- **Risk:** it fails the Java 1.4 lesson. A wrong-type put shows up only as a cache that never hits. Boxing
  allocates, and drop dispatches through a tag table, which is hidden work (R6).

## Hazards noted

- A derived `compare` makes field order significant.
- `group_by` consuming its receiver needs a clear move error.
- `min_by` returns a copy, because borrows can't be returned.
