#!/usr/bin/env python3
"""The 3 am resolver and checker for the three inheritance finalists (ADR-0005 amendment 1, step 3).

  resolve.py --rules h1|h2|h3 FILE [--detail]   check FILE under one finalist's rules, resolve every method call
  resolve.py --all DIR                          run h1/h2/h3/h1b corpora (and the old T3+ corpus) and print the comparison table
  resolve.py --rules h1b FILE [--exact]         h1b = H1 plus the review fixes (exact types, `super:` construction, take-self
                                                rules, exact override matching, capabilities); --exact resolves self-calls
                                                statically when no `dyn` path reaches the method
  resolve.py --api FILE                         each pub method's self-call set (fragile-base summary)
  resolve.py --api-diff OLD NEW                 flag a changed self-call set, an added or a removed method as BREAKING
  resolve.py --t3 FILE                          classify the calls of the old iface/impl corpus (p3n/corpus/types.p3)

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
import importlib.util   # noqa: E402

PRIMS = {'Str', 'Int', 'Float', 'Bool', 'Optional', 'Pool', 'Handle', 'Map', 'SortedMap', 'Lru', 'List', 'Event'}
DERIVED = {'show', 'copy', 'equals', 'hash'}
# built-in List declaration table: name -> (receiver mode, [(parameter, type)], return type); `T` is the element type.
# PRIMITIVES are the six methods a subclass may override to change what the list does. Every other method goes through them
# dynamically for subclass instances; an exact `List` keeps the direct path (S3).
LIST_PRIMITIVE = ['push', 'insert', 'remove_at', 'get', 'set', 'len']
LIST_TABLE = {
    'push': ('mut', [('x', 'T')], None), 'insert': ('mut', [('at', 'Int'), ('x', 'T')], None),
    'remove_at': ('mut', [('at', 'Int')], 'T'), 'get': ('self', [('at', 'Int')], 'Optional of T'),
    'set': ('mut', [('at', 'Int'), ('value', 'T')], None), 'len': ('self', [], 'Int'),
    # derived: go through the primitives for subclass instances
    'push_all': ('mut', [('xs', 'List of T')], None), 'pop': ('mut', [], 'Optional of T'),
    'retain': ('mut', [('keep', 'fn')], None),
    'is_empty': ('self', [], 'Bool'), 'get_mut': ('mut', [('at', 'Int')], 'Optional of T'),
    'take_out': ('mut', [('at', 'Int')], 'T'), 'map': ('self', [('each', 'fn')], 'List'), 'join': ('self', [('sep', 'Str')], 'Str'),
}
# value types: not classes, never a parent (S3). Built-in classes whose primitive set is not defined here yet.
VALUE_TYPES = {'Int', 'Float', 'Bool', 'Optional', 'Handle', 'Event'}
FUTURE_CLASSES = {'Str', 'Map', 'SortedMap', 'Lru', 'Pool'}
CAPS = ('show', 'copy', 'equals', 'hash')
COPYABLE = {'Int', 'Float', 'Bool'}


def m_name(n):
    return n.a[0]


def flat(x):
    for y in x.c:
        yield y
        for z in flat(y):
            yield z


def tyrepr(t):
    if t is None:
        return '()'
    if t[0] == 'other':
        return t[1]
    return ('dyn ' if t[0] == 'dyn' else '') + t[1] + ((' of ' + ', '.join(tyrepr(x) for x in t[2])) if t[2] else '')


def cname(ctx):
    return ctx[1].where() if ctx[0] else "fn %s" % ctx[1].a[0]


def cline(ctx):
    return getattr(ctx[1].node if ctx[0] else ctx[1], 'line', 0)


class Meth:
    def __init__(s, name, owner, flags, mode, params, ret, node, builtin=False, ret_str=None, ptypes=None):
        s.name, s.owner, s.flags, s.mode, s.params, s.ret, s.node = name, owner, set(flags), mode, params, ret, node
        s.builtin, s.ret_str = builtin, ret_str
        s.ptypes = ptypes or []          # [(name, type or type-string for built-ins, mode, has_default)]
        s.static = mode is None
        s.abstract = 'abstract' in s.flags
        s.pub = 'pub' in s.flags or builtin
        s.fails = 'fails' in s.flags
    def where(s):
        return "%s.%s" % (s.owner, s.name)


class Cls:
    def __init__(s, name, node=None, builtin=False):
        s.name, s.node, s.builtin = name, node, builtin
        s.parents, s.caps, s.fields, s.methods, s.line = [], set(), {}, {}, getattr(node, 'line', 0)
        s.list_t = None
        s.module, s.iface, s.variants = None, False, {}


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
        s.R = 'h1' if rules in ('h1b', 't3') else rules      # legacy rule family (open self-calls, one parent)
        s.b = rules == 'h1b'                                 # the review-fix checks
        s.sites, s.unresolved, s.ctors, s.supers = [], [], [], []
        s.selfcalls, s.fnmod, s.enums, s.lit_elems, s.lits = [], {}, set(), {}, []
        lst = Cls('List', builtin=True)
        for n, (mode, ps, r) in LIST_TABLE.items():
            lst.methods[n] = Meth(n, 'List', ['pub'], mode, [x for x, _ in ps], None, None, True, r,
                                  [(x, ty, None, False) for x, ty in ps])
        s.classes['List'] = lst
        s._res, s._desc = {}, None

    def err(s, line, msg):
        s.errors.append((line, msg))

    # ---------------- collect declarations
    def collect(s, n, mod=None):
        for k in n.c:
            if k.k == 'type':
                s.add_type(k, mod)
            elif k.k == 'module':
                s.collect(k, k.a[0])
            elif k.k == 'enum':
                s.enums.add(k.a[0])
            elif k.k == 'fn':
                s.fns[k.a[0]] = k
                s.fnmod[k.a[0]] = mod
    def add_type(s, n, mod=None):
        name = n.a[0]
        if name in s.classes:
            s.err(n.line, "type `%s` declared twice" % name)
            return
        c = Cls(name, n)
        c.module = mod
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
                c.fields[k.a[0]] = (tyconv(k.c[0]), 'pub' in k.a[1:], any(x.k == 'default' for x in k.c[1:]))
            elif k.k == 'fn':
                flags = k.a[1:]
                recv = [x for x in k.c if x.k == 'recv']
                mode = recv[0].a[0] if recv else None
                params = [x.a[0] + ('/' + x.a[1] if len(x.a) > 1 else '') for x in k.c if x.k == 'param']
                ptypes = [(x.a[0], tyconv(x.c[0]) if x.c and x.c[0].k != 'default' else None, x.a[1] if len(x.a) > 1 else None,
                           any(d.k == 'default' for d in x.c)) for x in k.c if x.k == 'param']
                ret = [x for x in k.c if x.k == 'ret']
                m = Meth(k.a[0], name, flags, mode, params, tyconv(ret[0].c[0]) if ret else None, k, ptypes=ptypes)
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
        R = s.R
        for cn, c in s.classes.items():
            if c.builtin:
                continue
            ln = c.line
            for p in c.parents:
                if s.b and (p in VALUE_TYPES or p in s.enums):
                    s.err(ln, "type `%s`: `%s` is a value type, not a class: it can't be a parent (only containers and Str are "
                          "classes; Int, Float, Bool, enums, Optional, tuples and Handle are values)" % (cn, p))
                elif s.b and p in FUTURE_CLASSES:
                    s.err(ln, "type `%s`: `%s` is a built-in class whose primitive set is not defined yet; only `List` can be "
                          "subclassed so far" % (cn, p))
                elif p not in s.classes:
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
                    elif s.b:
                        s.match_override(cn, m, b, line)
                if s.b and m.name in CAPS:
                    s.err(line, "`fn %s` in `%s`: `%s` is derived per exact class and dispatched by the vtable; it can't be written "
                          "or overridden (declare `is %s` on the type)" % (m.name, cn, m.name, m.name))
            if s.b:
                s.check_caps(cn, c)
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

    def lt(s, cn):
        for a in s.ancestors(cn):
            if s.classes[a].list_t is not None:
                return s.classes[a].list_t
        return None
    def ptypes_of(s, m, cn):
        """Parameter types of m with the built-in `T` replaced by the element type of class cn."""
        if not m.builtin:
            return m.ptypes
        T = s.lt(cn) if cn else None
        out = []
        for nm, ty, md, d in m.ptypes:
            if ty == 'T':
                ty = T
            elif ty == 'Int':
                ty = ('t', 'Int', [])
            elif ty == 'List of T':
                ty = ('t', 'List', [T])
            elif ty == 'fn':
                ty = None
            out.append((nm, ty, md, d))
        return out
    def ret_repr(s, m, cn):
        if not m.builtin:
            return tyrepr(m.ret)
        r, T = m.ret_str, s.lt(cn)
        if r is None:
            return '()'
        return {'T': tyrepr(T), 'Optional of T': 'Optional of ' + tyrepr(T), 'List': 'List'}.get(r, r)
    def match_override(s, cn, m, b, line):
        """S7: an override matches the base declaration exactly: parameter types, return type, fails, pub, no restated defaults."""
        bp = s.ptypes_of(b, cn)
        why = []
        for (pn, pt, pm, pd), (bn, bt, bm, bd) in zip(m.ptypes, bp):
            if pd:
                s.err(line, "`override fn %s` in `%s`: parameter `%s` restates a default; defaults belong to the base declaration "
                      "and are inherited" % (m.name, cn, pn))
            if bt is not None and tyrepr(pt) != tyrepr(bt):
                why.append("parameter `%s` is `%s`, the base has `%s`" % (pn, tyrepr(pt), tyrepr(bt)))
            if pm != bm:
                why.append("parameter `%s` mode `%s`, the base has `%s`" % (pn, pm, bm))
        if s.ret_repr(m, cn) != s.ret_repr(b, cn):
            why.append("return type is `%s`, the base has `%s`" % (s.ret_repr(m, cn), s.ret_repr(b, cn)))
        if m.fails != b.fails:
            why.append("`fails` differs from the base")
        if m.pub != b.pub:
            why.append("the base is %s, so the override must be %s" % ('`pub`' if b.pub else 'not `pub`', '`pub`' if b.pub else 'not `pub`'))
        for w in why:
            s.err(line, "`override fn %s` in `%s` changes the signature of `%s`: %s" % (m.name, cn, b.where(), w))
    def has_cap(s, t, cap):
        if t is None:
            return True
        if t[0] == 'other':
            return False
        n = t[1]
        if t[0] == 'dyn' or n in s.classes and not s.classes[n].builtin:
            return n in s.classes and any(cap in s.classes[a].caps for a in s.ancestors(n))
        if n == 'Float':
            return cap != 'hash'
        if n == 'Pool':
            return cap in ('show',)
        if n in ('Optional', 'List', 'Map', 'SortedMap', 'Lru'):
            return all(s.has_cap(x, cap) for x in t[2])
        return True
    def check_caps(s, cn, c):
        """S7: `is equals` (etc.) on a base is inherited: every subclass field must have it too."""
        for cap in CAPS:
            src = [a for a in s.ancestors(cn) if cap in s.classes[a].caps]
            if not src:
                continue
            for f, (ft, _pub, _d) in c.fields.items():
                if not s.has_cap(ft, cap):
                    s.err(c.line, "type `%s` is `%s` (from `%s`), but its field `%s: %s` has no `%s`" % (cn, cap, src[0], f, tyrepr(ft), cap))

    # ---------------- call sites
    def add(s, ctx, recv, m, kind, cause, up, cands, note=''):
        s.sites.append(dict(ctx=ctx, recv=recv, m=m, kind=kind, cause=cause, up=up, cands=cands, note=note))

    def visit_all(s):
        for cn, c in s.classes.items():
            for m in c.methods.values():
                if m.node is None:
                    continue
                env = {} if m.static else {'self': ('dyn', cn, []) if s.b else ('t', cn, [])}
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
        elif p.k == 'pvariant' and t and t[0] == 't' and t[1] in s.classes and p.a[0] in s.classes[t[1]].variants:
            for sub, vt in zip(p.c, s.classes[t[1]].variants[p.a[0]]):
                s.bind(sub, vt, env)
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
    def check_list(s, dt, val, ctx):
        """A list literal assigned to `List of X`: each element must convert to X (exact unless X is `dyn`)."""
        if s.b and dt and dt[1] in ('List', 'Pool') and dt[2] and val.k == 'list':
            for x, tx in zip(val.c, s.lit_elems.get(id(val), [])):
                s.need(dt[2][0], tx, x, cline(ctx), cname(ctx), "list element")
    def cmod(s, ctx):
        return s.classes[ctx[0]].module if ctx[0] else s.fnmod.get(ctx[1].a[0])
    def can_see(s, ctx, owner):
        """A private field of class `owner` is visible in owner's module and in its subclasses (F2)."""
        if ctx[0] and owner in s.ancestors(ctx[0]):
            return True
        return s.cmod(ctx) == s.classes[owner].module
    def is_self(s, n):
        return n is not None and n.k == 'name' and n.a[0] == 'self'
    def conv_err(s, dst, src, node=None):
        """F1: exact types. A plain `Base` is exactly Base; `dyn Base` holds Base or any subclass. Returns an error text or None."""
        if dst is None or src is None or dst[0] not in ('t', 'dyn') or src[0] not in ('t', 'dyn'):
            return None
        dn, sn = dst[1], src[1]
        if dn not in s.classes or sn not in s.classes or dn == 'Optional':
            return None
        up = dn in s.ancestors(sn)
        who = "`self` (a borrowed `dyn %s`)" % sn if s.is_self(node) else ("a `dyn %s`" % sn if src[0] == 'dyn' else "a `%s`" % sn)
        if dst[0] == 'dyn':
            return None if up else "%s is not a `%s`" % (who, dn)
        if src[0] == 't' and sn == dn:
            return None
        if up:
            return "%s can't be used where a plain `%s` is expected: a plain `%s` means exactly `%s`, so it would slice; write `dyn %s`" % (
                who, dn, dn, dn, dn)
        return "%s is not a `%s`" % (who, dn)
    def need(s, dst, src, node, line, where, what):
        if not s.b:
            return
        e = s.conv_err(dst, src, node)
        if e:
            s.err(line, "%s in `%s`: %s" % (what, where, e))
    def no_store_self(s, node, line, where, what):
        if s.b and s.is_self(node):
            s.err(line, "%s in `%s`: `self` is a borrowed `dyn` of the current class and can't be stored; pass it to a `dyn` "
                  "parameter, or use `self.copy()`" % (what, where))
    def argvals(s, args, env, ctx):
        """Visit each argument once; returns [(label or None, value node, type)]."""
        out = []
        for a in args:
            if a.k == 'named':
                out.append((a.a[0], a.c[0], s.v(a.c[0], env, ctx)))
            else:
                out.append((None, a, s.v(a, env, ctx)))
        return out
    def fn_ptypes(s, f):
        return [(x.a[0], tyconv(x.c[0]) if x.c and x.c[0].k != 'default' else None, None, False) for x in f.c if x.k == 'param']
    def check_args(s, ps, label, argt, line, where):
        """Match arguments to the declared parameters (named by label, else by position) and check each type."""
        if not s.b:
            return
        pos = 0
        for nm, node, ty in argt:
            if nm is None and node is not None and node.k == 'key':
                continue
            if nm is None:
                if pos >= len(ps):
                    continue
                pn, pt = ps[pos][0], ps[pos][1]
                pos += 1
            else:
                hit = [x for x in ps if x[0] == nm]
                if not hit:
                    continue
                pn, pt = hit[0][0], hit[0][1]
            s.need(pt, ty, node, line, where, "argument `%s` of `%s`" % (pn, label))
    def ret_type(s, ctx):
        if ctx[0]:
            return ctx[1].ret
        r = [x for x in ctx[1].c if x.k == 'ret']
        return tyconv(r[0].c[0]) if r else None
    def check_literal(s, n, nm, named, ctx, line, where):
        """F2: `Sub(super: Base.new(..), extra: 1)`. The base part is one value; base fields are named only through it."""
        c = s.classes[nm]
        anc = s.ancestors(nm)[1:]
        user_parent = [p for p in c.parents if p in s.classes and not s.classes[p].builtin]
        base_has_fields = any(s.classes[a].fields for a in anc if not s.classes[a].builtin)
        left = s.abstract_left(nm)
        own_static = ctx[0] == nm and ctx[1].static
        if left and not own_static:
            s.err(line, "cannot build `%s` in `%s`: abstract method%s %s not overridden" % (
                nm, where, 's' if len(left) > 1 else '', ", ".join("`%s`" % x for x in left)))
        seen = set()
        for an, node, ty in named:
            if an is None:
                continue
            seen.add(an)
            if an == 'super':
                if not user_parent or not base_has_fields:
                    s.err(line, "`%s(super: ..)` in `%s`: `%s` has no base part to build (its parent has no fields)" % (nm, where, nm))
                else:
                    s.need(('t', user_parent[0], []), ty, node, line, where, "`super:` of `%s`" % nm)
                continue
            if an in c.fields:
                ft, pub, _d = c.fields[an]
                if not pub and not s.can_see(ctx, nm):
                    s.err(line, "`%s` literal in `%s`: field `%s` is private to module `%s` and its subclasses; build it with `%s.new`"
                          % (nm, where, an, c.module, nm))
                s.no_store_self(node, line, where, "field `%s`" % an)
                s.need(ft, ty, node, line, where, "field `%s` of `%s`" % (an, nm))
                continue
            owner = [a for a in anc if an in s.classes[a].fields]
            if owner:
                s.err(line, "`%s` literal in `%s` names the base field `%s` of `%s` directly: build the base part and pass it as "
                      "`super: %s.new(..)` (a base keeps its own invariants)" % (nm, where, an, owner[0], owner[0]))
            else:
                s.err(line, "`%s` literal in `%s`: `%s` has no field `%s`" % (nm, where, nm, an))
        for f, (ft, pub, dflt) in c.fields.items():
            if f not in seen and not dflt:
                s.err(line, "`%s` literal in `%s` doesn't set field `%s`: no object exists until every field is set" % (nm, where, f))
        if base_has_fields and 'super' not in seen:
            s.err(line, "`%s` literal in `%s` is missing `super:`: the base part (`%s`) must be built first" % (nm, where, user_parent[0]))

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
            dt = tyconv(decl[0]) if decl else None
            s.no_store_self(val, cline(ctx), cname(ctx), "`%s %s`" % (k, n.a[0]))
            if dt is not None:
                s.need(dt, t, val, cline(ctx), cname(ctx), "`%s %s`" % (k, n.a[0]))
                s.check_list(dt, val, ctx)
            env[n.a[0]] = dt if decl else t
            return None
        if k == 'field':
            t = s.v(n.c[0], env, ctx)
            if s.b and t and t[0] == 'dyn' and not s.is_self(n.c[0]):
                s.err(cline(ctx), "`.%s` in `%s`: fields are not reachable through `dyn %s`; call a method" % (n.a[0], cname(ctx), t[1]))
                return None
            if t and t[0] in ('t', 'dyn') and t[1] in s.classes:
                for a in s.ancestors(t[1]):
                    f = s.classes[a].fields.get(n.a[0])
                    if f:
                        if s.b and not f[1] and not s.can_see(ctx, a):
                            s.err(cline(ctx), "field `%s` of `%s` is private to module `%s` and its subclasses; `%s` can't read it"
                                  % (n.a[0], a, s.classes[a].module, cname(ctx)))
                        return f[0]
            return None
        if k == 'index':
            t = s.v(n.c[0], env, ctx)
            s.v(n.c[1], env, ctx)
            return s.elem(t)
        if k == 'list':
            ts = [s.v(x, env, ctx) for x in n.c]
            s.lit_elems[id(n)] = ts
            for x in n.c:
                s.no_store_self(x, cline(ctx), cname(ctx), "list element")
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
        if k == 'named':
            return s.v(n.c[0], env, ctx)
        if k == 'assign':
            tl = s.v(n.c[0], env, ctx)
            tr = s.v(n.c[1], env, ctx)
            s.no_store_self(n.c[1], cline(ctx), cname(ctx), "assignment")
            s.need(tl, tr, n.c[1], cline(ctx), cname(ctx), "assignment")
            s.check_list(tl, n.c[1], ctx)
            return None
        if k == 'return':
            tr = s.v(n.c[0], env, ctx) if n.c else None
            if n.c and s.b:
                rt = s.ret_type(ctx)
                if s.is_self(n.c[0]):
                    s.need(rt, tr, n.c[0], cline(ctx), cname(ctx), "`return self`")
                    if ctx[0] and ctx[1].mode != 'take':
                        s.err(cline(ctx), "`return self` in `%s`: `self` is borrowed here; only a `take self` method can hand "
                              "it back (as a `dyn %s`)" % (cname(ctx), ctx[0]))
                else:
                    s.need(rt, tr, n.c[0], cline(ctx), cname(ctx), "`return`")
            return None
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
            argt = s.argvals(n.c[1:], env, ctx)
            if callee.k == 'name':
                nm = callee.a[0]
                if nm in s.classes and not s.classes[nm].builtin:
                    s.ctors.append((ctx, nm))
                    if s.b:
                        s.check_literal(n, nm, argt, ctx, cline(ctx), cname(ctx))
                    return ('t', nm, [])
                f = s.fns.get(nm)
                if f is not None:
                    s.check_args(s.fn_ptypes(f), "fn %s" % nm, argt, cline(ctx), cname(ctx))
                    r = [x for x in f.c if x.k == 'ret']
                    return tyconv(r[0].c[0]) if r else None
            else:
                s.v(callee, env, ctx)
            return None
        if k == 'supercall':
            via = [x for x in n.c if x.k == 'via']
            argt = s.argvals([x for x in n.c if x.k != 'via'], env, ctx)
            return s.do_super(n, via[0].a[0] if via else None, ctx, argt)
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
        argt = []
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
                argt.append((a.a[0], lam, None))
            else:
                argt.append(s.argvals([a], env, ctx)[0])
        where = cname(ctx)
        R = s.R
        line = cline(ctx)
        def chk(meth, cn_, T=None):
            ps = s.ptypes_of(meth, cn_) if T is None else [(a, (T if b == 'T' else ('t', 'Int', []) if b == 'Int' else
                                                              ('t', 'List', [T]) if b == 'List of T' else None) if meth.builtin else b, c_, d)
                                                          for a, b, c_, d in meth.ptypes]
            s.check_args(ps, meth.where(), argt, line, where)
        # self call
        if recv.k == 'name' and recv.a[0] == 'self' and ctx[0]:
            cn = ctx[0]
            r = s.res(cn, m)
            if not r and s.b and m in DERIVED:
                if m == 'copy' and not any('copy' in s.classes[a].caps for a in s.ancestors(cn)):
                    s.err(line, "`self.copy()` in `%s`: `%s` is not `is copy`" % (where, cn))
                s.add(where, 'self', m, 'derived', '', 0, [])
                return ('dyn', cn, []) if m == 'copy' else None     # copy of `self` is virtual: an owned `dyn C`
            if not r:
                s.err(cline(ctx), "`self.%s()` in `%s`: no such method" % (m, where))
                return None
            chk(r[0], cn)
            hook = s.is_hook(cn, m)
            open_ = R == 'h1' and (s.rules != 't3' or s.classes[cn].iface)    # t3: only provided iface functions are open
            if open_ or hook:
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
                chk(c.methods[m], cn)
                return s.ret_of(c.methods[m], None, cn)
            s.add(where, cn, m, 'builtin', '', 0, [])
            return None
        cn = rt[1]
        if s.b and cn == 'Pool' and rt[0] == 't':
            s.add(where, cn, m, 'builtin', '', 0, [])
            T = rt[2][0] if rt[2] else None
            if m == 'add':
                s.check_args([('value', T, None, False)], "Pool.add", argt, line, where)
                return ('t', 'Handle', [T])
            return None
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
            chk(r[0], cn, rt[2][0] if rt[2] else None)
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
            chk(r, cn, rt[2][0] if rt[2] else None)
            return s.ret_of(r, rt, cn)
        r = s.res(cn, m)
        if not r:
            if m in DERIVED:
                s.add(where, cn, m, 'derived', '', 0, [])
                return ('t', 'Str', [])
            s.err(cline(ctx), "`%s` calls `%s.%s`: no such method" % (where, cn, m))
            return None
        s.add(where, cn, m, 'static-up', 'static', s.steps(cn, m), r[:1])
        chk(r[0], cn)
        return s.ret_of(r[0], rt, cn)
    def prim_ret(s, cn, m, rt):
        if m in ('sqrt',):
            return ('t', 'Float', [])
        return None

    def do_super(s, n, via, ctx, argt=()):
        cn = ctx[0]
        m = n.a[0]
        c = s.classes.get(cn)
        line, where = cline(ctx), cname(ctx)
        R = s.R
        if c is None or not c.parents:
            s.err(line, "`super.%s()` in `%s`: the type has no parent" % (m, where))
            return None
        if s.b and (ctx[1].name != m or 'override' not in ctx[1].flags):
            s.err(line, "`super.%s()` in `%s`: `super.m()` is only allowed inside `override fn m` (the same name); to share code "
                  "with another method, call it as `self.%s()`" % (m, where, m))
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
        if s.b:
            s.check_args(s.ptypes_of(r[0], cn), r[0].where(), argt, line, where)
            if r[0].mode == 'take':
                s.check_take_super(n, ctx)
        return s.ret_of(r[0], None, p)
    def check_take_super(s, n, ctx):
        """F3: in a `take self` override, `super.m()` gets `self` whole: it is a whole statement at the top level of the body,
        nothing was moved out of `self` before it, and `self` is not used after it (the base's m drops what is left, then the
        subclass tail through the vtable)."""
        line, where, meth = cline(ctx), cname(ctx), ctx[1]
        body = [x for x in meth.node.c if x.k == 'block']
        stmts = body[0].c if body else []
        def has(x, pred):
            return pred(x) or any(has(y, pred) for y in x.c)
        def mentions_self(x):
            return has(x, lambda q: q.k == 'name' and q.a[0] == 'self')
        idx = [i for i, st in enumerate(stmts) if has(st, lambda q: q is n)]
        if not idx:
            s.err(line, "`super.%s()` in `%s`: a `take self` override must call `super.%s()` as a statement of the method body "
                  "(not inside an `if`, loop or closure), so it runs exactly once with `self` whole" % (m_name(n), where, m_name(n)))
            return
        i = idx[0]
        st = stmts[i]
        core = st
        while core.k in ('try', 'try-context') and core.c:
            core = core.c[0]
        if st.k in ('if', 'while', 'for', 'match', 'iflet', 'with', 'block', 'lambda'):
            s.err(line, "`super.%s()` in `%s`: a `take self` override must call `super.%s()` as a statement of the method body "
                  "(not inside an `if`, loop or closure), so it runs exactly once with `self` whole" % (m_name(n), where, m_name(n)))
            return
        direct = core is n or (st.k in ('return', 'let', 'var') and any(
            (y is n or (y.k in ('try', 'try-context') and y.c and y.c[0] is n)) for y in st.c))
        if not direct:
            s.err(line, "`super.%s()` in `%s`: in a `take self` override the call must be a whole statement (`super.%s(..)`, "
                  "`return super.%s(..)` or `let x = super.%s(..)`); nothing else in the statement may touch `self`"
                  % ((m_name(n), where) + (m_name(n),) * 3))
            return
        if any(mentions_self(a) for a in n.c if a.k != 'via'):
            s.err(line, "`super.%s()` in `%s`: the arguments mention `self`, which is passed whole" % (m_name(n), where))
        for st2 in stmts[:i]:
            for q in [y for y in [st2] + [z for z in flat(st2)] if y.k in ('let', 'var', 'assign')]:
                val = q.c[-1] if q.k != 'assign' else q.c[1]
                if val.k == 'field' and s.is_self(val.c[0]):
                    ft = None
                    for a in s.ancestors(ctx[0]):
                        f = s.classes[a].fields.get(val.a[0])
                        if f:
                            ft = f[0]
                    if ft is None or ft[1] not in COPYABLE:
                        s.err(line, "`super.%s()` in `%s`: `self.%s` was moved out before the call (`%s`), so `self` is no longer whole; "
                              "move fields out only in a method that does not call `super`" % (m_name(n), where, val.a[0], q.k))
        for st2 in stmts[i + 1:]:
            if mentions_self(st2):
                s.err(line, "`super.%s()` in `%s`: `self` is used after the call; the base method has already dropped it"
                      % (m_name(n), where))
                break

    def check_calls(s):
        for ctx, cn in s.ctors:
            left = s.abstract_left(cn)
            if left and not s.b:
                s.err(cline(ctx), "cannot build `%s` in `%s`: abstract method%s %s not overridden"
                      % (cn, cname(ctx), 's' if len(left) > 1 else '', ", ".join("`%s`" % x for x in left)))
        for w, m, ln in s.unresolved:
            s.err(ln, "receiver type of `.%s()` in `%s` could not be worked out" % (m, w))
        if s.R in ('h2', 'h3'):
            seen = set()
            for cn, m, where in s.selfcalls:
                target = s.res(cn, m)[:1]
                for d in s.descendants(cn):
                    if d != cn and s.res(d, m)[:1] != target and (cn, m, d) not in seen:
                        seen.add((cn, m, d))
                        s.warnings.append("warning: `%s.%s` overrides `%s.%s`, but `%s` calls `self.%s()` statically, so the "
                                          "override is NOT reached from there (declare `hook fn %s` in the base to open it)"
                                          % (d, m, target[0].owner, m, where, m, m))

    def cycles(s):
        """S2: self-call / super edges between bodies (open recursion); every strongly connected set of 2+ bodies is a cycle."""
        edges, order = {}, []
        for x in s.sites:
            if x['cause'] in ('self-open', 'super') and x['ctx'] and x['cands']:
                a = x['ctx']
                if a not in order:
                    order.append(a)
                edges.setdefault(a, [])
                for c in x['cands']:
                    if c.node is not None:
                        b = c.where()
                        if b not in order:
                            order.append(b)
                        edges[a].append(b)
        idx, low, st, on, out, cnt = {}, {}, [], set(), [], [0]
        def sc(v):
            idx[v] = low[v] = cnt[0]
            cnt[0] += 1
            st.append(v)
            on.add(v)
            for w in edges.get(v, []):
                if w not in idx:
                    sc(w)
                    low[v] = min(low[v], low[w])
                elif w in on:
                    low[v] = min(low[v], idx[w])
            if low[v] == idx[v]:
                comp = []
                while True:
                    w = st.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1:
                    out.append(sorted(comp, key=order.index))
        for v in order:
            if v not in idx:
                sc(v)
        return out

    def collect_t3(s, tree):
        """The old iface/impl corpus: an `iface` is a class (provided functions have bodies), `impl I for T` makes T a conformer
        of I, an enum with fns is a class with variants. Self-calls are open only inside iface functions."""
        impls = []
        def walk(n):
            for k in n.c:
                if k.k == 'module':
                    walk(k)
                elif k.k in ('type', 'iface', 'enum'):
                    s.add_type(k)
                    c = s.classes[k.a[0]]
                    if k.k == 'iface':
                        c.iface = True
                        for m in c.methods.values():
                            if not any(x.k == 'block' for x in m.node.c):
                                m.flags.add('abstract')
                                m.abstract = True
                    if k.k == 'enum':
                        for v in k.c:
                            if v.k == 'variant':
                                c.variants[v.a[0]] = [tyconv(f.c[0]) for f in v.c if f.k == 'vfield']
                elif k.k == 'impl':
                    impls.append((k.a[0], k.a[1]))
                elif k.k == 'fn':
                    s.fns[k.a[0]] = k
        walk(tree)
        for i, ty in impls:
            s.classes[ty].parents.append(i)

    def run_t3(s, tree):
        s.collect_t3(tree)
        s.visit_all()
        s.check_calls()

    def run(s, tree):
        s.collect(tree)
        s.check_decls()
        if not s.errors:
            s.visit_all()
            s.check_calls()
            if s.b:
                for comp in s.cycles():
                    s.warnings.append("warning: self-call cycle through overrides: %s (each reaches the next through `self.` calls "
                                      "or `super`; a call to one of them may not terminate)" % " -> ".join(comp + comp[:1]))


