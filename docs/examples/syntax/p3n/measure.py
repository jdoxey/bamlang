"""Measures the F1b corpus (p3n, already punned) against the positional P3 corpus. No subtraction: p3n/corpus is counted.
Per side: whole-file chars; code-only chars (comments, leading indentation, trailing blanks and newlines dropped);
code minus the literal text of string literals; lines over 100 and 120 columns.
F2 (one-argument labels removed) is derived from p3n/expected/*.ast: each call with exactly one named, non-pun argument
saves len(label)+2 characters."""
import glob, os
here = os.path.dirname(os.path.abspath(__file__))

def classify(src):
    """Return (code_lines, str_chars): code_lines are the lines with comments removed; str_chars counts literal text."""
    lines, cur, strc = [], [], 0
    stack = []                     # 'S' inside string text, or an int brace depth inside an interpolation
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == '\r': i += 1; continue
        top = stack[-1] if stack else None
        if c == '\n':
            lines.append(''.join(cur)); cur = []; i += 1; continue
        if top == 'S':
            if c == '\\' and i + 1 < n:
                cur.append(src[i:i+2]); strc += 2 if src[i+1] != '\n' else 1; i += 2; continue
            if c == '"': stack.pop(); cur.append(c); i += 1; continue
            if c == '{': stack.append(0); cur.append(c); i += 1; continue
            cur.append(c); strc += 1; i += 1; continue
        # code (top level or inside an interpolation)
        if c == '"': stack.append('S'); cur.append(c); i += 1; continue
        if c == '#' and not stack:
            while i < n and src[i] != '\n': i += 1
            continue
        if stack:
            if c == '{': stack[-1] += 1
            elif c == '}':
                if stack[-1] == 0: stack.pop(); cur.append(c); i += 1; continue
                stack[-1] -= 1
        cur.append(c); i += 1
    lines.append(''.join(cur))
    return lines, strc

def stats(dirname):
    whole = code = nostr = o100 = o120 = 0
    for f in sorted(glob.glob(os.path.join(here, dirname, 'corpus', '*.p3'))):
        with open(f, encoding='utf-8', newline='') as fh: src = fh.read().replace('\r\n', '\n')
        whole += len(src)
        lines, strc = classify(src)
        c = sum(len(l.strip()) for l in lines)
        code += c; nostr += c - strc
        for l in src.split('\n'):
            if len(l) > 100: o100 += 1
            if len(l) > 120: o120 += 1
    return dict(whole=whole, code=code, nostr=nostr, o100=o100, o120=o120)

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

tot = dict(labels=0, puns=0, one_arg=0, one_arg_saved=0)
def walk(n):
    if not isinstance(n, list) or not n: return
    if n[0] in ('call', 'mcall', 'mcall?'):
        args = n[2:] if n[0] == 'call' else n[3:]
        named = [a for a in args if isinstance(a, list) and a and a[0] == 'named']
        for a in named:
            tot['labels'] += 1
            if a[2] == ['name', a[1]]: tot['puns'] += 1
        if len(args) == 1 and named and named[0][2] != ['name', named[0][1]]:
            tot['one_arg'] += 1; tot['one_arg_saved'] += len(named[0][1]) + 2
    for c in n: walk(c)

for f in sorted(glob.glob(os.path.join(here, 'expected', '*.ast'))):
    with open(f, encoding='utf-8') as fh: walk(parse(toks(fh.read())))

a, b = stats(os.path.join('..', 'p3')), stats('.')
def pct(x, y): return "%+.1f%%" % (100.0 * (y - x) / x)
print("%-28s %8s %8s %8s" % ("", "P3", "P3n F1b", "change"))
for key, label in (('whole', 'whole-file chars'), ('code', 'code-only chars'), ('nostr', 'code minus string text'),
                   ('o100', 'lines over 100 cols'), ('o120', 'lines over 120 cols')):
    ch = pct(a[key], b[key]) if a[key] else "%+d" % (b[key] - a[key])
    print("%-28s %8d %8d %8s" % (label, a[key], b[key], ch))
print("labelled args %d (puns %d); one-argument non-pun labels %d, %d chars" % (tot['labels'], tot['puns'], tot['one_arg'], tot['one_arg_saved']))
for key, label in (('whole', 'whole-file'), ('code', 'code-only'), ('nostr', 'code minus strings')):
    f2 = b[key] - tot['one_arg_saved']
    print("F2 estimate (derived), %-18s %8d (%s vs P3)" % (label, f2, pct(a[key], f2)))
