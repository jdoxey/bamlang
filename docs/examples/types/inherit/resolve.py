#!/usr/bin/env python3
"""The 3 am resolver and checker for the three inheritance finalists (ADR-0005 amendment 1, step 3).

  resolve.py --rules h1|h2|h3 FILE [--detail]   check FILE under one finalist's rules, resolve every method call
  resolve.py --all DIR                          run h1/h2/h3 corpora under DIR and print the comparison table

For every method call the resolver lists the bodies that can run and classifies the lookup:
  static-up    the receiver's static type is a class: walk up from it (steps = classes walked, 1 = on the class itself);
               `super.m()` and, under H2/H3, a closed self-call are static-up too
  dynamic-down a `dyn Base` receiver, or an open self-call: every body of m in Base and its concrete subclasses
Calls that are not class dispatch are counted apart: type-calls (`Circle.new`), built-in receivers (Str, Int, plain List,
...) and derived capabilities (`show`)."""
import sys, os
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parser import Lexer, Parser, Err   # noqa: E402

PRIMS = {'Str', 'Int', 'Float', 'Bool', 'Optional', 'Pool', 'Handle', 'Map', 'SortedMap', 'Lru', 'List', 'Event'}
DERIVED = {'show', 'copy', 'equals', 'hash'}
# built-in List declaration table: name -> (receiver mode, parameter names, return type or 'T' for the element type)
LIST_TABLE = {
    'push': ('mut', ['x'], None), 'push_all': ('mut', ['xs'], None), 'len': ('self', [], 'Int'),
    'is_empty': ('self', [], 'Bool'), 'get': ('self', ['at'], 'Optional of T'), 'get_mut': ('mut', ['at'], 'Optional of T'),
    'take_out': ('mut', ['at'], 'T'), 'map': ('self', ['each'], 'List'), 'join': ('self', ['sep'], 'Str'),
}
# primitive set of the built-in List: methods that never call another overridable List method (H1/H2/H3 rule)
LIST_PRIMITIVE = {'push', 'push_all', 'len', 'is_empty', 'get', 'get_mut', 'take_out', 'map', 'join'}


def cname(ctx):
    return ctx[1].where() if ctx[0] else "fn %s" % ctx[1].a[0]


def cline(ctx):
    return (ctx[1].node if ctx[0] else ctx[1]).line


class Meth:
    def __init__(s, name, owner, flags, mode, params, ret, node, builtin=False, ret_str=None):
        s.name, s.owner, s.flags, s.mode, s.params, s.ret, s.node = name, owner, set(flags), mode, params, ret, node
        s.builtin, s.ret_str = builtin, ret_str
        s.static = mode is None
        s.abstract = 'abstract' in s.flags
    def where(s):
        return "%s.%s" % (s.owner, s.name)


class Cls:
    def __init__(s, name, node=None, builtin=False):
        s.name, s.node, s.builtin = name, node, builtin
        s.parents, s.caps, s.fields, s.methods, s.line = [], set(), {}, {}, getattr(node, 'line', 0)
        s.list_t = None


def tyconv(n):
    if n is None:
        return None
    if n.k == 't':
        return ('t', n.a[0], [tyconv(k) for k in n.c])
    if n.k == 'dyn':
        return ('dyn', n.a[0], [tyconv(k) for k in n.c])
    return ('other', n.k, [])


