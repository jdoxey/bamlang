"""ADR-0007 scores (Opus, before the review). Run: python3 scores.py"""
W = dict(read=20, transp=20, simple=15, general=15, errors=10, fit=10, impl=10)
S = {
    # clause items in list literals; children are a labelled list field; +12% chars from ADR-0006 amendment 1
    "D1 clauses": dict(read=4, transp=5, simple=4, general=4, errors=4, fit=5, impl=4),
    # no grammar change; take-self setter chains; +28% chars after labelling; a missing leading `.` parses silently
    "D3 pipelines": dict(read=2, transp=4, simple=4, general=3, errors=2, fit=4, impl=5),
    # D2 variadic is ineligible: ADR-0006 amendment 1 forbids positional items after named arguments
}
def total(s, w=W): return sum(s[k] * w[k] / 5 for k in w)
for n, s in sorted(S.items(), key=lambda x: -total(x[1])): print(f"{total(s):5.1f}  {n}")
w2 = dict(W, read=10, impl=20)
print("sensitivity (readability 10, impl 20):")
for n, s in sorted(S.items(), key=lambda x: -total(x[1], w2)): print(f"{total(s, w2):5.1f}  {n}")
