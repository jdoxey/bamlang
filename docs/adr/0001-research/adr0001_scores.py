# ADR-0001 score, sensitivity and single-cell-flip calculator.
# total = sum(w*s) * 20 / sum(w)  (equals sum(w*s)/5 when weights sum to 100)
CRIT = ["Simp", "Safety", "Expr", "Impl", "Perf", "Conc", "Tool"]
BASE_W = {"Simp": 25, "Safety": 15, "Expr": 15, "Impl": 15, "Perf": 10, "Conc": 10, "Tool": 10}
S = {
    "O1": [4, 5, 5, 5, 3, 2, 4],
    "O2": [3, 5, 2, 3, 4, 4, 3],
    "O3": [3, 4, 5, 3, 4, 3, 4],
    "O4": [3, 4, 5, 4, 5, 4, 5],
    "O5": [1, 5, 4, 1, 5, 5, 5],
    "O6": [3, 4, 4, 4, 3, 4, 3],
    "O7": [5, 5, 5, 3, 2, 1, 3],
    "O8": [2, 2, 4, 4, 5, 2, 3],
}
ELIGIBLE = ["O1", "O2", "O3", "O4", "O6", "O8"]   # O5 fails G3; O7 pending G2 ruling

def total(scores, w):
    return sum(w[c] * s for c, s in zip(CRIT, scores)) * 20 / sum(w.values())

def winner(scores_by_opt, w, pool=ELIGIBLE):
    t = {o: round(total(scores_by_opt[o], w), 1) for o in pool}
    best = max(t.values())
    return [o for o in pool if t[o] == best], t

print("BASE")
for o in S:
    raw = sum(BASE_W[c] * s for c, s in zip(CRIT, S[o]))
    print(f"{o} raw={raw} total={total(S[o], BASE_W):.1f}")

variants = [("Base", dict(BASE_W))]
for c in CRIT:
    for d in (+10, -10):
        w = dict(BASE_W); w[c] = max(0, w[c] + d)
        variants.append((f"{c} {w[c]}", w))
variants.append(("All equal", {c: 1 for c in CRIT}))

print("\nWEIGHT SENSITIVITY (eligible winner excludes O5, O7)")
order = ["O1", "O4", "O3", "O6", "O2", "O8", "O7", "O5"]
print("Variant | " + " | ".join(order) + " | Eligible winner")
for name, w in variants:
    win, _ = winner(S, w)
    row = [f"{total(S[o], w):.1f}" for o in order]
    print(f"{name} | " + " | ".join(row) + " | " + " = ".join(win))

print("\nSINGLE-CELL FLIPS at base weights (one score +/-1 changes or ties the eligible winner)")
base_win, _ = winner(S, BASE_W)
for o in S:
    for i, c in enumerate(CRIT):
        for d in (+1, -1):
            v = S[o][i] + d
            if v < 1 or v > 5:
                continue
            S2 = {k: list(x) for k, x in S.items()}
            S2[o][i] = v
            win, t = winner(S2, BASE_W)
            if win != base_win:
                top = sorted(t.items(), key=lambda kv: -kv[1])[:2]
                print(f"{o} {c} {S[o][i]}->{v}: winner {' = '.join(win)} "
                      f"({top[0][0]} {top[0][1]}, {top[1][0]} {top[1][1]})")

print("\nALTERNATIVE READINGS (base weights)")
alt = {k: list(v) for k, v in S.items()}
alt["O3"][2] = 4; alt["O4"][2] = 4   # also charge escaping-capture traps under Expressiveness
print("Capture traps also charged to Expr (O3=O4=4): " +
      ", ".join(f"{o} {total(alt[o], BASE_W):.1f}" for o in ["O1", "O4", "O3"]))
o1plus = [3, 4, 5, 3, 3, 2, 4]  # O1 user types + CoW value List/Map/String (not one of the eight)
print(f"O1+ (ARC objects + CoW value containers): {total(o1plus, BASE_W):.1f}")
