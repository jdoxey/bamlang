# ADR-0004 scores (criteria.md weights). total = sum(w*s)/5.
C = ["Ignore", "Transp", "Simp", "Syntax", "Context", "Fit", "Impl", "Perf"]
W = dict(zip(C, [20, 20, 15, 15, 10, 10, 5, 5]))
S = {
    "E1 fails+try, one Error":   [5, 5, 4, 3, 4, 4, 4, 5],
    "E2 Result+check, one Error": [4, 5, 4, 2, 4, 5, 5, 5],
    "E3 typed enums + ?":        [4, 4, 2, 4, 3, 3, 4, 5],
}
def t(s, w): return sum(w[c] * x for c, x in zip(C, s)) * 20 / sum(w.values())
for o, s in S.items(): print(f"{o}: {t(s, W):.1f}")
for name, w in [(f"{c}{d:+d}", {**W, c: max(0, W[c] + d)}) for c in C for d in (10, -10)] + [("equal", {c: 1 for c in C})]:
    r = sorted(((t(s, w), o) for o, s in S.items()), reverse=True)
    print(f"  {name}: {r[0][1][:2]} {r[0][0]:.1f}, margin {r[0][0]-r[1][0]:.1f}")
