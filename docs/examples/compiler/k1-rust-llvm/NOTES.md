# K1: Rust compiler, textual LLVM IR, clang

Status (loop 2): `./run.sh` passes locally on Linux (clang 19.1.7, gdb, lldb 19) for `spike.p3`, `spike2.p3` and
`uncaught.p3` and prints `k1 spike OK`. CI run 43448112789 passed `spike.p3` on macOS and Windows (loop 1 code). Loop 2 code
is **untested on macOS and Windows**; its IR (including coverage) was only assembled for `x86_64-pc-windows-msvc`,
`x86_64-apple-macosx` and `aarch64-apple-macosx` on Linux (clang verifier). It needs `cargo`, `clang`, and `gdb`/`lldb`/`cdb`
and `llvm-cov`/`llvm-profdata` for the debug and coverage steps. Output goes to `build/` (generated).

## Lines per stage (`wc -l`)

| Stage | File | Lines |
|---|---|---|
| lexer (with columns) | `src/lexer.rs` | 93 |
| parser + AST | `src/parser.rs` + `src/ast.rs` | 324 + 84 |
| checker (enums, match, crews) | `src/check.rs` | 286 |
| lowering to structured IR | `src/lower.rs` + `src/ir.rs` | 500 + 72 |
| IR emission (text, debug metadata, coverage globals) | `src/emit.rs` | 229 |
| coverage mapping encoder + MD5 | `src/cov.rs` | 92 |
| driver | `src/main.rs` | 37 |
| **Compiler total (src/)** | | **1717** |
| runtime (C11) | `runtime.c` | 208 |
| `run.sh` | | 152 |

Loop 1 was 1268 compiler lines. Build time of the compiler: about 2 s (`cargo build --release`, no dependencies,
`Cargo.lock` committed, edition 2021, zero warnings).

## What changed in loop 2

- Cargo package, no dependencies (review M1). `run.sh` runs `cargo build --release --quiet`.
- New trap ABI without a C++ runtime (S5, below). Trap state is thread-local.
- F1: drops called from cleanup pads go through `p3_cleanup_drop`, which catches a trap in the drop and appends
  `; then: <msg>` to the chain; the remaining drops run. `spike2.p3` matches `expected2.txt`.
- F3: `crew c { c.go(task: fn() { .. }) }` with capture-free lambdas; one OS thread per `go`, join at the brace, first
  child trap (in `go` order) re-raised in the parent with its message unchanged. `return` inside a crew block is rejected
  by the checker. A trap in the crew body still joins the children (the handle is a droppable local).
- Uncaught trap: no catcher on this thread, so `p3_trap` flushes stdout, prints `trap: <msg>` and `  at <fn> (<file>:<line>)`
  to stderr, exits 101. The compiler passes the trap's `file:line` and function as arguments, so it works on every OS (no
  `backtrace`). Only the trap site is shown, not the callers.
- S1: enums with labelled payload fields, `Shape.Rect(w: 3, h: 4)`, `match` with positional binders (exhaustive, no
  duplicates, arms give Int or Str; payload fields are Int or Str).
- F4: real LLVM source-based coverage (below). The per-line fallback is gone.
- S3: IR carries `target triple` and `target datalayout`, taken by `run.sh` from `clang -S -emit-llvm` of an empty C file
  (with `--target=x86_64-pc-windows-msvc` on Windows). `run.sh` prints `clang --version | head -1`, the triple and the datalayout.
- S2 / Win64 (coordinator, CI run 43486847096): cdb showed `p = 0x3` because by-value `%Point` params do not follow the Win64
  ABI. Now every struct or enum argument is passed as a `ptr` to a caller-made temporary on all targets; the callee copies
  it into its own alloca, which `dbg.declare` describes. On Windows with cdb, `run.sh` now asserts `: 3 [Type: __int64]`
  and `: 4 [Type: __int64]` in the `dx p` output. Not re-run on Windows yet. Struct return values are still by value
  (no spike function returns one).
- Debug flags unchanged (`DW_LANG_C99`, M2).

## Trap ABI (S5)