class Prog:
    def __init__(s, rules):
        s.rules, s.classes, s.errors, s.warnings, s.fns = rules, {}, [], [], {}
        s.sites, s.unresolved, s.ctors, s.supers = [], [], [], []
        s.selfcalls = []
        lst = Cls('List', builtin=True)
        for n, (mode, ps, r) in LIST_TABLE.items():
            lst.methods[n] = Meth(n, 'List', [], mode, ps, None, None, True, r)
        s.classes['List'] = lst
        s._res, s._desc = {}, None

    def err(s, line, msg):
        s.errors.append((line, msg))

    # ---------------- collect declarations
    def collect(s, n):
        for k in n.c:
            if k.k == 'type':
                s.add_type(k)
            elif k.k == 'module':
                s.collect(k)
            elif k.k == 'fn':
                s.fns[k.a[0]] = k
    def add_type(s, n):
        name = n.a[0]
        if name in s.classes:
            s.err(n.line, "type `%s` declared twice" % name)
            return
        c = Cls(name, n)
        s.classes[name] = c
        for k in n.c:
            if k.k == 'is':
                c.caps |= set(k.a)
            elif k.k == 'extends':
                for t in k.c:
                    c.parents.append(t.a[0])
                    if t.a[0] == 'List' and t.c:
                        c.list_t = tyconv(t.c[0])
            elif k.k == 'field':
                c.fields[k.a[0]] = (tyconv(k.c[0]), 'pub' in k.a[1:])
            elif k.k == 'fn':
                flags = k.a[1:]
                recv = [x for x in k.c if x.k == 'recv']
                mode = recv[0].a[0] if recv else None
                params = [x.a[0] + ('/' + x.a[1] if len(x.a) > 1 else '') for x in k.c if x.k == 'param']
                ret = [x for x in k.c if x.k == 'ret']
                m = Meth(k.a[0], name, flags, mode, params, tyconv(ret[0].c[0]) if ret else None, k)
                if m.name in c.methods:
                    s.err(k.line, "`%s` declared twice in `%s`" % (m.name, name))
                c.methods[m.name] = m

    # ---------------- hierarchy
    def ancestors(s, cn, seen=None):
        """DFS order, the class first (steps = position in this walk)."""
        seen = [] if seen is None else seen
        if cn in seen or cn not in s.classes:
            return seen
        seen.append(cn)
        for p in s.classes[cn].parents:
            s.ancestors(p, seen)
        return seen
    def res(s, cn, m):
        """Distinct declarations of m reachable from cn going up: [Meth]; more than one means H2 ambiguity."""
        key = (cn, m)
        if key in s._res:
            return s._res[key]
        s._res[key] = []
        c = s.classes.get(cn)
        out = []
        if c is not None:
            if m in c.methods:
                out = [c.methods[m]]
            else:
                for p in c.parents:
                    for x in s.res(p, m):
                        if x not in out:
                            out.append(x)
        s._res[key] = out
        return out
    def steps(s, cn, m):
        for i, a in enumerate(s.ancestors(cn)):
            if m in s.classes[a].methods:
                return i + 1
        return 0
    def descendants(s, cn):
        out = [cn]
        for n, c in s.classes.items():
            if n != cn and cn in s.ancestors(n):
                out.append(n)
        return out
    def abstract_left(s, cn):
        names = set()
        for a in s.ancestors(cn):
            names |= set(s.classes[a].methods)
        out = []
        for m in sorted(names):
            r = s.res(cn, m)
            if r and r[0].abstract:
                out.append(m)
        return out
    def concrete(s, cn):
        return not s.abstract_left(cn)
    def has_fields(s, cn):
        c = s.classes[cn]
        return c.builtin or any(s.classes[a].fields or s.classes[a].builtin for a in s.ancestors(cn))
    def is_hook(s, cn, m):
        for a in s.ancestors(cn):
            x = s.classes[a].methods.get(m)
            if x is not None and ('hook' in x.flags or x.abstract):
                return True
        return False
    def candidates(s, cn, m):
        out = []
        for d in s.descendants(cn):
            if not s.concrete(d):
                continue
            r = s.res(d, m)
            if r and not r[0].abstract and r[0] not in out:
                out.append(r[0])
        return out

    # ---------------- declaration rules
    def check_decls(s):
        R = s.rules
        for cn, c in s.classes.items():
            if c.builtin:
                continue
            ln = c.line
            for p in c.parents:
                if p not in s.classes:
                    s.err(ln, "type `%s`: unknown parent `%s`" % (cn, p))
            if any(cn in s.ancestors(p) for p in c.parents if p in s.classes):
                s.err(ln, "type `%s` inherits from itself" % cn)
                continue
            if R in ('h1', 'h3') and len(c.parents) > 1:
                s.err(ln, "type `%s`: %s allows one parent, found %d (%s); model a second role with a field and forwarding methods"
                      % (cn, R.upper(), len(c.parents), ", ".join(c.parents)))
            if R == 'h2':
                st = [p for p in c.parents if p in s.classes and s.has_fields(p)]
                if len(st) > 1:
                    s.err(ln, "type `%s`: parent `%s` has fields; only one parent may have fields (`%s` already does)"
                          % (cn, st[1], st[0]))
            anc = [a for a in s.ancestors(cn)[1:]]
            for f in c.fields:
                for a in anc:
                    if f in s.classes[a].fields:
                        s.err(ln, "type `%s`: field `%s` hides the field of `%s`" % (cn, f, a))
            for m in c.methods.values():
                if m.static:
                    continue
                base = []
                for p in c.parents:
                    for x in s.res(p, m.name):
                        if x not in base and not x.static:
                            base.append(x)
                ov, hk = 'override' in m.flags, 'hook' in m.flags
                line = m.node.line
                if hk and R == 'h1':
                    s.err(line, "`hook fn %s`: `hook` is not part of H1 (self-calls are always dynamic)" % m.name)
                if base and not ov:
                    s.err(line, "`%s.%s` is already defined in `%s`: write `override fn %s` (a same-named method without "
                          "`override` would hide it)" % (cn, m.name, base[0].owner, m.name))
                if ov and not base:
                    s.err(line, "`override fn %s` in `%s`: no base type has a method `%s`" % (m.name, cn, m.name))
                for b in base[:1] if ov else []:
                    if b.mode != m.mode or [p.split('/')[0] for p in b.params] != [p.split('/')[0] for p in m.params]:
                        s.err(line, "`override fn %s` in `%s` changes the signature of `%s`" % (m.name, cn, b.where()))
            if R == 'h2' and len(c.parents) > 1:
                names = set()
                for p in c.parents:
                    for a in s.ancestors(p):
                        names |= set(s.classes[a].methods)
                for m in sorted(names):
                    if m in c.methods:
                        continue
                    r = [x for x in s.res(cn, m) if not x.static]
                    if len(r) > 1:
                        s.err(ln, "type `%s` inherits `%s` from both `%s` and `%s`: override it in `%s` "
                              "(and call `super(Parent).%s()` if you want one of them)" % (cn, m, r[0].owner, r[1].owner, cn, m))

    # ---------------- call sites
    def add(s, ctx, recv, m, kind, cause, up, cands, note=''):
        s.sites.append(dict(ctx=ctx, recv=recv, m=m, kind=kind, cause=cause, up=up, cands=cands, note=note))

    def visit_all(s):
        for cn, c in s.classes.items():
            for m in c.methods.values():
                if m.node is None:
                    continue
                env = {'self': ('t', cn, [])}
                for x in m.node.c:
                    if x.k == 'param':
                        env[x.a[0]] = tyconv(x.c[0]) if x.c and x.c[0].k in ('t', 'dyn', 'fnt', 'ttuple') else None
                for x in m.node.c:
                    if x.k == 'block':
                        s.v(x, env, (cn, m))
        for n, f in s.fns.items():
            env = {}
            for x in f.c:
                if x.k == 'param':
                    env[x.a[0]] = tyconv(x.c[0]) if x.c and x.c[0].k in ('t', 'dyn', 'fnt', 'ttuple') else None
            for x in f.c:
                if x.k == 'block':
                    s.v(x, env, (None, f))
    def bind(s, p, t, env):
        if p.k == 'pbind':
            env[p.a[0]] = t
        elif p.k == 'pvariant' and p.a[0] == 'some' and p.c and t and t[0] == 't' and t[1] == 'Optional' and t[2]:
            s.bind(p.c[0], t[2][0], env)
        else:
            for k in p.c:
                s.bind(k, None, env)
    def elem(s, t):
        if t and t[0] in ('t', 'dyn') and t[1] in ('List', 'Pool') and t[2]:
            return t[2][0]
        if t and t[0] == 't' and t[1] in s.classes:
            c = s.classes[t[1]]
            for a in s.ancestors(t[1]):
                if s.classes[a].list_t is not None:
                    return s.classes[a].list_t
        return None
    def v(s, n, env, ctx):
        """Visit n, record call sites, return the static type of n (or None)."""
        k = n.k
        if k == 'block':
            e = dict(env)
            for x in n.c:
                s.v(x, e, ctx)
            return None
        if k == 'name':
            nm = n.a[0]
            if nm in env:
                return env[nm]
            if nm in s.classes or nm in PRIMS:
                return ('typeref', nm, [])
            return None
        if k in ('str', 'interp'):
            for x in n.c:
                s.v(x, env, ctx)
            return ('t', 'Str', [])
        if k in ('int', 'float', 'bool'):
            return ('t', {'int': 'Int', 'float': 'Float', 'bool': 'Bool'}[k], [])
        if k in ('let', 'var', 'const'):
            decl = [x for x in n.c if x.k in ('t', 'dyn', 'fnt', 'ttuple')]
            val = [x for x in n.c if x not in decl][-1]
            t = s.v(val, env, ctx)
            env[n.a[0]] = tyconv(decl[0]) if decl else t
            return None
        if k == 'field':
            t = s.v(n.c[0], env, ctx)
            if t and t[0] == 't' and t[1] in s.classes:
                for a in s.ancestors(t[1]):
                    f = s.classes[a].fields.get(n.a[0])
                    if f:
                        return f[0]
            return None
        if k == 'index':
            t = s.v(n.c[0], env, ctx)
            s.v(n.c[1], env, ctx)
            return s.elem(t)
        if k == 'list':
            ts = [s.v(x, env, ctx) for x in n.c]
            return ('t', 'List', [ts[0] if ts else None])
        if k in ('try', 'try-context'):
            r = s.v(n.c[0], env, ctx)
            for x in n.c[1:]:
                s.v(x, env, ctx)
            return r
        if k == 'try-or':
            r = s.v(n.c[0], env, ctx)
            e = dict(env)
            e[n.a[0]] = None
            s.v(n.c[1], e, ctx)
            return r
        if k == 'bin':
            a = s.v(n.c[0], env, ctx)
            b = s.v(n.c[1], env, ctx)
            if n.a[0] in ('==', '!=', '<', '<=', '>', '>=', 'and', 'or'):
                return ('t', 'Bool', [])
            return a if n.a[0] != '??' else (a[2][0] if a and a[1] == 'Optional' and a[2] else b)
        if k == 'for':
            it = s.v(n.c[1], env, ctx)
            e = dict(env)
            s.bind(n.c[0], s.elem(it), e)
            s.v(n.c[2], e, ctx)
            return None
        if k == 'with':
            t = s.v(n.c[0], env, ctx)
            e = dict(env)
            e[n.a[0]] = t
            s.v(n.c[1], e, ctx)
            return None
        if k == 'iflet':
            t = s.v(n.c[0], env, ctx)
            e = dict(env)
            e[n.a[0]] = t[2][0] if t and t[1] == 'Optional' and t[2] else t
            s.v(n.c[1], e, ctx)
            for x in n.c[2:]:
                s.v(x, env, ctx)
            return None
        if k == 'match':
            t = s.v(n.c[0], env, ctx)
            for arm in n.c[1:]:
                e = dict(env)
                s.bind(arm.c[0], t, e)
                for x in arm.c[1:]:
                    s.v(x.c[0] if x.k == 'guard' else x, e, ctx)
            return None
        if k == 'lambda':
            e = dict(env)
            for x in n.c:
                if x.k == 'param':
                    e[x.a[0]] = None
            for x in n.c:
                if x.k != 'param':
                    s.v(x, e, ctx)
            return None
        if k == 'call':
            callee = n.c[0]
            for x in n.c[1:]:
                s.v(x, env, ctx)
            if callee.k == 'name':
                nm = callee.a[0]
                if nm in s.classes and not s.classes[nm].builtin:
                    s.ctors.append((ctx, nm))
                    return ('t', nm, [])
                f = s.fns.get(nm)
                if f is not None:
                    r = [x for x in f.c if x.k == 'ret']
                    return tyconv(r[0].c[0]) if r else None
            else:
                s.v(callee, env, ctx)
            return None
        if k == 'supercall':
            via = [x for x in n.c if x.k == 'via']
            for x in n.c:
                if x.k != 'via':
                    s.v(x, env, ctx)
            return s.do_super(n, via[0].a[0] if via else None, ctx)
        if k == 'mcall':
            return s.do_mcall(n, env, ctx)
        for x in n.c:
            s.v(x, env, ctx)
        return None

    def ret_of(s, m, recv_t, cn):
        if m.builtin:
            r = m.ret_str
            if r is None:
                return None
            T = None
            if recv_t and recv_t[2]:
                T = recv_t[2][0]
            if T is None and cn:
                for a in s.ancestors(cn):
                    if s.classes[a].list_t is not None:
                        T = s.classes[a].list_t
            if r == 'T':
                return T
            if r == 'Optional of T':
                return ('t', 'Optional', [T])
            return ('t', r, [None] if r == 'List' else [])
        return m.ret

    def do_mcall(s, n, env, ctx):
        recv, args = n.c[0], n.c[1:]
        m = n.a[0]
        rt = s.v(recv, env, ctx)
        el = s.elem(rt)
        for a in args:
            lam = a.c[0] if a.k == 'named' and a.c and a.c[0].k == 'lambda' else None
            if lam is not None:
                e = dict(env)
                for x in lam.c:
                    if x.k == 'param':
                        e[x.a[0]] = el
                for x in lam.c:
                    if x.k != 'param':
                        s.v(x, e, ctx)
            else:
                s.v(a, env, ctx)
        where = cname(ctx)
        R = s.rules
        # self call
        if recv.k == 'name' and recv.a[0] == 'self' and ctx[0]:
            cn = ctx[0]
            r = s.res(cn, m)
            if not r:
                s.err(cline(ctx), "`self.%s()` in `%s`: no such method" % (m, where))
                return None
            if m in DERIVED and not r:
                return None
            hook = s.is_hook(cn, m)
            if R == 'h1' or hook:
                s.add(where, 'self', m, 'dynamic-down', 'self-open' if R == 'h1' else 'self-hook', s.steps(cn, m), s.candidates(cn, m))
            else:
                s.add(where, 'self', m, 'static-up', 'self-closed', s.steps(cn, m), r[:1])
                s.selfcalls.append((cn, m, where))
            return s.ret_of(r[0], ('t', cn, []), cn)
        if rt is None:
            s.unresolved.append((where, m, cline(ctx)))
            return None
        if rt[0] == 'typeref':
            cn = rt[1]
            c = s.classes.get(cn)
            if c is not None and m in c.methods and not c.builtin:
                s.add(where, cn, m, 'type-call', '', 1, [c.methods[m]])
                return s.ret_of(c.methods[m], None, cn)
            s.add(where, cn, m, 'builtin', '', 0, [])
            return None
        cn = rt[1]
        if rt[0] == 'dyn':
            c = s.classes.get(cn)
            if c is None:
                s.err(cline(ctx), "`dyn %s` in `%s`: unknown type" % (cn, where))
                return None
            r = s.res(cn, m)
            if not r:
                if m in DERIVED and any(m in s.classes[a].caps or True for a in s.ancestors(cn)):
                    s.add(where, 'dyn ' + cn, m, 'derived', '', 0, [])
                    return None
                s.err(cline(ctx), "`%s` calls `%s` on `dyn %s`, which has no such method" % (where, m, cn))
                return None
            s.add(where, 'dyn ' + cn, m, 'dynamic-down', 'dyn', s.steps(cn, m), s.candidates(cn, m))
            return s.ret_of(r[0], rt, cn)
        c = s.classes.get(cn)
        if c is None or (c.builtin and cn in PRIMS and False):
            s.add(where, cn, m, 'builtin', '', 0, [])
            return s.prim_ret(cn, m, rt)
        if c.builtin and cn == 'List':
            s.add(where, cn, m, 'builtin', '', 0, [])
            r = c.methods.get(m)
            if r is None:
                s.err(cline(ctx), "`%s` calls `List.%s`: not in the built-in List table" % (where, m))
                return None
            return s.ret_of(r, rt, cn)
        r = s.res(cn, m)
        if not r:
            if m in DERIVED:
                s.add(where, cn, m, 'derived', '', 0, [])
                return ('t', 'Str', [])
            s.err(cline(ctx), "`%s` calls `%s.%s`: no such method" % (where, cn, m))
            return None
        s.add(where, cn, m, 'static-up', 'static', s.steps(cn, m), r[:1])
        return s.ret_of(r[0], rt, cn)
    def prim_ret(s, cn, m, rt):
        if m in ('sqrt',):
            return ('t', 'Float', [])
        return None

    def do_super(s, n, via, ctx):
        cn = ctx[0]
        m = n.a[0]
        c = s.classes.get(cn)
        line, where = cline(ctx), cname(ctx)
        R = s.rules
        if c is None or not c.parents:
            s.err(line, "`super.%s()` in `%s`: the type has no parent" % (m, where))
            return None
        if via is not None:
            if R != 'h2':
                s.err(line, "`super(%s).%s()` in `%s`: %s has one parent, write `super.%s()`" % (via, m, where, R.upper(), m))
                return None
            if via not in c.parents:
                s.err(line, "`super(%s)` in `%s`: `%s` is not a parent of `%s`" % (via, where, via, cn))
                return None
            p = via
        else:
            if len(c.parents) > 1:
                s.err(line, "`super.%s()` in `%s` is ambiguous: `%s` has parents %s; write `super(Parent).%s()`"
                      % (m, where, cn, ", ".join(c.parents), m))
                return None
            p = c.parents[0]
        r = s.res(p, m)
        if not r:
            s.err(line, "`super.%s()` in `%s`: no parent method `%s`" % (m, where, m))
            return None
        if len(r) > 1:
            s.err(line, "`super.%s()` in `%s`: `%s` reaches two bodies" % (m, where, m))
        if r[0].abstract:
            s.err(line, "`super.%s()` in `%s`: `%s` is abstract" % (m, where, r[0].where()))
        s.add(where, 'super' + ('(%s)' % via if via else ''), m, 'static-up', 'super', s.steps(p, m), r[:1])
        return s.ret_of(r[0], None, p)

    def check_calls(s):
        for ctx, cn in s.ctors:
            left = s.abstract_left(cn)
            if left:
                s.err(cline(ctx), "cannot build `%s` in `%s`: abstract method%s %s not overridden"
                      % (cn, cname(ctx), 's' if len(left) > 1 else '', ", ".join("`%s`" % x for x in left)))
        for w, m, ln in s.unresolved:
            s.err(ln, "receiver type of `.%s()` in `%s` could not be worked out" % (m, w))
        if s.rules in ('h2', 'h3'):
            seen = set()
            for cn, m, where in s.selfcalls:
                target = s.res(cn, m)[:1]
                for d in s.descendants(cn):
                    if d != cn and s.res(d, m)[:1] != target and (cn, m, d) not in seen:
                        seen.add((cn, m, d))
                        s.warnings.append("warning: `%s.%s` overrides `%s.%s`, but `%s` calls `self.%s()` statically, so the "
                                          "override is NOT reached from there (declare `hook fn %s` in the base to open it)"
                                          % (d, m, target[0].owner, m, where, m, m))

    def run(s, tree):
        s.collect(tree)
        s.check_decls()
        if not s.errors:
            s.visit_all()
            s.check_calls()


