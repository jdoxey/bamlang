"""ADR-0007 scores. Pre-review rows kept; loop-2 rows after review-d1.md and the C1 baseline build. Run: python3 scores.py"""
W = dict(read=20, transp=20, simple=15, general=15, errors=10, fit=10, impl=10)
S = {
    # clause items in list literals; children are a labelled list field; +12% chars from ADR-0006 amendment 1
    "D1 pre-review": dict(read=4, transp=5, simple=4, general=4, errors=4, fit=5, impl=4),
    # no grammar change; take-self setter chains; +28% chars after labelling; a missing leading `.` parses silently
    "D3 pre-review": dict(read=2, transp=4, simple=4, general=3, errors=2, fit=4, impl=5),
    # loop 2: D1 with review fixes (nesting, binding clauses, no rewind, normative desugaring, declared libs, copies)
    "D1 loop 2": dict(read=4, transp=4.5, simple=4, general=4, errors=4, fit=4, impl=4),
    # loop 2: C1 baseline, no new syntax; view() builds kids with push statements and map, so the tree shape is lost
    "C1 baseline (built)": dict(read=2.5, transp=5, simple=5, general=3.5, errors=4.5, fit=4, impl=5),
    # D3 as corrected by the review (illegal corpus: generic children_of, field/method clash)
    "D3 (review)": dict(read=2, transp=3.5, simple=3, general=3, errors=2, fit=3, impl=5),
    # D2 variadic is ineligible: ADR-0006 amendment 1 forbids positional items after named arguments
}
def total(s, w=W): return sum(s[k] * w[k] / 5 for k in w)
for n, s in sorted(S.items(), key=lambda x: -total(x[1])): print(f"{total(s):5.1f}  {n}")
w2 = dict(W, read=10, impl=20)
print("sensitivity (readability 10, impl 20):")
for n, s in sorted(S.items(), key=lambda x: -total(x[1], w2)): print(f"{total(s, w2):5.1f}  {n}")
