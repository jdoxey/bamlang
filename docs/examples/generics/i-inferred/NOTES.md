# Option I: inferred generic functions (Go generics standing in for "no annotations")

Files: main.go 215 lines (Part 2 ~95), builtins.go 86 lines. Every type-parameter list carries the comment
`// inferred, not written by the user`.

## Type-parameter lists (each would be inferred in the real language)
- User code (main.go): 3 lists: `touch[K]`, `lruGet[K, V]`, `lruPut[K, V]`. 28 non-blank lines of LRU logic.
- builtins.go: 10 lists (Optional, Some, None, Then, Filter, Map, GroupBy, MinBy, MaxBy, SortedKeys),
  the built-in set, same as A and C.

## Deviation: option I as specified forbids generic structs (fields concrete)
- The LRU state is two concrete structs, `profileCache` and `queryCache` (11 lines, fields only, no methods).
  The generic functions take the state's PARTS (`&pc.order`, `pc.vals`, `pc.cap`) as arguments. This works only
  because the state is just a slice and a map; no methods can be shared, so call sites repeat the 3-argument
  spread. A real `LRU of K to V` struct would need a generic struct, which I forbids.
- Could not do: methods (`cache.Get(k)`) on the shared logic; any state that needs a field of an unknown type
  beyond built-in containers (e.g. a linked list of entries) cannot be expressed. The order list is O(n).
- Optional is a generic struct in builtins.go; this is the language's built-in, not a user declaration.

## Run-time vs compile-time
- Nothing is dynamic: all errors are compile time. No casts, no `any`, no per-use LRU logic.

## Deliberate mistake: `lruPut(qc.cap, &qc.order, qc.vals, "q", Profile{"x", "y"})`
Compile error:
`./main.go:160:42: in call to lruPut, type Profile of Profile{…} does not match inferred type []int for V`
It points at the user's call line and the offending argument (col 42), not inside the generic body. The wording
names "inferred type" and V, a name the user never wrote; in the real language the message would need to say
"query cache holds List of Int".

## Hidden costs
- Go compiles generics via GC-shape stenciling (dictionary passing): little code duplication, some indirection.
  A monomorphising language would duplicate code per instantiation (G3: the cost is hidden).
- Signatures do not say what they accept; the reader must infer `K` and `V` from the body.
