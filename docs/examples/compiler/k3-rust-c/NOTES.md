# K3: Rust compiler emitting C, built by clang

Status on Linux (Debian clang 19.1.7, gdb, llvm-cov, lldb present): `./run.sh` passes spike.p3, spike2.p3 and uncaught.p3 and ends `k3 spike OK`. Windows and macOS: untested (see Loop 2, risks). Loop 2 changes are in the last section; sections above describe loop 1 and are still accurate unless the loop-2 section says otherwise.

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

Compiler build (loop 1): `rustc -O`, about 1 s. Loop 2: Cargo package, zero dependencies, `cargo build --release --quiet` (~1.7 s, no warnings); Cargo.lock is checked in. Spike compile (k3c + 2 clang -c + link, -O0 -g): well under 1 s.

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

HONEST RESULT (loop 1; loop 2 below adds the remap): the report is against the generated C (`spike_cov.c`), NOT `spike.p3`. clang's coverage mapping ignores `#line` presumed locations (it uses the real file, and the `#line` lines appear as uncovered-blank lines in `show`). Per-function counts exist and are correct, and the generated C is readable so mapping by eye works, but real coverage against `.p3` would need a post-processing step that rewrites llvm-cov's JSON (`llvm-cov export`) through the `#line` table, or emitting LLVM IR directly (K1/K2). Also, the runtime header's inline functions appear if not filtered; run.sh restricts to spike_cov.c.

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

## Loop 2 (review F1, F3, F4, S1, S3, M1)

Sizes (wc -l): ast 67, lexer 66, parser 314, check 231, lower 284, emit 162, covmap 150, main 81 = 1355 Rust; runtime 184 + 44 = 228. Total 1583 (loop 1: 970). The coverage remap is the largest single addition (150).

**Cargo (M1).** `Cargo.toml` (`[[bin]] k3c`, no deps), `Cargo.lock` checked in, `run.sh` does `cargo build --release --quiet` and copies `target/release/k3c` to `build/`. Warnings fixed (none left). `run.sh` prints `clang --version | head -1` (S3): here `Debian clang version 19.1.7 (3+b1)`.

**F1, trap in a drop.** `p3_trap` keeps the message chain in a local of the outermost trap call. Each drop runs under a drop frame (`run_drop`: a trap frame with `is_drop`, its own `setjmp`). A trap inside a drop sees a drop frame on top, appends `; then: <msg>` to the chain, unwinds the drops registered since that frame, and `longjmp`s back to `run_drop`, so only that drop is abandoned and the loop carries on with the next one. Result for spike2: `trapped: first; then: trap in drop`, with `drop inner guard`, `drop bad`, `drop outer guard` all printed. A trap inside an `expect_trap` that itself runs inside a drop is a fresh trap (the nearest frame is a catcher, not a drop frame) and does not corrupt the outer chain, because the chain is per `p3_trap` call and not global.

**F3, crews.** `crew c { c.go(task: fn() {...}) }`. Lowering emits `p3_crew c; p3_crew_begin(&c, ...)` in a C block; `begin` pushes a cleanup node onto the same cleanup stack, whose function joins all children and re-raises. So the brace (`p3_pop_run(&c.node)`), an early `return`, and a trap in the crew body (unwinding) all join before continuing. Each `go` starts one OS thread (`pthread_create`; `_beginthreadex` on Windows) running `task_entry`: its own trap frame, `setjmp`, and the lifted lambda. A child trap runs the child's drops on the child thread, is caught at the entry, stored (message and trap site) in its task record, and the thread ends normally. After the join the parent re-raises the first trapped task in `go` order (ADR-0004 rule 9: "first" is lowest `go` order), via `p3_trap` with the child's original site. If the parent is already unwinding, the re-raise is appended as `; then: ...`. All trap state (`p3_top`, `frame`) is `_Thread_local`; nothing is shared between threads except the task records, which are published by the join. Checked: spike2 output exact; ASan+UBSan clean apart from the known never-freed strings; TSan clean on spike2; an extra test (parent traps inside the crew body while two children run, `return` inside a crew, an uncaught child trap) behaved as described. Limits: locals declared in the crew body are dropped before the join (LIFO cleanup stack); harmless here because lambdas are capture-free, wrong once children may borrow (ADR-0003 rule 2) and would need the crew node registered after the body's locals. No cancellation. Lambdas are capture-free only.

**Uncaught trap.** No frame: all drops run, then `fflush(stdout)`, then stderr `trap: <msg>` and `  at <fn> (<file>:<line>)`, `exit(101)`. The generated call is `p3_trap(msg, "uncaught.p3", 4, "inner")`. The trace is the trap site only (no shadow stack, so no caller frames); a real trace needs either a per-call shadow stack (cost on every call) or backtrace/unwinder support. Checked by `run.sh`: stdout exactly `before` (stdout is a file there), `trap: boom`, `inner`, exit 101.