def exact_sites(p):
    """S5: with exact receivers, a self-call resolves statically unless the method body can be reached with a `dyn` (unknown)
    receiver. Seeds: every body that a `dyn` call can run; then every body their open self-calls or `super` calls can run."""
    reached = set()
    for x in p.sites:
        if x['cause'] == 'dyn':
            reached |= {c.where() for c in x['cands']}
    grew = True
    while grew:
        grew = False
        for x in p.sites:
            if x['ctx'] in reached and x['cause'] in ('self-open', 'super'):
                new = {c.where() for c in x['cands']} - reached
                if new:
                    reached |= new
                    grew = True
    out = []
    for x in p.sites:
        if x['cause'] == 'self-open' and x['ctx'] not in reached:
            x = dict(x, kind='static-up', cause='self-exact', cands=x['cands'][:1])
        out.append(x)
    return out


def stats(p, sites=None):
    sites = p.sites if sites is None else sites
    cls = [x for x in sites if x['kind'] in ('static-up', 'dynamic-down')]
    st = [x for x in cls if x['kind'] == 'static-up']
    dy = [x for x in cls if x['kind'] == 'dynamic-down']
    cnt = lambda xs: [len(x['cands']) for x in xs]
    return dict(
        sites=len(cls), static=len(st), super=sum(1 for x in st if x['cause'] == 'super'),
        closed=sum(1 for x in st if x['cause'] in ('self-closed', 'self-exact')),
        dyn=len(dy), dynrecv=sum(1 for x in dy if x['cause'] == 'dyn'),
        selfdyn=sum(1 for x in dy if x['cause'] != 'dyn'),
        avg=(sum(cnt(cls)) / len(cls)) if cls else 0, avgdyn=(sum(cnt(dy)) / len(dy)) if dy else 0,
        maxc=max(cnt(cls) or [0]), maxsteps=max([x['up'] for x in cls] or [0]),
        tcalls=sum(1 for x in sites if x['kind'] == 'type-call'),
        excl=sum(1 for x in sites if x['kind'] in ('builtin', 'derived')), warns=len(p.warnings))


