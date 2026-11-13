#!/usr/bin/env python3
"""timing.py: nested list items must parse in linear time (review F7). Fails above 2 s; depth 18 of each shape."""
import sys, time, os, importlib.util
here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('d1_parser', os.path.join(here, 'parser.py'))
P = importlib.util.module_from_spec(spec); spec.loader.exec_module(P)
D = 18
shapes = {
    'if-expressions': ("[if a { ", "0", " } else { 1 }]"),
    'if-clauses':     ("[if a => ", "0", "]"),
    'iflet-clauses':  ("[if x = o => ", "0", "]"),
    'if-expr-in-clause': ("[if a => [if b { ", "0", " } else { 1 }]]"),
    'for-clauses':    ("[for x in xs if g => ", "0", "]"),
}
worst = 0.0
for name, (pre, core, post) in shapes.items():
    src = "fn f() {\n  let v = " + pre * D + core + post * D + "\n}\n"
    t = time.perf_counter()
    try:
        P.Parser(P.Lexer(src).run()).file()
    except P.Err as e:
        print("FAIL timing %s: %s" % (name, e.msg)); sys.exit(1)
    dt = time.perf_counter() - t; worst = max(worst, dt)
    print("  depth %d %-18s %.3f s" % (D, name, dt))
if worst > 2.0:
    print("FAIL timing: %.2f s > 2 s" % worst); sys.exit(1)
print("timing OK (worst %.3f s)" % worst)
