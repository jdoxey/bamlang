#!/usr/bin/env python3
"""DSL copy of ../syntax/p3n/check_labels.py. Differences: `check_labels.py [--parser PARSER.py] FILE...` (the option's own
parser, so clause items parse); the libraries named by the file's `use extras.NAME` / `use std.NAME` lines are loaded from
lib/NAME.names (NAMES.md shape, comments after `#`, optional `-> Type` / `fails` suffix); capitalised library names are
constructors; `Enum.Variant(..)` calls are checked against the variant's fields. Prints per-file `checked/skipped`.
Original doc: check_labels.py FILE... -- checks the labels of every resolvable call against the declarations (F1b rules 1, 6, 7).
Declarations come from the FILE itself (each corpus file is a separate program); built-ins from NAMES.md (machine-readable block).
Resolved calls: plain fn names declared once (a fn-typed parameter in scope wins; a corpus fn beats a built-in),
Type(..) struct construction, variant constructors, Type.f(..) statics, methods whose name has exactly one distinct
signature (corpus declarations, or else built-ins; a name in both is ambiguous), and calls through fn-typed fields.
Also: pattern swap guard (rule 6) and impl parameter names equal the iface's (rule 7).
Prints `labels OK: N calls checked, M skipped`; exits 1 on errors."""
import sys, os, re, glob, importlib.util
here = os.path.dirname(os.path.abspath(__file__))
p3n = os.path.join(here, '..', 'syntax', 'p3n')
pp = os.path.join(p3n, 'parser.py')
if len(sys.argv) > 2 and sys.argv[1] == '--parser':
    pp = sys.argv[2]; del sys.argv[1:3]
spec = importlib.util.spec_from_file_location('opt_parser', pp)
P = importlib.util.module_from_spec(spec); spec.loader.exec_module(P)
LINE = re.compile(r'^(\.?)([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\(([^)]*)\)\s*(?:->.*|fails.*)?$')

def parse(path):
    with open(path, 'rb') as f: src = f.read().decode('utf-8')
    if src.startswith('﻿'): src = src[1:]
    try: return P.Parser(P.Lexer(src).run()).file()
    except P.Err as e:
        sys.stderr.write("%s:%d:%d: %s\n" % (path, e.line, e.col, e.msg)); sys.exit(1)

def walk(n):
    yield n
    for c in n.c:
        yield from walk(c)

def sig_of(fn):                          # [(name, defaulted)] without the receiver
    return tuple((c.a[0], any(k.k == 'default' for k in c.c)) for c in fn.c if c.k == 'param')
def fnt_sig(t):
    return tuple((c.a[0], False) for c in t.c if c.k == 'arg')
def fmt(sig): return "(" + ", ".join(n + ("=" if d else "") for n, d in sig) + ")"

class Decls:
    def __init__(s):
        s.fns = {}; s.types = {}; s.variants = {}; s.statics = {}; s.methods = {}; s.ifaces = {}
        s.impls = []; s.fnfields = {}; s.tymeth = {}; s.enums = set()
    def add(s, root):
        s.collect(root, None)
    def collect(s, n, owner):
        for c in n.c:
            if c.k == 'fn':
                sg = sig_of(c)
                if owner is None: s.fns.setdefault(c.a[0], set()).add(sg)
                else:
                    s.tymeth.setdefault(owner[1], {})[c.a[0]] = sg
                    if any(k.k == 'recv' for k in c.c): s.methods.setdefault(c.a[0], set()).add(sg)
                    else: s.statics.setdefault(owner[1] + '.' + c.a[0], set()).add(sg)
                    if owner[0] == 'iface': s.ifaces.setdefault(owner[1], {})[c.a[0]] = sg
            elif c.k == 'type':
                s.types.setdefault(c.a[0], set()).add(tuple((f.a[0], any(k.k == 'default' for k in f.c))
                                                          for f in c.c if f.k == 'field'))
                for f in c.c:
                    if f.k == 'field':
                        for t in f.c:
                            if t.k == 'fnt': s.fnfields.setdefault(f.a[0], set()).add(fnt_sig(t))
                s.collect(c, ('type', c.a[0]))
            elif c.k == 'iface': s.ifaces.setdefault(c.a[0], {}); s.collect(c, ('iface', c.a[0]))
            elif c.k == 'enum':
                s.enums.add(c.a[0])
                for v in c.c:
                    if v.k == 'variant':
                        s.variants.setdefault(v.a[0], set()).add(tuple((f.a[0], False) for f in v.c if f.k == 'vfield'))
            elif c.k == 'impl': s.impls.append((c.a[0], c.a[1]))
            elif c.k == 'module': s.collect(c, owner)

def load_names(path, fns, meth, stat, ctor, fenced):
    inb = not fenced
    for line in open(path, encoding='utf-8'):
        line = line.split('#')[0].strip() if not fenced else line.strip()
        if line.startswith('```'): inb = not inb; continue
        m = LINE.match(line)
        if not (inb and m): continue
        dot, name, ps = m.groups()
        sg = tuple((p.strip().rstrip('='), p.strip().endswith('=')) for p in ps.split(',') if p.strip())
        (meth if dot else stat if '.' in name else ctor if name[:1].isupper() else fns).setdefault(name, set()).add(sg)

