"""Scores (corrected by review-f1.md) for ADR-0006 amendment 1 (issue #4). Run: python3 scores.py"""
W = dict(owner=25, simple=20, read=20, brevity=15, evolve=10, impl=10)
S = {
    # strict, pun f(x) = f(x: x), named function types; parser enforces; +6.1% chars on the corpus
    "F1 strict+pun (as first proposed)": dict(owner=4, simple=3, read=4, brevity=3, evolve=2, impl=3),
    # F1 plus review fixes 1-6: free lambda names, pattern swap guard, strict pun token, iface names, no variadics
    "F1b": dict(owner=4, simple=4, read=4, brevity=3, evolve=3, impl=4),
    # one-parameter calls unlabelled; +1.5%; adding a 2nd (even defaulted) parameter breaks callers; checker, not parser
    "F2 one-param exempt": dict(owner=2, simple=3, read=4, brevity=5, evolve=2, impl=4),
    # function values positional (Swift SE-0111); 8 calls in the corpus; parser can't enforce
    "F3 positional fn values": dict(owner=3, simple=4, read=4, brevity=3, evolve=3, impl=4),
}
def total(s, w=W): return sum(s[k] * w[k] / 5 for k in w)
for n, s in sorted(S.items(), key=lambda x: -total(x[1])): print(f"{total(s):5.1f}  {n}")
print("sensitivity: owner weight 10 (shifted to brevity):")
w2 = dict(W, owner=10, brevity=30)
for n, s in sorted(S.items(), key=lambda x: -total(x[1], w2)): print(f"{total(s, w2):5.1f}  {n}")
