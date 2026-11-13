# K3: Rust compiler emitting C, built by clang

Status on Linux (clang, gdb, llvm-cov, lldb present): `./run.sh` passes, ends `k3 spike OK`. Windows and macOS: untested.

## Size (wc -l)

| Stage | File | Lines |
|---|---|---|
| AST | src/ast.rs | 51 |
| Lexer | src/lexer.rs | 66 |
| Parser | src/parser.rs | 238 |
| Checker | src/check.rs | 163 |
| Lowering | src/lower.rs | 194 |
| C emission | src/emit.rs | 103 |
| Driver (CLI, clang calls) | src/main.rs | 67 |
| Runtime | runtime/p3rt.h + p3rt.c | 30 + 58 |
| **Total compiler** | | **882** (970 with runtime) |

Compiler build: `rustc -O --edition 2021 src/main.rs`, about 1 s (std only, no cargo, no crates). Spike compile (k3c + 2 clang -c + link, -O0 -g): well under 1 s.

## Pipeline

lex -> parse (AST; pun `area(p, ...)` becomes label p) -> check (labels must match params in order, types, let/var mutability, capture-free lambda only as `expect_trap(action:)`) -> lower (C-shaped IR, lambdas lifted to `static` functions, interpolation to `p3_fmt`, cleanup push/pop placement) -> emit (readable C with `#line N "spike.p3"` before every statement and function) -> `clang -c` x2 -> link.

Naming: user types keep their name as the C struct (`Point`, `Guard`); functions get `p3_` (`p3_area`); drop is `Guard__drop`; lambdas `p3_lambda_N`. Locals keep source names (C keywords get `_`).

## Trap unwinding: option (b) setjmp/longjmp plus a per-thread cleanup stack

Why (b) over (a) status-return: (a) makes every call site a branch, changes every function signature (out-params for results), and needs a precise live-locals set at every call site. Cost is paid by all code, trap or not. (b) puts the cost only on droppable locals, leaves ordinary functions as plain C functions (debugger/coverage/FFI-friendly), and gives innermost-first order for free because the stack is LIFO. Trade-off: longjmp cannot run drops of non-registered state, and every droppable must be registered.

