#!/usr/bin/env python3
"""P3 parser: Go-style statement ends; only ( ) [ ] and a leading . or ?. continue a line; same-line braces.
Usage: parser.py FILE   (prints the AST described in ../AST.md, or exits 1 with FILE:LINE:COL: message)"""
import sys, json

KW = set("""module use pub const type enum iface impl for fn drop let var if else while in match return fail fails
break continue try context or and not crew lock with of to dyn is take mut self true false none desc as""".split())
ENDER_KW = {'return', 'break', 'continue', 'true', 'false', 'none', 'self', 'fails', 'desc'}
OPS2 = ['==', '!=', '<=', '>=', '+=', '-=', '*=', '/=', '%=', '=>', '->', '?.', '??', '..']
OPS1 = '+-*/%<>=.,:;()[]{}|'
ESC = {'n': '\n', 't': '\t', 'r': '\r', '0': '\0', '\\': '\\', '"': '"', '{': '{', '}': '}'}
ASSIGN = ('=', '+=', '-=', '*=', '/=', '%=')
CLOSE = {')': '(', ']': '[', '}': '{'}
TO_HEADS = ('Map', 'SortedMap')
BINOPS = ('+', '-', '*', '/', '%', '==', '!=', '<', '<=', '>', '>=', '??', '..', '..=')


class Err(Exception):
    def __init__(s, line, col, msg):
        Exception.__init__(s, msg)
        s.line, s.col, s.msg = line, col, msg


class Tok:
    def __init__(s, k, v, line, col):
        s.k, s.v, s.line, s.col = k, v, line, col
    def desc(s):
        if s.k == 'nl':
            return 'end of line'
        if s.k == 'eof':
            return 'end of file'
        if s.k == 'str':
            return 'a string'
        return "'%s'" % s.v


