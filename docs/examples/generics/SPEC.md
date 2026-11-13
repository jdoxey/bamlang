# `generics`: the benchmark for D2 (containers and generic algorithms)

One program with three parts. No input; it prints a fixed report. Every option's version must print identical
output (`expected.txt`).

## Part 1: algorithms over a user struct

`Employee { name, dept, salary }`, eight employees (fixed list in the source, including two with equal dept and
salary so the name tie-break matters).
- Sort by dept ascending, salary descending, name ascending; print them.
- `min_by` salary and `max_by` salary (print name and salary).
- `group_by` dept into a map; print each dept (sorted) with its member count and total salary.
- `filter` salary > 50000 then `map` to names; print the list.

## Part 2: a user-written LRU cache, reused for two key/value pairs

The LRU logic (get, put, evict least-recently-used at capacity) is written **once in user code**, then used for:
- `UserKey { tenant: Int, id: Int }` → `Profile { name, email }`, capacity 2;
- `String` → `List of Int` (a query cache), capacity 3.
Run a fixed sequence of puts and gets on each that forces at least two evictions and one hit that changes
eviction order. Print every hit, miss and eviction.

## Part 3: an `Optional` pipeline across a thread

- `find_user(id) -> Optional of User` (users 1 and 2 exist; 3 doesn't).
- Map that to `Optional of Address` (user 2 has no address, so `none`).
- Send each result through a channel to a worker thread, which prints "addr for N: ..." or "addr for N: none".
  Make the output order deterministic.

## What to record in each option's NOTES.md

- Line counts. Lines that exist only because of the mechanism (casts, wrappers, copy-pasted logic).
- Every place a type mistake would be caught at run time instead of compile time.
- The error message for one deliberate mistake: put a `Profile` into the query cache. Paste the exact compiler or
  run-time text.
- Hidden costs (boxing, dispatch, code duplication).
