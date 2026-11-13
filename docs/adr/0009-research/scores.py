"""ADR-0009 scores (Opus, before the review). Run: python3 scores.py
Install is scored equal (T1 system clang; the T2/T3 spike is blocked), so it doesn't separate the options."""
W = dict(simple=20, repro=20, transp=15, install=15, ffi=10, eco=10, impl=10)
S = {
    # MVS over tags, /vN paths, deps.sum; all 10 scenarios pass; 96 lines; MVS downgrade surprise in S4
    "B1 MVS": dict(simple=4, repro=5, transp=4, install=3, ffi=4, eco=4, impl=4.5),
    # exact pins with hashes in the manifest; diamond needs a manual pin; S4 (two majors) cannot build; publish order
    "B2 pins": dict(simple=3.5, repro=5, transp=5, install=3, ffi=3.5, eco=2, impl=4.5),
    # semver ranges + backtracking + deps.lock; 191 lines; solver errors show only the last conflict
    "B3 semver": dict(simple=3.5, repro=4, transp=3.5, install=3, ffi=4, eco=4.5, impl=3),
}
def total(s, w=W): return sum(s[k] * w[k] / 5 for k in w)
for n, s in sorted(S.items(), key=lambda x: -total(x[1])): print(f"{total(s):5.1f}  {n}")
w2 = dict(W, transp=25, eco=0)
print("sensitivity (transparency 25, ecosystem 0):")
for n, s in sorted(S.items(), key=lambda x: -total(x[1], w2)): print(f"{total(s, w2):5.1f}  {n}")
