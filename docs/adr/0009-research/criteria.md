# ADR-0009 criteria (written before the options)

The question: what a module is, how code imports code, how a project describes its build, how dependencies (git repos,
per the roadmap) are fetched, versioned and locked, how C libraries are linked (FFI), and how users get the C toolchain
that ADR-0008 needs.

## Gates

- **G3:** the build description is not a macro or annotation system. Only the stdlib and `extras` may use the generic
  dialect (ADR-0002 owner answer), so the build tool must enforce that.
- **R9:** the same project builds on Linux, Windows and macOS with the same commands.
- **ADR-0005 and ADR-0003:** whole-program checks see every linked module, because there is no dynamic loading in v1.

## Scored criteria

| Criterion | Weight | What a 5 means | Anchor |
|---|---|---|---|
| Simplicity | 20 | One obvious project layout; one small data file; few commands; the beginner path is `new`, `build`, `run`, `test` | G1, G7 |
| Reproducibility and security | 20 | The same inputs give the same build on every machine; dependencies are pinned by hash; no code runs at fetch or build time unless declared and visible | G7, R6 |
| Transparency | 15 | A reader can see which code and which version is in the program, and where every name comes from | R6 |
| Install story | 15 | The toolchain, including the C compiler, installs in one step on each OS, with debugging and coverage working | G7, G8, G9, R9 |
| FFI and C interop | 10 | Linking a C library is declarative and works on three OSes | P-C |
| Ecosystem scale | 10 | Diamonds, monorepos, private repos and offline builds all work without special cases | G7 |
| Implementation risk | 10 | Small enough to build in M7 | project constraint |

Total = Σ weight × score ÷ 5, computed by script. A gap under 5 is a tie, broken by the examples, then by
reversibility.
