# State

## For John (kept to 10 lines)

- **Now:** M0, the conformance test harness (all 12 decisions are made). The language is named **Lantern** (`.ltn`); veto by issue if you dislike it.
- **Decided:** ADR-0001 memory, 0002 containers, 0003 crews, 0004 errors, 0005 types, 0006 syntax (+ amendment 1: every argument `name: value`, your issue #4), 0007 DSLs (`[if c => x, for t in xs => Row(…)]`), 0008 compiler (Rust emitting C for clang; debuggers proven on all three OSes), 0009 dependencies (git paths, MVS, hashed, no build scripts), 0010 stdlib v1 scope, 0011 test/cover/debug tools, 0012 name: Lantern; ADR-0005 amended for inheritance (your issues #5, #6). Veto by opening an issue.
- **Needs you (optional yes/no):** may CI download a SHA-pinned llvm-mingw (182 MB) to test replacing the 6–7 GB VS Build Tools on Windows? I recommend yes.

## Next action

**M0** (see `docs/PLAN.md`): create the `compiler/` Cargo workspace (no third-party crates) with a `lantern-tests` harness; copy the `p3n` corpus, expected ASTs and bad files into `tests/` as `.ltn`; wire `cargo test` and the harness into `ci/run.sh` on three OSes with `--allow-missing` until M1. Exit: harness runs on Linux, Windows and macOS. Then M1 (parser, ported from `docs/examples/syntax/p3n/parser.py` plus the ADR-0007 clause and ADR-0005 amendment grammar).

## Open questions carried forward

- **Issue #3 (G3 reading):** answered yes by John. D9 must restrict the generic dialect to the stdlib and `extras`; D10 must set the container quality bar.
- **Q15:** closed by ADR-0007 (G11 is syntax; frameworks are libraries; D10 scopes the UI library).
- From ADR-0001: D3 must define channels, `Mutex of T` and the main-thread rule; D4 optional handles and traps; D5 methods on pool entries.

## Environment

- This machine runs Debian 13. Installed: `build-essential`, `clang` 19, `llvm-dev` 19, `lld`, `lldb`, `gdb`, `valgrind`, `cmake`, `ninja`, `go`, `swiftlang` 6.0.3, `ocaml`, `rustc`/`cargo` 1.100, `jq`, `gh`. There is no `sudo` in the session. If a decision needs a missing tool (for example Zig or Kotlin), list it under Blocked with the exact install command and carry on with other work.
- CI runs `ci/run.sh` on `ubuntu-24.04`, `windows-2025` and `macos-26`. Keep all three green. Windows has MinGW gcc/g++ and Rust but no Swift; Swift examples skip there and say so.
- A hook pauses the session at 85% of the account's usage. A long pause before a tool call is that hook, not a fault.

## Blocked

- **D9 toolchain spike (T2 llvm-mingw, T3 zig cc on Windows):** the session's permission check denied an agent that would download and run third-party toolchain binaries in CI. Not retried. T1 (system clang, already green on all three OSes in ADR-0008's CI) is the v1 default until John allows the downloads; see ADR-0009.

## Log

- 2026-11-14: D12 done (ADR-0012: Lantern, Light). Phase 1 decisions complete.

- 2026-11-14: D11 done (ADR-0011, Light).

- 2026-11-14: D10 done (ADR-0010, Light).

- 2026-11-14: issue #5 handled (ADR-0005 amendment 1: inheritance; issue #6 asked about abstract-only parents).

- 2026-11-14: D9 done (ADR-0009 Accepted after two loops; B1+ over B2+ on the major-break scenario).

- 2026-11-14: D8 done (ADR-0008 Accepted after two loops; K3 Rust to C won once cdb ran on Windows).

- 2026-11-14: issue #4 handled (ADR-0006 amendment 1); D7 done (ADR-0007 Accepted after two loops; C1 baseline tied, broken by the examples and G11).

- 2026-11-13: repo set up from the planning conversation.
- 2026-11-13: first run on Sonnet skipped the real-examples step. John reset `main`; that work is on the `sonnet-attempt` branch for reference only.
- 2026-11-13: ADR-0006 Accepted (P3 after review; three real parsers checked against one shared AST).
- 2026-11-13: ADR-0005 Accepted (T3+ after review and a loop-2 example).
- 2026-11-13: ADR-0004 Accepted (merged E1 spelling over E2 values after one review loop). Issue #3 answered yes by John and closed.
- 2026-11-13: ADR-0003 Accepted (a tie broken by the examples and reversibility after one review loop).
- 2026-11-13: ADR-0002 Accepted after two review loops (a tie broken by the examples and reversibility). OCaml added to CI on Linux and macOS.
- 2026-11-13: chatsim in C, Swift (O1), Rust (O4) and C (O9); widgets under O9-S. Opus review found a fatal hole in O9, fixed as O9-S. ADR-0001 Accepted. Issues #1 and #2 handled and closed.
