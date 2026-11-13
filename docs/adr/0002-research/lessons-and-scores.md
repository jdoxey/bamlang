# D2: what the `generics` examples taught, and scores

All three versions in `docs/examples/generics/` print identical output. `builtins.go` (86 lines, identical in each)
stands in for the built-in set (Optional, map, filter, group_by, min_by, max_by).

| | A closed set + decomposition | C interfaces + box | I inferred generic functions |
|---|---|---|---|
| `main.go` lines | 272 | 223 | 215 |
| LRU code | 25 shared + ~32 glue **per key/value pair** | 42, written once | 28 generic + 11 concrete state |
| Put a `Profile` into the query cache | **compile error at the user's line** | compiles; reads as a silent **miss** (or panics far from the put) | compile error at the call, but in terms of a `V` the user never wrote |
| Run-time type failures possible | none | 4 assertion sites | none |
| Hidden cost | none (one indirection) | boxing, dynamic hashing, assertion per access | per-type code (or dictionaries) not visible in source |
| What couldn't be written | a reusable LRU without per-use glue | a statically typed user container | a generic struct with methods; the state had to be spread into 3 arguments |

## What each taught

- **A** is the only option with nothing hidden and every mistake at compile time. Its cost is real but bounded: about
  32 lines of near-copy per new key/value pair, *only* for containers the stdlib doesn't ship. The copies can drift
  (forgetting `delete(slots, old)`), which is the silent-bug surface.
- **C** reproduced the Java 1.4 lesson exactly: the wrong type is stored without complaint, and the failure is a miss
  nowhere near the cause. That fails R6 ("safer than C") and the Static-safety criterion.
- **I** reads nicely and is safe. But a reusable container *wants* to be a struct, and banning generic structs
  forced the state into loose arguments. Allowing generic structs is plainly G3's "templated types". Its errors
  name invented type variables, and per-instance move checking would break ADR-0001's local checker.

## Scores (criteria.md weights: reach 20, simplicity 20, transparency 15, safety 15, errors 10, impl 10, syntax 5, perf 5)

| Option | Reach | Simp | Transp | Safety | Errors | Impl | Syntax | Perf | Total |
|---|---|---|---|---|---|---|---|---|---|
| A | 3 | 5 | 5 | 5 | 5 | 5 | 4 | 5 | **91** |
| I | 4 | 3 | 3 | 5 | 3 | 2 | 5 | 4 | 71 |
| C | 4 | 3 | 2 | 2 | 2 | 4 | 3 | 2 | 57 |

- **A's Reach is 3, not 5,** because the literal test 2 ("written once in user code") is met only for the shared
  recency core, not the whole cache.
- **A leads by 20.** Under the reach-heavy variant (reach 40, simplicity 10) the totals are A 84.5, I 73.6; A still leads
  by more than the 5-point tie line.
