# Adversarial review of D2 option A (Opus reviewer, 2026-11-13; condensed)

**Verdict.** A still wins, but narrowly. Corrected scores: A 77, I 73, C 57. That is a tie under the 5-point
rule, broken towards A because I adds templated *functions* and needs generic structs for reusable state, which G3
forbids by name. A must not be Accepted in its current form.

## Findings

| # | Severity | Finding | Fix proposed |
|---|---|---|---|
| F1 | serious | criteria.md ruled on G3's meaning in its own favour. `List of T` *is* a templated type; the stdlib would be written in a privileged generic dialect | `needs-john` yes/no question; carry on |
| F2 | serious | The A example ran in Go, which has a GC and aliasing, so ADR-0001's moves, copies, borrows and drops are invisible and A's costs are understated | Redo A in a model that honours ADR-0001 |
| F3 | serious | "Element-free over `Int` slots" brings back raw indices: forgetting `delete(slots, old)` returns the *wrong* value silently (ABA) | Built-in untyped, generation-checked `Id` and `Ids`, plus `Table of T` |
| F4 | serious | G7 libraries and G11 toolkits hit the ceiling: JSON/ORM glue per field, mixed widget kinds, event buses, `Result` | User sum types; records of functions as the extension pattern; derived encode/decode to a `Value` tree; say plainly that libraries can't ship typed containers |
| F5 | serious | Closures capture by move or copy (ADR-0001), so `sort_by(fn a b -> { n += 1 … })` leaves `n` at 0 | Non-escaping closure arguments may capture by borrow, with exclusivity checked |
| F6 | serious | `m.get(k)` returns a copy, so a hand-built group_by is O(n²); `min_by` deep-copies | `m[k]` place expression; `entry`; `with`; index-returning algorithms |
| F7 | serious | About 18 shapes needed for 90% of programs, each compiler-known or written in a privileged dialect | Freeze the v1 set; state the dialect; a criterion for adding a shape |
| F8 | serious/minor | Derived `compare` makes field order a hidden annotation; NaN breaks derived equals/hash; handles and closures have no meaningful order | No derived `compare`; derived `equals`/`hash` only where well-defined; `Float.total_order` |
| F9 | minor | The benchmark tests a container A's stdlib already ships (Lru) | Add a case outside the stdlib (mixed widget kinds, an event bus) |
| F10 | minor | Is exclusivity per field? If not, decomposition doesn't compile | State per-field exclusivity |
| F11 | minor | Stored closures box their captures; `sort_by` either specialises per closure or calls indirectly | State both costs; Transparency 4 |

## Corrected scores

| Option | Reach | Simp | Transp | Safety | Errors | Impl | Syntax | Perf | Total |
|---|---|---|---|---|---|---|---|---|---|
| A | 2 | 4 | 4 | 4 | 5 | 4 | 4 | 4 | 74 (originally misstated as 77) |
| I | 4 | 3 | 3 | 5 | 3 | 3 | 5 | 4 | 73 |
| C | 4 | 3 | 2 | 2 | 2 | 4 | 3 | 2 | 57 |

With `Id` (F3) and the derived-operation rules (F8), A's Safety returns to 5, giving A 77 (originally misstated as 80), a 4-point lead: still a tie.
