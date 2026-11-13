"""Measures the three finalists of ADR-0006 amendment 1 on the fully labelled corpus (p3n/expected/*.ast).
F1: strict, with the pun f(x) for f(x: x). F2: F1 plus one-parameter calls unlabelled. F3: F1 with positional calls
through function values (counted from same_meaning output by hand: 8 calls, 7 function-type labels)."""
import sys, glob, os
here = os.path.dirname(os.path.abspath(__file__))
def toks(s):
    i, out = 0, []
    while i < len(s):
        c = s[i]
        if c in '()': out.append(c); i += 1
        elif c.isspace(): i += 1
        elif c == '"':
            j = i + 1
            while s[j] != '"': j += 2 if s[j] == '\\' else 1
            out.append(s[i:j+1]); i = j + 1
        else:
            j = i
            while j < len(s) and not s[j].isspace() and s[j] not in '()': j += 1
            out.append(s[i:j]); i = j
    return out
def parse(ts):
    st = [[]]
    for t in ts:
        if t == '(': st.append([])
        elif t == ')': x = st.pop(); st[-1].append(x)
        else: st[-1].append(t)
    return st[0]
tot = dict(labels=0, label_chars=0, puns=0, pun_saved=0, one_arg=0, one_arg_saved=0, print_=0)
def walk(n):
    if not isinstance(n, list) or not n: return
    if n[0] in ('call', 'mcall', 'mcall?'):
        args = n[2:] if n[0] == 'call' else n[3:]
        named = [a for a in args if isinstance(a, list) and a and a[0] == 'named']
        for a in named:
            tot['labels'] += 1; tot['label_chars'] += len(a[1]) + 2
            if a[2] == ['name', a[1]]: tot['puns'] += 1; tot['pun_saved'] += len(a[1]) + 2
        if len(args) == 1 and named:
            a = named[0]
            tot['one_arg'] += 1
            # F2 saves the label only where F1's pun did not already remove it
            if a[2] != ['name', a[1]]: tot['one_arg_saved'] += len(a[1]) + 2
        if n[0] == 'call' and n[1] == ['name', 'print']: tot['print_'] += 1
    for c in n: walk(c)
chars = 0
for f in sorted(glob.glob(os.path.join(here, 'expected', '*.ast'))):
    walk(parse(toks(open(f).read())))
for f in glob.glob(os.path.join(here, 'corpus', '*.p3')): chars += len(open(f).read())
old = sum(len(open(f).read()) for f in glob.glob(os.path.join(here, '..', 'p3', 'corpus', '*.p3')))
f1 = chars - tot['pun_saved']; f2 = f1 - tot['one_arg_saved']
print(f"labels={tot['labels']} puns={tot['puns']} one_arg_calls={tot['one_arg']} print={tot['print_']}")
print(f"chars: positional P3 {old}; written out {chars} (+{100*(chars-old)/old:.1f}%)")
print(f"F1 strict+pun {f1} (+{100*(f1-old)/old:.1f}%); F2 one-param exempt {f2} (+{100*(f2-old)/old:.1f}%); F3 ~F1 minus 8 call labels")
