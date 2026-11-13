# K1: Rust compiler, textual LLVM IR, clang

Status: **passes on Linux** (clang 19.1.7, gdb, lldb 19). macOS and Windows are **untested**; the Windows IR was only assembled
to a COFF object on Linux (`clang --target=x86_64-pc-windows-msvc -g -gcodeview -c`, which runs the LLVM verifier), and
the macOS IR to a Mach-O object. Neither was linked or run.

Run `./run.sh`. It needs `rustc`, `clang` (and `gdb`/`lldb`/`cdb` for the debug step). No crates; `rustc` on one crate, so
there is no Cargo.lock. Output goes to `build/` (generated; do not commit).

## Lines per stage (`wc -l`)

| Stage | File | Lines |
|---|---|---|
| lexer | `src/lexer.rs` | 90 |
| parser (+ AST types) | `src/parser.rs` + `src/ast.rs` | 246 + 65 |
| checker | `src/check.rs` | 192 |
| lowering to structured IR | `src/lower.rs` + `src/ir.rs` | 393 + 68 |
| IR emission (text, debug metadata) | `src/emit.rs` | 171 |
| driver | `src/main.rs` | 43 |
| runtime (C++-subset) | `runtime.c` | 41 |
| `run.sh` | | 84 |
| **Compiler total (src/)** | | **1268** (1309 with runtime) |

**Build time of the compiler:** 1.3 s wall (`rustc -O --edition 2021 src/main.rs`, 6.6 s CPU on several cores).

## What it supports

The whole SPEC subset: `type` with fields and `drop(mut self)`, `fn` with labelled parameters and the pun, `let`/`var`,
`Int`/`Str`, `+ - * < > ==`, `+= -= =`, `if/else`, `while`, `return`, `print`, `trap`, `expect_trap` with a capture-free
lambda, `{expr}` interpolation. The checker rejects: unknown names, wrong or missing labels (pun error says "write `count: n`"),
type mismatches, shadowing, assigning a `let`, lambda captures, unused non-call values, a missing final `return`, and
copying or moving a value whose type has a `drop` (the spike has no move semantics, so that would double-drop).
Errors print `spike.p3:LINE: error: ...`.

## How traps unwind

A trap is a **real C++ exception**. `runtime.c` is compiled with `clang -x c++` (it uses only the C subset plus `throw`,
no C++ headers) and `p3_trap(msg)` stores the message and does `throw 1`.

- **Linux/macOS:** personality `__gxx_personality_v0` from libstdc++ / libc++abi (link with `-lstdc++` / `-lc++`). This is the
  simplest choice: no hand-written personality or LSDA parser. A call that can unwind while droppable locals are live becomes
  `invoke ... unwind label %cleanup.N`. The cleanup block is `landingpad { ptr, i32 } cleanup`, then drop calls in reverse
  declaration order (innermost first), then `resume`. One cleanup block is shared by all calls with the same set of live locals.
  `expect_trap` is an `invoke` of the lambda whose landing pad is `catch ptr null` (catch-all): `__cxa_begin_catch`, print
  `trapped: <msg>`, `__cxa_end_catch`, continue.
