# ADR-0004 research notes (errors and absence)

URLs from memory of primary sources; not re-fetched this session.

| Language | Approach | Lesson |
|---|---|---|
| Java | checked + unchecked exceptions, null | Hoare's "billion dollar mistake" https://www.infoq.com/presentations/Null-References-The-Billion-Dollar-Mistake-Tony-Hoare/ ; checked exceptions widely abandoned in later languages. |
| C++ | exceptions, error codes, `std::optional` | Two or three conventions per codebase; exceptions disabled in many projects. |
| Go | `(value, error)` returns, `nil` | Explicit and readable, but `if err != nil` noise and nil pointers remain. https://go.dev/blog/error-handling-and-go |
| Rust | `Result`, `Option`, `?`, `panic!` | One mechanism, compiler enforces handling; `?` keeps code short. https://doc.rust-lang.org/book/ch09-00-error-handling.html |
| Swift | `throws` + `Optional` | Optional chaining is readable; `try` keyword marks call sites. https://docs.swift.org/swift-book/documentation/the-swift-programming-language/errorhandling/ |
| Zig | error unions `!T`, `try`, `catch`, `orelse` | Error sets are inferred; no hidden control flow. https://ziglang.org/documentation/master/#Errors |
| Python | exceptions, `None` | Any call can raise; failures are invisible in signatures. |
| Erlang | let it crash + `{ok,V}`/`{error,E}` | Separates bugs from expected failures. |

Lessons: (1) absence and failure are different and both need to be visible in the type; (2) exceptions hide control flow, against R6; (3) a short propagation operator removes Go's noise; (4) separate bugs (panic) from expected failures (Result).
