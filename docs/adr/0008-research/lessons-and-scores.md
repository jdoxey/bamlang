# D8 step 3 lessons and pre-review scores (Opus)

Every spike compiles the same program, `docs/examples/compiler/spike.p3`: a struct, a loop, interpolation, and a trap
three calls deep that must run four drops while it unwinds. CI runs each spike on Linux, Windows and macOS.

## Results

| | K1 Rust → LLVM IR | K2 OCaml → LLVM IR | K3 Rust → C |
|---|---|---|---|
| Compiler lines (`src/`) | 1268 | 918 | 882 |
| Runtime lines | 41 | 112 | 88 |
| Compiler build | 1.3 s (`rustc -O`) | 0.27 s (`ocamlopt`) | about 1 s |
| Linux: output, gdb `p = {x = 3, y = 4}` | pass | pass | pass |
| macOS: output, lldb `p = {x = 3, y = 4}` | pass | pass | pass |
| Windows: output (drops during unwind) | **pass** (funclets, `__CxxFrameHandler3`) | not run (no OCaml) | pass (setjmp) |
| Windows: PDB has `Point{x,y}` and `spike.p3` lines | pass | not run | pass |
| Windows: scripted debugger session | lldb didn't run; no cdb | – | same |
| Trap unwinding | C++ `throw` plus `landingpad`/`cleanuppad`. Zero cost on the normal path (tables only). | `_Unwind_ForcedUnwind` plus `longjmp`. Zero cost on the normal path. Windows SEH path untested. | `setjmp` per `expect_trap`, and a thread-local cleanup stack with a push and pop per droppable local. A missed registration silently skips a drop. |
| Coverage | own per-line counters, lcov (not llvm-cov) | same | real llvm-cov, but mapped to the generated C; `#line` is ignored |
| Debugger names | `p3_area`, `Point` | `area`, `Point` | `p3_area`, `Point` |

## What the code taught

- **The research's biggest risk was Windows zero-cost unwinding, and it is retired.** K1's funclet IR runs correctly
  on the Windows runner on the first try. LLVM, not us, writes the per-OS unwind tables.
- **OCaml on the Windows runner is the real problem, not OCaml itself.** `setup-ocaml` switched every bash step to
  Cygwin and broke unrelated tests, and `ocamlopt` still wasn't on the PATH. Users on Windows would face the same
  toolchain friction to build the compiler.
- **Owning the debug metadata (K1, K2) is what G8 needs.** It is the only way to describe enums as variant parts,
  handles, and lists to the debugger. K3 gets C's types, so every language-level value needs formatters in three
  formats.
- **Coverage is unfinished in every option.** K1 and K2 need `llvm.instrprof.increment` plus a coverage-mapping
  emitter (a known, documented format). K3 needs a remap of `llvm-cov export` through the `#line` table.
- **The two Rust spikes share a host, so the host is decided by the evidence on its own merits:** Rust built on all
  three runners with std only, and both Rust compilers were written in one pass.

## Scores (`scores.py`)

| Option | Debug | 3 OS | Agent | Cov | Trap | Transp | Effort | Perf | Total |
|---|---|---|---|---|---|---|---|---|---|
| **K1 Rust + LLVM IR** | 4.5 | 5 | 4 | 3 | 5 | 3.5 | 3.5 | 5 | **85** |
| K3 Rust + C | 3.5 | 5 | 4 | 3.5 | 3 | 5 | 4.5 | 4.5 | 82 |
| K2 OCaml + LLVM IR | 4.5 | 2 | 4.5 | 3 | 4 | 3.5 | 4 | 5 | 76.5 |

- **K1 and K3 tie** (a gap of 3). With debug weighted 10 and effort 20, K3 leads 84 to 83.
- **The examples break the tie for K1.** It proved zero-cost unwinding on all three OSes, owns its debug info, and has
  no per-scope run-time cost.
- **Reversibility favours keeping a lowered-IR boundary,** so that a C emitter stays possible as a fallback. The
  reviewer attacks K1.

## Windows debugger evidence (CI 43486847096, cdb from the Windows SDK)

- **K3 (C through clang):** `dx p` gives `p [Type: Point]` with `x : 3 [Type: __int64]` and `y : 4 [Type: __int64]`.
  It meets the G8 gate on Windows.
- **K1 (own LLVM IR):** `dx p` gives `p : 0x3 [Type: Point *]` and "Unable to read memory at Address 0x3". The Win64
  ABI passes a 16-byte struct by reference, while K1's IR passes `%Point` by value with a `dbg.declare` that no
  longer matches. This is review S2 (the frontend owns the per-target ABI) showing up as wrong debug info.

## Final CI (43490431655, all green)

- **K1 on Windows:**
  - Its SEH funclets also pass `spike2.p3`: the drop chain, the crew trap and the enum output.
  - `uncaught.p3` passes.
  - Coverage mapping works (13 regions, 1 missed).
  - Only cdb's view of struct parameters is wrong.
- **What this changes:** it narrows K1's loss to the debug-info and ABI ownership cost recorded in ADR-0008, and
  keeps it as the starting point if an LLVM emitter is ever added behind the lowered IR.
