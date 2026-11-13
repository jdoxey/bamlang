# Build plan (M0–M7)

Written after ADR-0008. Every milestone ends with its exit tests passing in CI on Linux, Windows and macOS, and then a
tick in `docs/ROADMAP.md`.

## Ground rules

- **Layout.**
  - `compiler/`: one Cargo package, no third-party crates; the binary is `p3c` until D12 names the language.
  - `runtime/`: C11.
  - `tests/`: conformance.
  - `editors/` and `debug/`: formatters, from M7.
- **Pipeline (ADR-0008):** `lex`, `parse` (AST with spans), `resolve`, `check` (types, ownership, borrows,
  whole-program call graphs), `lower` (lowered IR: explicit drops, cleanup registration, trap calls, resolved labelled
  calls), `emit_c`, then `clang`. Each stage is a pure function over the previous stage's data.
- **Conformance (append-only).** `tests/corpus/` holds the source programs; `tests/expected/` the expected AST, output,
  stderr and exit code; `tests/bad/` the programs that must fail, each with its first line
  `# expect: LINE: substring`. Never weaken or delete a conformance test to make it pass. A wrong test is fixed only in
  a commit that says why and points to the ADR.
- **Golden files** update with `cargo run -p p3c-tests -- --update`, and every update diff is reviewed before it is
  committed.
- **Each milestone** also adds its own unit tests (`cargo test`) and leaves `docs/STATE.md` pointing at the next one.
- **The decisions D9–D12** are made just before the milestone that needs them: D9 before M7, D10 before M6, D11 before
  M7, D12 any time.

## M0: conformance harness

- **Work:**
  - Copy `docs/examples/syntax/p3n/corpus/*.p3`, `expected/*.ast` and `bad/` into `tests/`, keeping the
    meaning-check and label-check scripts as references.
  - Add `tests/run`, a Rust test binary that runs every case through a given stage and compares against golden files.
  - Wire it into `ci/run.sh`.
- **Exit:**
  - The harness runs on three OSes.
  - With no compiler yet, it reports every case as "not implemented" and passes only in `--allow-missing` mode, which
    CI uses until M1.

## M1: lexer and parser

- **Work:**
  - The full ADR-0006 grammar, with amendment 1 and ADR-0007 clauses, ported from the Python parsers
    (`p3n/parser.py`, `dsl/d1-clauses/parser.py`).
  - The same AST printer, so the expected ASTs match byte for byte.
  - Error recovery at item and statement boundaries; indentation hints only on the error path.
- **Exit:**
  - Every `tests/corpus` AST matches.
  - Every `tests/bad` file fails at the right line with the right substring.
  - CRLF variants match.
  - The parser is fuzzed for 60 s without a panic.
  - `--allow-missing` is removed for the parser stage.

## M2: resolver and checker

- **Work:**
  - Names, modules, types, interfaces and `impl`s.
  - Labelled-argument checks (amendment 1 rules 1–7).
  - Ownership: moves, `.copy()`, call-length borrows, exclusivity (ADR-0001).
  - `fails`/`try` rules (ADR-0004).
  - Receiver modes (ADR-0005).
  - Clause typing (ADR-0007).
  - The whole-program checks: main-thread module state (ADR-0001 rule 6), crew captures (ADR-0003), `dyn` impls
    (ADR-0005 rule 9).
  - Unreachable and unused-value errors (ADR-0006 F9).
- **Exit:**
  - A `tests/check/` suite of at least 150 small programs, each either accepted or rejected with an expected message.
    It includes every "expected compile error" recorded in the ADR examples (ADR-0005 `t3plus`, ADR-0007 `check_bad`).

## M3: code generation, hello world

- **Work:**
  - The lowered IR and the C emitter, with `#line`.
  - The runtime: print, strings, traps with the cleanup stack (ADR-0008 rule 4), the uncaught-trap trace.
  - The driver that calls `clang` per OS.
  - `--emit-c`.
- **Exit:**
  - `hello.p3`, `docs/examples/compiler/spike.p3`, `spike2.p3` (without crews) and `uncaught.p3` give the expected
    output on three OSes.
  - A scripted gdb, lldb and cdb session shows a struct value.

## M4: memory model and containers

- **Work:**
  - Drops, moves and drop flags.
  - `Pool`/`Handle`/`Id` with generations and owner cascades.
  - Run-time borrow flags.
  - The built-in containers (List, Array, Map, Set, SortedMap, Deque, Heap, Lru, Optional, Result, tuples).
  - `Error`, `Report`, `Txn`.
  - Valgrind, or ASan with LeakSanitizer, clean in CI on Linux.
- **Exit:**
  - `chatsim` written in the language (from `docs/examples/syntax/p3n/corpus/chatsim.p3`, made runnable) passes
    `docs/examples/chatsim/script.txt` against `expected.txt` on three OSes.
  - So do `widgets`, `errors` and `types`.

## M5: threads

- **Work:**
  - Crews on OS threads, cancellation, channels, `Mutex`/`lock`, `Atomic`.
  - Lock-while-blocking traps, poisoning.
  - Debug wait-for-cycle detection and the release thread dump (ADR-0003).
- **Exit:**
  - `spike2.p3` with crews, the `docs/examples/threads` programs rewritten in the language, and a TSan-clean run on
    Linux.

## M6: standard library v1

- **Work:** what D10 scopes, at the container quality bar from ADR-0002's owner answer: benchmarks against C++ and Rust
  equivalents, docs, conformance tests. It also includes the DSL libraries (`docs/examples/dsl/lib/`) at the scope D10
  sets.
- **Exit:** the D10 checklist passes, with benchmarks reported in CI.

## M7: tools

- **Work:**
  - The build and dependency tool (D9).
  - `test` (G10).
  - `cover`: the llvm-cov remap to source files (ADR-0008 rule 7).
  - `debug`: gdb, lldb and natvis formatters for List, Map, Handle, enums and `dyn` (ADR-0008 rule 6).
  - `fmt` (ADR-0006).
- **Exit:**
  - A new project is created, built, tested, covered and debugged with the language's own tools on three OSes, by a
    script in CI.
  - The formatters show `List of Int = [1, 2, 3]`, a live Handle's target, and an enum's active variant only.
