# ADR-0005 research notes (types and OO)

URLs from memory of primary sources; not re-fetched this session.

| Language | Approach | Lesson |
|---|---|---|
| Python | classes, explicit `self` first parameter | P-PY: the explicit `self` is the complaint. https://docs.python.org/3/tutorial/classes.html |
| Go | structs, methods declared outside with a receiver, structural interfaces, embedding, no inheritance | Structural interfaces are light; receiver syntax is odd; embedding reuses without a hierarchy. https://go.dev/ref/spec#Interface_types |
| Rust | structs, `impl` blocks, traits (nominal), enums, no inheritance | Enums + match carry most design weight; traits plus generics are the learning cliff (P-RUST). |
| Swift | classes with inheritance, structs, protocols, extensions | Too many kinds of type (P-SWIFT): class, struct, enum, actor, protocol, extension. |
| Java | single inheritance classes, interfaces | Deep hierarchies; "favor composition over inheritance" (Effective Java, item 18 in 2e). |
| Kotlin | classes final by default, interfaces with defaults, data classes | Closed-by-default inheritance reduced abuse. https://kotlinlang.org/docs/classes.html |
| Zig | structs with methods (first param by convention), tagged unions, no interfaces | Minimal; dynamic dispatch hand-built with vtables. |
| Odin | structs, procedure groups, no methods | Data-oriented; no OO (P-C complaint). |

Lessons: (1) implicit `self` and methods inside the type body answer P-PY; (2) inheritance is the main source of complexity and hierarchy problems; (3) structural interfaces avoid declaring conformance; (4) tagged enums with `match` cover most "one of several shapes" needs; (5) fewer kinds of type is better (P-SWIFT).
