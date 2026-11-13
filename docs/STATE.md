# State

## For John (kept to 10 lines)

- **Now:** D7 (DSL), resumed. Issue #4 done: ADR-0006 amendment 1, every argument is `name: value` (with `f(count)` as shorthand for `count: count`); cost +8% of code. If you'd rather have `print("hi")` than `print(text: "hi")`, say so on an issue: that fallback (one-parameter calls unlabelled) is ready.
- **Decided:** ADR-0001 memory, 0002 containers, 0003 crews, 0004 errors, 0005 types, 0006 syntax (newline-terminated, braces, `Name(field: v)`; parser and corpus in `docs/examples/syntax/p3/`). Veto by opening an issue.
- **Needs you:** nothing. Issue #3 answered (yes); your mitigations are in ADR-0002.

## Next action

**D7 loop 2** (review `0007-research/review-d1.md`): `docs/examples/dsl/lib/` declares the UI, build, HTML and test libraries in the stdlib generic dialect. D1's grammar is fixed (nesting, `if x = opt =>`, no rewind); the D1 corpus is rewritten with copies, 20 test cases and escaping; the C1 baseline (no new syntax) is built. Then rescore D1 vs C1 by script and write ADR-0007 (a tie goes to D1 on G11 unless C1 reads as well).


Roadmap item **D7** (ADR-0007, Full). Inputs:
- G11 and Q15: is G11 syntax only, or a UI framework in v1? Earlier ADRs assumed syntax only for v1. Decide.
- ADR-0006 left trailing closures open (they collide with `if f(x) {`); its review's UI sample (nested `Name(children: [...])`) had a `]), ])` staircase.
- ADR-0005: `pub` fields with defaults, named arguments, `iface` + `dyn`, the Widget enum with `Ext`. ADR-0001's DSL constraint: state is framework-owned and addressed by handles; callbacks capture handles.

1. Step 1: research (SwiftUI result builders, Kotlin type-safe builders and Compose, Flutter, Elm/HTML DSLs, QML, Jetpack, Gradle Kotlin DSL, Ruby blocks, Lua tables), with what went wrong (G3: annotations and macros).
2. Step 2: criteria first, then 6 sane and 4 crazy ideas, plus combinations.
3. Step 3: extend the P3 parser (copy it to `docs/examples/dsl/<option>/`) for each finalist's DSL form, and write a UI layout, a build file and an HTML or test DSL in each. Parse them in CI, and run one end to end through a small interpreter or C model if the option needs runtime support.
4. Step 4: an Opus reviewer attacks the winner; scores by script; decide; ADR under 300 lines.

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
- 2026-11-13: ADR-0006 Accepted (P3 after review; three real parsers checked against one shared AST).
- 2026-11-13: ADR-0005 Accepted (T3+ after review and a loop-2 example).
- 2026-11-13: ADR-0004 Accepted (merged E1 spelling over E2 values after one review loop). Issue #3 answered yes by John and closed.
- 2026-11-13: ADR-0003 Accepted (a tie broken by the examples and reversibility after one review loop).
- 2026-11-13: ADR-0002 Accepted after two review loops (a tie broken by the examples and reversibility). OCaml added to CI on Linux and macOS.
- 2026-11-13: chatsim in C, Swift (O1), Rust (O4) and C (O9); widgets under O9-S. Opus review found a fatal hole in O9, fixed as O9-S. ADR-0001 Accepted. Issues #1 and #2 handled and closed.
