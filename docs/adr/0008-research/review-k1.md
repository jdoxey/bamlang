# Adversarial review of K1 (Fable 5.2 reviewer, 2026-11-14; condensed)

**Verdict:** K1 remains the direction, but the ADR is not to be Accepted until F1–F4 have evidence in CI. The corrected
scores are a three-way tie: K3 78.5, K1 75, K2 73.5.

## Holds up

- Drops run on normal exit, early return and in loops.
- Nested `expect_trap` works.
- Zero-cost unwinding works on three OSes (CI 43448112789).
- LLVM coverage through textual IR works: clang lowers `llvm.instrprof.increment` plus covmap globals when given
  `-fprofile-instr-generate -fcoverage-mapping`, and `llvm-cov` shows lines and branches.

## Fatal

- **F1. A trap inside a drop during unwinding skips the remaining drops** in K1 and K2. The cleanup pad calls the drop
  with a plain `call`, so `outer guard` is never dropped and the first message is lost (ADR-0004 rule 8). K3 is
  correct here.
  - **Fix:** drops called from cleanup pads go through a shim that catches, appends to the chain and returns.
- **F2. The G8 gate is not met on Windows by any option:** `lldb.exe` failed to load its shared libraries, and there is
  no `cdb`. K1 never asserts the `spike.p3` line records.
- **F3. Threads and crews are unproven.**
  - `g_msg` is not thread-local.
  - A C++ exception can't cross threads, so the child needs a catch-all plus a re-raise after the join.
  - An uncaught trap prints `terminate called…` with no trace and loses buffered stdout.

## Serious

- **S1. A `DW_TAG_variant_part` enum** shows in gdb, but lldb shows `{}` and CodeView has an empty field list. Enums
  need a tag plus union encoding and formatters in three formats, as with K3.
- **S2. By-value structs in LLVM IR don't follow the C ABI.** A C call printed `x=3 y=0`. The frontend owns per-target
  ABI classification.
  - **Fix:** generated C shims for FFI, and a C runtime.
- **S3. Each runner's LLVM version is unknown.** "17+" is untested, Apple clang is a fork, macOS needs `xcrun
  llvm-cov`, and the IR has no target triple or datalayout.
- **S4. The user install story is undecided.**
  - Linux: clang plus libstdc++.
  - macOS: the Command Line Tools.
  - Windows: LLVM, VS Build Tools and the Windows SDK.

  Options: bundle clang and lld, or use llvm-mingw.
- **S5. The trap ABI was chosen by accident.** C++ `throw` needs libstdc++/libc++ and catches foreign exceptions. K2's
  forced unwind needs no C++ runtime. Unwinding through C frames must abort.
- **S6. K2 was judged on CI host friction** (`opam exec`), not on its design. Users never need OCaml.
- **S7. The per-line coverage fallback can't ship:** no branches, one counter per line, non-atomic. The covmap encoder
  (LEB128, MD5) is the real work.

## Minor

- **M1.** Use Cargo with zero dependencies.
- **M2.** `DW_LANG_C99`.
- **M3.** Moves and drop flags are not spiked.
- **M4.** K1's NOTES.md is stale.

## Corrected scores

| Option | Total | Debug 10 / effort 20 |
|---|---|---|
| K3 | 78.5 | 80.5 |
| K1 | 75 | 74 |
| K2 | 73.5 | 73.5 |

**Required in CI on three OSes before Accepted:**
- F1: the drop shim, with `b.p3`;
- F2: a real Windows debugger session;
- F3: the crew-trap spike;
- F4: a real llvm-cov report;
- S1: an enum shown in a debugger;
- S3: LLVM versions recorded;
- S4: the install story.

If F1 or F3 fail on Windows funclets, reversibility favours K3 behind the same lowered IR.
