# D8 research: backends, debug info, unwinding, coverage (Sonnet researcher, 2026-11-14; condensed)

[unverified] marks claims without a fetched source.

## LLVM

- **API stability.** The C API is "best effort" stable, and debug-info creation is called less stable. Textual IR is
  not backward compatible; bitcode is, but debug metadata is dropped on upgrade
  (https://llvm.org/docs/DeveloperPolicy.html). Crystal spans LLVM 8–23 with version flags
  (https://github.com/crystal-lang/crystal/blob/master/src/llvm/lib_llvm.cr), so churn is manageable.
- **Size and speed.** Zig quotes about 150 MiB with LLVM against about 5 MiB without, and wants to drop it for size,
  speed, bugs and packaging (https://github.com/ziglang/zig/issues/16270). Zig's own x86-64 backend is about 5x faster
  in Debug but buggy. On Windows, LLVM remains the default "due to Linker deficiencies"
  (https://ziglang.org/download/0.15.1/release-notes.html).
- **Debug info.** One metadata set gives DWARF (gdb, lldb) and CodeView (Visual Studio)
  (https://llvm.org/docs/SourceLevelDebugging.html). A PDB needs lld-link or link.exe [unverified].
- **Coverage.** The source-based flow is profraw, then `llvm-profdata`, then `llvm-cov`, with lcov export
  (https://llvm.org/docs/CommandGuide/llvm-cov.html). Any frontend can emit the mapping format
  (https://llvm.org/docs/CoverageMappingFormat.html). Rust does this. It suggests continuous mode `%c` so data survives
  crashes, and warns that the LLVM versions must match (https://doc.rust-lang.org/rustc/instrument-coverage.html).
- **Unwinding** (https://llvm.org/docs/ExceptionHandling.html):
  - Itanium-style `invoke`/`landingpad`/`cleanup` on Linux and macOS;
  - WinEH funclets (`cleanuppad`) on Windows, a second IR shape;
  - compact unwind emitted by LLVM on macOS.

  Running drops on a trap maps onto cleanup pads on both.
- **Users:** Rust, Swift, Julia, Crystal, Odin. Odin ships `LLVM-C.dll` and uses the C API
  (https://github.com/odin-lang/Odin).

## C as a backend

- **Nim** emits C with `--lineDir:on` `#line` directives, and has `--debugger:native` (https://nim-lang.org/docs/nimc.html).
- **Debuggers through `#line`** show source lines but C-level values. Custom formatters are needed anyway [unverified].
- **Windows** means MSVC or clang-cl for PDBs. Rust calls its windows-gnu targets "not properly maintained"
  (https://doc.rust-lang.org/nightly/rustc/platform-support/windows-gnu.html).
- **Coverage** uses gcov (https://gcc.gnu.org/onlinedocs/gcc/Instrumentation-Options.html) or clang's. Mapping back
  through `#line` is unproven.
- **No portable unwinding:** traps that run drops need `setjmp`/`longjmp` or status-return propagation.

## Others

- **QBE** (https://c9x.me/compile/): no Windows, no debug info, no unwinding. Disqualified by G8, G9 and R9.
- **Cranelift** (https://cranelift.dev/, https://github.com/rust-lang/rustc_codegen_cranelift): Windows x86-64 only.
  Panic unwinding is "experimental and not supported on Windows or macOS". Debug info is weak [unverified].
- **Go's own backend** (https://go.dev/doc/gdb): own DWARF and no Windows DWARF listed. gdb "does not understand Go
  well", so Go built Delve, a whole debugger. An own backend means owning the debugger story.
- **Raw machine code:** three object formats, two debug formats and three unwind formats. Not viable for one agent.

## Debugger value display (G8)

- **gdb:** Python pretty-printers
  (https://sourceware.org/gdb/current/onlinedocs/gdb.html/Writing-a-Pretty_002dPrinter.html). Rust embeds them via
  `debugger_visualizer`, but auto-load needs a safe path
  (https://doc.rust-lang.org/nightly/reference/attributes/debugger.html).
- **lldb:** Python summaries and synthetic children (https://lldb.llvm.org/use/variable.html). Exceptions are
  swallowed silently.
- **Visual Studio:** natvis XML, embedded in the PDB
  (https://learn.microsoft.com/en-us/visualstudio/debugger/create-custom-views-of-native-objects). It can't call
  functions, so layouts must be readable as field arithmetic.
- **Consequence:** keep simple, stable layouts (pointer, length, tag, payload) and ship three formatter sets.

## Risks

1. Trap unwinding with drops is the hardest feature and differs on each OS.
2. Three formatter systems to keep in step with the layout.
3. Windows PDBs need lld-link or link.exe.
4. Coverage mapping fidelity.
5. LLVM's weight and churn.

## CI facts (2026-11-14, run 43486134629)

- **clang versions:**
  - ubuntu-24.04: Ubuntu clang 18.1.3;
  - windows-2025: clang 20.1.8 (`x86_64-pc-windows-msvc`);
  - macos-26: Apple clang 21.0.0 (arm64), with `llvm-cov`/`llvm-profdata` through `xcrun`;
  - local: 19.1.7.

  The spikes' textual IR was accepted by all four.
- **Windows debuggers:**
  - `liblldb.dll` needs `python310.dll` (fixed with setup-python 3.10).
  - The Windows SDK Debuggers directory exists but isn't on the PATH (added).
