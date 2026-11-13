# D8 ideas (Opus, 2026-11-14)

Two axes: the **host** (what the compiler is written in) and the **backend** (what it emits). Ideas name both.

## Sane

- **S1 Rust plus the LLVM C API** (inkwell or llvm-sys pinned to 19).
  - Strongest ecosystem. Linking LLVM on Windows and macOS CI is the known pain.
- **S2 Rust plus textual LLVM IR, compiled by `clang`.**
  - No bindings. clang is the driver, assembler and linker on every OS (`clang-cl`/`lld-link` give PDBs).
  - The IR text is pinned to one LLVM version.
- **S3 OCaml plus textual LLVM IR, compiled by `clang`.**
  - Best AST ergonomics and fastest builds. OCaml on Windows CI is unproven (the D2 examples skipped it).
- **S4 Rust plus C as the backend, compiled by `clang` everywhere.**
  - Source lines come from `#line`.
  - Traps unwind by status return or `setjmp`.
  - Coverage comes from clang's.
- **S5 Go plus textual LLVM IR.** Easiest single binary and fastest builds, but no sum types.
- **S6 Two stages.** A C backend first for fast bring-up, then LLVM IR once the language is stable.
- **S7 A Python prototype compiler first,** grown from the existing parser, emitting LLVM IR; rewritten later.

## Crazy

- **X1 Emit Zig source** and use `zig cc` and Zig's cross-platform toolchain. Zig is still changing, and its debug
  info is Zig's, not ours.
- **X2 Emit WebAssembly**, with `wasm2c` plus clang for native builds. One target, but debug info passes through two
  translations.
- **X3 Cranelift plus our own DWARF and CodeView.** Fast debug builds, but no unwinding on Windows or macOS.
- **X4 Interpreter only in v1,** with native code later. Debugging and coverage come from the interpreter itself, so
  G8 and G9 are easy, but performance and P-C are not met.
- **X5 Write the compiler in our own language from day one,** bootstrapped through a C translation.

## Combinations

- **S2 + S4 (one host, two emitters behind one lowered IR).** It doubles the backend tests. Kept as a fallback only.
- **S2 + X4's kernel.** A reference interpreter over the lowered IR is the differential-testing oracle (research), not
  the product. It is adopted as a kernel by every finalist.