def load(path, rules):
    with open(path, 'rb') as f:
        src = f.read().decode('utf-8')
    tree = Parser(Lexer(src).run()).file()
    p = Prog(rules)
    p.run(tree)
    return p


def load_t3(path):
    here = os.path.dirname(os.path.abspath(__file__))
    old = os.path.join(here, '..', '..', 'syntax', 'p3n', 'parser.py')
    spec = importlib.util.spec_from_file_location('p3n_parser_old', old)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with open(path, 'rb') as f:
        src = f.read().decode('utf-8')
    tree = mod.Parser(mod.Lexer(src).run()).file()
    p = Prog('t3')
    p.run_t3(tree)
    return p


# ---------------- S2: the API summary (fragile base class tooling)
def api(p):
    """{ 'Class.method': (receiver mode, sorted self-call names) } for every pub method of a user class (pub = what a subclass
    author may override or call)."""
    out = {}
    calls = {}
    for x in p.sites:
        if x['recv'] == 'self':
            calls.setdefault(x['ctx'], set()).add(x['m'])
    for cn, c in p.classes.items():
        if c.builtin:
            continue
        for m in c.methods.values():
            if m.pub and not m.static:
                out[m.where()] = (m.mode, sorted(calls.get(m.where(), set())))
    return out


def print_api(a):
    for k, (mode, cs) in a.items():
        print("%-28s %-5s self-calls: %s" % (k, mode, ", ".join(cs) if cs else "-"))


