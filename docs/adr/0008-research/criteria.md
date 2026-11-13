# ADR-0008 criteria (written before the options)

The question: what the compiler is written in, what it emits, and how it gives debug info (G8) and coverage (G9) on
Linux, Windows and macOS (R9). It must implement ADRs 0001–0007: owned values, pools, OS-thread crews, traps that
unwind and run drops, vtables with type descriptors, and the clause desugaring.

## Gates

- **R9:** the compiler builds and runs on all three CI OSes, and so do the programs it produces.
- **ADR-0004:** a trap unwinds and runs drops on all three OSes.
- **G8:** a debugger on each OS can stop at a source line and show a language struct value.

## Scored criteria

| Criterion | Weight | What a 5 means | Anchor |
|---|---|---|---|
| Debugging | 20 | gdb, lldb and Visual Studio/VS Code show source lines, locals and language-level values (`Point{x: 1, y: 2}`, enums, lists, handles) | G8 |
| Three-OS reliability | 15 | Toolchain installs from standard packages on every runner; no per-OS special cases in the compiler | R9 |
| Agent productivity | 15 | The host language catches the agent's mistakes at compile time (exhaustive matches, types), builds fast, and has a tight test loop | project constraint |
| Coverage | 10 | Line and branch coverage reported against *our* source files on all three OSes | G9 |
| Trap and unwind fidelity | 10 | Drops run during trap unwinding with no per-call cost on the non-trap path; thread-safe | ADR-0004, ADR-0003 |
| Transparency | 10 | A developer can see what the compiler made of their code (readable output or a documented IR dump) | R6 |
| Implementation effort | 10 | Fewest lines and moving parts to reach M7; small backend layer | project constraint |
| Generated-code performance | 10 | Optimised output competitive with C | P-C, G2 |

Total = Σ weight × score ÷ 5, computed by script. A gap under 5 is a tie, broken by the examples, then by
reversibility.