Codegen only knows these runtime calls: `p3_trap(msg, loc, fn)`, `p3_expect_trap(fn)`, `p3_cleanup_drop(drop, obj)`,
`p3_crew_new/go/join/quiet`. Raise and catch are in `runtime.c`, so the unwinder can change without touching codegen.
`expect_trap` is now a plain runtime call (no landing pad in generated code).

- **Linux/macOS (chosen: forced unwind, as in K2).** `p3_trap` calls `_Unwind_ForcedUnwind` with a stop function. Generated
  functions have `landingpad { ptr, i32 } cleanup` blocks (drops via the shim, then `resume`) with personality
  `__gcc_personality_v0` (libgcc / compiler-rt, C, cleanups only; no LSDA parser of our own). The stop function longjmps to
  the catch site (`setjmp` in `run_caught`) once the unwinder reaches that frame (CFA above the frame's marker). No libstdc++
  or libc++, no `-lstdc++`; links with `-pthread` only. Why not a hand-written personality: the C personality in libgcc
  already runs cleanups, and catching is the runtime's job, so there is nothing left for ours to do. The cost is that a
  trap reaching a frame with no unwind info (a C frame) hits the end of the stack and aborts, which is the S5 rule.
- **Windows (not run).** `RaiseException(0xE0503354)`; catch sites are `__try/__except` in the C runtime (filter on the
  code). Generated cleanups are `cleanuppad within none []` + `cleanupret ... unwind to caller` with personality
  `__C_specific_handler` (what clang emits for `__try/__finally`). I chose SEH over `__CxxFrameHandler3` because the whole path
  is C and SEH, with no ThrowInfo or vcruntime C++ state, and the same personality serves the `__try` in the runtime. Calls inside
  a pad carry `"funclet"` bundles. Nested raise inside a cleanup (trap in drop) is caught by the shim's own `__try`.
- **Trap in drop (F1).** Catch sites form a thread-local stack. The shim pushes its own catcher; a trap in the drop lands in
  it; the shim appends to the enclosing catcher's message and returns, so the outer unwind resumes. A nested forced unwind from a
  landing pad is fine because the outer unwinder's frames are gone by then; the exception object is thread-local and reused
  (same stop function, same argument).
- **Cost on the non-trap path:** zero instructions. Calls that can unwind are `invoke` (a `call` plus table entries). Drops on
  normal exit are plain calls. `expect_trap` costs one `setjmp` when entered. Generated functions have `uwtable`.
- **Limits:** drops on normal scope exit are plain calls, so a trap in one skips the rest of that scope's drops; only
  unwinding is chained. Message chains and crew state leak (never freed).

## Enums (S1) and what debuggers show

LLVM type `%Shape = { i64, [N x i64] }` (tag, then N payload slots, N = widest variant; `Str` goes through
`ptrtoint`/`inttoptr`). Debug info: `DW_TAG_structure_type Shape { tag: DW_TAG_enumeration_type (enumerators = variants),
payload: DW_TAG_union_type { Circle: struct { r }, Rect: struct { w, h } } }`. No `DW_TAG_variant_part`.
gdb (Linux, run here), `print s` in `describe`:

```
Breakpoint 1, p3_describe (s=...) at spike2.p3:24
$1 = {tag = Rect, payload = {Circle = {r = 3}, Rect = {w = 3, h = 4}}}
```

`run.sh` asserts `w = 3` and `h = 4` (gdb on Linux, `lldb -b` on macOS: lldb prints the same members as nested structs,
not run on macOS). Without a formatter you see every variant of the union, including the ones that are not active; the
`tag` field says which is. On Windows: cdb or lldb if they work; otherwise `llvm-pdbutil` checks the PDB holds `Shape`
(CodeView struct, union, enum) and line records for `spike2.p3`. Binders `r`, `w`, `h` are locals of `describe`
(unset until the arm runs; gdb shows 0).

`spike.p3` under gdb: `$1 = {x = 3, y = 4}`; frames show `p3_area` (a `p3_` prefix avoids C name clashes), Int as `long`.

## Coverage (F4): real source-based coverage

`p3c --coverage` emits, per function, `llvm.instrprof.increment(ptr @__profn_<fn>, i64 hash, i32 counters, i32 idx)` and
the coverage mapping by hand: one `__covrec_<hash>u` record per function (section `__llvm_covfun`, `__LLVM_COV,__llvm_covfun` on
Mach-O, `.lcovfun$M` on COFF; comdat except Mach-O) and `__llvm_coverage_mapping` (filename table: compilation dir, then
`spike.p3`). Encoding is in `src/cov.rs`: ULEB128, MD5 (own implementation) of function names and the filename table,
counters only (no expressions), code regions plus branch regions (`4<<3`, true counter, false counter). Format version written
is 6 on the wire (enum `Version6`, the format of clang 14 to 17; clang 19 writes 7 and reads this). I verified the layout by
decoding clang 19's own output for an equivalent C file. Regions: function body; each `if` (branch region on the condition,
then block, else block, rest of the enclosing block); each `while` (condition, branch region, body, rest of block); each
`match` arm. Build with `-fprofile-instr-generate -fprofile-update=atomic`; run with `LLVM_PROFILE_FILE`; then
`llvm-profdata merge -sparse` and `llvm-cov report/show/export`. Tools are found on PATH, via `xcrun --find` or Homebrew on
macOS, and in `/c/Program Files/LLVM/bin` on Windows. `run.sh` asserts line counts and branch records from the lcov export.

