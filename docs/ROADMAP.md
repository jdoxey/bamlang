# Roadmap

Work top to bottom. Tick an item when its ADR is Accepted or its milestone passes CI on all three OSes. Each decision follows `docs/PROCESS.md`.

## Phase 1: decisions

- [x] **D1 Memory model** (ADR-0001, Full). Accepted 2026-11-13: O9-S, owned values plus checked handles into pools.
- [ ] **D2 Generics and containers** (Full). How typed `List`/`Map` exist under G3. Is memory safety a stated goal?
- [ ] **D3 Concurrency model** (Full). Threads are in v1 (R1). What crosses threads, and how is shared state guarded?
- [ ] **D4 Errors and absence** (Full). Exceptions, results or error values. Whether anything can be null.
- [ ] **D5 Types and OO** (Full). Methods with implicit `self`, interfaces, and whether inheritance exists.
- [ ] **D6 Core syntax** (Full). Statement endings without semicolons or indentation rules (G5), blocks, declarations, naming. Produce a corpus of example programs that become the syntax tests.
- [ ] **D7 DSL and declarative layout** (Full). The mechanism for G11 without macros or annotations.
- [ ] **D8 Compiler implementation** (Full). Host language, backend, debug info (G8) and coverage (G9) on all three OSes.
- [ ] **D9 Modules, build and dependencies** (Full). Dependencies are git repos (G7); lockfile and reproducibility.
- [ ] **D10 Standard library v1 scope** (Light). Lists, arrays, time, calendar and what else (G6).
- [ ] **D11 Testing, coverage and debugger tooling** (Light). G8–G10.
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
