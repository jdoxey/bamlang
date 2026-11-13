# Second, focused review of A+ (Opus reviewer, 2026-11-13; condensed)

**Verdict: accept with listed changes.**
- **Example stale:** `aplus.txt` still used the dropped `Ids`/`Table`.
- **Arithmetic:** review-a's totals were wrong (A 74, not 77; 77 with Safety 5, not 80).
- **Rescore:** A+ as specified 71, fixed 74; I 70. That is a **tie**. The tie-break by the examples favours A+: its
  example is the only one that honours ADR-0001, and I needs generic structs.

| # | Severity | Finding | Decision |
|---|---|---|---|
| S1 | serious (fatal if unspecified) | `with first = log[0] { note("b") }`, where `note` pushes to a module-level `log`: push reallocates under a borrow, and no local check sees it | **Adopt.** Every built-in container keeps a run-time borrow count. Structural mutation (push, insert, remove, rehash) while it is non-zero traps in debug and release. |
| S2 | serious | Local helper closures `get_p` and `put_p` both capture `pc`, so the second is a use-after-move | **Adopt.** A closure that never escapes acts as a nested function: it reaches its captures at each call, with exclusivity checked per call. |
| S3 | serious | "A direct call argument doesn't outlive the call" is false for `subscribe(fn …)` | **Adopt.** A closure escapes exactly when it is passed to a `take` parameter, returned or assigned. `take` is part of function types. |
| S4 | serious | Two stored closures, `inc` and `get`, share a copied `n`, so `get` is always 0 | **Adopt.** A captured Copy variable mutated by an escaping closure is treated as moved: a later read or a second capture is a use-after-move error. This replaces the "reads later" rule. Document the module-level asymmetry. |
| S5 | serious | A foreign `Id` taking `else` is option C's silent miss | **Adopt.** A foreign Id always traps; only staleness takes `else`. Teach a sum type of typed handles first; `Id` is for element-free logic. Pool ids are 64-bit, allocated atomically, and never reused. |
| S6 | serious | `m[k].push(m[j].pop())`: the place is computed before the argument mutates the map | **Adopt.** Arguments are evaluated before the receiver place (two-phase), and the place is borrowed only for the operation. |
| S7 | serious | `with x = m[k] { m.remove(k) }` | **Adopt.** A block borrow of a Map or List element borrows the whole container (a static error inside the block, the S1 trap across calls). A block binding of a Copy type copies, so its borrow ends at once. The hint says "copy it out first". |
| M1 | minor | `counts[w] += 1` trapping in a word count | **Adopt.** `m[k] = v` inserts; compound updates and field writes on a missing key trap; `entry` upserts. |
| M2 | minor | What `take` covers | **Adopt.** `take` means "moves out of the caller". Built-in `push`, `insert` and `send` take. Consuming methods use `take self`. |
| M3 | minor | `f(n, fn -> n += 1)` | **Adopt.** Captures of non-escaping closures join the overlapping-argument check. |
| M4 | minor | The LRU shape under the untyped Id | **Adopt.** `Lru` holds `order: List of Id`; the cache is a `Pool of Entry{key, val}`. |

The reviewer's rule count is about 11 core rules plus 6 conventions. G1 is still plausible because every rule is
concrete and visible at run time, but the P-RUST risk rises. Option I would need the same memory-model rules plus
inferred type variables and inferred Eq/Hash constraints.
