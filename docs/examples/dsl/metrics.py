#!/usr/bin/env python3
"""Layout metrics for a DSL benchmark file: lines, max bracket depth, closer-only lines, longest closer run.
Comments and string contents are ignored. Usage: metrics.py FILE..."""
import re, sys
def strip(line):
    line = re.sub(r'"(\\.|[^"\\])*"', '""', line)
    return line.split('#')[0].rstrip()
for path in sys.argv[1:]:
    n = depth = mx = only = run = 0
    for raw in open(path, encoding='utf-8'):
        t = strip(raw)
        if not t.strip():
            continue
        n += 1
        for c in t:
            if c in '([{':
                depth += 1
                mx = max(mx, depth)
            elif c in ')]}':
                depth -= 1
        if re.fullmatch(r'[\s)\]},;]+', t) and re.search(r'[)\]}]', t):
            only += 1
        for m in re.finditer(r'[)\]}]+', t):
            run = max(run, len(m.group()))
    print("%s lines=%d depth=%d closer_only_lines=%d longest_run=%d" % (path, n, mx, only, run))
