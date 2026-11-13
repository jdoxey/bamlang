# Option C: user container over `any` + checked narrowing (Go, no type parameters in user code)

Files: main.go 223 lines (Part 2 ~100), builtins.go 86 lines (stands in for the built-in generic set, as in A).

## Mechanism cost
- The LRU is written once, no per-use code: 42 non-blank lines (type, `touch`, `Get`, `Put`), holding `any`
  keys and values. Cheapest in code, but the type information is gone inside it.
- Type assertions: 4 in user code, all at the use sites: 2 on `Get` results (`v.(Profile)`, `v.([]int)`, checked
  with `v, ok :=`) and 2 on the evicted key (`old.(UserKey)`, `old.(string)`).
  Every use of the cache needs them; a third key/value pair adds 2 more.
- Keys are `any` as map keys: hashability is checked at run time (an unhashable key such as a slice panics).

## Where a wrong type surfaces (all run time, none at compile time)
- `Put(k, v)` accepts anything: a wrong key/value type compiles and is stored.
- It surfaces only at the narrowing: with the checked form `v, ok := x.(T)` the wrong value is reported as
  `ok == false`, which this program treats as a miss. So the mistake is SILENT.
- With the unchecked form `x.([]int)` it panics.
- Evicted key assertions: `old.(string)` with `, _` would silently give "".

## Deliberate mistake: `qc.Put("q", Profile{"x", "y"})` into the query cache
- Compile: succeeds, no diagnostic at all.
- Run, checked narrowing: prints `queries get q miss` (wrong-typed entry looks like a miss).
- Run, unchecked `v.([]int)`:
  `panic: interface conversion: interface {} is main.Profile, not []int`
  (the stack points at the assertion, not at the Put that stored the wrong value).

## Hidden costs
- Boxing: every key and value is converted to an interface (allocation for non-pointer values).
- Dynamic dispatch on map hashing/equality of `any` keys; type-assert cost per access.
- Error location is far from the cause (the Put).
