# State

## For John

- **Phase:** Explore (`docs/EXPLORE.md`). The compiler and `tests/` are parked.
- **Next:** paste prompt 1 from `docs/EXPLORE.md` ("Consolidate").
- **Name:** bam, `.bam` (R16).

## Next action

Wait for John's prompt. Do only what it asks, then stop.

## Known problems the consolidation must fix

- **Too many rules.** ADR-0001 to ADR-0009 hold well over 100. The budget is 25 concepts (R19).
- **The parts disagree.** Amendment 1 of ADR-0005 removed `iface` and `impl`, but `tests/corpus/types.ltn`, `docs/PLAN.md` and ADR-0002 still use them. No example uses inheritance.
- **Whole-program and inferred checks** (ADR-0003 rules 4–5, ADR-0005 rule 9 and amendment rule 11) fail the 3 am test.
- **Many run-time traps** stand in for compile-time checks.
- **Subclassable built-ins** (R15) currently need "primitive sets" and a self-call-set diff tool. Look for something simpler.

## Environment

- This machine runs Debian 13. Installed: `build-essential`, `clang` 19, `llvm-dev` 19, `lld`, `lldb`, `gdb`, `valgrind`, `cmake`, `ninja`, `go`, `swiftlang` 6.0.3, `ocaml`, `rustc`/`cargo` 1.100, `jq`, `gh`. There is no `sudo` in the session. If a decision needs a missing tool (for example Zig or Kotlin), list it under Blocked with the exact install command and carry on with other work.
- CI runs `ci/run.sh` on `ubuntu-24.04`, `windows-2025` and `macos-26`. Keep all three green. Windows has MinGW gcc/g++ and Rust but no Swift; Swift examples skip there and say so.
- A hook pauses the session at 85% of the account's usage. A long pause before a tool call is that hook, not a fault.

## Blocked

Nothing. John allowed the SHA-pinned llvm-mingw download on Windows (R18); it matters again when the build resumes.

## Log

- 2026-11-14: John stopped the loop after all 12 decisions. A review found the language too large and inconsistent. Explore phase started; name changed to bam (R16).

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
