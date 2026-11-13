# ADR-0006 scores (criteria.md weights). total = sum(w*s)/5.
C = ["Unamb", "Read", "Brevity", "Consist", "Errors", "Impl", "DSL"]
W = dict(zip(C, [20, 20, 15, 15, 10, 10, 10]))
S = {
    "P1 braces, Go lines + Kotlin joins": [4, 4, 5, 4, 4, 5, 4],
    "P2 do...end":                         [4, 4, 3, 3, 3, 4, 3],
    "P3 braces, brackets-only continue":  [5, 4, 5, 5, 5, 5, 4],
}
def t(s, w): return sum(w[c] * x for c, x in zip(C, s)) * 20 / sum(w.values())
for o, s in S.items(): print(f"{o}: {t(s, W):.1f}")
for name, w in [(f"{c}{d:+d}", {**W, c: max(0, W[c] + d)}) for c in C for d in (10, -10)] + [("equal", {c: 1 for c in C})]:
    r = sorted(((t(s, w), o) for o, s in S.items()), reverse=True)
    if r[0][0] - r[1][0] < 5 or not r[0][1].startswith("P3"): print(f"  {name}: {r[0][1]} margin {r[0][0]-r[1][0]:.1f}")
