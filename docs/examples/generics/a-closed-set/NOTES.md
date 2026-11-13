# Option A: closed set + decomposition (Go, no type parameters in user code)

Files: main.go 272 lines (Part 1 ~45, Part 2 ~135, Part 3 ~55), builtins.go 86 lines.
builtins.go stands in for the language's built-in generic set (Optional, Filter, Map, GroupBy, MinBy, MaxBy,
SortedKeys); it is the only file with type parameters and is identical in all three options.

## Mechanism cost
- LRU core, written once over int slot ids (`lruOrder`): 25 non-blank lines.
- Per-use glue: 64 non-blank lines for two uses (about 32 each): a struct (slots map, key array, value array),
  a constructor, `Get`, `Put`. Each new key/value pair needs another ~32 lines, near copy-paste.
  The shared core only does recency; map lookup, key-forget-on-evict and value storage are re-written per use.
- No `any`, no casts, no wrappers around values.

## Run-time vs compile-time
- No type mistake in the LRU is a run-time error. All are compile-time.
- Only run-time risk: a glue bug (e.g. forgetting `delete(c.slots, old)` on evict) in one copy; the compiler
  cannot check that the copies agree with each other or with `lruOrder`.

## Deliberate mistake: `qc.Put("q", Profile{"x", "y"})` into the query cache
Compile error:
`./main.go:217:14: cannot use Profile{…} (value of struct type Profile) as []int value in argument to qc.Put`
It points at the user's own line.

## Hidden costs
- Duplication: the glue is copy-pasted per element type (the cost being measured).
- No boxing; one extra indirection (key -> slot -> value array). `touch` is O(n) in capacity (slice scan).
- Silent-bug surface: key array and slot map must stay in step by hand.
