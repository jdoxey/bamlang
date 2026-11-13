# ADR-0001 rubric v2 scores (see rubric-v2.md). total = sum(w*s)/5, weights sum to 100.
CRIT = ["Transp", "Simp", "Safety", "Conc", "Expr", "Impl", "Perf", "Tool"]
W = dict(zip(CRIT, [20, 20, 15, 15, 10, 10, 5, 5]))
S = {
    # Final cells after the adversarial review (review-o9.md) and the widgets example.
    "O1 pure ARC":           [2, 3, 3, 2, 5, 4, 3, 4],
    "O4 ownership + shared": [3, 2, 5, 5, 3, 2, 3, 5],
    "O9-S values + pools":   [4, 3, 5, 4, 3, 3, 4, 4],
}
def total(s, w): return sum(w[c] * x for c, x in zip(CRIT, s)) * 20 / sum(w.values())
print("Option | " + " | ".join(CRIT) + " | Total")
for o, s in S.items(): print(o, "|", " | ".join(map(str, s)), "|", f"{total(s, W):.1f}")
print("\nWeight sensitivity (each weight +/-10, and all equal): winner, margin")
vs = [("base", W)] + [(f"{c}{d:+d}", {**W, c: max(0, W[c] + d)}) for c in CRIT for d in (10, -10)] + [("equal", {c: 1 for c in CRIT})]
for name, w in vs:
    t = sorted(((total(s, w), o) for o, s in S.items()), reverse=True)
    print(f"{name}: {t[0][1]} {t[0][0]:.1f}, next {t[1][1]} {t[1][0]:.1f}, margin {t[0][0]-t[1][0]:.1f}")
print("\nLargest single-cell drop for O9 that still leaves it ahead by 5+:")
base = {o: total(s, W) for o, s in S.items()}
for i, c in enumerate(CRIT):
    s = list(S["O9-S values + pools"]); s[i] = max(1, s[i] - 2)
    t = total(s, W); rival = max(v for o, v in base.items() if not o.startswith("O9-S"))
    print(f"O9 {c} -2 -> {t:.1f} (rival {rival:.1f}, {'ahead' if t - rival >= 5 else 'TIE/LOSS'})")
