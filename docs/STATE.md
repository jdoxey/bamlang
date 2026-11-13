# State

## For John (kept to 10 lines)

- **Now:** D5, types and OO (methods with implicit `self`, interfaces, inheritance).
- **Decided:** ADR-0001 memory (owned values, moves, checked handles into pools), ADR-0002 containers (built-in `List of T` etc.; no user type parameters), ADR-0003 concurrency (scoped `crew` threads, no async), ADR-0004 errors (`fails`/`try` over `Result`, one `Error`, no null). Veto by opening an issue.
- **Needs you:** nothing. Issue #3 answered (yes); your mitigations are in ADR-0002.

## Next action

Roadmap item **D5** (ADR-0005, Full). Inputs:
- Charter P-PY ("passing self makes OO weird") and P-C ("no native OO support").
- ADR-0001: owned values, pools and handles; methods on pool entries (implicit `self` is the borrowed entry); `take self`.
- ADR-0002: user sum types with `match`, records of functions as the extension pattern, no user type parameters, derived `equals`/`hash`.
- ADR-0004: `fails` methods.
- Decide: methods and implicit `self`; interfaces (structural? nominal? dispatch cost and transparency); inheritance or not; constructors and visibility; enums and structs.

1. Step 1: research (Go interfaces, Rust traits, Swift protocols, Java/Kotlin classes, Odin/Zig no-OO, Python self, C++ virtual, Objective-C), with what went wrong.
2. Step 2: criteria first, then 6 sane and 4 crazy ideas, plus combinations.
3. Step 3: write the top 3 as real code on a shapes/plugins/UI-widget benchmark, with `run.sh` on all three OSes. Model each design, not its host language (PROCESS lesson).
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
- 2026-11-13: ADR-0004 Accepted (merged E1 spelling over E2 values after one review loop). Issue #3 answered yes by John and closed.
- 2026-11-13: ADR-0003 Accepted (a tie broken by the examples and reversibility after one review loop).
- 2026-11-13: ADR-0002 Accepted after two review loops (a tie broken by the examples and reversibility). OCaml added to CI on Linux and macOS.
- 2026-11-13: chatsim in C, Swift (O1), Rust (O4) and C (O9); widgets under O9-S. Opus review found a fatal hole in O9, fixed as O9-S. ADR-0001 Accepted. Issues #1 and #2 handled and closed.