**S1, enums.** `enum Shape { Circle(r: Int), Rect(w: Int, h: Int) }`, `Shape.Rect(w: 3, h: 4)`, `match s { Circle(r) => ..., Rect(w, h) => ... }` (positional binders, exhaustive, unqualified variant names, arms are expressions). C:
```c
enum Shape_Tag { Shape_Circle, Shape_Rect };
typedef struct Shape { enum Shape_Tag tag; union { struct { int64_t r; } Circle; struct { int64_t w; int64_t h; } Rect; } u; } Shape;
```
`match` is lowered to `switch (tmp.tag)` with the binders as real C locals (so they show in the debugger), and the result in a `match_N` temporary hoisted before the statement; so a `match` may not appear in a `while` condition (checker error), and evaluation order against other side effects in the same statement is not preserved (spike limit).

Debugger on Linux (gdb 16, `-batch`, break `spike2.p3:24`, the `let probe = 0` line), raw:
```
Breakpoint 1, p3_describe (s=...) at .../build/spike2.p3:24
24	  let probe = 0
$1 = {tag = Shape_Rect, u = {Circle = {r = 3}, Rect = {w = 3, h = 4}}}
$2 = Shape_Rect
$3 = {w = 3, h = 4}
s = {tag = Shape_Rect, u = {Circle = {r = 3}, Rect = {w = 3, h = 4}}}      (info args)
```
What this shows: the tag is named (`Shape_Rect`), and gdb prints every union member, including the inactive `Circle = {r = 3}`, which is just the first 8 bytes of the Rect payload reinterpreted (`r` aliases `w`). The user must read the tag to know which one is live; a pretty printer (gdb Python, lldb synthetic provider, natvis) would hide the others. Nothing was needed for the active member to be right. lldb (macOS) and cdb/PDB (Windows) are scripted in `run.sh` for the same line but not run; the lldb check asserts `w = 3` and `h = 4`; the Windows path asserts that the PDB has `Shape` and prints its tag/union members, and tries a real lldb session if available (loop-1 observation: Windows lldb failed to start on the runner).

