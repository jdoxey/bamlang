# Roadmap

Work top to bottom. Tick an item when its ADR is Accepted or its milestone passes CI on all three OSes. Each decision follows `docs/PROCESS.md`.

## Phase 1: decisions

- [x] **D1 Memory model** (ADR-0001, Full). Accepted 2026-11-13: O9-S, owned values plus checked handles into pools.
- [x] **D2 Generics and containers** (Full). ADR-0002 Accepted 2026-11-13: a frozen built-in set, no user type parameters (pending issue #3).
- [x] **D3 Concurrency model** (Full). ADR-0003 Accepted 2026-11-13: scoped crews, owned channels, lock and blocking traps, no async.
- [x] **D4 Errors and absence** (Full). ADR-0004 Accepted 2026-11-13: `fails`/`try` over `Result` values, one `Error`, no null, traps caught only at crews and tests.
- [x] **D5 Types and OO** (Full). ADR-0005 Accepted 2026-11-13: methods in types with receiver modes, nominal `iface` + `dyn`, provided functions, no inheritance.
- [x] **D6 Core syntax** (Full). ADR-0006 Accepted 2026-11-13: newline-terminated, only brackets or a leading `.` continue; braces; `Name(field: v)`; corpus and parser in `docs/examples/syntax/p3/`.
- [x] **D7 DSL and declarative layout** (Full). ADR-0007 Accepted 2026-11-14: `if`/`for` clause items in list literals, one desugaring; DSL libraries in the stdlib dialect; examples in `docs/examples/dsl/`.
- [x] **D8 Compiler implementation** (Full). ADR-0008 Accepted 2026-11-14: Rust (no third-party crates) emitting C for clang; setjmp cleanup-stack traps; gdb/lldb/cdb proven in CI; coverage remapped to `.p3`. Spikes in `docs/examples/compiler/`.
- [x] **D9 Modules, build and dependencies** (Full). ADR-0009 Accepted 2026-11-14: path imports, MVS with the full build list in `project.toml`, `deps.sum` over git objects, no build scripts, C libraries as data, toolchain-only generic dialect; system clang interim. Prototypes in `docs/examples/build/deps/`.
- [x] **D10 Standard library v1 scope** (Light). ADR-0010 Accepted 2026-11-14: container primitive sets and quality bar, v1 `std` modules incl. time/calendar/net/json, 12 error kinds, `extras` (html, terminal ui, tz).
- [x] **D11 Testing, coverage and debugger tooling** (Light). ADR-0011 Accepted 2026-11-14: `name_test.p3` + `spec()` data suites run as crew children, `here` locations, golden files, `lang cover` (remapped llvm-cov), `lang debug` with formatters, `lang bench`.
- [ ] **D12 Language name and file extension** (Light). Propose 5; pick one; John can veto.

## Phase 2: build

After D8, write `docs/PLAN.md` with the detailed milestones. The outline:

- [ ] **M0** A conformance test harness, wired into the existing three-OS CI (`ci/run.sh`), which runs the D6 corpus. Conformance tests are append-only: never weaken one to make it pass.
- [ ] **M1** Lexer and parser for the whole D6 corpus.
- [ ] **M2** Type checker.
- [ ] **M3** Code generation: "hello world" runs on all three OSes.
- [ ] **M4** Memory model and containers. `chatsim` written in the language passes its script.
- [ ] **M5** Threads.
- [ ] **M6** Standard library v1.
- [ ] **M7** Build and dependency tool, test runner, coverage, debugger support.
