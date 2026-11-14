"""ADR-0005 amendment 1 (issue #5) scores (Opus, before the review). Run: python3 scores.py"""
W = dict(am3=25, owner=20, safety=15, simple=15, ext=10, fit=10, impl=5)
S = {
    # single inheritance, open recursion: one rule ("self and dyn calls may go to an override; overrides say
    # `override`"); 23/44 calls dynamic, max 5 candidates; LoggedNames counts every push; two roles = forwarding
    "H1 single, open": dict(am3=3.5, owner=5, safety=3.5, simple=4.5, ext=3.5, fit=4, impl=4),
    # one stateful + stateless parents, closed recursion with `hook`: two roles natural; two parent chains to check;
    # a forgotten `hook` silently skips an override (CountedNames counted 1 of 4)
    "H2 stateless parents, closed": dict(am3=3.5, owner=4, safety=3, simple=3, ext=4.5, fit=3.5, impl=3),
    # single inheritance, closed recursion: fewest dynamic self-calls, but the same silent miscount as H2
    "H3 single, closed": dict(am3=4, owner=4.5, safety=3, simple=3.5, ext=3.5, fit=4, impl=4),
}
def total(s, w=W): return sum(s[k] * w[k] / 5 for k in w)
for n, s in sorted(S.items(), key=lambda x: -total(x[1])): print(f"{total(s):5.1f}  {n}")
w2 = dict(W, am3=35, owner=10)
print("sensitivity (3 am 35, owner fit 10):")
for n, s in sorted(S.items(), key=lambda x: -total(x[1], w2)): print(f"{total(s, w2):5.1f}  {n}")
