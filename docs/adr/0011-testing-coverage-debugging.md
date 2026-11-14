# ADR-0011: Testing, coverage and debugger tooling

- **Status:** Accepted
- **Date:** 2026-11-14
- **Tier:** Light (see `docs/PROCESS.md`)
- **Decided by:** Claude (ruling R7). John may veto by opening an issue.

## Context

G8, G9 and G10 ask for debugging, coverage and unit testing tools. The mechanisms exist already: test suites as data
(0007), `expect_trap` (0004), debug info and the llvm-cov remap (0008), and the commands (0009). This ADR fixes the
user-facing tools; they are cheap to change, so it is Light.

## Decision

1. **Discovery.**
   - A test file is `name_test.p3` next to the module it tests, and belongs to that module (ADR-0005 rule 12).
   - `lang test` calls each test file's `pub fn spec() -> Suite`, a tree of `Group(name:, kids:)` and
     `Case(name:, body: fn() fails)` built with ADR-0007 clauses.
   - No annotations or naming magic beyond the file suffix.
2. **Running.**
   - Each case runs as a crew child (ADR-0003), so a trap fails only that case. Cases run in parallel by default;
     `--serial` and `--only "Stack / push"` (a path prefix) are available.
   - A failure prints the path (`Stack / push many / len after 10`), the message and the location. Exit code 1 if any
     case fails.
3. **Locations without macros.** A parameter may default to `here`, a built-in `Location` value (file, line,
   function) evaluated at the caller: `fn expect_eq(actual: Int, expected: Int, at: Location = here) fails`. This is
   one built-in, not a macro, and user helpers may use it too.
4. **Assertions** (`std.test`):
   - `expect_eq`, `expect_true`, `expect_err(kind:)`, `expect_trap`;
   - `expect_matches_file(actual:, path:)` for golden files, with `lang test --update` rewriting them and showing the
     diff.
5. **Debug-only checks** (R4).
   - Test builds report leaks at exit, unjoined crews and lock-order cycles (ADR-0003).
   - `--asan` adds clang's address and undefined-behaviour sanitizers on Linux and macOS.
   - None of this ships in release builds.
6. **`lang cover`.**
   - Builds with coverage, runs `lang test`, and remaps llvm-cov to `.p3` lines (ADR-0008 rule 7).
   - Prints per-file and per-function line and branch percentages; writes `cover.lcov` and, with `--html`, a page.
   - `--min 80` fails below a threshold.
   - Counters are atomic in crew programs.
7. **`lang debug`.**
   - Builds without optimisation and starts gdb (Linux), lldb (macOS) or cdb (Windows) with the formatters loaded:
     - gdb: an embedded `.debug_gdb_scripts` section;
     - lldb: a generated `command script import`;
     - Visual Studio and cdb: natvis embedded in the PDB.
   - Formatters show values in source terms (ADR-0010 rule 7); `--vscode` writes a `launch.json`.
   - Traps and traces print the concrete class of `dyn` values and `self` (ADR-0005 amendment 1).
8. **`lang bench`** uses the same data shape (`Bench(name:, body:)`), reports nanoseconds per iteration, and is used
   by ADR-0010's quality bar.
9. **Out of v1:** fuzzing, mutation testing, mocks (a test uses a subclass or a closure field instead), and
   record-and-replay debugging.

## Consequences

One command each for testing, coverage and debugging, the same on three OSes; failures name the case path and line.
Costs: the `here` default is a small new rule, and formatters must track layouts. M7's exit test covers all of this.