# ---------------------------------------------------------------- lexer
class Lexer:
    def __init__(s, src, line=1, col0=1, sub=False):
        s.src = src.replace('\r\n', '\n').replace('\r', '\n')   # CRLF and lone CR are line ends
        s.n = len(s.src)
        s.line, s.ls, s.sub = line, -(col0 - 1), sub
        s.toks, s.stack = [], []
    def pos(s, i):
        return s.line, i - s.ls + 1
    def err(s, i, msg):
        l, c = s.pos(i)
        raise Err(l, c, msg)
    def add(s, k, v, i):
        l, c = s.pos(i)
        s.toks.append(Tok(k, v, l, c))
    def run(s):
        src, n, i = s.src, s.n, 0
        while i < n:
            c = src[i]
            if c == '\n':
                s.newline(i)
                s.line += 1
                s.ls = i + 1
                i += 1
            elif c in ' \t':
                i += 1
            elif c == '#':
                while i < n and src[i] != '\n':
                    i += 1
            elif c.isdigit():
                i = s.number(i)
            elif c.isalpha() or c == '_':
                j = i
                while j < n and (src[j].isalnum() or src[j] == '_'):
                    j += 1
                w = src[i:j]
                s.add('kw' if w in KW else 'id', w, i)
                i = j
            elif c == '"':
                i = s.string(i)
            else:
                i = s.op(i)
        if s.stack:
            ch, l, c = s.stack[-1]
            raise Err(l, c, "unclosed '%s' (end of file reached)" % ch)
        if not s.sub and s.toks and s.is_ender(s.toks[-1]):
            s.add('nl', '\n', n)
        s.add('eof', '', n)
        return s.toks
    @staticmethod
    def is_ender(t):
        if t.k in ('id', 'int', 'float', 'str'):
            return True
        if t.k == 'op':
            return t.v in (')', ']', '}')
        return t.k == 'kw' and t.v in ENDER_KW
    def newline(s, i):
        if s.stack and s.stack[-1][0] in '([':
            return                      # nothing ends inside ( ) or [ ]
        t = s.toks[-1] if s.toks else None
        if t is not None and s.dangling(t):
            what = "'%s'" % t.v
            raise Err(t.line, t.col, "line ends with %s: wrap the whole expression in ( ) "
                      "(only brackets and a leading '.' continue a line)" % what.replace("'", '`'))
        if not s.toks or not s.is_ender(t):
            return
        c = s.continues(i + 1)
        if c == 'dot':
            return
        if c:
            l, col = c
            raise Err(l, col, "line starts with `%s`: wrap the whole expression in ( )"
                      "%s" % (s.lead, " (for try ... or e { }, keep `or` on the line of the try operand)" if s.lead == 'or' else ''))
        s.add('nl', '\n', i)
    @staticmethod
    def dangling(t):
        if t.k == 'op':
            return t.v in BINOPS or t.v == ',' or t.v in ASSIGN
        return t.k == 'kw' and t.v in ('and', 'or')
    def continues(s, j):
        """Next non-blank, non-comment line: 'dot' if it starts with . or ?. ; (line, col) if it starts with and / or."""
        src, n = s.src, s.n
        line, ls = s.line + 1, j
        while j < n:
            if src[j] in ' \t':
                j += 1
            elif src[j] == '\n':
                line += 1
                ls = j + 1
                j += 1
            elif src[j] == '#':
                while j < n and src[j] != '\n':
                    j += 1
            else:
                break
        else:
            return False
        if src.startswith('?.', j) or (src[j] == '.' and not src.startswith('..', j)):
            return 'dot'
        for w in ('and', 'or'):
            e = j + len(w)
            if src.startswith(w, j) and not (e < n and (src[e].isalnum() or src[e] == '_')):
                s.lead = w
                return (line, j - ls + 1)
        return False
    def number(s, i):
        src, n = s.src, s.n
        j = i
        while j < n and (src[j].isdigit() or src[j] == '_'):
            j += 1
        isf = False
        if j + 1 < n and src[j] == '.' and src[j + 1].isdigit():
            isf = True
            j += 1
            while j < n and (src[j].isdigit() or src[j] == '_'):
                j += 1
        if j < n and (src[j].isalpha() or src[j] == '_'):
            s.err(i, "invalid number '%s'" % src[i:j + 1])
        s.add('float' if isf else 'int', src[i:j].replace('_', ''), i)
        return j
    def skip_str(s, t, j):
        j += 1
        while j < len(t):
            c = t[j]
            if c == '\\':
                j += 2
            elif c == '"':
                return j + 1
            elif c == '{':
                j = s.scan_interp(t, j + 1) + 1
            elif c == '\n':
                break
            else:
                j += 1
        s.err(j, "unterminated string")
    def scan_interp(s, t, j):
        depth = 0
        while j < len(t):
            c = t[j]
            if c == '"':
                j = s.skip_str(t, j)
                continue
            if c in '([{':
                depth += 1
            elif c in ')]':
                depth -= 1
            elif c == '}':
                if depth == 0:
                    return j
                depth -= 1
            elif c == '\n':
                break
            j += 1
        s.err(j, "unterminated '{' in string interpolation")
    def split_fmt(s, body):
        depth, k = 0, 0
        while k < len(body):
            c = body[k]
            if c == '"':
                k = s.skip_str(body, k)
                continue
            if c in '([{':
                depth += 1
            elif c in ')]}':
                depth -= 1
            elif c == ':' and depth == 0:
                return body[:k], body[k + 1:]
            k += 1
        return body, None
    def string(s, i):
        src, n = s.src, s.n
        j, buf, parts = i + 1, [], []
        while True:
            if j >= n or src[j] == '\n':
                s.err(i, "unterminated string (strings end on the line they start)")
            c = src[j]
            if c == '"':
                break
            if c == '\\':
                e = src[j + 1] if j + 1 < n else ''
                if e not in ESC:
                    s.err(j, "unknown escape '\\%s'" % e)
                buf.append(ESC[e])
                j += 2
            elif c == '{':
                k = s.scan_interp(src, j + 1)
                body = src[j + 1:k]
                if not body.strip():
                    s.err(j, "empty interpolation (write \\{ for a literal brace)")
                text, fmt = s.split_fmt(body)
                if buf:
                    parts.append(('s', ''.join(buf)))
                    buf = []
                l, col = s.pos(j + 1)
                parts.append(('e', text, fmt, l, col))
                j = k + 1
            else:
                buf.append(c)
                j += 1
        if buf or not parts:
            parts.append(('s', ''.join(buf)))
        s.add('str', parts, i)
        return j + 1
    def op(s, i):
        src = s.src
        c = src[i]
        if src.startswith('..=', i):
            s.add('op', '..=', i)
            return i + 3
        two = src[i:i + 2]
        if two == '&&':
            s.err(i, "unknown operator '&&'; use 'and'")
        if two == '||':
            s.err(i, "unknown operator '||'; use 'or'")
        if two in OPS2:
            s.add('op', two, i)
            return i + 2
        if c == '!':
            s.err(i, "unknown operator '!'; use 'not'")
        if c not in OPS1:
            s.err(i, "unexpected character %r" % c)
        l, col = s.pos(i)
        if c in '([{':
            s.stack.append((c, l, col))
        elif c in ')]}':
            if not s.stack:
                s.err(i, "unexpected '%s' with nothing open" % c)
            o, ol, _ = s.stack[-1]
            if o != CLOSE[c]:
                s.err(i, "mismatched '%s': the '%s' opened at line %d is still open" % (c, o, ol))
            s.stack.pop()
        s.add('op', c, i)
        return i + 1


