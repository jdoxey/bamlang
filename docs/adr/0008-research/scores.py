"""ADR-0008 scores (Opus, before the review). Run: python3 scores.py"""
W = dict(debug=20, os3=15, agent=15, cov=10, trap=10, transp=10, effort=10, perf=10)
S = {
    # Rust + textual LLVM IR: passes on all three OSes incl. Windows funclets; own DWARF/CodeView; coverage fallback
    "K1 Rust+LLVM IR": dict(debug=4.5, os3=5, agent=4, cov=3, trap=5, transp=3.5, effort=3.5, perf=5),
    # OCaml + textual LLVM IR: Linux and macOS pass; Windows unproven (no OCaml on the Windows runner without Cygwin)
    "K2 OCaml+LLVM IR": dict(debug=4.5, os3=2, agent=4.5, cov=3, trap=4, transp=3.5, effort=4, perf=5),
    # Rust + C: passes on all three OSes; C-level types in the debugger; llvm-cov maps to generated C; setjmp stack
    "K3 Rust+C": dict(debug=3.5, os3=5, agent=4, cov=3.5, trap=3, transp=5, effort=4.5, perf=4.5),
}
def total(s, w=W): return sum(s[k] * w[k] / 5 for k in w)
for n, s in sorted(S.items(), key=lambda x: -total(x[1])): print(f"{total(s):5.1f}  {n}")
w2 = dict(W, debug=10, effort=20)
print("sensitivity (debug 10, effort 20):")
for n, s in sorted(S.items(), key=lambda x: -total(x[1], w2)): print(f"{total(s, w2):5.1f}  {n}")