def stats(p):
    cls = [x for x in p.sites if x['kind'] in ('static-up', 'dynamic-down')]
    st = [x for x in cls if x['kind'] == 'static-up']
    dy = [x for x in cls if x['kind'] == 'dynamic-down']
    cnt = lambda xs: [len(x['cands']) for x in xs]
    return dict(
        sites=len(cls), static=len(st), super=sum(1 for x in st if x['cause'] == 'super'),
        closed=sum(1 for x in st if x['cause'] == 'self-closed'),
        dyn=len(dy), dynrecv=sum(1 for x in dy if x['cause'] == 'dyn'),
        selfdyn=sum(1 for x in dy if x['cause'] != 'dyn'),
        avg=(sum(cnt(cls)) / len(cls)) if cls else 0, avgdyn=(sum(cnt(dy)) / len(dy)) if dy else 0,
        maxc=max(cnt(cls) or [0]), maxsteps=max([x['up'] for x in cls] or [0]),
        tcalls=sum(1 for x in p.sites if x['kind'] == 'type-call'),
        excl=sum(1 for x in p.sites if x['kind'] in ('builtin', 'derived')), warns=len(p.warnings))


def load(path, rules):
    with open(path, 'rb') as f:
        src = f.read().decode('utf-8')
    tree = Parser(Lexer(src).run()).file()
    p = Prog(rules)
    p.run(tree)
    return p


