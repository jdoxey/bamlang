# State

## For John (kept to 10 lines)

- **Now:** D2, generics and containers (how `List`, `Map`, `Pool` exist under G3). Option A (fixed built-in containers, no user generics) leads after real code and a review; loop 2 (A+) being tested.
- **Decided:** ADR-0001 memory model, Accepted: owned values, moves, explicit `.copy()`, and checked handles into pools. No reference counting, no `weak`. Veto by opening an issue.
- **Needs you:** issue #3, a yes/no on whether G3 allows built-in `List of T`-style types. I'm carrying on assuming yes.

## Next action

Roadmap item **D2** (ADR-0002, Full). Step 1 research is in `docs/adr/0002-research/research.md`.

1. Step 2: write criteria (include R6 transparency), then ideas: at least 6 sane, 4 crazy, and combinations. ADR-0001 needs `Pool of T`, `Handle of T`, `List of T`, `Map of K to V`, `Mutex of T`, `Channel of T` and an optional type to exist.
2. Step 3: write the three test programs from the research (generic sort with a user comparator, an LRU cache used for two key/value pairs, an `Optional` pipeline) in the closest real languages for the top 3 options, as `docs/examples/generics/<option>/` with `run.sh`.
3. Step 4: separate Opus reviewer attacks the winner; score; decide; ADR under 300 lines.

Then continue down `docs/ROADMAP.md`.

## Open questions carried forward

- **P2, built-in parameterised types under G3:** decide in D2.
- **Q15, is G11 syntax only:** decide in D7. Until then, assume syntax only for v1.
- From ADR-0001: D3 must define channels, `Mutex of T` and the main-thread rule; D4 optional handles and traps; D5 methods on pool entries.

## Environment

- This machine runs Debian 13. Installed: `build-essential`, `clang` 19, `llvm-dev` 19, `lld`, `lldb`, `gdb`, `valgrind`, `cmake`, `ninja`, `go`, `swiftlang` 6.0.3, `ocaml`, `rustc`/`cargo` 1.100, `jq`, `gh`. There is no `sudo` in the session. If a decision needs a missing tool (for example Zig or Kotlin), list it under Blocked with the exact install command and carry on with other work.
- CI runs `ci/run.sh` on `ubuntu-24.04`, `windows-2025` and `macos-26`. Keep all three green. Windows has MinGW gcc/g++ and Rust but no Swift; Swift examples skip there and say so.
- A hook pauses the session at 85% of the account's usage. A long pause before a tool call is that hook, not a fault.

## Blocked

Nothing.

## Log

- 2026-11-13: repo set up from the planning conversation.
- 2026-11-13: first run on Sonnet skipped the real-examples step. John reset `main`; that work is on the `sonnet-attempt` branch for reference only.
- 2026-11-13: chatsim in C, Swift (O1), Rust (O4) and C (O9); widgets under O9-S. Opus review found a fatal hole in O9, fixed as O9-S. ADR-0001 Accepted. Issues #1 and #2 handled and closed.