def builtins(root):
    fns, meth, stat, ctor = {}, {}, {}, {}
    load_names(os.path.join(p3n, 'NAMES.md'), fns, meth, stat, ctor, True)
    for n in walk(root):
        if n.k == 'use':
            lib = os.path.join(here, 'lib', n.a[0].split('.')[-1] + '.names')
            if os.path.exists(lib): load_names(lib, fns, meth, stat, ctor, False)
    return fns, meth, stat, ctor

def only(sigs):
    return next(iter(sigs)) if sigs and len(sigs) == 1 else None

checked = skipped = 0

def main(files):
    global checked, skipped
    errors = []
    for f in files:
        c0, s0 = checked, skipped
        D = Decls(); root = parse(f); D.add(root)
        bfns, bmeth, bstat, bctor = builtins(root)
        one(f, root, D, bfns, bmeth, bstat, bctor, errors)
        print("%s: %d checked, %d skipped" % (f, checked - c0, skipped - s0))
    return report(errors)

def one(f, root, D, bfns, bmeth, bstat, bctor, errors):

    def check(where, what, sg, call):
        labels = [a.a[0] for a in call if a.k == 'named']
        names = [n for n, _ in sg]
        bad = False
        for l in labels:
            if l not in names:
                errors.append("%s: %s has no parameter '%s'; its parameters are %s" % (where, what, l, fmt(sg))); bad = True
        if bad: return
        idx = [names.index(l) for l in labels]
        if idx != sorted(idx):
            errors.append("%s: %s labels are out of declaration order; write %s" % (where, what, fmt(sg))); return
        miss = [n for n, d in sg if not d and n not in labels]
        if miss: errors.append("%s: %s is missing required %s; its parameters are %s" % (where, what, ", ".join(miss), fmt(sg)))

    def resolve(c, local):
        if c.k == 'call':
            f = c.c[0]
            if f.k != 'name': return None
            nm = f.a[0]
            if nm in local: return nm + '(..)', only(local[nm])
            if nm[:1].isupper():
                if nm in D.types: return nm, only(D.types[nm])
                if nm in D.variants: return nm, only(D.variants[nm])
                if nm in bctor: return nm, only(bctor[nm])
                return None
            if nm in D.fns: return nm, only(D.fns[nm])
            if nm in bfns: return nm, only(bfns[nm])
            return None
        recv, nm = c.c[0], c.a[0]
        if recv.k == 'name' and recv.a[0][:1].isupper():
            key = recv.a[0] + '.' + nm
            if key in D.statics: return key, only(D.statics[key])
            if key in bstat: return key, only(bstat[key])
            if recv.a[0] in D.enums and nm in D.variants: return recv.a[0] + '.' + nm, only(D.variants[nm])
            return None
        sigs = D.methods.get(nm, set()) | D.fnfields.get(nm, set())
        if sigs: return '.' + nm, only(sigs) if nm not in bmeth else None
        if nm in bmeth: return '.' + nm, only(bmeth[nm])
        return None

    if True:
        def visit(n, local):
            global checked, skipped
            if n.k in ('fn', 'lambda') or n.k == 'drop':
                local = dict(local)
                for p in n.c:
                    if p.k == 'param':
                        for t in p.c:
                            if t.k == 'fnt': local[p.a[0]] = {fnt_sig(t)}
            if n.k in ('call', 'mcall', 'mcall?'):
                r = resolve(n, local)
                args = n.c[1:]
                if r and r[1] is not None:
                    checked += 1; check(f, r[0], r[1], args)
                else: skipped += 1
            if n.k == 'pvariant' and n.a[0] in D.variants and len(D.variants[n.a[0]]) == 1:
                sg = only(D.variants[n.a[0]])
                for i, b in enumerate(n.c):
                    if b.k == 'pbind' and b.a[0] in [x for x, _ in sg] and sg.index((b.a[0], False)) != i:
                        errors.append("%s: pattern %s binds '%s' at position %d, but '%s' is a different field of %s (fields %s)"
                                      % (f, n.a[0], b.a[0], i + 1, b.a[0], n.a[0], fmt(sg)))
            for c in n.c: visit(c, local)
        visit(root, {})
    for i, t in D.impls:
        for m, isg in D.ifaces.get(i, {}).items():
            tsg = D.tymeth.get(t, {}).get(m)
            if tsg is not None and [x for x, _ in tsg] != [x for x, _ in isg]:
                errors.append("impl %s for %s: method %s has parameters %s, the interface declares %s" % (i, t, m, fmt(tsg), fmt(isg)))
def report(errors):
    for e in errors: sys.stderr.write("LABELS " + e + "\n")
    if errors: return 1
    print("labels OK: %d calls checked, %d skipped (%d files)" % (checked, skipped, len(sys.argv) - 1))
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
