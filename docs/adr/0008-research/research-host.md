# D8 research: host language and architecture (Sonnet researcher, 2026-11-14; condensed)

[F] fetched, [S] search summary only, [unverified] from memory. Several fetches failed. Evidence on Odin, Hare, Vale
and Austral is unverified.

## Host languages

- **Rust** (rustc, Cranelift, Gleam).
  - **Roc's move to Zig.** Roc is moving its compiler, about 300k lines, from Rust to Zig. Its reasons: slow builds,
    and Rust's safety doing little for a compiler whose allocation lifetimes are simple. The change is confounded with
    a planned redesign. [S] https://weeklyrust.substack.com/p/why-roc-is-moving-away-from-rust
  - **inkwell** [F] https://github.com/TheDan64/inkwell:
    - supports LLVM 12–23 behind feature flags (`llvm19-1`);
    - is pre-1.0;
    - says nothing about Windows. Linking LLVM is the usual Windows pain [unverified].
- **OCaml** (the first Rust compiler [S], Hack, Flow, Haxe, ReScript and Coq [unverified]).
  - It has the best AST ergonomics and very fast builds.
  - **LLVM bindings** [S] https://ocaml.org/p/llvm:
    - `llvm.19-static` builds on OCaml 5.2–5.5;
    - Debian ships `libllvm-19-ocaml-dev`;
    - nothing exists for LLVM 20+, and Windows is doubtful.
  - **Expect tests:** ppx_expect gives inline expect tests [F] https://github.com/janestreet/ppx_expect.
- **Go.**
  - **The 1.5 translation.** Go 1.5 machine-translated its C compiler into Go. The translation found bugs, the
    compiler was 2x slower at first, and building Go now needs an existing Go [F] https://go.dev/doc/go1.5.
  - **Strengths and weaknesses:** single binaries and fast builds; no sum types.
- **C/C++** (Clang, GCC, Odin, Jai): native LLVM, but the C++ API is unstable, and there is no safety and no pattern
  matching.
- **Zig** [F] https://ziglang.org/news/goodbye-cpp/:
  - The 80k-line C++ compiler was replaced, because every feature had to be built twice.
  - It bootstraps through a committed wasm blob turned into C.
  - Peak memory fell from 11.3 to 3.8 GiB.
  - The language is still changing.
- **Swift:** its Windows support is the least mature [unverified].

## Self-hosting

- **Costs:** Zig's two-compiler period doubled the work for every feature; Go's translation was slow and needs an
  existing Go; Rust's bootstrap chain is long [S].
- **Verdict:** defer self-hosting. It is not a goal, and the language is still changing.

## Architecture

- **Queries.** rustc's query system [F] https://rustc-dev-guide.rust-lang.org/query.html memoizes results and tracks
  dependencies. It is fiddly: values are cloned on every hit, and the move from passes was unfinished as of 2021.
  Salsa [F] https://github.com/salsa-rs/salsa churns.
- **For a small compiler:** use a plain multi-IR pipeline (parse, AST, resolve, typed IR, borrow-check, lowered IR,
  backend). Make each stage a pure function over immutable data keyed by stable ids, with spans on every node and
  recovery at item and statement boundaries. Run the whole-program checks first (the call-graph analyses are
  whole-program anyway).

## Testing

- **Snapshot tests** suit an agent, because the diff shows exactly what changed: insta [F] https://insta.rs/,
  ppx_expect, or golden files with `--update`.
- **Csmith-style differential testing** [F] https://github.com/csmith-project/csmith needs a reference interpreter.
  Differential testing against a small interpreter on the corpus is the highest-value test for codegen.

## AI-agent angle

- No study compares host languages. Rust compiler feedback cut non-compiling output from 20.7% to 13.1% [S]
  https://arxiv.org/html/2512.02567v1.
- Exhaustive matching (OCaml, Rust) exposes every site a new variant touches.
- Rust's borrow checker costs iterations on tree code unless arenas with ids are used.

## Risks

1. LLVM on Windows and macOS CI, and version mismatches with the bindings.
2. Bindings pinned to one LLVM version.
3. Borrow-checker friction in Rust.
4. Slow builds of the compiler itself (Rust, C++).
5. Building self-hosting or queries too early.

**Researcher's lean:**
- **First:** Rust with arenas, pinned to LLVM 19.
- **Runner-up:** OCaml, with the best ergonomics and the weakest Windows LLVM.
- **Either way:** spike LLVM linking on all three OSes first.
