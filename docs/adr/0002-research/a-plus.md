# A+: option A with the review's fixes (loop 2), and my decisions

| Finding | Decision |
|---|---|
| F1 G3 reading | Asked John (issue #3), recommending yes. Work continues on yes. |
| F3 raw slot ids | **Adopt.** A built-in untyped `Id` (index, generation, issuer id) is issued by `Ids`. `Table of T` stores values by `Id`. A stale `Id` takes `else` or traps, exactly as handles do. `Pool of T` is `Ids` plus `Table of T` in one, and `Handle of T` is an `Id` known to belong to it. User element-free logic is written over `Id`. |
| F4 ceiling | **Adopt sum types:** user enums with payloads (not templated), with exhaustive `match` (D4 and D5 detail them). **Adopt records of functions** (a struct whose fields are function values) as the documented extension pattern. **Defer** derived encode/decode to `Value` to D10. **State plainly:** third-party libraries can't ship typed containers. |
| F5 closure capture | **Adopt, extending ADR-0001:** a closure written directly as a call argument doesn't outlive the call, so it captures by borrow (shared, or mutable under exclusivity). Stored or escaping closures capture by move or copy. |
| F6 copies in nested containers | **Adopt.** `m[k]` is a place, borrowed for one statement (`m[k].push(e)`), and traps if missing. `m.entry(k, make)` inserts if missing. `with l = m[k] { … }`. Algorithms have index or key forms (`min_index_by`); value forms return copies, and the name `min_by` says so in its docs. |
| F7 closed set | **Freeze v1:** `List`, `Array` (fixed length), `Map`, `Set`, `SortedMap`, `Deque`, `Heap`, `Lru`, `Optional`, `Result`, tuples, `Pool`, `Handle`, `Id` (untyped handle, see gap 2 below), `Mutex`, `Channel`, `Atomic`. A new shape is added only if two real programs need it and decomposition over `Id` costs more than 20 glue lines per use. The stdlib's internal dialect is named in issue #3. |
| F8 derived operations | **Adopt.** There is no derived ordering. Ordering is always a field list or a function at the call site. Derived `equals`/`hash` exist only when every field supports them. A Float, closure or `Mutex` field gives a compile error at the use site that names the field. Floats offer `total_order`. |
| F10 exclusivity | **Per field** (disjoint named paths), as ADR-0001 rule 4 says for named paths. |
| F11 hidden costs | **State them:** stored closures heap-allocate their captures; built-in algorithms call the function value indirectly unless the optimiser inlines it. |
| F2, F9 | The loop-2 example: the generics benchmark in a C model honouring ADR-0001, plus a Part 4 outside the stdlib. |

## Decisions on the gaps the A+ example found (`docs/examples/generics/aplus/NOTES.md`)

1. **Consuming parameters.** A parameter the function stores is declared `take` in the signature, so the caller can
   read the move from the signature (R6). It isn't inferred from the body, because callers' compile results would then
   change when the body changes. This is one keyword (D6 picks the spelling). It refines ADR-0001 rule 3.
2. **`Ids` and `Table` are dropped,** because a `Table` separate from its issuer has a reuse window. Instead, `Id` is an
   **untyped handle**:
   - `pool.id(h)` erases the type;
   - `pool.handle(id)` gives back `Handle of T`, checking pool id and generation (stale or foreign takes `else`);
   - `pool[id]` traps.

   Element-free user logic is written over `Id`s, and typed storage stays in `Pool`. A full cache reissues a slot with
   `remove` plus `add`. There are fewer concepts than in the review's proposal.
3. **Block borrows** (`if x = c.get(k) { … }`, `with x = c[k] { … }`) apply to every built-in container and to
   `Optional`. The borrow lasts the block, under exclusivity. This extends ADR-0001 rule 5's pool form.
4. **String literals** are fresh owned values. **Partial moves** out of an owned local are allowed, and the rest drops
   at once. D4 and D6 give the detail.
5. **Stored closures share state in one of three documented ways:** they own it, they hold an `Id` into a pool that is
   passed as an argument, or they use module-level (main-thread) state.
   - A stored closure that mutates a captured copy which the enclosing scope reads later is a **compile error**, which
     catches the "`n` stays 0" trap.