**F4, coverage against the .p3.** Pipeline: `k3c --coverage` (adds `-fprofile-instr-generate -fcoverage-mapping` to the generated C) -> run -> `llvm-profdata merge` -> `llvm-cov export -format=text` (JSON for the C file) -> `k3c --cov-remap export.json spike_cov.c.map spike.p3 out.lcov`. The compiler writes `<stem>.c.map` with one `<C line> <p3 line>` pair per generated C line that directly follows a `#line` directive (statement starts and function headers; closing braces and `} else {` lines are left out). The remap (src/covmap.rs, own tiny JSON reader, no crates): per-C-line counts from the export's segments with llvm-cov's rule (max of the segment active at the start of the line and the region entries on it; it reproduces `llvm-cov show` exactly on spike_cov.c), folded onto p3 lines by **max** over the C lines of that p3 line; branch regions are attributed to the p3 line of the C line they start on (T/F counts kept, one BRDA pair per branch); functions via their first region. Output: lcov (`SF`, `FN`, `FNDA`, `BRDA`, `DA`) plus this text report, `area` lines (from `build/coverage.txt`, count | branches):
```
  15|    1| fn area(p: Point, scale: Int) -> Int {
  16|    1|   var total = 0
  17|    1|   var i = 0
  18|    3|   while i < scale {  [T2/F1]
  19|    2|     total += p.x * p.y
  20|    2|     i += 1
  21|     |   }
  22|    1|   return total
  23|     | }
lines hit 24/25, branches taken 5/6, functions hit 5/5
```
lcov for area: `DA:15,1 DA:16,1 DA:17,1 DA:18,3 DA:19,2 DA:20,2 DA:22,1`, `BRDA:18,0,0,2`, `BRDA:18,0,1,1`, `FNDA:1,p3_area`. The not-taken branch is `if a > 20` else (line 37 `T1/F0`, line 40 `print "small"` = 0).
Fidelity limits, honestly:
- Several C lines per p3 line: **max, not sum**. Summing would double-count (a statement is `Decl` + `p3_push` + ...). Max is right when all the lines run together; it hides a line whose C lines have different counts (e.g. a `return` that is split into the value, the pops, and the return, if a trap fires between them).
- Lines that carry no `#line`-prefixed C line (closing braces, `else`, the `type` body) have no count; the `drop` function header is attributed to the `type` line (line 8 shows 4), and the drop body line is separate.
- Counts after a call to a `_Noreturn` function are not reduced: `depth` line 30 `return depth(...) + 1` shows 3, the real count is 2 (the n == 0 call traps first). That is clang's coverage mapping, not the remap.
- Branch coverage exists only where clang emits branch regions (`if`, `while`, `&&`, `||`, `?:`); `match` arms are `switch` cases and get line counts but, in this clang version, no branch regions were checked (only spike.p3 is run through the coverage step).
- The runtime is not instrumented (generated code only); counters are non-atomic, so a crew program under coverage can lose counts (not run).
- The JSON reader and the `export` shape (`data[0].files[].segments/branches`, `functions[].regions`) were checked against LLVM 19 only; macOS `xcrun llvm-cov` (Apple's LLVM) and Windows LLVM may differ in field details (e.g. `mcdc_records`, an extra branch-kind). Windows paths are normalised to `/` before matching.

**Non-trap cost (setjmp/cleanup-stack design).** `bench.p3`: `step` has one droppable local and a drop with an observable branch (so it cannot be deleted); the loop calls it 10 million times. "registered" = normal build (push/pop on the thread-local stack plus an indirect call through the thunk); "direct" = `k3c --no-cleanup` (no registration, the drop is a direct call; traps would skip the drops, so benchmark only). Best of 7 wall times on this Linux box (x86-64, clang 19), including about 1 ms of process start; `--no-inline` keeps `step` and the drop as real calls at -O2:

| Build | registered | direct | overhead |
|---|---|---|---|
| -O0 -g (what the spike ships) | 4.7-5.1 ns/call | 1.9-2.0 ns/call | about 3 ns/call |
| -O2, calls kept (`--opt --no-inline`) | 1.4 ns/call | 1.0-1.2 ns/call | about 0.2-0.4 ns/call (inside run-to-run noise of about 0.2) |
| -O2, everything inlined (`--opt`) | 0.5-0.6 ns/call | 0.6-0.7 ns/call | none measurable |

(Without the observable branch in the drop, -O2 deleted the registration entirely and the loop took 0.1-0.2 ns/call.) So the registration is about 3 stores to the frame node, one TLS load and two TLS stores; at -O0 it costs about 3 ns, at -O2 well under 1 ns, and when the optimiser can see the whole path it vanishes. Not measured: a call chain deep enough to matter for cache, `expect_trap` in a loop (one `setjmp` per call, unmeasured; more expensive on macOS where `setjmp` saves the signal mask, which is why the runtime uses `_setjmp` there), the trap path itself.

**setjmp, locals and the optimiser.** The C rule is that a local that is modified after `setjmp` and read after the second return has an indeterminate value unless it is `volatile`. K3 avoids the issue by construction: `setjmp` is called only in three runtime functions (`p3_expect_trap`, `run_drop`, `task_entry`), whose only locals are a trap frame whose address is stored in the thread-local `frame` (so it is memory the callee may modify: the message is written through that pointer before `longjmp`) and values read only on the first-return path. No generated-code local is ever read after a longjmp: the generated frames between the trap and the catcher are abandoned, after their drops have already run, and the only state that survives (message, site) is in the trap frame. clang treats `setjmp` as `returns_twice` and does not inline or optimise across such functions in a way that breaks this; -O0 and -O2 builds both pass. The optimiser cost is on the generated side: a droppable local whose address is stored in the cleanup stack (`&g` escapes through the TLS list) must live in memory and be up to date before any call that can trap, which blocks keeping it in registers or splitting it (SROA) across calls; drops that read the object see the memory value. `p3_push`/`p3_pop_run` are `always_inline` so `-fno-inline` and -O0 do not turn them into calls.

**Windows and macOS, what is untested and why it should or should not work.**
- Windows `setjmp`/`longjmp` (clang, MSVC target, x64): the UCRT `longjmp` unwinds via SEH (`RtlUnwindEx`) from the throw point to the `setjmp` frame, running any `__try/__finally` handlers in between. Our generated frames have none (no C++ objects, no `__try`), so the unwind is a plain stack reset; every function needs unwind data, which clang emits on x64. `_Thread_local` compiles to a native TLS slot (`__declspec(thread)` semantics, in `.tls`), not the stack, so a `longjmp` across frames does not disturb `p3_top` or `frame`; the cleanup nodes are in the abandoned frames but have already been popped (`p3_top` is reset before each drop runs). `_beginthreadex` needs the multithreaded CRT, which clang links by default. Not run. If the CRT's `longjmp` refuses to cross a frame (it can when `/guard:ehcont` or CET shadow stacks are enabled) `__builtin_longjmp` or a status-return fallback would be needed; the runner's clang does not enable them by default.
- Windows debugger: `-gcodeview -fuse-ld=lld` writes `spike.pdb`; the run.sh checks (cdb, else lldb attempt, else `llvm-pdbutil`) are copied from loop 1 and extended to `spike2.pdb`; an anonymous union inside `Shape` may show as `<unnamed-tag>` in the type stream and the grep for its members is informational only.
- macOS: Apple clang, `lldb -b`, `xcrun llvm-cov`; `_Thread_local` is fine on Apple clang; `-pthread` at link. The new lldb asserts for `Shape` (`w = 3`, `h = 4`) are unrun, as is the `_setjmp` switch.
- Cargo and `date +%s%N` (bench step; skipped if not numeric, as on macOS) are the new host requirements.

**What was awkward in loop 2.** Hoisting `match` out of expressions (the lowering needed a pending-statement list and a rule for `while`); making the crew join a cleanup node so that parent traps join children; deciding where the message chain lives (a per-trap local, because a global breaks nested `expect_trap`); the coverage JSON had everything needed but not a per-line count, so the segment rule had to be reimplemented.
