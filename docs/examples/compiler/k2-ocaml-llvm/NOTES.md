# K2: OCaml 5 compiler, textual LLVM IR, clang

Run `./run.sh` (prints `k2 spike OK`). Tested on Linux only (OCaml 5.3.0, clang 19.1.7, gdb, lldb). Windows and macOS
paths are written but unexecuted; see "Risks".

## Size (`wc -l`)

| Stage | File | Lines |
|---|---|---|
| AST types | `src/ast.ml` | 26 |
| Lexer | `src/lexer.ml` | 81 |
| Parser | `src/parser.ml` | 209 |
| Checker | `src/check.ml` | 126 |
| IR types | `src/ir.ml` | 27 |
| Lowering (drop scheduling, invoke choice, coverage counters) | `src/lower.ml` | 255 |
| IR text + debug metadata emission | `src/emit.ml` | 159 |
| Driver (calls clang) | `src/main.ml` | 35 |
| C runtime (print, concat, itoa, traps, lcov dump) | `runtime.c` | 112 |
| **Compiler (OCaml)** | | **918** |
| `run.sh` | | 71 |

Compiler build: `ocamlopt` on 8 files, 0.27 s wall (cold, no dune, no ocamlfind). Compiling `spike.p3` (OCaml compiler plus two
`clang -c` and a link) takes about 0.3 s.

## Design

Pipeline: `Lexer.tokenize` -> `Parser.program` -> `Check.program` (annotates `expr.ty`) -> `Lower.program` (to `Ir`) ->
`Emit.module_` (text) -> `clang -c x.ll`, `clang -c runtime.c`, link. Only the OCaml stdlib is used (`Sys.command`,
`Filename.quote_command`, no `unix`), so the mingw OCaml build is fine. `--os linux|macos|windows` chooses the personality,
the funclet form and the debug-info flavour; `run.sh` derives it from `uname -s`.

- Structs are LLVM `%Point = type { i64, i64 }`, passed by value (first-class aggregate), kept in allocas. A struct-typed
  value inside the compiler is a pointer to its storage. Strings are `ptr` to leaked C strings.
- Named arguments: the checker requires labels to equal the declaration order; puns are expanded by the parser. `self`
  in `drop` is passed by pointer.
- IR is LLVM 17 compatible: opaque pointers, `llvm.dbg.declare` intrinsic calls (never `#dbg_declare`).
  Functions carry `noinline optnone uwtable "frame-pointer"="all"`.

## Traps and unwinding

Real table-based unwinding, no cost on the normal path.

- Any call made while a droppable local is live is emitted as `invoke ... unwind label %lpadN`. `Lower.pad` makes one
  cleanup pad per distinct set of live droppables: it calls each `drop` innermost first, then continues unwinding.
  In `depth`, calls to `p3_trap` and `depth` are invokes; `area` and `main` have none and no personality.
- **Linux/macOS.** Pads are `landingpad { ptr, i32 } cleanup` + `resume`, personality `__gcc_personality_v0` (libgcc; the
  same one clang uses for C `__attribute__((cleanup))`). It needs no C++ runtime and no custom LSDA parser.
  `p3_trap` calls `_Unwind_ForcedUnwind` with a stop function. The unwinder runs the cleanup phase only, calling each
  frame's personality, so the drops run innermost first. The stop function compares each frame's CFA with a marker local
  in `p3_expect_trap`; at that frame it `longjmp`s back, and `expect_trap` prints `trapped: <msg>`. I chose forced
  unwind over `_Unwind_RaiseException` because a two-phase search needs a personality that reports a handler for the
  `expect_trap` frame, which means parsing LSDA ourselves (or linking libstdc++ for `__gxx_personality_v0`).
- **Windows (untested).** `p3_trap` calls `RaiseException(0xE0503354, ...)`. `p3_expect_trap` uses `__try/__except`
  (`_exception_code()`), which clang accepts in C for msvc targets. Generated functions use personality
  `__CxxFrameHandler3`; each cleanup pad is `cleanuppad within none []`, then the drop calls with a
  `[ "funclet"(token %pad) ]` bundle, then `cleanupret from %pad unwind to caller`. No `catchswitch` is needed because
  nothing in generated code catches; the catch lives in the C `__except`. `__CxxFrameHandler3` runs unwind-map
  cleanups for any exception during the unwind phase, which is why a foreign SEH code works. I verified only that this IR
  and `runtime.c` compile to COFF objects with `.xdata`, `.pdata`, `.debug$S` and `.debug$T` using
  `--target=x86_64-pc-windows-msvc` on Linux (runtime with stub headers). I did not link or run.
- **Non-trap cost.** Zero instructions on the happy path: an `invoke` is a `call` with an extra table entry. The cost
  is `.eh_frame` and `.gcc_except_table` size (both present in the binary), pads placed after the function body, and
  fewer optimisations around invokes (not visible at -O0). A trap costs a table walk per frame.
- Limits: traps during a drop are not chained; traps outside `expect_trap` print and `exit(101)`.

