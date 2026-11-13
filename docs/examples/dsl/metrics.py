#!/usr/bin/env python3
"""Layout metrics for DSL benchmark files.
Usage: metrics.py [--fn NAME] FILE...   one line per file plus a TOTAL line (sum; depth and runs are maxima).
       metrics.py --table               the shared three files (todo, build, spec; never edge) of each option, per benchmark.
lines: non-blank, non-comment lines. depth: max nesting of ( [ { (includes the fn body, a constant +2).
tree: max "tree levels", the number of nested constructor calls `Name(` (capitalised, not preceded by a dot) open at once;
      this is what a reader sees as the tree, unlike bracket depth (lists and blocks and data constructors like Msg.Add excluded).
closer-only: lines holding only closing brackets and commas. run: longest run of adjacent closers on a line.
chars: code characters (comments and indentation dropped, strings kept).
--fn NAME restricts to the lines of `fn NAME(...) { ... }` (brace matched)."""
import re, sys, os
def code(line):
    out, ins, i = '', False, 0
    while i < len(line):
        c = line[i]
        if c == '\\' and ins:
            out += line[i:i + 2]; i += 2; continue
        if c == '"': ins = not ins
        if c == '#' and not ins: break
        out += c; i += 1
    return out.strip()
def strip(line):
    line = re.sub(r'"(\\.|[^"\\])*"', '""', line)
    return line.split('#')[0].rstrip()
def select_fn(lines, name):
    out, on, bal = [], False, 0
    for raw in lines:
        t = strip(raw)
        if not on and re.match(r'\s*(pub\s+)?fn\s+%s\b' % re.escape(name), t): on = True
        if on:
            out.append(raw)
            bal += sum(t.count(c) for c in '{') - sum(t.count(c) for c in '}')
            if bal <= 0 and '{' in ''.join(strip(x) for x in out): break
    return out
def measure(lines):
    n = depth = mx = only = run = chars = lvl = tree = 0
    stack = []
    for raw in lines:
        t = strip(raw)
        if not t.strip():
            continue
        n += 1
        chars += len(code(raw))
        for i, c in enumerate(t):
            if c in '([{':
                depth += 1; mx = max(mx, depth)
                ctor = c == '(' and re.search(r'(?<![.\w])[A-Z]\w*$', t[:i]) is not None
                stack.append(ctor)
                if ctor: lvl += 1; tree = max(tree, lvl)
            elif c in ')]}':
                depth -= 1
                if stack and stack.pop(): lvl -= 1
        if re.fullmatch(r'[\s)\]},;]+', t) and re.search(r'[)\]}]', t):
            only += 1
        for m in re.finditer(r'[)\]}]+', t):
            run = max(run, len(m.group()))
    return dict(lines=n, depth=mx, tree=tree, closer_only=only, run=run, chars=chars)
def fmt(name, r):
    return "%s lines=%d depth=%d tree=%d closer_only_lines=%d longest_run=%d chars=%d" % (
        name, r['lines'], r['depth'], r['tree'], r['closer_only'], r['run'], r['chars'])
def total(rs):
    t = dict(lines=0, depth=0, tree=0, closer_only=0, run=0, chars=0)
    for r in rs:
        for k in t: t[k] = (max if k in ('depth', 'tree', 'run') else sum)([t[k], r[k]])
    return t
def read(path):
    with open(path, encoding='utf-8') as f: return f.read().splitlines()
OPTIONS = [('D1', 'd1-clauses', 'd1'), ('C1', 'c1-baseline', 'c1'), ('D3', 'd3-pipelines', 'd3'), ('D2', 'd2-variadic', 'd2')]
def table():
    here = os.path.dirname(os.path.abspath(__file__))
    print("%-4s %-9s %5s %5s %5s %7s %4s %6s" % ('opt', 'file', 'lines', 'depth', 'tree', 'closers', 'run', 'chars'))
    for label, d, ext in OPTIONS:
        rs = []
        for b in ('todo', 'build', 'spec'):
            r = measure(read(os.path.join(here, d, 'corpus', b + '.' + ext))); rs.append(r)
            print("%-4s %-9s %5d %5d %5d %7d %4d %6d" % (label, b, r['lines'], r['depth'], r['tree'], r['closer_only'], r['run'], r['chars']))
        r = measure(select_fn(read(os.path.join(here, d, 'corpus', 'todo.' + ext)), 'view'))
        print("%-4s %-9s %5d %5d %5d %7d %4d %6d" % (label, 'todo view', r['lines'], r['depth'], r['tree'], r['closer_only'], r['run'], r['chars']))
        t = total(rs)
        print("%-4s %-9s %5d %5d %5d %7d %4d %6d" % (label, 'TOTAL', t['lines'], t['depth'], t['tree'], t['closer_only'], t['run'], t['chars']))
if __name__ == '__main__':
    a = sys.argv[1:]
    if a == ['--table']:
        table(); sys.exit(0)
    fn = None
    if a[:1] == ['--fn']: fn, a = a[1], a[2:]
    rs = []
    for path in a:
        ls = read(path)
        if fn: ls = select_fn(ls, fn)
        r = measure(ls); rs.append(r)
        print(fmt(path, r))
    if len(rs) > 1: print(fmt('TOTAL(%d files)' % len(rs), total(rs)))
