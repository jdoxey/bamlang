# ADR-0003 research notes (concurrency)

URLs from memory of primary sources; not re-fetched this session.

| Language | Model | Lesson |
|---|---|---|
| Go | goroutines + channels, shared memory allowed | Easy to start; data races still possible; "share memory by communicating" is advice, not enforced. https://go.dev/doc/effective_go#concurrency |
| Rust | threads, `Send`/`Sync` marker traits, `Mutex<T>` owns its data | Races are compile errors; the traits are a learning cost (P-RUST). https://doc.rust-lang.org/book/ch16-00-concurrency.html |
| Swift | actors, `Sendable`, structured concurrency | Retrofitted over years; many annotations (P-SWIFT). https://www.swift.org/migration/documentation/swift-6-concurrency-migration-guide/ |
| Erlang/Elixir | isolated processes, copy messages | Races impossible by construction; copying cost; no shared state without a process. https://www.erlang.org/doc/system/conc_prog.html |
| Pony | actors + reference capabilities | Safe and fast, but capability vocabulary is heavy. https://tutorial.ponylang.io/reference-capabilities/ |
| Python | threads + GIL, asyncio | Threads do not parallelise (P-PY); async colours functions. |
| JS/C#/Rust async | async/await | Function colouring, two worlds for every API. |
| Java | threads + `synchronized`, java.util.concurrent | Locks by convention, forgotten locks are silent. |

Lessons: (1) Rust's `Mutex` owning its data removes the forgotten-lock bug; (2) async/await splits APIs into two colours, bad for G1; (3) enforced isolation (Erlang) is simplest but needs copying; ADR-0001 already moves values, so moves are free here.
