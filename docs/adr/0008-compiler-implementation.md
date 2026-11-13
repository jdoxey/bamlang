# ADR-0008: Compiler implementation

- **Status:** Accepted
- **Date:** 2026-11-14
- **Tier:** Full (see `docs/PROCESS.md`)
- **Examples:** `docs/examples/compiler` (K3 in `k3-rust-c/`; rivals in `k1-rust-llvm/`, `k2-ocaml-llvm/`; programs `spike.p3`, `spike2.p3`, `uncaught.p3`)
- **Decided by:** Claude (ruling R7). John may veto by opening an issue.

## Context

ADRs 0001–0007 fixed what the compiler must implement:
- owned values and pools;
- OS-thread crews;
- traps that unwind and run drops, caught only at `try crew` and `expect_trap`;
- vtables and type descriptors;
- labelled arguments;
- clause desugaring.

The charter also needs debugging tools (G8) and coverage tools (G9), both on Linux, Windows and macOS (R9). The
compiler is written about 95% autonomously by an AI agent. This ADR decides the host language, what the compiler
emits, and how traps, debug info and coverage work.

## Charter

| Goal / problem | Effect | Why |
|---|---|---|
| G8 | serves | A scripted session on every OS (gdb, lldb, cdb) stops at a `.p3` line and shows `Point{x: 3, y: 4}` and an enum's tag and payload |
| G9 | serves, with a strain | llvm-cov counts are remapped to `.p3` lines through the compiler's line table. Lines and branches work; several C lines on one source line are folded with max. |
| R9 | serves | Every check passes on ubuntu-24.04 (clang 18), windows-2025 (clang 20, MSVC target) and macos-26 (Apple clang 21) |
| G1 (R6) | serves | The emitted C is readable, so a developer can see exactly what their code became |
| G2, P-C | serves | Native code from `clang -O2`. The trap mechanism costs 0.2–0.4 ns per call with a droppable local, which is within noise. |
| G7 | strains | Users need clang (the LLVM installer on Windows, Xcode tools on macOS). D9 decides whether to bundle it. |

## Criteria

From `0008-research/criteria.md`, written before the options.

**Gates:**
- R9;
- ADR-0004 unwinding with drops;
- a G8 debugger session on each OS.

| Criterion | Weight |
|---|---|
| Debugging | 20 |
| Three-OS reliability | 15 |
| Agent productivity | 15 |
| Coverage | 10 |
| Trap fidelity | 10 |
| Transparency | 10 |
| Implementation effort | 10 |
| Generated-code performance | 10 |

## Options considered

There were 12 ideas (`0008-research/ideas.md`, `analysis.md`).
- **Ruled out:**
  - the LLVM C API (bindings on three OSes);
  - Go (no sum types);
  - two backends at once;
  - a Python compiler;
  - Zig or wasm output;
  - Cranelift (no unwinding on Windows or macOS);
  - an interpreter-only v1;
  - early self-hosting;
  - QBE (no Windows, no debug info).
- **Finalists (a spike compiler each):**
  - **K1:** Rust emitting textual LLVM IR.
  - **K2:** OCaml emitting textual LLVM IR.
  - **K3:** Rust emitting C.

## What the real examples taught

See `0008-research/lessons-and-scores.md`, `review-k1.md` and each spike's `NOTES.md`. All three compile the same
programs. `spike2.p3` and `uncaught.p3` were added after the review:
- an enum shown in the debugger;
- a trap inside a drop during unwinding;
- a trap in a crew child, re-raised in the parent;
- an uncaught trap that must keep stdout and print a trace.

- **Loop 1.** All three passed on Linux and macOS. K1 and K3 also passed on Windows; K2 couldn't run there.
- **The review (Fable 5.2):**
  - K1 and K2 skipped drops when a drop trapped during unwinding. K3 was the only correct one.
  - No option had a real Windows debugger session.
  - Threads were unproven.
  - LLVM IR by-value structs break the C ABI.

  The corrected scores were a three-way tie.
- **Loop 2 (CI 43487717429, 43488361625):**
  - **K3 passes every check on all three OSes.** cdb on Windows shows `p [Type: Point]` with `x : 3`, `y : 4`, and
    `s [Type: Shape]` with `tag : Shape_Rect`. lldb on macOS shows `Rect = (w = 3, h = 4)`. Crews, the drop chain and
    the uncaught trace work everywhere.
  - **K1 dropped the C++ runtime and works on Linux and macOS.** It uses forced unwind there and SEH funclets on
    Windows, and emits real llvm-cov mappings with branches. But after two attempts, cdb on Windows still shows `p` as
    `Point * = 0x3`: owning the Win64 ABI and CodeView details is error-prone, and clang gets them right for free.
  - **K3's cleanup stack costs 3 ns per call at `-O0` and 0.2–0.4 ns at `-O2`** with a droppable local (10M-call
    benchmark), and nothing when inlined. That answers the review's per-scope cost objection.

## Decision

**Adopt K3: the compiler is written in Rust and emits C, which `clang` compiles on every OS.**

