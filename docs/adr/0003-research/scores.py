# ADR-0003 scores (criteria.md). total = sum(w*s)/5, weights sum to 100.
C = ["Race", "Transp", "Simp", "Deadlock", "Expr", "Impl", "Perf", "Debug"]
W = dict(zip(C, [20, 20, 20, 10, 10, 10, 5, 5]))
S = {
    "F1 crew":           [5, 4, 4, 4, 4, 3, 5, 4],
    "F2 scope + spawn":  [5, 4, 3, 3, 4, 3, 5, 3],
    "F3 main + offload": [5, 3, 4, 4, 3, 3, 4, 4],
}
def t(s, w): return sum(w[c] * x for c, x in zip(C, s)) * 20 / sum(w.values())
for o, s in S.items(): print(f"{o}: {t(s, W):.1f}")
print("sensitivity (each weight +/-10, equal):")
for name, w in [("base", W)] + [(f"{c}{d:+d}", {**W, c: max(0, W[c] + d)}) for c in C for d in (10, -10)] + [("equal", {c: 1 for c in C})]:
    r = sorted(((t(s, w), o) for o, s in S.items()), reverse=True)
    print(f"  {name}: {r[0][1]} {r[0][0]:.1f}, margin {r[0][0]-r[1][0]:.1f}")
