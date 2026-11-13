#!/usr/bin/env python3
"""P3 parser: Go-style statement ends; only ( ) [ ] and a leading . or ?. continue a line; same-line braces.
Usage: parser.py FILE   (prints the AST described in ../AST.md, or exits 1 with FILE:LINE:COL: message)"""
import sys, json

# Truly reserved (28). Contextual words (desc asc to of context crew lock with drop take is dyn fails module use as)
# are plain names lexed as ids; the parser gives them meaning only where the grammar expects them.
KW = set("""pub const type enum iface impl for fn let var if else while in match return fail break continue try
or and not mut self true false none""".split())
ENDER_KW = {'return', 'break', 'continue', 'true', 'false', 'none', 'self'}
OPS2 = ['==', '!=', '<=', '>=', '+=', '-=', '*=', '/=', '%=', '=>', '->', '?.', '??', '..']
OPS1 = '+-*/%<>=.,:;()[]{}|'
ESC = {'n': '\n', 't': '\t', 'r': '\r', '0': '\0', '\\': '\\', '"': '"', '{': '{', '}': '}'}
ASSIGN = ('=', '+=', '-=', '*=', '/=', '%=')
CLOSE = {')': '(', ']': '[', '}': '{'}
TO_HEADS = ('Map', 'SortedMap', 'Lru')
BINOPS = ('+', '-', '*', '/', '%', '==', '!=', '<', '<=', '>', '>=', '??', '..', '..=')
CMP = ('==', '!=', '<', '<=', '>', '>=')
DANGLE = BINOPS + (',', ':', '.', '?.', '->', '=>') + ASSIGN


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
        s.toks, s.stack, s.opens = [], [], []
        s.lines = s.src.split('\n')
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
                pv = s.toks[-1] if s.toks else None
                after_dot = pv is not None and pv.k == 'op' and pv.v in ('.', '?.')
                s.add('kw' if w in KW and not after_dot else 'id', w, i)   # after `.` any word is a member name
                i = j
            elif c == '"':
                i = s.string(i)
            else:
                i = s.op(i)
        if s.stack:
            o = s.stack[-1]
            raise s.unclosed(o, "unclosed '%s' (end of file reached)" % o[0])
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
        t = s.toks[-1] if s.toks else None
        top = s.stack[-1][0] if s.stack else None
        if top in ('(', '['):           # nothing ends inside ( ) or [ ]
            if t is not None and s.is_ender(t):
                c = s.nextline(i + 1)
                if c and (s.src[c[0]] in '([' or (s.src[c[0]] == '-' and not s.src.startswith('->', c[0]))):
                    raise Err(c[1], c[2], "line starts with `%s` after a complete item: add `,` or move it to "
                              "the previous line" % s.src[c[0]])
            return
        if t is not None and t.k == 'op' and t.v == ',' and top == '{':
            s.add('nl', '\n', i)        # a trailing ',' in an item body ({ }) is allowed
            return
        if t is not None and s.dangling(t):
            raise Err(t.line, t.col, "line ends with `%s`: wrap the whole expression in ( ) "
                      "(only brackets and a leading '.' continue a line)" % t.v)
        if not s.toks or not s.is_ender(t):
            return
        c = s.nextline(i + 1)
        if c and (s.src.startswith('?.', c[0]) or (s.src[c[0]] == '.' and not s.src.startswith('..', c[0]))):
            if t.k in ('id', 'int', 'float', 'str') or (t.k == 'op' and t.v in (')', ']')) or \
                    (t.k == 'kw' and t.v in ('self', 'true', 'false', 'none')):
                return
            raise Err(c[1], c[2], "line starts with `.` after %s: a leading `.` continues only after `)`, `]`, "
                      "a name, a literal or `self`" % t.desc().replace("'", '`'))
        if c:
            for w in ('and', 'or'):
                e = c[0] + len(w)
                if s.src.startswith(w, c[0]) and not (e < s.n and (s.src[e].isalnum() or s.src[e] == '_')):
                    raise Err(c[1], c[2], "line starts with `%s`: wrap the whole expression in ( )" % w)
        s.add('nl', '\n', i)
    def dangling(s, t):
        if t.k == 'op':
            return t.v in DANGLE
        if t.k == 'kw':
            return t.v in ('and', 'or', 'not')
        if t.k == 'id' and t.v in ('of', 'to') and len(s.toks) > 1:
            p = s.toks[-2]
            return p.k == 'id' or (p.k == 'op' and p.v in (')', ']'))
        return False
    def nextline(s, j):
        """Start of the next non-blank, non-comment line: (index, line, col), or None at end of file."""
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
                return j, line, j - ls + 1
        return None
    def unclosed(s, o, msg, at=None):
        """Error path only: indentation names the likely unclosed opener (meaning never depends on it)."""
        if not s.sub:
            best = None
            for q in s.opens:
                if q[5] == q[1]:
                    continue
                last = q[5] if q[5] else len(s.lines)
                for ln in range(q[1] + 1, last + 1):
                    txt = s.lines[ln - 1].strip() if ln <= len(s.lines) else ''
                    if not txt or txt[0] == '#':
                        continue
                    ind = s.indent(s.lines[ln - 1])
                    if ind < q[3] or (ind == q[3] and txt[0] not in ')]}'):
                        if best is None or (q[1], q[2]) > (best[0][1], best[0][2]):
                            best = (q, ln)
                        break
            if best:
                q, ln = best
                return Err(q[1], q[2], "unclosed `%s` from line %d (the line after it dedents at line %d)" % (q[0], q[1], ln))
        return Err(at[0], at[1], msg) if at else Err(o[1], o[2], msg)
    @staticmethod
    def indent(line):
        return len(line) - len(line.lstrip(' \t')) + 3 * line[:len(line) - len(line.lstrip(' \t'))].count('\t')
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
        s.err(j, "unterminated '{' in string interpolation (write \\{ for a literal brace)")
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
                try:
                    k = s.scan_interp(src, j + 1)
                except Err:
                    s.err(j, "unterminated `{` in a string (write \\{ for a literal brace)")
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
            o = [c, l, col, s.indent(s.lines[l - 1]) if l <= len(s.lines) else 0, None, 0]
            s.stack.append(o)
            s.opens.append(o)
        elif c in ')]}':
            if not s.stack:
                s.err(i, "unexpected '%s' with nothing open" % c)
            o = s.stack[-1]
            if o[0] != CLOSE[c]:
                raise s.unclosed(o, "mismatched '%s': the '%s' opened at line %d is still open" % (c, o[0], o[1]), s.pos(i))
            o[5] = l
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
        s.pending = None                # D1: an if-expression already parsed by item(), to be used as the next primary
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
    def isw(s, v, o=0):                 # a contextual word: a plain name that means something only here
        t = s.peek(o)
        return t.k == 'id' and t.v == v
    def name_colon(s):                  # any word followed by ':' is a name (argument, parameter, field)
        return s.peek().k in ('id', 'kw') and s.isop(':', 1)
    def upper(s, what):
        t = s.peek()
        if t.k == 'id' and not t.v[0].isupper():
            s.fail("%s names must start with a capital letter (found `%s`)" % (what, t.v))
    def accop(s, v):
        if s.isop(v):
            s.i += 1
            return True
        return False
    def accw(s, v):
        if s.isw(v):
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
            if t.k == 'op' and t.v == ',' and s.peek(1).k == 'nl':
                s.fail("line ends with `,`: wrap the whole expression in ( ) (a list continues on the next line "
                       "only inside ( ) or [ ])")
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
        elif t.k == 'id':               # contextual statement words, recognised by what follows them
            n1, n2 = s.peek(1), s.peek(2)
            v = t.v
            if v == 'use' and n1.k == 'id':
                return s.st_use(False)
            if v == 'module' and n1.k == 'id' and n2.k == 'op' and n2.v == '{':
                return s.st_module(False)
            if v == 'lock' and (n1.k in ('id', 'str', 'int') or (n1.k == 'kw' and n1.v == 'self')):
                return s.st_lock(False)
            if v == 'with' and n1.k == 'id' and n2.k == 'op' and n2.v == '=':
                return s.st_with(False)
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
        if s.isw('as') and s.peek(1).k == 'id':
            s.i += 1
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
        s.upper('type')
        name = s.ident('a type name')
        return N('type', [name] + (['pub'] if pub else []), s.body('type', lambda: s.member('type'), True))
    def st_enum(s, pub):
        s.i += 1
        s.upper('enum')
        name = s.ident('an enum name')
        return N('enum', [name] + (['pub'] if pub else []), s.body('enum', lambda: s.member('enum'), True))
    def st_iface(s, pub):
        s.i += 1
        s.upper('interface')
        name = s.ident('an interface name')
        kids = []
        if s.isw('is') and s.peek(1).k == 'id':
            s.i += 1
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
        pub = False if s.name_colon() else s.acckw('pub')
        if s.iskw('fn') and not s.name_colon():
            return s.st_fn(pub)
        if s.isw('drop') and s.isop('(', 1) and kind != 'iface':
            s.i += 1
            s.expop('(', " after 'drop'")
            ps = s.params()
            s.expop(')')
            return N('drop', (), ps + [s.block('drop')])
        fl = ['pub'] if pub else []
        if kind == 'type':
            name = s.nxt().v if s.name_colon() else s.ident('a field name or fn')
            s.expop(':', " after the field name")
            kids = [s.type()]
            if s.accop('='):
                kids.append(N('default', (), [s.expr()]))
            return N('field', [name] + fl, kids)
        if kind == 'enum':
            s.upper('variant')
            name = s.ident('a variant name or fn')
            vf = []
            if s.accop('('):
                while not s.isop(')'):
                    if not s.name_colon():
                        s.fail("variant fields need names: write `name: Type`")
                    n = s.nxt().v
                    s.i += 1
                    vf.append(N('vfield', [n], [s.type()]))
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
        if not s.name_colon() and (s.iskw('mut') or (s.isw('take') and (s.peek(1).k == 'id' or s.iskw('self', 1)))):
            mode = s.nxt().v
        if s.iskw('self') and not s.name_colon():
            s.i += 1
            return N('recv', [mode or 'self'])
        name = s.nxt().v if s.name_colon() else s.ident('a parameter name')
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
        fl = (['pub'] if pub else []) + (['fails'] if s.accw('fails') else [])
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
    def type(s, inner=False):
        t = s.peek()
        if s.isw('dyn') and s.peek(1).k == 'id':
            s.i += 1
            return N('dyn', [s.ident('an interface name')])
        if s.acckw('fn'):
            s.expop('(', " after 'fn' in a function type")
            args = []
            while not s.isop(')'):
                mode = s.nxt().v if (not s.name_colon() and (s.iskw('mut') or (s.isw('take') and s.peek(1).k == 'id'))) else None
                if not s.name_colon():
                    s.fail("function type parameters need names: write `name: Type`")
                an = s.nxt().v
                s.i += 1
                args.append(N('arg', [an] + ([mode] if mode else []), [s.type()]))
                if not s.accop(','):
                    break
            s.expop(')')
            if s.accop('->'):
                args.append(N('ret', (), [s.type()]))
            return N('fnt', ['fails'] if s.accw('fails') else [], args)
        if s.accop('('):
            ts = [s.type()]
            while s.accop(','):
                ts.append(s.type())
            s.expop(')')
            return N('ttuple', (), ts)
        name = s.ident('a type')
        if not (s.isw('of') and s.peek(1).k != 'nl'):
            return N('t', [name])
        s.i += 1
        kids = [s.type(name in TO_HEADS)]
        if s.isw('to') and s.peek(1).k != 'nl':
            if name in TO_HEADS:
                s.i += 1
                kids.append(s.type())
            elif not inner:
                s.fail("`to` follows only Map, SortedMap, Lru")
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
    def expr(s):
        l = s.p_and()
        while s.iskw('or'):
            s.i += 1
            l = N('bin', ['or'], [l, s.p_and()])
        return l
    def p_and(s):
        l = s.p_not()
        while s.acckw('and'):
            l = N('bin', ['and'], [l, s.p_not()])
        return l
    def p_not(s):
        if not s.pending and s.acckw('not'):
            return N('un', ['not'], [s.p_not()])
        l = s.p_coalesce()
        t = s.peek()
        if t.k == 'op' and t.v in CMP:
            s.i += 1
            l = N('bin', [t.v], [l, s.p_coalesce()])
            t = s.peek()
            if t.k == 'op' and t.v in CMP:
                s.fail("comparisons don't chain: use `and`")
        return l
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
        if not s.pending and s.accop('-'):
            return N('un', ['-'], [s.p_unary()])
        if not s.pending and s.iskw('try'):
            return s.try_expr()
        return s.postfix()
    def try_expr(s):
        s.i += 1
        e = s.postfix()                 # the operand is one postfix chain; `else` starts the handler
        if s.isw('context') and (s.peek(1).k != 'op' or s.isop('(', 1)):
            s.i += 1
            return N('try-context', (), [e, s.expr()])
        if s.acckw('else'):
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
                if nt.k not in ('id', 'kw', 'int'):
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
        out, seen = [], set()
        while not s.isop(')'):
            st = s.peek()
            a = s.arg()
            if a.k in ('named', 'key'):
                nm = a.a[0]
                if nm in seen:
                    if a.k == 'key':
                        s.fail("key argument '.%s' appears twice in one call" % nm, st)
                    s.fail("label '%s' appears twice in one call" % nm, st)
                seen.add(nm)
            out.append(a)
            if not s.accop(','):
                break
        s.close_list(')', "the argument list")
        return out
    def close_list(s, c, what):
        if not s.isop(c):
            t = s.peek()
            if t.k in ('id', 'int', 'float', 'str', 'kw'):
                s.fail("expected `,` or `%s` in %s, found %s: a `,` is probably missing" % (c, what, t.desc()))
            s.fail("expected `,` or `%s` in %s, found %s" % (c, what, t.desc()))
        s.i += 1
    def arg(s):
        if s.accop('.'):
            name = s.ident('a field name after the leading .')
            while s.accop('.'):
                name += '.' + s.ident('a field name')
            for w in ('desc', 'asc'):
                if s.accw(w):
                    return N('key', [name, w])
            return N('key', [name])
        if s.name_colon():
            name = s.nxt().v
            s.i += 1
            return N('named', [name], [s.expr()])
        st = s.peek()
        i0 = s.i
        e = s.expr()
        # pun: exactly one lowercase identifier token (not self, not capitalised, not parenthesised)
        if e.k == 'name' and s.i - i0 == 1 and st.k == 'id' and (st.v[0].islower() or st.v[0] == '_'):
            return N('named', list(e.a), [e])      # `x` means `x: x`
        s.fail("argument needs a name: write 'name: value' (a pun is one lowercase identifier, not self, a type or a parenthesised name)", st)
    def primary(s):
        if s.pending:
            e, s.pending = s.pending, None
            return e
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
            if t.v == 'crew' and s.peek().k == 'id' and s.isop('{', 1):
                name = s.nxt().v
                return N('crew', [name], [s.block('crew')])
            if s.isw('of') and s.peek(1).k != 'nl':
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
            if v == 'for':
                s.fail("a `for … =>` clause is only allowed as an item directly inside `[ ]`")
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
                    items.append(s.item())
                    if not s.accop(','):
                        break
                s.close_list(']', "the list")
                return N('list', (), items)
            if t.v == '{':
                s.fail("unexpected '{': a block must start on the same line as its header, and braces are never "
                       "literals (construct with Name(field: value))")
        s.fail("expected an expression, found %s" % t.desc())
    # ---- D1: clause items, legal only as list items; the body of a clause is itself an item (clauses nest).
    # `if` is parsed once: after its condition, `=>` makes a clause, `{` an if-expression (no rewinding).
    def item(s):
        if s.name_colon():
            return s.expr()
        if s.iskw('for'):
            s.i += 1
            pat = s.pattern()
            if not s.iskw('in'):
                s.fail("expected 'in' after the pattern of a `for` clause, found %s" % s.peek().desc())
            s.i += 1
            kids = [pat, s.expr()]
            if s.acckw('if'):
                kids.append(N('guard', (), [s.expr()]))
            s.clause_arrow('for')
            kids.append(s.clause_body())
            return N('item-for', (), kids)
        if s.iskw('if'):
            at = s.peek()
            s.i += 1
            name, c = s.if_head()
            if s.isop('=>'):
                s.i += 1
                body = s.clause_body()
                return N('item-iflet', [name], [c, body]) if name else N('item-if', (), [c, body])
            if not s.isop('{'):
                s.clause_arrow('if')
            e = s.if_tail(name, c)
            if not (e.c and e.c[-1].k == 'else'):
                s.fail("an `if` without `else` is not a value in a list; write the clause `if <condition> => <item>`", at)
            s.pending = e                # the if-expression is the primary; operators may follow it
            return s.expr()
        return s.expr()
    def clause_body(s):
        b = s.item()
        if s.iskw('else'):
            s.fail("a list clause has no `else`; for one-or-other write an if-expression: `if c { a } else { b }`")
        return b
    def clause_arrow(s, what):
        if not s.isop('=>'):
            s.fail("expected `=>` in the `%s` clause (a list clause is `%s … => item`), found %s"
                   % (what, what, s.peek().desc()))
        s.i += 1
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
        name, c = s.if_head()
        if name is None and s.isop('=>'):
            s.fail("an `if … =>` clause is only allowed as an item directly inside `[ ]`")
        return s.if_tail(name, c)
    def if_head(s):                     # after `if`: (binding name or None, expression)
        if s.peek().k == 'id' and s.isop('=', 1):
            name = s.nxt().v
            s.i += 1
            return name, s.expr()
        return None, s.expr()
    def if_tail(s, name, c):
        node = N('iflet', [name], [c, s.block('if')]) if name else N('if', (), [c, s.block('if')])
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
        if s.isop('{'):
            kids.append(s.block('match arm'))
        else:
            st = s.peek()
            kids.append(s.stmt())
            if kids[-1].k in ('assign', 'opassign'):
                s.fail("`=>` takes an expression; use `{ }` for statements", st)
        return N('arm', (), kids)
    def lambda_(s):
        s.i += 1
        s.expop('(', " after 'fn'")
        ps = s.params()
        s.expop(')')
        seen = set()
        for p in ps:
            if p.k == 'param' and p.a and p.a[0] != '_':
                if p.a[0] in seen:
                    s.fail("lambda parameter '%s' appears twice" % p.a[0])
                seen.add(p.a[0])
        if s.accop('=>'):
            st = s.peek()
            e = s.expr()
            if s.peek().k == 'op' and s.peek().v in ASSIGN:
                s.fail("`=>` takes an expression; use `{ }` for statements", st)
            return N('lambda', (), ps + [e])
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
