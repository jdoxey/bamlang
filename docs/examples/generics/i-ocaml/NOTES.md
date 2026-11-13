# Option I in OCaml 5.3 (HM inference, no annotations anywhere)

PASS: `./run.sh` matches expected.txt; `ocamlopt -o build/prog main.ml` with no flags, no warnings (Domain +
Mutex/Condition from Stdlib). main.ml 175 lines (LRU logic ~20 lines; the two per-use state records 8 lines).

## Inferred signatures (`ocamlopt -i`)
    val touch   : 'a list ref -> 'a -> unit
    val lru_get : 'a list ref -> ('a, 'b) Hashtbl.t -> 'a -> 'b option
    val lru_put : int -> 'a list ref -> ('a, 'b) Hashtbl.t -> 'a -> 'b -> 'a option
Readable: they show shape (order list, table, key, value, evicted key). They do NOT show the capability: `'a`
silently needs structural equality/hashing (body uses `<>` and Hashtbl). Same weakness as Go's "must read body".

## Deliberate mistake: `put_q "q" (pf "x" "y")` (Profile into query cache)
    File "main.ml", line 127, characters 12-24:
    Error: This expression has type "profile" but an expression was expected of type "int list"
Points at the user's call argument, in concrete types the user wrote (profile, int list). No type-variable names.
Better than Go's "does not match inferred type []int for V". Cause: put_q's types were fixed by earlier use.

## Capability inferred from the body: closure as key
`touch` uses polymorphic `<>`; `lru_put 3 order vals f 1` with `f = fun x -> x+1` COMPILES. At run time:
`Fatal error: exception Invalid_argument("compare: functional value")` (when the second closure key is compared).
A lone `Hashtbl.replace h (fun x -> x+1) 1` compiles AND runs ("done"), no error. So capabilities are NOT inferred
from the body: equality/hashing are universal and fail late (or never). A run-time hole that Go's `comparable`
(compile time) closes. For option I, the language needs its own inferred "Eq/Hash" constraint, which HM does not give.

## What was easier / harder than Go
- Easier: no `[K comparable, V any]` anywhere; the generic fns take the parts of a record (`list ref`, `Hashtbl.t`).
  The built-in parameterised types (Hashtbl.t, option, ref, Queue.t) let the per-use records stay concrete with no
  user-declared `'a t`. Same shape as the Go version, 3 call args spread at every use site.
- Easier: option/Some/None/Option.bind built in; no Optional struct; pattern matching on it.
- Harder: record labels must be unique (e_name, p_name, u_name); a shared `name` label resolves to the last record
  and breaks unannotated inference. Under option I this is a real cost (or needs type-directed disambiguation).
- Could not write: methods on the shared LRU state (`cache.get k`), or a user `'a lru` record; same limit as Go version.
  An unannotated polymorphic `make_chan` is fine, but the value restriction would block a polymorphic global channel.

Run-time vs compile-time: type mistakes all compile time; run-time only: functional values under `compare`/`=`/Hashtbl (above).

## vs Go-generics version of option I
Go: explicit-but-hidden `[K comparable, V any]` plus compile-time capability checks; OCaml: truly nothing written,
better error text, but no capability checking. Line count 175 vs 215 (Go also carries builtins.go, 86 more).