def detail(p):
    for x in p.sites:
        if x['kind'] in ('builtin', 'derived'):
            continue
        print("  %-32s %-14s .%-10s %-12s steps=%d cands=%d %s" % (
            x['ctx'], x['recv'], x['m'], x['kind'] + (':' + x['cause'] if x['cause'] else ''), x['up'], len(x['cands']),
            ",".join(c.where() for c in x['cands'])))


def table(rows):
    hdr = ("finalist", "class calls", "static-up", "(super)", "(closed self)", "dynamic-down", "(dyn recv)", "(open self)",
           "avg cand", "avg cand dyn", "max cand", "max steps", "type-calls", "excluded", "warnings")
    print(" | ".join(hdr))
    for name, st in rows:
        print(" | ".join(str(x) for x in (name, st['sites'], st['static'], st['super'], st['closed'], st['dyn'], st['dynrecv'],
                                          st['selfdyn'], "%.2f" % st['avg'], "%.2f" % st['avgdyn'], st['maxc'], st['maxsteps'],
                                          st['tcalls'], st['excl'], st['warns'])))


def main(argv):
    args = argv[1:]
    det = '--detail' in args
    args = [a for a in args if a != '--detail']
    try:
        if args and args[0] == '--all':
            rows, bad = [], 0
            for h in ('h1', 'h2', 'h3'):
                path = os.path.join(args[1], h, 'types.p3')
                p = load(path, h)
                for line, msg in p.errors:
                    sys.stderr.write("%s:%d: error: %s\n" % (path, line, msg))
                    bad = 1
                for w in p.warnings:
                    print("%s: %s" % (h, w))
                if det:
                    print(h)
                    detail(p)
                rows.append((h.upper(), stats(p)))
            table(rows)
            return bad
        if len(args) == 3 and args[0] == '--rules':
            p = load(args[2], args[1])
            for line, msg in p.errors:
                sys.stderr.write("%s:%d: error: %s\n" % (args[2], line, msg))
            for w in p.warnings:
                print(w)
            if det:
                detail(p)
            if not p.errors:
                st = stats(p)
                print("SUMMARY " + " ".join("%s=%s" % kv for kv in st.items()))
            return 1 if p.errors else 0
    except Err as e:
        sys.stderr.write("%s:%d:%d: %s\n" % (args[-1], e.line, e.col, e.msg))
        return 1
    sys.stderr.write(__doc__ + "\n")
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