# ---------------------------------------------------------------- AST
class N:
    def __init__(s, k, a=(), c=()):
        s.k, s.a, s.c = k, list(a), list(c)


def Q(text):
    return json.dumps(text, ensure_ascii=False)


def render(n, d, out):
    head = '(' + ' '.join([n.k] + n.a)
    if not n.c:
        out.append('  ' * d + head + ')')
        return
    out.append('  ' * d + head)
    for k in n.c:
        render(k, d + 1, out)
    out[-1] += ')'


# ---------------------------------------------------------------- parser
class Parser:
    def __init__(s, toks):
        s.t, s.i = toks, 0
    def peek(s, o=0):
        return s.t[min(s.i + o, len(s.t) - 1)]
    def nxt(s):
        t = s.t[s.i]
        if t.k != 'eof':
            s.i += 1
        return t
    def isop(s, v, o=0):
        t = s.peek(o)
        return t.k == 'op' and t.v == v
    def iskw(s, v, o=0):
        t = s.peek(o)
        return t.k == 'kw' and t.v == v
    def accop(s, v):
        if s.isop(v):
            s.i += 1
            return True
        return False
    def acckw(s, v):
        if s.iskw(v):
            s.i += 1
            return True
        return False
    def fail(s, msg, t=None):
        t = t or s.peek()
        raise Err(t.line, t.col, msg)
    def expop(s, v, ctx=''):
        if not s.isop(v):
            s.fail("expected '%s'%s, found %s" % (v, ctx, s.peek().desc()))
        s.i += 1
    def expkw(s, v):
        if not s.iskw(v):
            s.fail("expected '%s', found %s" % (v, s.peek().desc()))
        s.i += 1
    def ident(s, what='a name'):
        t = s.peek()
        if t.k != 'id':
            s.fail("expected %s, found %s" % (what, t.desc()))
        s.i += 1
        return t.v
    def seq(s, one, end, commas=False):
        out = []
        while True:
            while s.peek().k == 'nl' or s.isop(';') or (commas and s.isop(',')):
                s.i += 1
            t = s.peek()
            if end is None and t.k == 'eof':
                return out
            if end is not None and t.k == 'op' and t.v == end:
                return out
            if t.k == 'eof':
                s.fail("expected '%s', found end of file" % end)
            out.append(one())
            t = s.peek()
            if t.k == 'nl' or (end is None and t.k == 'eof'):
                continue
            if t.k == 'op' and (t.v == ';' or t.v == end or (commas and t.v == ',')):
                continue
            s.fail("expected end of line or ';' before %s" % t.desc())
    def body(s, what, one, commas=False):
        t = s.peek()
        if not (t.k == 'op' and t.v == '{'):
            s.fail("expected '{' to open the %s body (the '{' must be on the same line as the header), found %s"
                   % (what, t.desc()))
        s.i += 1
        kids = s.seq(one, '}', commas)
        s.expop('}')
        return kids
    def block(s, what):
        return N('block', (), s.body(what, s.stmt))
    def file(s):
        return N('file', (), s.seq(s.stmt, None))

    # ---- statements and declarations
    def stmt(s):
        t = s.peek()
        pub = False
        if t.k == 'kw':
            v = t.v
            if v == 'pub':
                s.i += 1
                pub = True
                t = s.peek()
                if t.k != 'kw' or t.v not in ('fn', 'type', 'enum', 'iface', 'const', 'var'):
                    s.fail("'pub' must be followed by fn, type, enum, iface, const or var")
                v = t.v
            if v == 'else':
                s.fail("'else' must follow the closing '}' of the if on the same line ('} else {')")
            h = getattr(s, 'st_' + v, None)
            if h and not (v == 'fn' and s.peek(1).k != 'id'):
                return h(pub)
        return s.simple()
    def simple(s):
        e = s.expr()
        t = s.peek()
        if t.k == 'op' and t.v in ASSIGN:
            if e.k not in ('name', 'field', 'index'):
                s.fail("cannot assign to this expression", t)
            s.i += 1
            r = s.expr()
            return N('assign', (), [e, r]) if t.v == '=' else N('opassign', [t.v[0]], [e, r])
        return e
    def st_use(s, pub):
        s.i += 1
        path = s.ident('a module name')
        while s.accop('.'):
            path += '.' + s.ident('a module name')
        a = [path]
        if s.acckw('as'):
            a += ['as', s.ident()]
        return N('use', a)
    def st_module(s, pub):
        s.i += 1
        name = s.ident('a module name')
        return N('module', [name], s.body('module', s.stmt))
    def decl_var(s, pub, kind):
        s.i += 1
        name = s.ident('a variable name')
        ty = s.type() if s.accop(':') else None
        s.expop('=', " (a variable needs an initial value) after '%s'" % name)
        e = s.expr()
        return N(kind, [name] + (['pub'] if pub else []), ([ty] if ty else []) + [e])
    def st_let(s, pub):
        return s.decl_var(pub, 'let')
    def st_var(s, pub):
        return s.decl_var(pub, 'var')
    def st_const(s, pub):
        return s.decl_var(pub, 'const')
    def st_type(s, pub):
        s.i += 1
        name = s.ident('a type name')
        return N('type', [name] + (['pub'] if pub else []), s.body('type', lambda: s.member('type'), True))
    def st_enum(s, pub):
        s.i += 1
        name = s.ident('an enum name')
        return N('enum', [name] + (['pub'] if pub else []), s.body('enum', lambda: s.member('enum'), True))
    def st_iface(s, pub):
        s.i += 1
        name = s.ident('an interface name')
        kids = []
        if s.acckw('is'):
            names = [s.ident('a built-in capability')]
            while s.accop(','):
                names.append(s.ident('a built-in capability'))
            kids.append(N('is', names))
        return N('iface', [name] + (['pub'] if pub else []), kids + s.body('interface', lambda: s.member('iface')))
    def st_impl(s, pub):
        s.i += 1
        i = s.ident('an interface name')
        s.expkw('for')
        return N('impl', [i, s.ident('a type name')])
    def member(s, kind):
        pub = s.acckw('pub')
        if s.iskw('fn'):
            return s.st_fn(pub)
        if s.iskw('drop') and kind != 'iface':
            s.i += 1
            s.expop('(', " after 'drop'")
            ps = s.params()
            s.expop(')')
            return N('drop', (), ps + [s.block('drop')])
        fl = ['pub'] if pub else []
        if kind == 'type':
            name = s.ident('a field name or fn')
            s.expop(':', " after the field name")
            kids = [s.type()]
            if s.accop('='):
                kids.append(N('default', (), [s.expr()]))
            return N('field', [name] + fl, kids)
        if kind == 'enum':
            name = s.ident('a variant name or fn')
            vf = []
            if s.accop('('):
                while not s.isop(')'):
                    if s.peek().k == 'id' and s.isop(':', 1):
                        n = s.nxt().v
                        s.i += 1
                        vf.append(N('vfield', [n], [s.type()]))
                    else:
                        vf.append(N('vfield', (), [s.type()]))
                    if not s.accop(','):
                        break
                s.expop(')')
            return N('variant', [name], vf)
        s.fail("expected 'fn' in an interface, found %s" % s.peek().desc())
    def params(s):
        out = []
        while not s.isop(')'):
            out.append(s.param())
            if not s.accop(','):
                break
        return out
    def param(s):
        mode = None
        if s.iskw('mut') or s.iskw('take'):
            mode = s.nxt().v
        if s.acckw('self'):
            return N('recv', [mode or 'self'])
        name = s.ident('a parameter name')
        kids = []
        if s.accop(':'):
            kids.append(s.type())
        if s.accop('='):
            kids.append(N('default', (), [s.expr()]))
        return N('param', [name] + ([mode] if mode else []), kids)
    def st_fn(s, pub):
        s.i += 1
        name = s.ident('a function name')
        s.expop('(', " after the function name")
        kids = s.params()
        s.expop(')', " after the parameters")
        if s.accop('->'):
            kids.append(N('ret', (), [s.type()]))
        fl = (['pub'] if pub else []) + (['fails'] if s.acckw('fails') else [])
        if s.isop('{'):
            kids.append(s.block('function'))
        return N('fn', [name] + fl, kids)
    def st_while(s, pub):
        s.i += 1
        c = s.expr()
        return N('while', (), [c, s.block('while')])
    def st_for(s, pub):
        s.i += 1
        p = s.pattern()
        s.expkw('in')
        it = s.expr()
        return N('for', (), [p, it, s.block('for')])
    def ends_stmt(s):
        t = s.peek()
        return t.k in ('nl', 'eof') or (t.k == 'op' and t.v in (';', '}'))
    def st_return(s, pub):
        s.i += 1
        return N('return', (), [] if s.ends_stmt() else [s.expr()])
    def st_break(s, pub):
        s.i += 1
        return N('break')
    def st_continue(s, pub):
        s.i += 1
        return N('continue')
    def exprs(s):
        out = [s.expr()]
        while s.accop(','):
            out.append(s.expr())
        return out
    def st_fail(s, pub):
        s.i += 1
        return N('fail', (), s.exprs())
    def st_lock(s, pub):
        s.i += 1
        es = s.exprs()
        return N('lock', (), es + [s.block('lock')])
    def st_with(s, pub):
        s.i += 1
        name = s.ident('a name to bind')
        s.expop('=', " after the name in 'with'")
        e = s.expr()
        return N('with', [name], [e, s.block('with')])

    # ---- types
    def type(s):
        t = s.peek()
        if s.acckw('dyn'):
            return N('dyn', [s.ident('an interface name')])
        if s.acckw('fn'):
            s.expop('(', " after 'fn' in a function type")
            args = []
            while not s.isop(')'):
                mode = s.nxt().v if (s.iskw('mut') or s.iskw('take')) else None
                a = s.type()
                args.append(N(mode, (), [a]) if mode else a)
                if not s.accop(','):
                    break
            s.expop(')')
            if s.accop('->'):
                args.append(N('ret', (), [s.type()]))
            return N('fnt', ['fails'] if s.acckw('fails') else [], args)
        if s.accop('('):
            ts = [s.type()]
            while s.accop(','):
                ts.append(s.type())
            s.expop(')')
            return N('ttuple', (), ts)
        name = s.ident('a type')
        if not s.acckw('of'):
            return N('t', [name])
        kids = [s.type()]
        if name in TO_HEADS and s.acckw('to'):
            kids.append(s.type())
        return N('t', [name], kids)

    # ---- patterns
    def pattern(s):
        p = s.pat1()
        if s.isop('|'):
            alts = [p]
            while s.accop('|'):
                alts.append(s.pat1())
            return N('por', (), alts)
        return p
    def pat1(s):
        t = s.peek()
        if t.k == 'id':
            s.i += 1
            if t.v == '_':
                return N('pwild')
            name = t.v
            while s.isop('.') and s.peek(1).k == 'id':
                s.i += 1
                name += '.' + s.nxt().v
            if s.accop('('):
                subs = []
                while not s.isop(')'):
                    subs.append(s.pattern())
                    if not s.accop(','):
                        break
                s.expop(')')
                return N('pvariant', [name], subs)
            if name[0].isupper() or '.' in name:
                return N('pvariant', [name])
            return N('pbind', [name])
        if t.k in ('int', 'float', 'str') or (t.k == 'kw' and t.v in ('true', 'false', 'none')):
            return N('plit', (), [s.primary()])
        if t.k == 'op' and t.v == '-' and s.peek(1).k in ('int', 'float'):
            s.i += 2
            return N('plit', (), [N(s.t[s.i - 1].k, ['-' + s.t[s.i - 1].v])])
        if s.accop('('):
            ps = []
            while not s.isop(')'):
                ps.append(s.pattern())
                if not s.accop(','):
                    break
            s.expop(')')
            return N('ptuple', (), ps)
        if s.accop('['):
            ps = []
            while not s.isop(']'):
                if s.accop('..'):
                    ps.append(N('prest', [s.nxt().v] if s.peek().k == 'id' else []))
                else:
                    ps.append(s.pattern())
                if not s.accop(','):
                    break
            s.expop(']')
            return N('plist', (), ps)
        s.fail("expected a pattern, found %s" % t.desc())

    # ---- expressions
    def expr(s, no_or=False):
        l = s.p_and()
        while not no_or and s.iskw('or'):
            s.i += 1
            l = N('bin', ['or'], [l, s.p_and()])
        return l
    def p_and(s):
        l = s.p_not()
        while s.acckw('and'):
            l = N('bin', ['and'], [l, s.p_not()])
        return l
    def p_not(s):
        if s.acckw('not'):
            return N('un', ['not'], [s.p_not()])
        return s.binlevel(s.p_coalesce, ('==', '!=', '<', '<=', '>', '>='))
    def p_coalesce(s):
        return s.binlevel(s.p_range, ('??',))
    def p_range(s):
        l = s.p_add()
        t = s.peek()
        if t.k == 'op' and t.v in ('..', '..='):
            s.i += 1
            return N('bin', [t.v], [l, s.p_add()])
        return l
    def p_add(s):
        return s.binlevel(s.p_mul, ('+', '-'))
    def p_mul(s):
        return s.binlevel(s.p_unary, ('*', '/', '%'))
    def binlevel(s, sub, ops):
        l = sub()
        while True:
            t = s.peek()
            if t.k == 'op' and t.v in ops:
                s.i += 1
                l = N('bin', [t.v], [l, sub()])
            else:
                return l
    def p_unary(s):
        if s.accop('-'):
            return N('un', ['-'], [s.p_unary()])
        if s.iskw('try'):
            return s.try_expr()
        return s.postfix()
    def try_expr(s):
        s.i += 1
        e = s.expr(no_or=True)          # 'or' after a try operand starts the handler
        if s.acckw('context'):
            return N('try-context', (), [e, s.expr(no_or=True)])
        if s.acckw('or'):
            name = s.ident("a name for the error (or '_')")
            return N('try-or', [name], [e, s.block('try handler')])
        return N('try', (), [e])
    def postfix(s):
        e = s.primary()
        while True:
            t = s.peek()
            if t.k != 'op':
                return e
            v = t.v
            if v in ('.', '?.'):
                s.i += 1
                nt = s.peek()
                if nt.k not in ('id', 'int'):
                    s.fail("expected a field or method name after '%s', found %s" % (v, nt.desc()))
                s.i += 1
                q = '?' if v == '?.' else ''
                if s.accop('('):
                    e = N('mcall' + q, [nt.v], [e] + s.args())
                else:
                    e = N('field' + q, [nt.v], [e])
            elif v == '(':
                s.i += 1
                e = N('call', (), [e] + s.args())
            elif v == '[':
                s.i += 1
                ix = s.expr()
                s.expop(']', " to close the index")
                e = N('index', (), [e, ix])
            else:
                return e
    def args(s):
        out = []
        while not s.isop(')'):
            out.append(s.arg())
            if not s.accop(','):
                break
        s.expop(')', " or ',' in the argument list")
        return out
    def arg(s):
        if s.accop('.'):
            name = s.ident('a field name after the leading .')
            while s.accop('.'):
                name += '.' + s.ident('a field name')
            if s.iskw('desc'):
                s.i += 1
                return N('key', [name, 'desc'])
            if s.peek().k == 'id' and s.peek().v == 'asc':
                s.i += 1
                return N('key', [name, 'asc'])
            return N('key', [name])
        if s.peek().k == 'id' and s.isop(':', 1):
            name = s.nxt().v
            s.i += 1
            return N('named', [name], [s.expr()])
        return s.expr()
    def primary(s):
        t = s.peek()
        k = t.k
        if k == 'int' or k == 'float':
            s.i += 1
            return N(k, [t.v])
        if k == 'str':
            s.i += 1
            return s.string(t.v)
        if k == 'id':
            s.i += 1
            if s.iskw('of'):
                s.i -= 1
                return s.type()          # 'Pool of Widget' in expression position; a call may follow
            return N('name', [t.v])
        if k == 'kw':
            v = t.v
            if v in ('true', 'false'):
                s.i += 1
                return N('bool', [v])
            if v == 'none':
                s.i += 1
                return N('none')
            if v == 'self':
                s.i += 1
                return N('name', ['self'])
            if v == 'if':
                return s.if_expr()
            if v == 'match':
                return s.match_expr()
            if v == 'fn':
                return s.lambda_()
            if v == 'crew':
                s.i += 1
                name = s.ident('a crew name')
                return N('crew', [name], [s.block('crew')])
            if v == 'else':
                s.fail("'else' must follow the closing '}' of the if on the same line ('} else {')")
        if k == 'op':
            if t.v == '(':
                s.i += 1
                if s.accop(')'):
                    return N('tuple')
                e = s.expr()
                if s.isop(','):
                    items = [e]
                    while s.accop(','):
                        if s.isop(')'):
                            break
                        items.append(s.expr())
                    s.expop(')')
                    return N('tuple', (), items)
                s.expop(')', " to close the parenthesis")
                return e
            if t.v == '[':
                s.i += 1
                items = []
                while not s.isop(']'):
                    items.append(s.expr())
                    if not s.accop(','):
                        break
                s.expop(']', " to close the list")
                return N('list', (), items)
            if t.v == '{':
                s.fail("unexpected '{': a block must start on the same line as its header, and braces are never "
                       "literals (construct with Name(field: value))")
        s.fail("expected an expression, found %s" % t.desc())
    def string(s, parts):
        if len(parts) == 1 and parts[0][0] == 's':
            return N('str', [Q(parts[0][1])])
        kids = []
        for p in parts:
            if p[0] == 's':
                kids.append(N('s', [Q(p[1])]))
                continue
            _, text, fmt, line, col = p
            sub = Parser(Lexer(text, line, col, True).run())
            try:
                e = sub.expr()
            except Err as x:
                raise Err(x.line, x.col, x.msg.replace('end of file', 'the end of the interpolation'))
            if sub.peek().k != 'eof':
                sub.fail("unexpected %s in string interpolation" % sub.peek().desc())
            kids.append(N('part', (), [e]) if fmt is None else N('partf', [Q(fmt)], [e]))
        return N('interp', (), kids)
    def if_expr(s):
        s.i += 1
        if s.peek().k == 'id' and s.isop('=', 1):
            name = s.nxt().v
            s.i += 1
            e = s.expr()
            node = N('iflet', [name], [e, s.block('if')])
        else:
            c = s.expr()
            node = N('if', (), [c, s.block('if')])
        if s.acckw('else'):
            node.c.append(N('else', (), [s.if_expr() if s.iskw('if') else s.block('else')]))
        return node
    def match_expr(s):
        s.i += 1
        scrut = s.expr()
        return N('match', (), [scrut] + s.body('match', s.arm, True))
    def arm(s):
        kids = [s.pattern()]
        if s.acckw('if'):
            kids.append(N('guard', (), [s.expr()]))
        s.expop('=>', " after the match pattern")
        kids.append(s.block('match arm') if s.isop('{') else s.stmt())
        return N('arm', (), kids)
    def lambda_(s):
        s.i += 1
        s.expop('(', " after 'fn'")
        ps = s.params()
        s.expop(')')
        if s.accop('=>'):
            return N('lambda', (), ps + [s.expr()])
        if s.isop('{'):
            return N('lambda', (), ps + [s.block('lambda')])
        s.fail("expected '=>' or '{' after the lambda parameters, found %s" % s.peek().desc())


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: parser.py FILE\n")
        return 2
    path = argv[1]
    try:
        with open(path, 'rb') as f:
            src = f.read().decode('utf-8')
    except (OSError, UnicodeDecodeError) as e:
        sys.stderr.write("%s:1:1: cannot read file: %s\n" % (path, e))
        return 1
    if src.startswith('﻿'):
        src = src[1:]
    try:
        ast = Parser(Lexer(src).run()).file()
    except Err as e:
        sys.stderr.write("%s:%d:%d: %s\n" % (path, e.line, e.col, e.msg))
        return 1
    out = []
    render(ast, 0, out)
    data = ("\n".join(out) + "\n").encode('utf-8')
    getattr(sys.stdout, 'buffer', sys.stdout).write(data)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