## Debug info (G8)

`!DICompileUnit` (language C99 so debuggers use C expression syntax), `!DIFile("spike.p3", dir)`, one `!DISubprogram` per
function, a `!DILocation` per statement line on every instruction, `!DICompositeType` for `Point` and `Guard` with
`!DIDerivedType` members, `Int` as `DIBasicType`, `Str` as pointer to `char` (so it prints as a string), and
`llvm.dbg.declare` for every param and local. DWARF 4 on Linux/macOS; on Windows the module flag `CodeView` and
`-g -gcodeview -fuse-ld=lld -Wl,/DEBUG` give a PDB. macOS runs `dsymutil` after linking (lldb needs it because the `.o`
files are temporaries).

Raw gdb output, no pretty-printers (`gdb -batch -ex 'break spike.p3:19' -ex run -ex 'print p' -ex 'print p.x' -ex 'print p.y' -ex 'info locals'`):

```
Breakpoint 1 at 0x12aa: file spike.p3, line 19.
Breakpoint 1, area (p=..., scale=2) at spike.p3:19
19	    total += p.x * p.y
$1 = {x = 3, y = 4}
$2 = 3
$3 = 4
total = 0
i = 0
```

lldb on Linux (same binary) also shows `(Point) p = { x = 3 y = 4 }`. Both are the natural struct view with no custom
formatter. Frame #1 is `main` at `spike.p3:35`; the C entry `main` appears as a second `main` frame (name clash between the
user's `main` and the C entry point; the user's is `p3.main` in the symbol table).

## Coverage (G9): per-line counters, not llvm-cov

Honest fidelity: **fallback**, not source-based coverage. `--coverage` makes `Lower` insert a `Cov idx` (load, add, store on
an `i64` global array, non-atomic) at every statement and at each function entry; one counter per source line. The
runtime writes an lcov tracefile (`build/spike_cov.lcov`) when `main` returns. No branch or region data, no counts for
expressions sharing a line (they share a counter), no output if the program traps out of `main`, and it is not readable by
`llvm-cov`. I did not attempt `__llvm_coverage_mapping`: its binary format changed between LLVM 17-19 and I could not
validate it on CI runners. A real mapping would be a separate emitter (about 150 lines).

Output for `area` (from `run.sh`):

```
FN:15,area
FNDA:1,area
     1 |  15 | fn area(p: Point, scale: Int) -> Int {
     1 |  16 |   var total = 0
     1 |  17 |   var i = 0
     3 |  18 |   while i < scale {
     2 |  19 |     total += p.x * p.y
     2 |  20 |     i += 1
       |  21 |   }
     1 |  22 |   return total
LF:25 LH:24
```

(The one unhit line is `print(text: "small")`.)

## What was awkward

- Newlines: the lexer must drop newlines inside `( )` but not inside the lambda's `{ }` nested in the call. A bracket stack
  in the lexer solved it in 5 lines.
- Landing pads: every call site needs to know the live droppables at that point; the pad is cached by that set. Early
  `return` must drop everything live without truncating the list (other paths still need it).
- Debug info ids: forward references (composite <-> members) need pre-allocated metadata ids.
- LLVM IR is verbose but forgiving; clang reported no verifier errors on the first run.
- OCaml: variants make the checker and lowering pleasant; `let rec ... and` with labelled arguments forced the labels to be
  used in definition order.

## What each OS needs

- Linux: `ocamlopt`, `clang` (links libgcc for `_Unwind_ForcedUnwind` and `__gcc_personality_v0`), `gdb` for the debug step.
- macOS: `clang` (Apple or Homebrew), `lldb`, `dsymutil`. `<unwind.h>` is from clang's resource dir.
- Windows (Git Bash): mingw `ocamlopt`, LLVM clang plus `lld` (`/c/Program Files/LLVM/bin`), MSVC/Windows SDK libs for the
  link (`clang` finds them itself), `cdb` or `llvm-pdbutil` for the debug step.

## Risks (not tested)

1. Windows: the whole path (SEH raise, `__CxxFrameHandler3` cleanups for a foreign exception code, `__try/__except` in
   C, `-Wl,/DEBUG`, PDB contents, `Filename.quote_command` through `cmd`). The most doubtful point is the unwind-phase
   behaviour of `__CxxFrameHandler3` on a non-C++ exception. Fallback: switch the personality to `__C_specific_handler`
   (SEH `__finally` form, same `cleanuppad` shape).
2. macOS: `__gcc_personality_v0` and `_Unwind_ForcedUnwind` availability and behaviour with compact unwind on arm64;
   the IR does compile for `arm64-apple-macos`. If `__gcc_personality_v0` is missing, fall back to `__gxx_personality_v0`
   with `-lc++`.
3. `run.sh` Windows debugger step: `cdb` command syntax and output matching are guesses; the `llvm-pdbutil` branch only
   greps for `Point`.
4. Stack direction: `longjmp` out of the stop function assumes the stack grows down (true on all three targets).
