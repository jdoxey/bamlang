"""ADR-0008 scores (Opus, before the review). Run: python3 scores.py"""
W = dict(debug=20, os3=15, agent=15, cov=10, trap=10, transp=10, effort=10, perf=10)
S = {
    # Rust + textual LLVM IR: passes on all three OSes incl. Windows funclets; own DWARF/CodeView; coverage fallback
    "K1 Rust+LLVM IR": dict(debug=4.5, os3=5, agent=4, cov=3, trap=5, transp=3.5, effort=3.5, perf=5),
    # OCaml + textual LLVM IR: Linux and macOS pass; Windows unproven (no OCaml on the Windows runner without Cygwin)
    "K2 OCaml+LLVM IR": dict(debug=4.5, os3=2, agent=4.5, cov=3, trap=4, transp=3.5, effort=4, perf=5),
    # Rust + C: passes on all three OSes; C-level types in the debugger; llvm-cov maps to generated C; setjmp stack
    "K3 Rust+C": dict(debug=3.5, os3=5, agent=4, cov=3.5, trap=3, transp=5, effort=4.5, perf=4.5),
    # after review-k1.md (Fable): F1 trap-in-drop bug (K1, K2), F2 Windows debugger unproven, F3 threads unproven, S1-S7
    "K1 (review)": dict(debug=3.5, os3=4, agent=4, cov=3, trap=4, transp=3.5, effort=3, perf=5),
    "K2 (review)": dict(debug=3.5, os3=3, agent=4.5, cov=3, trap=3.5, transp=3.5, effort=3.5, perf=5),
    "K3 (review)": dict(debug=3, os3=4.5, agent=4, cov=3.5, trap=3.5, transp=5, effort=4, perf=4.5),
    # loop 2, CI 43487717429 / 43488361625. K3: every program and debugger check passes on all three OSes (cdb shows
    # Point and Shape). K1: real llvm-cov with branches, no C++ runtime, Linux/macOS pass; Windows debug info still
    # wrong after two attempts (Win64 ABI); 1717 lines with its own ABI, debug metadata and covmap encoder.
    "K1 loop 2": dict(debug=3, os3=4, agent=4, cov=4.5, trap=4.5, transp=3.5, effort=2.5, perf=5),
    "K3 loop 2": dict(debug=4, os3=5, agent=4, cov=3.5, trap=4, transp=5, effort=4, perf=4.5),
}
def total(s, w=W): return sum(s[k] * w[k] / 5 for k in w)
for n, s in sorted(S.items(), key=lambda x: -total(x[1])): print(f"{total(s):5.1f}  {n}")
w2 = dict(W, debug=10, effort=20)
print("sensitivity (debug 10, effort 20):")
for n, s in sorted(S.items(), key=lambda x: -total(x[1], w2)): print(f"{total(s, w2):5.1f}  {n}")