def api_diff(old, new):
    n = 0
    for k, (mode, cs) in old.items():
        if k not in new:
            print("BREAKING: %s removed" % k)
            n += 1
        elif new[k][1] != cs:
            lost, gained = sorted(set(cs) - set(new[k][1])), sorted(set(new[k][1]) - set(cs))
            print("BREAKING: %s self-call set changed: -{%s} +{%s}: a subclass that overrides %s no longer %s" % (
                k, ", ".join(lost), ", ".join(gained), "/".join(lost + gained),
                "sees this method call it" if lost else "is called from it unnoticed (new open call)"))
            n += 1
    for k in new:
        if k not in old:
            print("BREAKING: %s added: a subclass that already declares `%s` now fails to compile (`override` missing)"
                  % (k, k.split('.')[1]))
            n += 1
    if n == 0:
        print("compatible: same public methods, same self-call sets")
    return n


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


def report(p, path):
    for line, msg in p.errors:
        sys.stderr.write("%s:%d: error: %s\n" % (path, line, msg))
    return 1 if p.errors else 0


def main(argv):
    args = argv[1:]
    det = '--detail' in args
    exact = '--exact' in args
    args = [a for a in args if a not in ('--detail', '--exact')]
    try:
        if args and args[0] == '--all':
            rows, bad = [], 0
            for h in ('h1', 'h2', 'h3', 'h1b'):
                path = os.path.join(args[1], h, 'types.p3')
                p = load(path, h)
                bad |= report(p, path)
                for w in p.warnings:
                    print("%s: %s" % (h, w))
                if det:
                    print(h)
                    detail(p)
                rows.append((h.upper() if h != 'h1b' else 'H1b', stats(p)))
                if h == 'h1b':
                    rows.append(('H1b --exact', stats(p, exact_sites(p))))
            path = os.path.join(args[1], '..', '..', 'syntax', 'p3n', 'corpus', 'types.p3')
            p = load_t3(path)
            bad |= report(p, path)
            rows.append(('T3+ iface/impl', stats(p)))
            table(rows)
            return bad
        if args and args[0] == '--t3' and len(args) == 2:
            p = load_t3(args[1])
            if det:
                detail(p)
            if report(p, args[1]):
                return 1
            print("SUMMARY " + " ".join("%s=%s" % kv for kv in stats(p).items()))
            return 0
        if len(args) == 2 and args[0] == '--api':
            p = load(args[1], 'h1b')
            if report(p, args[1]):
                return 1
            print_api(api(p))
            return 0
        if len(args) == 3 and args[0] == '--api-diff':
            ps = [load(a, 'h1b') for a in args[1:]]
            if any(report(p, a) for p, a in zip(ps, args[1:])):
                return 1
            return 1 if api_diff(api(ps[0]), api(ps[1])) else 0
        if len(args) == 3 and args[0] == '--rules':
            p = load(args[2], args[1])
            for line, msg in p.errors:
                sys.stderr.write("%s:%d: error: %s\n" % (args[2], line, msg))
            for w in p.warnings:
                print(w)
            if det:
                detail(p)
            if not p.errors:
                st = stats(p, exact_sites(p) if exact else None)
                print("SUMMARY " + " ".join("%s=%s" % kv for kv in st.items()))
            return 1 if p.errors else 0
    except Err as e:
        sys.stderr.write("%s:%d:%d: %s\n" % (args[-1], e.line, e.col, e.msg))
        return 1
    sys.stderr.write(__doc__ + "\n")
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