Mechanism (runtime/p3rt.[ch]):
- Each droppable local `g` gets a `p3_cleanup g__cleanup` node (prev, fn, obj) in its own stack frame, pushed on the thread-local list `p3_top` right after initialisation, popped and run (`p3_pop_run`) at scope exit and before every `return` (value is evaluated into `p3_ret` first, then drops of all live locals innermost first).
- `p3_expect_trap` records `p3_top` as a mark in a `p3_trapframe` (thread-local chain) and calls `setjmp`.
- `p3_trap` walks `p3_top` down to the mark, popping each node before running its drop (so a trap in a drop can't re-run it), then `longjmp`s to the frame. Drops therefore run at the trap point with all frames still intact, innermost first, before the catch. With no frame it runs all drops then prints `trap: msg` to stderr and exits 101.
- State is `_Thread_local` (`p3_top`, trap-frame chain), so it is thread-safe in principle: each thread has its own stack and frames. Not tested with threads (the subset has none).

Non-trap cost: functions without droppable locals: zero. Per droppable local: one push (3 stores into the frame node, 1 TLS load, 1 TLS store) and one pop (1 TLS store, 1 indirect call to the drop thunk, which the program needs anyway). `expect_trap` pays one `setjmp` (about 200 bytes of jmp_buf on the stack, a register save) per call, not per iteration. No per-call branches. Not benchmarked beyond reading the -O0 code; the spike has nothing to time. Known limits: drops of temporaries (a `Guard(...)` never bound by `let`) are not tracked; no move semantics (copying a droppable into a callee would double-drop; the subset has no case); strings are malloc'd and never freed.

## What was awkward

- Interpolation: lexer must find the matching `}` and the parser re-lexes the inside; nested strings inside `{}` are not supported.
- `return` inside nested scopes with droppables: needs the scope stack in lowering to pop every enclosing scope; easy once lowering keeps a per-block list.
- `drop(mut self)`: modelled as `Guard *self`, so field access in drop bodies needs `->` (special case on name `self`).
- C quirks: function-pointer type for the cleanup callback needs a generated thunk per droppable type to avoid casting function types; `(void)` for discarded results.
- Rust itself was easy: first build of ~880 lines compiled with no errors.
- Missing return in a non-Unit function is not diagnosed (C compiler warns at best).

## Debugger (no custom formatters), Linux gdb

Break `spike.p3:19` (the `total += p.x * p.y` line), raw output:
```
Breakpoint 1 at 0x11ea: file /home/jdoxey/Code/jdoxey/lang-repo/docs/examples/compiler/k3-rust-c/build/spike.p3, line 19.
[Thread debugging using libthread_db enabled]
Using host libthread_db library "/lib/x86_64-linux-gnu/libthread_db.so.1".

Breakpoint 1, p3_area (p=..., scale=2) at /home/jdoxey/Code/jdoxey/lang-repo/docs/examples/compiler/k3-rust-c/build/spike.p3:19
19	    total += p.x * p.y
$1 = {x = 3, y = 4}
$2 = 3
total = 0
i = 0
#0  p3_area (p=..., scale=2) at /home/jdoxey/Code/jdoxey/lang-repo/docs/examples/compiler/k3-rust-c/build/spike.p3:19
#1  0x00005555555553a0 in p3_main () at /home/jdoxey/Code/jdoxey/lang-repo/docs/examples/compiler/k3-rust-c/build/spike.p3:35
#2  0x0000555555555454 in main () at /home/jdoxey/Code/jdoxey/lang-repo/docs/examples/compiler/k3-rust-c/build/spike.p3:50
```
Findings: gdb resolves the breakpoint by `spike.p3:19` through the `#line` directive and shows source lines of spike.p3 (it reads build/spike.p3, a copy placed next to the compiler output). `p` prints as `{x = 3, y = 4}` with no pretty printer (plain C struct named `Point`); the function shows as `p3_area` (prefix mangling is visible to users; it would be hidden by a gdb `set` of names or by dropping the prefix for user functions, at the cost of libc collisions). Params print as `p=...` in frames (struct by value), as usual for gdb. Compiling with `-O0` is needed for locals to be reliable. lldb is installed here but not run by the script on Linux; the script uses `lldb -b -o 'breakpoint set -f spike.p3 -l N' -o run -o 'frame variable p'` on macOS (untested).

Windows (untested): driver adds `-g -gcodeview -fuse-ld=lld`; `run.sh` uses `cdb` if present, else `llvm-pdbutil dump -types -lines spike.pdb` and greps for `Point` and `spike.p3`.

## Coverage (clang source-based)

Commands: `k3c --coverage` (adds `-fprofile-instr-generate -fcoverage-mapping` to the generated C only, not the runtime), run with `LLVM_PROFILE_FILE=spike.profraw`, `llvm-profdata merge -sparse`, `llvm-cov report/show exe -instr-profile=... spike_cov.c`.

HONEST RESULT: the report is against the generated C (`spike_cov.c`), NOT `spike.p3`. clang's coverage mapping ignores `#line` presumed locations (it uses the real file, and the `#line` lines appear as uncovered-blank lines in `show`). Per-function counts exist and are correct, and the generated C is readable so mapping by eye works, but real coverage against `.p3` would need a post-processing step that rewrites llvm-cov's JSON (`llvm-cov export`) through the `#line` table, or emitting LLVM IR directly (K1/K2). Also, the runtime header's inline functions appear if not filtered; run.sh restricts to spike_cov.c.

Report:
```
Filename                                                                                  Regions    Missed Regions     Cover   Fu
----------------------------------------------------------------------------------------------------------------------------------
/home/jdoxey/Code/jdoxey/lang-repo/docs/examples/compiler/k3-rust-c/build/spike_cov.c          14                 1    92.86%     
----------------------------------------------------------------------------------------------------------------------------------
```
Line counts for `area` (from `llvm-cov show`, generated-C line numbers):
```
   38|       |#line 15 "spike.p3"
   39|      1|int64_t p3_area(Point p, int64_t scale) {
   40|      1|#line 16 "spike.p3"
   41|      1|    int64_t total = 0;
   42|      1|#line 17 "spike.p3"
   43|      1|    int64_t i = 0;
   44|      1|#line 18 "spike.p3"
   45|      3|    while (i < scale) {
   46|      2|#line 19 "spike.p3"
   47|      2|        total += (p.x * p.y);
   48|      2|#line 20 "spike.p3"
   49|      2|        i += 1;
   50|      2|    }
   51|      1|#line 22 "spike.p3"
   52|      1|    return total;
   53|      1|}
```

## Generated C for `area`
```c
#line 15 "spike.p3"
int64_t p3_area(Point p, int64_t scale) {
#line 16 "spike.p3"
    int64_t total = 0;
#line 17 "spike.p3"
    int64_t i = 0;
#line 18 "spike.p3"
    while (i < scale) {
#line 19 "spike.p3"
        total += (p.x * p.y);
#line 20 "spike.p3"
        i += 1;
    }
#line 22 "spike.p3"
    return total;
}
```

## What each OS needed

- Linux: clang, gdb, llvm-cov, llvm-profdata, rustc. Nothing else. (Tested.)
- macOS (untested): Apple clang works for building; `xcrun llvm-cov` / `xcrun llvm-profdata` are used if not on PATH; Apple clang's profile runtime should be present with Xcode CLT. `lldb -b` for the debugger.
- Windows Git Bash (untested): LLVM at `/c/Program Files/LLVM/bin`; `_Thread_local` and `setjmp/longjmp` under clang with the MSVC target (note: MSVC `longjmp` may run SEH unwinding, harmless for plain C frames but unverified); `-gcodeview -fuse-ld=lld` for a PDB; Rust toolchain needed (`rustc`).
