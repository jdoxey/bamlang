# D8 compiler spike spec

Each finalist (`k1-rust-llvm/`, `k2-ocaml-llvm/`, `k3-rust-c/`) is a tiny compiler for `spike.p3`. They are judged on
the same program, so the comparison is fair.

## The subset

The subset covers only what `spike.p3` uses:
- `type` with fields, and a `drop(mut self)` block;
- `fn` with labelled parameters and the pun `area(p, …)`;
- `let`/`var`, `Int` and `Str`;
- `+ - * <`, `==`, `>`, `+=`;
- `if`/`else`, `while`, `return`;
- `print(text:)` with `{expr}` interpolation of Int and Str;
- the built-in `trap(text:)`;
- a capture-free lambda passed to the built-in `expect_trap(action:)`.

## Required behaviour

- **Output.** Printed output equals `expected.txt` exactly.
  - Drops run innermost-first while the trap unwinds, then `expect_trap` prints `trapped: <message>` and returns.
  - Drops of locals also run on normal scope exit. In this program only the `Guard`s have drops, and every `Guard` is
    dropped during the unwind.
- **Run.** `run.sh` builds the compiler, compiles `spike.p3`, runs it and diffs the output. It works on Linux,
  Windows (Git Bash) and macOS.
  - It uses `clang` from the environment: on Windows the LLVM on the runner, on macOS Apple clang or Homebrew LLVM.
  - It prints `<k> spike OK`.
- **Debug (G8).** A scripted, non-interactive debugger session breaks inside `area` at `total += p.x * p.y` (by our
  source file and line) and shows `p` with fields `x = 3` and `y = 4`.
  - Linux: `gdb -batch`.
  - macOS: `lldb -b`.
  - Windows: `cdb` if present, otherwise `llvm-pdbutil dump -types` proving the PDB holds `Point` with `x` and `y`, and
    line records for `spike.p3`.
  - Record the debugger's output. If a tool is missing on a runner, print `SKIP debug (<tool> missing)`; don't fail.
- **Coverage (G9).** Build with coverage instrumentation, run, and produce an `llvm-cov report` (or `show`) against
  `spike.p3`, with line counts for `area`.
  - Record it. Missing tools are handled as for debugging.
- **Notes.** `NOTES.md` records:
  - lines of compiler code, per stage;
  - build time of the compiler;
  - what was awkward;
  - what the debugger shows *without* custom formatters;
  - what each OS needed;
  - how traps unwind, and their cost on the non-trap path.
