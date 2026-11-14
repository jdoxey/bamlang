#!/usr/bin/env python3
"""same_meaning.py OLD.ast NEW.ast -- checks the labelled AST means the same as the unlabelled one.
Allowed differences (all printed): label added in a call (named L X where OLD had X; labels in one call must be
distinct), fnt (arg NAME [mode] T) for old T / (mut T) / (take T), vfield names added, and lambda-parameter renames.
A rename must be injective, must not capture a name free in the body, and applies only to (name X) nodes, never to
field or method names. Anything else: exit 1. (Whether labels match declarations is check_labels.py's job.)"""
import sys, re, collections

def parse(text):
    toks = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+', text)
    pos = 0
    def node():
        nonlocal pos
        assert toks[pos] == '(', toks[pos]
        pos += 1
        n = [toks[pos]]
        pos += 1
        while toks[pos] != ')':
            if toks[pos] == '(':
                n.append(node())
            else:
                n.append(toks[pos])
                pos += 1
        pos += 1
        return n
    r = node()
    assert pos == len(toks), "trailing tokens"
    return r

def fmt(n):
    return n if isinstance(n, str) else '(' + ' '.join(fmt(x) for x in n) + ')'

allowed = collections.Counter()
renames = collections.OrderedDict()
errors = []

def lam_params(n):
    return [c[1] for c in n[1:] if isinstance(c, list) and c[0] == 'param']

def names_in(n, out):
    if isinstance(n, list):
        if n and n[0] == 'name' and len(n) > 1 and isinstance(n[1], str): out.add(n[1])
        for c in n: names_in(c, out)

def cmp_lambda(o, n, path, ren):
    ops, nps = lam_params(o), lam_params(n)
    if len(ops) != len(nps): errors.append("%s: lambda arity differs" % path); return
    news = [b for b in nps if b != '_']
    if len(news) != len(set(news)): errors.append("%s: lambda parameter names repeat" % path)
    body = [c for c in o[1:] if not (isinstance(c, list) and c[0] == 'param')]
    free = set(); names_in(body, free); free -= set(ops)
    r2 = dict(ren)
    for a, b in zip(ops, nps):
        if a == '_' or b == '_':
            if a != b: errors.append("%s: lambda rename involves _" % path)
            continue
        if a != b:
            if b in free or b in ren.values():
                errors.append("%s: lambda rename %s -> %s captures a name" % (path, a, b))
            renames[path] = renames.get(path, []) + ["%s -> %s" % (a, b)]
            print("allowed lambda rename %s: %s -> %s" % (path, a, b))
        r2[a] = b
    for k, (x, y) in enumerate(zip(o[1:], n[1:])):
        if isinstance(x, list) and x[0] == 'param':
            if not (isinstance(y, list) and y[0] == 'param' and len(x) == len(y)):
                errors.append("%s: lambda param shape differs" % path); continue
            for u, v in zip(x[2:], y[2:]):
                if isinstance(u, str) or isinstance(v, str):
                    if u != v: errors.append("%s: lambda param differs" % path)
                else: cmp(u, v, path + '/param', ren)
        else:
            cmp(x, y, path + '/lam' + str(k), r2)

