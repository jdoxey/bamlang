# ADR-0002 research notes (generics and containers)

URLs are from memory of well-known primary sources and were not re-fetched this session.

| Language | Approach | What went wrong / lesson |
|---|---|---|
| Go 1.0-1.17 | Built-in `slice`, `map`, `chan` are generic; users cannot write generics. Use `interface{}` + casts. | Ten years of `interface{}` containers and code generation; generics added in 1.18 after the longest-running request. https://go.dev/blog/why-generics |
| Go 1.18+ | Type parameters with constraints | Added syntax and a subtle `comparable`/constraint vocabulary. Same blog. |
| Java | Generics via erasure | Runtime type info lost; boxing of primitives; wildcard complexity (`? extends`). https://docs.oracle.com/javase/tutorial/java/generics/erasure.html |
| C++ | Templates | Compile-time blow-up, unreadable errors (P-CPP). Concepts added in C++20 to repair it. |
| Zig | `comptime` type parameters: types are values, generics are functions | One mechanism, but compile-time evaluation is a second language to learn. https://ziglang.org/documentation/master/#comptime |
| Odin | Parametric polymorphism `$T` | Compact, but still a generics system. https://odin-lang.org/docs/overview/#parametric-polymorphism |
| Hare | No generics, no macros; built-in slices, arrays | Containers are written per type or with `void *` style; deliberate simplicity. https://harelang.org |
| Pony / Oberon | Oberon: no generics at all; arrays and records only | Small language; users wrote per-type code. |
| C | `void *` containers | Unsafe (P-C). |

Lessons: (1) Go and Hare show a language can ship and be useful with only built-in generic containers; (2) Go's `interface{}` containers were the main complaint, so the dynamic escape hatch must not be the default; (3) every user-facing generics system adds a vocabulary that runs against G1 and G3.