1. **Host.**
   - Rust, as a Cargo package with **no third-party dependencies**.
   - Tests use `cargo test` plus golden files with an update flag, so a conformance diff is one command to review.
2. **Pipeline.**
   - Stages: parse to AST, resolve, type and borrow check, then lower to a **lowered IR** (explicit drops, cleanup
     registration, trap calls and labelled calls already resolved).
   - **The C emitter is the only backend in v1.**
   - The lowered IR is the boundary that keeps an LLVM IR emitter possible later (K1's coverage encoder and unwind
     work are kept in `k1-rust-llvm/` for that).
   - Every node carries a span. The whole-program checks (ADR-0003 and ADR-0005 call graphs) run after resolution.
3. **Emitted C.**
   - C11, compiled by `clang` (MSVC target on Windows), with `#line "file.p3" N` on every statement.
   - Names are prefixed (`p3_area`, `Point`, `Shape_Tag`).
   - No undefined behaviour is relied on: wrapping and overflow are explicit runtime calls, and aliasing follows
     ADR-0001's exclusivity.
   - A `--emit-c` flag shows the output (R6).
4. **Traps** (ADR-0004).
   - A thread-local cleanup stack: each droppable local registers after initialisation and unregisters at scope exit.
   - `expect_trap` and `try crew` use `setjmp`; `p3_trap` runs the registered drops down to the mark, then
     `longjmp`s.
   - A trap in a drop during unwinding is appended to the chain (`; then: …`), and unwinding continues.
   - No catcher: flush stdout, print `trap: <msg>` and the trace to stderr, and exit 101.
   - A C callback that a trap would cross aborts (D9 FFI rule).
5. **Crews** (ADR-0003). Each `go` is an OS thread (pthreads or `_beginthreadex`). A child's trap is caught at its
   entry and re-raised in the parent after the join, and the join is itself a cleanup node.
6. **Enums** are `struct { Tag tag; union { … } u; }`. Debuggers show the tag and every member, and the formatters
   (gdb Python, lldb Python, natvis) hide inactive members. The formatters are M-phase work, and every layout change
   updates all three.
7. **Coverage** uses clang's source-based coverage on the generated C, then `llvm-cov export` remapped through the
   compiler's `.map` line table to an lcov file and a report against `.p3` files. It is wrapped as `lang cover`
   (D11). Counters are made atomic before crews ship.
8. **Debugging.** The DWARF/PDB comes from clang. CI runs a scripted gdb, lldb and cdb session for every debugger
   check, and asserts the values shown.

### Scores (`0008-research/scores.py`)

| Option | Debug | 3 OS | Agent | Cov | Trap | Transp | Effort | Perf | Total |
|---|---|---|---|---|---|---|---|---|---|
| **K3 Rust → C (loop 2)** | 4 | 5 | 4 | 3.5 | 4 | 5 | 4 | 4.5 | **85** |
| K1 Rust → LLVM IR (loop 2) | 3 | 4 | 4 | 4.5 | 4.5 | 3.5 | 2.5 | 5 | 76 |
| K2 OCaml → LLVM IR (review) | 3.5 | 3 | 4.5 | 3 | 3.5 | 3.5 | 3.5 | 5 | 73.5 |

The margin is 9, and 10 with debug at 10 and effort at 20. That reverses the pre-review order (K1 85, K3 82). Both
the review and loop 2 moved the evidence toward K3.

## Consequences

**Easier:**
- clang owns the per-target ABI, debug formats and object files.
- FFI to C is natural (D9).
- The output is readable.
- The same flags work on three OSes.
- An LLVM emitter can be added later behind the lowered IR.

**Harder:**
- Coverage is a remap, so its fidelity has limits (max per line; a count after a `noreturn` call isn't reduced).
- Language-level values need formatters in three formats.
- Every droppable local's address escapes into the cleanup stack, which costs some optimisation.
- `setjmp` per catcher.
- The emitter must never produce C with undefined behaviour.

**Ruled out:**
- The LLVM C API, Cranelift, QBE, our own backend, and early self-hosting.
- OCaml as host. Its design matched K1's backend, and building on the Windows runner was impractical (Cygwin
  hijacked the shell).

**Passed on:**
- **D9:**
  - whether to bundle clang and lld, or require them, per OS (G7);
  - the FFI rule that traps never cross C frames.
- **D10:** formatters for List, Map, Handle and enums.
- **D11:** `lang test`, `lang cover`, `lang debug` wrappers.
- **M1–M7:** follow `docs/PLAN.md`.

## Syntax budget impact

None. This is an implementation decision.

## Adversarial review log

| Review | Findings | Outcome |
|---|---|---|
| `0008-research/review-k1.md` (Fable 5.2) | F1 trap in drop skips drops (K1, K2); F2 no Windows debugger session; F3 threads unproven; S1 enums in lldb and CodeView; S2 by-value ABI; S3 versions; S4 install story; S5 trap ABI; S6 K2 judged on host; S7 coverage fallback | Loop 2 on K1 and K3 with `spike2.p3` and `uncaught.p3`. cdb and lldb were enabled on Windows; versions recorded. K3 passed everything; K1 kept a Windows debug-info bug. Decision moved to K3. |