def cmp(o, n, path, ren):
    if isinstance(o, str) or isinstance(n, str):
        if o != n:
            errors.append("%s: %s != %s" % (path, o, n))
        return
    # fnt: old args (types, (mut T), (take T)) vs new (arg NAME [mode] T)
    if o[0] == 'fnt' and n[0] == 'fnt':
        oa = [c for c in o[1:] if not (isinstance(c, list) and c[0] == 'ret') and c != 'fails']
        na = [c for c in n[1:] if not (isinstance(c, list) and c[0] == 'ret') and c != 'fails']
        orr = [c for c in o[1:] if isinstance(c, list) and c[0] == 'ret']
        nrr = [c for c in n[1:] if isinstance(c, list) and c[0] == 'ret']
        if ('fails' in o) != ('fails' in n) or len(oa) != len(na):
            errors.append("%s: fnt shape differs" % path); return
        for k, (x, y) in enumerate(zip(oa, na)):
            if not (isinstance(y, list) and y[0] == 'arg'):
                errors.append("%s: fnt arg %d is not (arg ...)" % (path, k)); continue
            atoms = [a for a in y[1:] if isinstance(a, str)]
            ty = [a for a in y[1:] if isinstance(a, list)][0]
            mode = atoms[1] if len(atoms) > 1 else None
            if isinstance(x, list) and x[0] in ('mut', 'take'):
                if mode != x[0]: errors.append("%s: fnt arg mode differs" % path)
                x = x[1]
            elif mode:
                errors.append("%s: new fnt arg has mode %s, old none" % (path, mode))
            allowed['fnt-label'] += 1
            print("allowed fnt label   %s: %s" % (path, atoms[0]))
            cmp(x, ty, path + '/fnt', ren)
        if len(orr) != len(nrr): errors.append("%s: fnt ret differs" % path)
        for x, y in zip(orr, nrr): cmp(x, y, path + '/fnt', ren)
        return
    if o[0] == 'variant' and n[0] == 'variant':
        if o[1] != n[1] or len(o) != len(n): errors.append("%s: variant differs" % path); return
        for x, y in zip(o[2:], n[2:]):
            # old (vfield T) or (vfield NAME T); new always named
            if len(x) == 2 and len(y) == 3:
                allowed['vfield-name'] += 1
                print("allowed vfield name %s: %s.%s" % (path, o[1], y[1]))
                cmp(x[1], y[2], path, ren)
            else:
                cmp(x, y, path, ren)
        return
    # call argument lists: children after the callee
    if o[0] in ('call', 'mcall', 'mcall?') and n[0] == o[0]:
        if o[:2] != n[:2] if o[0] != 'call' else False:
            errors.append("%s: %s method differs" % (path, o[0])); return
        start = 1 if o[0] == 'call' else 2
        oc, nc = o[start:], n[start:]
        if len(oc) != len(nc): errors.append("%s: arg count differs" % path); return
        labels = [c[1] for c in nc if isinstance(c, list) and c[0] == 'named']
        if len(labels) != len(set(labels)): errors.append("%s: label repeated in one call" % path)
        # first child is callee / receiver
        cmp(oc[0], nc[0], path + '/' + o[0], ren)
        for k, (x, y) in enumerate(zip(oc[1:], nc[1:])):
            if isinstance(y, list) and y[0] == 'named' and not (isinstance(x, list) and x[0] == 'named'):
                allowed['call-label'] += 1
                callee = fmt(oc[0])[:40] if o[0] == 'call' else o[1]
                print("allowed arg label   %s: %s(%s:)" % (path, callee, y[1]))
                cmp(x, y[2], path + '/arg', ren)
            else:
                cmp(x, y, path + '/arg', ren)
        return
    if o[0] != n[0] or len(o) != len(n):
        errors.append("%s: %s vs %s" % (path, fmt(o)[:70], fmt(n)[:70])); return
    if o[0] == 'lambda':
        cmp_lambda(o, n, path, ren); return
    for k, (x, y) in enumerate(zip(o, n)):
        if isinstance(x, str) and isinstance(y, str):
            if x != y and not (o[0] == 'name' and k == 1 and ren.get(x) == y):
                errors.append("%s: atom %s != %s (in %s)" % (path, x, y, o[0]))
        else:
            if isinstance(x, str) != isinstance(y, str):
                errors.append("%s: structure differs" % path); continue
            cmp(x, y, path + '/' + x[0] + str(k), ren) if True else None

def main(a):
    o = parse(open(a[1]).read()); n = parse(open(a[2]).read())
    cmp(o, n, 'file', {})
    print("summary: " + ", ".join("%s=%d" % kv for kv in sorted(allowed.items())) + (", renames=%d" % sum(len(v) for v in renames.values())))
    if errors:
        for e in errors[:20]: print("DIFF " + e)
        print("%d disallowed differences" % len(errors)); return 1
    return 0
sys.exit(main(sys.argv))
