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
    # after review-b1.md (Fable): F1 hash coverage, F2 per-OS hashes, F3 majors undefined, S1-S9
    "B1 (review)": dict(simple=3.5, repro=3.5, transp=3.5, install=2.5, ffi=2.5, eco=3, impl=4),
    "B2 (review)": dict(simple=3.5, repro=4, transp=4.5, install=2.5, ffi=2.5, eco=2.5, impl=4.5),
    "B3 (review)": dict(simple=3, repro=3.5, transp=3.5, install=2.5, ffi=2.5, eco=3.5, impl=3),
    "B1+ (projected)": dict(simple=3.5, repro=4.5, transp=4.5, install=2.5, ffi=3, eco=3.5, impl=3.5),
}
def total(s, w=W): return sum(s[k] * w[k] / 5 for k in w)
for n, s in sorted(S.items(), key=lambda x: -total(x[1])): print(f"{total(s):5.1f}  {n}")
w2 = dict(W, transp=25, eco=0)
print("sensitivity (transparency 25, ecosystem 0):")
for n, s in sorted(S.items(), key=lambda x: -total(x[1], w2)): print(f"{total(s, w2):5.1f}  {n}")
