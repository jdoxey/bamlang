# State

## For John (kept to 10 lines)

- **Now:** D6, core syntax (statement endings without semicolons or indentation, blocks, declarations, naming) and the example corpus that becomes the syntax tests.
- **Decided:** ADR-0001 memory, ADR-0002 containers, ADR-0003 concurrency (crews), ADR-0004 errors (`fails`/`try`, no null), ADR-0005 types (methods, `iface` + `dyn`, no inheritance). Veto by opening an issue.
- **Needs you:** nothing. Issue #3 answered (yes); your mitigations are in ADR-0002.

## Next action

Roadmap item **D6** (ADR-0006, Full). Inputs:
- G4 (clean, non-verbose) and G5 (no significant whitespace, no mandatory semicolons).
- Every ADR's "Syntax budget impact" section lists keywords and grammar to spell: `of`, `take`, `with`, `lock`, `crew`, `fails`, `try … or e`, `context`, `iface`, `impl`, `dyn`, `pub`, `is`, `match`, `enum`, receiver modes, field lists `.dept desc`, `if x = …`, named arguments with defaults (ADR-0005).
- The pseudo-syntax files written so far are the raw material: `docs/examples/widgets/o9s.txt`, `generics/aplus/aplus.txt`, `threads/f1-crew/crew.txt`, `errors/merged/errors.txt`, `types/t3plus/types.txt`.

1. Step 1: research how Go, Kotlin, Swift, Scala 3, Lua, Ruby, JavaScript (ASI) and Odin end statements without semicolons and without indentation, and what went wrong (ASI hazards, line continuation).
2. Step 2: criteria first, then 6 sane and 4 crazy syntax options, plus combinations.
3. Step 3: write the same corpus (at least chatsim, widgets and errors) in the top 3 syntaxes. Build a real parser for each finalist (for example a small recursive-descent parser in Python or Rust in `docs/examples/syntax/<option>/`) that parses the whole corpus in CI on three OSes. This is the "real code" for a syntax decision.
4. Step 4: an Opus reviewer attacks the winner; scores by script; decide; ADR under 300 lines. The winning corpus becomes `tests/corpus/` for M0.

## Open questions carried forward

- **Issue #3 (G3 reading):** answered yes by John. D9 must restrict the generic dialect to the stdlib and `extras`; D10 must set the container quality bar.
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
- 2026-11-13: ADR-0005 Accepted (T3+ after review and a loop-2 example).
- 2026-11-13: ADR-0004 Accepted (merged E1 spelling over E2 values after one review loop). Issue #3 answered yes by John and closed.
- 2026-11-13: ADR-0003 Accepted (a tie broken by the examples and reversibility after one review loop).
- 2026-11-13: ADR-0002 Accepted after two review loops (a tie broken by the examples and reversibility). OCaml added to CI on Linux and macOS.
- 2026-11-13: chatsim in C, Swift (O1), Rust (O4) and C (O9); widgets under O9-S. Opus review found a fatal hole in O9, fixed as O9-S. ADR-0001 Accepted. Issues #1 and #2 handled and closed.
