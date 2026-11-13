# Roadmap

Work top to bottom. Tick an item when its ADR is Accepted or its milestone passes CI on all three OSes. Each decision follows `docs/PROCESS.md`.

## Phase 1: decisions

- [x] **D1 Memory model** (ADR-0001, Full). Accepted: owned values + borrows + pool handles (O9+).
- [x] **D2 Generics and containers** (Full). Accepted: closed set of built-in parameterised types, no user generics (ADR-0002).
- [x] **D3 Concurrency model** (Full). Accepted: OS threads, moves, channels, mutex owning its data (ADR-0003).
- [x] **D4 Errors and absence** (Full). Accepted: no null, Optional/Result, `?`, panic for bugs (ADR-0004).
- [x] **D5 Types and OO** (Full). Accepted: `type` with methods and implicit `self`, `enum`, structural `interface`, no inheritance (ADR-0005).
- [x] **D6 Core syntax** (Full). Accepted (ADR-0006). Corpus in `tests/conformance/` (12 programs, unparsed until M1).
- [ ] **D7 DSL and declarative layout** (Full). The mechanism for G11 without macros or annotations.
- [ ] **D8 Compiler implementation** (Full). Host language, backend, debug info (G8) and coverage (G9) on all three OSes.
- [ ] **D9 Modules, build and dependencies** (Full). Dependencies are git repos (G7); lockfile and reproducibility.
- [ ] **D10 Standard library v1 scope** (Light). Lists, arrays, time, calendar and what else (G6).
- [ ] **D11 Testing, coverage and debugger tooling** (Light). G8–G10.
- [ ] **D12 Language name and file extension** (Light). Propose 5; pick one; John can veto.

## Phase 2: build

After D8, write `docs/PLAN.md` with the detailed milestones. The outline:

- [ ] **M0** CI on macOS, Windows and Linux. A conformance test harness that runs the D6 corpus. Conformance tests are append-only: never weaken one to make it pass.
- [ ] **M1** Lexer and parser for the whole D6 corpus.
- [ ] **M2** Type checker.
- [ ] **M3** Code generation: "hello world" runs on all three OSes.
- [ ] **M4** Memory model and containers. `chatsim` written in the language passes its script.
- [ ] **M5** Threads.
- [ ] **M6** Standard library v1.
- [ ] **M7** Build and dependency tool, test runner, coverage, debugger support.