```
Filename        Regions  Missed  Cover   Functions  Missed  Executed   Lines  Missed  Cover   Branches  Missed  Cover
.../spike.p3         13       1  92.31%           5       0   100.00%     38       1  97.37%          6       1  83.33%
   15|      1|fn area(p: Point, scale: Int) -> Int {
   18|      3|  while i < scale {
  |  Branch (18:9): [True: 2, False: 1]
   19|      2|    total += p.x * p.y
   22|      1|  return total
```

(1 missed line, 1 missed branch: the `print(text: "small")` side of `if a > 20`.) Limits: regions use one counter each (no
counter expressions); code after a call that traps (e.g. after `inner()` in `uncaught.p3`) is counted with its region; no gap
regions; columns are character offsets, so non-ASCII text before a region on the same line shifts it. Only `spike.p3` is
covered in `run.sh`.

## How the C runtime and OS needs differ

- Linux: `clang` (libgcc_s for the unwinder), `-pthread`, `gdb`.
- macOS: `clang` (Apple or Homebrew), `lldb`; `<unwind.h>` from clang's resource dir; `__gcc_personality_v0` comes from
  compiler-rt (always linked). The `.o` files stay in `build/` so lldb can follow the debug map (no dsymutil step).
  Coverage tools via `xcrun`.
- Windows (Git Bash): LLVM on PATH or `/c/Program Files/LLVM/bin`, VS Build Tools / Windows SDK for headers and libs, `lld`,
  `cdb` or `llvm-pdbutil`; the profile runtime `clang_rt.profile` ships with LLVM. Output is piped through `tr -d '\r'`.

## Riskiest untested parts

1. Windows: SEH raise from the runtime into `cleanuppad` funclets with `__C_specific_handler`, including a nested
   `RaiseException` from a drop inside a funclet (F1), and `_beginthreadex` children (F3).
2. macOS: forced unwind via libunwind (`_Unwind_ForcedUnwind`, `_Unwind_GetCFA`, exception object private fields) and
   `__gcc_personality_v0` from compiler-rt; arm64 longjmp out of the stop function.
3. Coverage on Windows/macOS: section names and the profile runtime link (`-fprofile-instr-generate` at link time), and
   Apple's `llvm-cov` accepting version 6 mappings.
4. The by-reference aggregate fix on Windows (cdb should now show `Point` with x = 3, y = 4).

## What was awkward

- Region bookkeeping: llvm-cov needs exact start/end columns, so the lexer and parser now track columns and statement end
  positions; the "rest of block" regions need the enclosing block's end.
- The textual IR for the covmap has to match the layout the InstrProfiling pass expects; decoding clang's own output was the
  only reliable reference.
- Forced unwind needs a frame marker trick (CFA compared with a local's address) to find the catch site.
- Hand-written debug metadata is mechanical, and the LLVM verifier catches most mistakes.
- Strings and trap chains are never freed.