- **Windows (MSVC ABI), written but not run:** same runtime, but now `throw 1` compiles to `_CxxThrowException`. Personality
  `__CxxFrameHandler3` (used for x86_64 as well). Cleanups are `cleanuppad within none []` ... `cleanupret from %pad unwind to caller`.
  `expect_trap`'s handler is `catchswitch within none [label %catch.body] unwind to caller`, then
  `catchpad within %cs [ptr null, i32 64, ptr null]` (this is exactly clang's `catch (...)`), the report calls, and
  `catchret from %cp to label %cont`. Every call inside a pad carries `[ "funclet"(token %pad) ]`; this is tracked in
  `Cx.funclet`. The emitted triple is `x86_64-pc-windows-msvc` and the module flag is `CodeView` instead of `Dwarf Version`.
  I judged this path acceptable, not too risky, because it mirrors what clang itself emits and because it reuses the C++
  throw/catch machinery rather than raising a custom SEH code (a custom code would not be caught by `catchpad` with flag 64, and a
  hand-built `ThrowInfo` would be the risky route). Remaining risks: (1) the Windows runtime compile needs the Windows SDK/UCRT
  headers (`stdio.h`) that clang finds from a VS Build Tools install; (2) not run at all.
- **Cost on the non-trap path:** nothing at run time. `invoke` is a `call` plus table entries (`.eh_frame` + `.gcc_except_table`,
  0x208 + 0x34 bytes here; no registration, no flags, no checks after calls). Drops on normal exit are plain calls. Code size grows
  by the cleanup blocks only. Every generated function has `uwtable` so frames without cleanups still unwind.
- **Limits:** a trap inside a `drop` during unwinding would terminate (C++ rule); ADR-0004's "append to chain" is not modelled.
  An uncaught trap calls `std::terminate`, no trace.

## Debug info

Hand-written metadata, intrinsic call form (`call void @llvm.dbg.declare(metadata ptr %t, metadata !N, metadata !DIExpression())`),
no `#dbg_declare` records, no IR syntax newer than LLVM 17. Nodes: `DICompileUnit` (language `DW_LANG_C99` so gdb prints
structs), `DIFile("spike.p3", cwd)`, `DIBasicType` Int, `Str` as a pointer type to `char`, `DICompositeType` per struct with `DIDerivedType`
members at their offsets, a `DISubprogram` per function (including the lambda and `Guard.drop`), `DILocalVariable` per
parameter and local, and a `DILocation` per (function, line). Lines come from the source. On Windows `run.sh` passes
`-g -gcodeview` and `-fuse-ld=lld`, which makes lld write a PDB; the debug step uses `cdb` if present, else
`llvm-pdbutil dump -types -lines`.

Note: `area`'s `total += p.x * p.y` is **line 19** of `spike.p3` (a comment line and blank line start the file); `run.sh` finds
it with grep.

### Raw gdb output (no pretty-printers; `gdb -batch -ex 'break spike.p3:19' -ex run -ex 'print p' -ex 'print scale' -ex 'print total' -ex 'info locals' -ex bt`)

```
Breakpoint 1 at 0x126d: file spike.p3, line 19.
[Thread debugging using libthread_db enabled]
Using host libthread_db library "/lib/x86_64-linux-gnu/libthread_db.so.1".

Breakpoint 1, p3_area (p=..., scale=2) at spike.p3:19
19	    total += p.x * p.y
$1 = {x = 3, y = 4}
$2 = 2
$3 = 0
total = 0
i = 0
#0  p3_area (p=..., scale=2) at spike.p3:19
#1  0x000055555555535a in p3_main () at spike.p3:35
#2  0x0000555555555446 in main ()
```

lldb 19 on Linux (the macOS command line, not run on macOS):

```
(lldb) frame variable
(Point) p = {
  x = 3
  y = 4
}
(long) scale = 2
(long) total = 0
(long) i = 0
```

Without formatters the user sees our function names as `p3_area` (a `p3_` prefix avoids clashes with C symbols such as `main`;
`DISubprogram.name` is `area`, but gdb shows the linkage name), Int as `long`/`i64`, the `Point` struct with fields, and `Str` as
a `char *` (prints the text). Frame `p3_main`/`main` shows the wrapper entry. `p=...` in the frame line is gdb's default for aggregates.

## Coverage: fallback, not source-based

I did **not** implement `llvm.instrprof.increment` plus a `__llvm_coverage_mapping` record. That means writing the covmap/covfun
binary format (LLVM 17-19 versions differ), MD5 name hashes and `__llvm_prf_*` sections by hand, and failing silently is easy.
Instead (the permitted fallback): with `--coverage`, the compiler adds a counter increment (`load/add/store` on a global
`[N x i64]` indexed by source line) at the start of each statement, at each function entry and at each `while` condition test, and
writes `spike_cov.covmap` (function line ranges and instrumented lines). The runtime dumps nonzero counters at exit
(`P3_COV_OUT`), and `run.sh` (awk) writes `build/spike.lcov` (`FN`, `FNDA`, `DA`, `LF`, `LH`) and prints an annotated listing; `genhtml`
runs if installed (it is not here). **Fidelity:** per-line statement counts, correct for this program. No branch or region
coverage, no sub-line detail (e.g. `a and b`), non-atomic counters, not llvm-cov compatible, and counts are by line, not by
statement (two statements on a line would share a counter).

```
  15 |      1 | fn area(p: Point, scale: Int) -> Int {
  16 |      1 |   var total = 0
  17 |      1 |   var i = 0
  18 |      3 |   while i < scale {
  19 |      2 |     total += p.x * p.y
  20 |      2 |     i += 1
  22 |      1 |   return total
summary LH:24 of LF:25
```
(25 instrumented lines, 24 hit; the missed one is the `print(text: "small")` branch. `FNDA` for `area` is 1.)

## What each OS needs

- Linux: `clang`, `libstdc++` (for `-lstdc++`), `gdb`.
- macOS: `clang`, libc++ (`-lc++`), `lldb`. The `.o` files stay in `build/` so lldb can follow the debug map (no dsymutil step).
- Windows (Git Bash): LLVM on `PATH` or `/c/Program Files/LLVM/bin`, a Visual Studio Build Tools/Windows SDK for headers and
  vcruntime libs, `lld` (ships with LLVM), `cdb` or `llvm-pdbutil`. Output is piped through `tr -d '\r'` before the diff.

## What was awkward

- Keeping the checked AST usable by lowering: lambdas must be hoisted and given a lifetime that outlives the function being
  lowered (`'a` threaded through lowering).
- The IR emitter needs forward references in metadata (struct members point at their composite and back), solved by
  reserving ids.
- Windows funclets: every call in a pad needs a bundle, and the pad token must be threaded through; the structured IR
  makes this one field (`funclet`).
- Hand-written debug metadata is mechanical but easy to get subtly wrong; the LLVM verifier catches most of it, which is a plus
  of emitting text and letting clang check it.
- `-x c++` is needed for `runtime.c`, so its name is slightly misleading.
- Strings are never freed (every interpolation leaks); fine for a spike, wrong for the real runtime.
- `clang` prints `-Woverride-module` for IR without a triple; `run.sh` passes `-Wno-override-module`.
