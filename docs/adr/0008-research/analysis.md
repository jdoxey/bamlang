# D8 analysis (Opus)

## Ruled out

| Idea | Why |
|---|---|
| S1 LLVM C API | Same output as S2, plus bindings to link on three OSes and a less stable debug-info API. Textual IR keeps the option to switch later. |
| S5 Go | No sum types or exhaustive matching. The agent-productivity criterion depends on them. |
| S6 Two stages | Two backends to keep correct before M7 |
| S7 Python first | No static checking of the compiler itself, plus a rewrite later |
| X1 Zig, X2 wasm, X3 Cranelift | Each fails a gate: debug info we don't control (X1, X2), or no unwinding on Windows and macOS (X3) |
| X4 Interpreter only | Fails P-C performance; kept as the testing kernel |
| X5 Self-hosting | Research: it doubles the work while the language still changes |

## Finalists (step 3 builds each as a spike)

| | **K1 = S2** | **K2 = S3** | **K3 = S4** |
|---|---|---|---|
| Host | Rust | OCaml 5 | Rust |
| Emits | textual LLVM IR | textual LLVM IR | C |
| Trap unwinding | `invoke`/`landingpad`; `cleanuppad` on Windows | same | status returns (or `setjmp`) |
| Debug info | DWARF/CodeView metadata in the IR | same | `#line`, plus clang's C-level DWARF/PDB |

Every spike compiles the same small program, `docs/examples/compiler/SPEC.md`:
- a struct with a `drop`;
- functions, `if`, `while` and integer maths;
- `print` with interpolation;
- a trap inside nested calls, caught by `expect_trap`, which must run drops while unwinding.

On each OS it must produce:
- the executable and its expected output;
- a scripted debugger session that stops at a line and shows the struct (gdb on Linux, lldb on macOS, `cdb` or a PDB
  type dump on Windows);
- an `llvm-cov` report against our source file.
