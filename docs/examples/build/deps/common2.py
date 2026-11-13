"""Shared helpers for the D9 loop-2 spikes B1+ and B2+ (stdlib only, ASCII output).
Replaces common.py for the new tools: strict TOML 1.0 subset, git-object hashing, hashed-set checks,
validated C declarations, a real C build with duplicate-symbol detection, the dialect gate."""
import difflib, hashlib, json, os, re, shutil, subprocess, sys, time, unicodedata
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ToolError, note, PROG, MIN_AGE_HOURS, sv, repo_name, url_for, rmtree, write_text, topo, fmt_age  # noqa: E402,F401

LANG_VERSION = "0.1"
RESERVED = ("std", "extras")


def warn(msg):
    print("warning: " + msg, file=sys.stderr)


# ================================================================ strict TOML 1.0 subset
# Supported: [tables] (dotted, quoted parts), key = value, basic strings (\b \t \n \f \r \" \\ \uXXXX
# \UXXXXXXXX), literal strings, integers, booleans, arrays of strings/ints/bools (multi-line, comments,
# trailing comma), comments, LF or CRLF. Everything else is an error, never a silent misreading:
# dotted keys, inline tables, [[arrays of tables]], multi-line strings, floats, dates, hex/underscore
# integers, mixed or nested arrays, duplicate keys or tables, BOM, bare CR, control characters.
_BARE = re.compile(r"[A-Za-z0-9_-]+")
_TOKEN = re.compile(r"[A-Za-z0-9_+\-.:]+")
_ESC = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}


class _P:
    def __init__(s, text, what):
        s.t, s.i, s.what = text, 0, what

    def err(s, msg):
        raise ToolError(f"{s.what}:{s.t.count(chr(10), 0, s.i) + 1}: {msg}")

    def peek(s):
        return s.t[s.i] if s.i < len(s.t) else ""

    def ws(s):
        while s.peek() in (" ", "\t"):
            s.i += 1

    def comment(s):
        while s.peek() != "" and s.peek() != "\n":
            c = s.peek()
            if c == "\r" and s.t[s.i + 1:s.i + 2] == "\n":
                return
            if (ord(c) < 32 and c != "\t") or c == "\x7f":
                s.err("control character in a comment")
            s.i += 1

    def skip(s):
        while True:
            c = s.peek()
            if c in (" ", "\t", "\n"):
                s.i += 1
            elif c == "\r":
                if s.t[s.i + 1:s.i + 2] != "\n":
                    s.err("bare carriage return")
                s.i += 2
            elif c == "#":
                s.comment()
            else:
                return

    def eol(s):
        s.ws()
        if s.peek() == "#":
            s.comment()
        c = s.peek()
        if c == "":
            return
        if c == "\n":
            s.i += 1
        elif c == "\r" and s.t[s.i + 1:s.i + 2] == "\n":
            s.i += 2
        else:
            s.err("unexpected text after the value")

    def basic(s):
        s.i += 1
        if s.t.startswith('""', s.i):
            s.err('multi-line strings (""") are not supported')
        out = []
        while True:
            c = s.peek()
            if c == "":
                s.err("unterminated string")
            if c == '"':
                s.i += 1
                return "".join(out)
            if c in ("\n", "\r"):
                s.err("newline inside a basic string")
            if (ord(c) < 32 and c != "\t") or c == "\x7f":
                s.err("control character in a string; write it as an escape")
            if c == "\\":
                n = s.t[s.i + 1:s.i + 2]
                if n and n in _ESC:
                    out.append(_ESC[n])
                    s.i += 2
                elif n in ("u", "U"):
                    k = 4 if n == "u" else 8
                    h = s.t[s.i + 2:s.i + 2 + k]
                    if len(h) != k or not re.fullmatch(r"[0-9A-Fa-f]+", h):
                        s.err("bad \\" + n + " escape")
                    cp = int(h, 16)
                    if cp > 0x10FFFF or 0xD800 <= cp <= 0xDFFF:
                        s.err("escape is not a Unicode scalar value")
                    out.append(chr(cp))
                    s.i += 2 + k
                else:
                    s.err("unknown escape \\" + n)
            else:
                out.append(c)
                s.i += 1

    def literal(s):
        s.i += 1
        if s.t.startswith("''", s.i):
            s.err("multi-line strings (''') are not supported")
        j = s.i
        while s.t[j:j + 1] not in ("'", "\n", "\r", ""):
            if ord(s.t[j]) < 32 and s.t[j] != "\t":
                s.err("control character in a string")
            j += 1
        if s.t[j:j + 1] != "'":
            s.err("unterminated literal string")
        v, s.i = s.t[s.i:j], j + 1
        return v

    def key(s):
        c = s.peek()
        if c == '"':
            k = s.basic()
        elif c == "'":
            k = s.literal()
        else:
            m = _BARE.match(s.t, s.i)
            if not m:
                s.err("expected a key")
            k, s.i = m.group(0), m.end()
        if k == "":
            s.err("empty keys are not supported")
        return k

    def array(s):
        s.i += 1
        items = []
        while True:
            s.skip()
            if s.peek() == "]":
                s.i += 1
                break
            if s.peek() == "":
                s.err("unterminated array")
            items.append(s.value())
            s.skip()
            c = s.peek()
            if c == ",":
                s.i += 1
            elif c == "]":
                s.i += 1
                break
            else:
                s.err("expected ',' or ']' in an array")
        kinds = {type(x) for x in items}
        if list in kinds:
            s.err("nested arrays are not supported")
        if len(kinds) > 1:
            s.err("arrays must hold one type of value")
        return items

    def value(s):
        c = s.peek()
        if c == '"':
            return s.basic()
        if c == "'":
            return s.literal()
        if c == "[":
            return s.array()
        if c == "{":
            s.err("inline tables are not supported; use a [table]")
        m = _TOKEN.match(s.t, s.i)
        if not m:
            s.err("expected a value")
        tok, s.i = m.group(0), m.end()
        if tok in ("true", "false"):
            return tok == "true"
        if re.fullmatch(r"[+-]?(0|[1-9][0-9]*)", tok):
            return int(tok)
        s.err(f"unsupported value {tok!r} (floats, dates, hex numbers and underscores are not supported)")


def parse_toml(text, what="file"):
    if text.startswith("﻿"):
        raise ToolError(f"{what}: byte order mark is not supported; save as plain UTF-8")
    p, root, explicit = _P(text, what), {}, set()
    cur = root
    while True:
        p.skip()
        c = p.peek()
        if c == "":
            return root
        if c == "[":
            if p.t.startswith("[[", p.i):
                p.err("arrays of tables ([[...]]) are not supported")
            p.i += 1
            keys = []
            while True:
                p.ws()
                keys.append(p.key())
                p.ws()
                c = p.peek()
                p.i += 1
                if c == "]":
                    break
                if c != ".":
                    p.i -= 1
                    p.err("bad table header")
            p.eol()
            node = root
            for k in keys[:-1]:
                if k not in node:
                    node[k] = {}
                node = node[k]
                if not isinstance(node, dict):
                    p.err(f"table name clashes with the value of {k!r}")
            last = keys[-1]
            if last in node:
                if not isinstance(node[last], dict):
                    p.err(f"table name clashes with the value of {last!r}")
                if tuple(keys) in explicit:
                    p.err("duplicate table [" + ".".join(keys) + "]")
            else:
                node[last] = {}
            explicit.add(tuple(keys))
            cur = node[last]
        else:
            k = p.key()
            p.ws()
            if p.peek() == ".":
                p.err("dotted keys are not supported; use a [table]")
            if p.peek() != "=":
                p.err("expected '='")
            p.i += 1
            p.ws()
            if k in cur:
                p.err(f"duplicate key {k!r}")
            v = p.value()
            p.eol()
            cur[k] = v


def _qs(s):
    out = ['"']
    for c in s:
        if c == "\\":
            out.append("\\\\")
        elif c == '"':
            out.append('\\"')
        elif c == "\n":
            out.append("\\n")
        elif c == "\t":
            out.append("\\t")
        elif c == "\r":
            out.append("\\r")
        elif ord(c) < 32 or c == "\x7f":
            out.append("\\u%04X" % ord(c))
        else:
            out.append(c)
    return "".join(out) + '"'


def _key(k):
    return k if _BARE.fullmatch(k) else _qs(k)


def _val(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_val(x) for x in v) + "]"
    return _qs(v)


def dump_toml(d, prefix=()):
    blocks = []
    scal = [(k, v) for k, v in d.items() if not isinstance(v, dict)]
    if scal:
        lines = ["[" + ".".join(_key(k) for k in prefix) + "]"] if prefix else []
        lines += [f"{_key(k)} = {_val(v)}" for k, v in scal]
        blocks.append("\n".join(lines))
    for k, v in d.items():
        if isinstance(v, dict):
            sub = dump_toml(v, prefix + (k,))
            if sub:
                blocks.append(sub.rstrip("\n"))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def read_toml(path):
    p = Path(path)
    try:
        text = p.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise ToolError(f"{p.name}: not valid UTF-8")
    return parse_toml(text, p.name)


# ================================================================ paths and names
def safe_rel(x, what):
    if x == ".":
        return x
    if (not isinstance(x, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.+/-]*", x)
            or any(s in ("", ".", "..") for s in x.split("/"))):
        raise ToolError(f"{what}: {x!r} must be a relative path inside the package "
                        "(letters, digits and _ . + - /; no '..', no absolute paths, no drive letters, no leading '-')")
    return x


def is_reserved(path):
    return "." not in path.split("/")[0]


def check_import_path(path, what):
    segs = path.split("/") if isinstance(path, str) else [""]
    if not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", s) for s in segs):
        raise ToolError(f"{what}: {path!r} is not a valid import path (segments of letters, digits, '.', '_', '-')")


def refuse_reserved(path, what):
    if is_reserved(path):
        raise ToolError(f"{what}: {path!r} is reserved for the toolchain (import paths whose first segment has no dot, "
                        "such as std and extras, ship with the toolchain); it cannot be required, replaced or vendored")


def pkg_table(m):
    return m.get("module") or m.get("package") or {}


def manifest_files(m):
    f = pkg_table(m).get("files")
    if f is None:
        return None
    if not (isinstance(f, list) and all(isinstance(x, str) for x in f)):
        raise ToolError("files must be a list of strings")
    for x in f:
        safe_rel(x, "files")
    return f


def check_lang(m, label, ctx_lang):
    want = pkg_table(m).get("lang")
    if want is None:
        return
    try:
        w = tuple(int(x) for x in want.split("."))
        have = tuple(int(x) for x in ctx_lang.split("."))
    except (ValueError, AttributeError):
        raise ToolError(f"{label}: lang must look like \"0.1\"")
    if w > have:
        raise ToolError(f"{label} needs lang {want} or newer; this toolchain is {ctx_lang}")


def check_dialect(m, label):
    if pkg_table(m).get("dialect"):
        raise ToolError(f"{label} declares dialect = true; a dialect is part of the toolchain (ADR-0002) and is allowed only "
                        "in the toolchain directory, never in a third-party package or the project")


# ================================================================ git objects, hashing
def git2(*args, cwd=None, check=True, input_bytes=None):
    cmd = ["git", "-c", "advice.detachedHead=false", "-c", "protocol.file.allow=always",
           "-c", "user.name=spike", "-c", "user.email=spike@example.invalid", *args]
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    r = subprocess.run(cmd, cwd=cwd, env=env, input=input_bytes, capture_output=True)
    if check and r.returncode:
        raise ToolError("git " + " ".join(args[:2]) + " failed: " + r.stderr.decode("utf-8", "replace").strip())
    return r


def stdout(r):
    return r.stdout.decode("utf-8", "replace").strip()


def list_tree(repo, commit):
    """{path: (mode, type, sha)} straight from the git object database; never a checkout."""
    r = git2("ls-tree", "-r", "-z", "--full-tree", commit, cwd=repo)
    ents = {}
    for rec in r.stdout.split(b"\0"):
        if rec:
            meta, _, path = rec.partition(b"\t")
            mode, typ, sha = meta.decode().split()
            try:
                ents[path.decode("utf-8")] = (mode, typ, sha)
            except UnicodeDecodeError:
                raise ToolError("a file name in the repository is not valid UTF-8")
    return ents


def cat_blobs(repo, shas):
    r = git2("cat-file", "--batch", cwd=repo, input_bytes="".join(s + "\n" for s in shas).encode())
    data, pos, res = r.stdout, 0, {}
    for sha in shas:
        nl = data.index(b"\n", pos)
        hdr = data[pos:nl].split()
        if len(hdr) != 3 or hdr[1] != b"blob":
            raise ToolError(f"git object {sha} is not a blob")
        size = int(hdr[2])
        res[sha] = data[nl + 1:nl + 1 + size]
        pos = nl + 1 + size + 1
    return res


def check_paths(paths, label):
    seen = {}
    for p in paths:
        segs = p.split("/")
        if (any(s in ("", ".", "..") or s.lower() == ".git" for s in segs) or "\\" in p or ":" in p
                or any(ord(c) < 32 for c in p)):
            raise ToolError(f"{label}: unsafe file name {p!r}")
        k = unicodedata.normalize("NFC", p).casefold()
        if k in seen and seen[k] != p:
            raise ToolError(f"{label}: files {seen[k]!r} and {p!r} differ only by case; "
                            "they would collide on Windows and macOS, so the package is refused")
        seen[k] = p


ALWAYS = ("project.toml", "deps.sum")


def select(paths, files, label):
    """The hashed file set: `files` (files or directories) plus project.toml and deps.sum; all files if files is None."""
    paths = set(paths)
    if "project.toml" not in paths:
        raise ToolError(f"{label} has no project.toml")
    if files is None:
        return sorted(paths)
    sel = set()
    for f in list(files) + list(ALWAYS):
        hit = {p for p in paths if p == f or p.startswith(f + "/")}
        if not hit and f not in ALWAYS:
            raise ToolError(f"project.toml of {label} lists {f!r} in files, but it does not exist there")
        sel |= hit
    return sorted(sel)


def hash_items(items):
    h = hashlib.sha256()
    for rel, data in sorted(items):
        h.update(rel.encode("utf-8") + b"\0" + str(len(data)).encode() + b"\0" + data)
    return "sha256:" + h.hexdigest()


def disk_files(d, skip_git=False):
    """Every file under d (posix names). Symlinks anywhere are an error."""
    d, out = Path(d), []
    for root, dirs, files in os.walk(d, followlinks=False):
        if skip_git and ".git" in dirs:
            dirs.remove(".git")
        for n in list(dirs) + files:
            full = Path(root) / n
            if full.is_symlink():
                raise ToolError(f"{d.name}: {full.relative_to(d).as_posix()} is a symlink; symlinks are never hashed or followed")
        out += [(Path(root) / n).relative_to(d).as_posix() for n in files]
    return sorted(out)


def verify_tree(d, label):
    """Hash an extracted tree on disk. Files outside the hashed set are rejected. Returns (hash, manifest)."""
    d = Path(d)
    if not (d / "project.toml").is_file():
        raise ToolError(f"{label} has no project.toml")
    m = read_toml(d / "project.toml")
    allp = disk_files(d)
    sel = select(allp, manifest_files(m), label)
    extra = sorted(set(allp) - set(sel))
    if extra:
        raise ToolError(f"{label} contains {len(extra)} file(s) outside the hashed set: {', '.join(extra[:3])}"
                        f"{' ...' if len(extra) > 3 else ''}\n  the compiler may read only hashed files; this copy is not trusted")
    check_paths(sel, label)
    return hash_items([(p, (d / p).read_bytes()) for p in sel]), m


def mismatch(name, tag, where, source, expected, got):
    return ToolError(f"hash mismatch for {name} {tag} (from {where})\n  expected {expected} (recorded in {source})\n"
                     f"  got      {got}\n  the tag was moved or the files were changed; this copy is not trusted")


# ================================================================ store
Pkg = namedtuple("Pkg", "dir hash commit where time manifest")


class Store:
    """vendor/ first, then the cache, then the network (unless offline). The cache and vendor hold only the
    hashed file set, written from git objects (never from a checkout)."""

    def __init__(self, cache, vendor, offline=False):
        self.cache, self.vendor, self.offline = Path(cache), Path(vendor), offline

    @staticmethod
    def key(name, tag):  # escaping: '%' -> %25, '/' -> %2F (reversible, no collisions)
        return name.replace("%", "%25").replace("/", "%2F") + "@" + tag

    @staticmethod
    def unkey(k):
        return k.rsplit("@", 1)[0].replace("%2F", "/").replace("%25", "%")

    def known_names(self):
        names = set()
        for base in (self.cache, self.vendor):
            if base.is_dir():
                names |= {self.unkey(p.name) for p in base.iterdir() if "@" in p.name}
        return names

    def _missing(self, name, url, fetching=False):
        msg = f"cannot find {name}: no repository at {url}"
        if fetching:
            msg += f"\n  the upstream may have been deleted; `{PROG} vendor` keeps a copy inside your project"
        near = [n for n in difflib.get_close_matches(name, self.known_names(), 2, 0.8) if n != name]
        if near:
            msg += f"\n  did you mean {near[0]}?"
        segs = name.split("/")
        for n in range(len(segs) - 1, 1, -1):
            parent = "/".join(segs[:n])
            if git2("ls-remote", "--tags", "--refs", url_for(parent), check=False).returncode == 0:
                msg += (f"\n  {parent} is a project (a repository); {name} may be a module (a directory) inside it:"
                        f"\n  require {parent} and import {name}")
                break
        return msg

    def tags(self, name, url=None):
        if self.offline:
            raise ToolError(f"offline: cannot list the versions of {name}")
        url = url or url_for(name)
        r = git2("ls-remote", "--tags", "--refs", url, check=False)
        if r.returncode:
            raise ToolError(self._missing(name, url))
        tags = [m.group(1) for line in stdout(r).splitlines() if (m := re.search(r"refs/tags/(v\d+\.\d+\.\d+)$", line))]
        return sorted(tags, key=sv)

    def _fetch_repo(self, name, tag, url, tmp):
        repo = tmp / "repo.git"
        git2("init", "--bare", "-q", str(repo))
        r = git2("fetch", "-q", "--no-tags", url, f"+refs/tags/{tag}:refs/tags/{tag}", cwd=repo, check=False)
        if r.returncode:
            if git2("ls-remote", "--tags", "--refs", url, check=False).returncode:
                raise ToolError(self._missing(name, url, fetching=True))
            raise ToolError(f"{name} has no tag {tag} (tags: {', '.join(self.tags(name, url)) or 'none'})")
        commit = stdout(git2("rev-parse", f"refs/tags/{tag}^{{commit}}", cwd=repo))
        return repo, commit

    def _fetch(self, name, tag, url):
        final, tmp = self.cache / self.key(name, tag), self.cache / (self.key(name, tag) + ".tmp")
        rmtree(tmp)
        tmp.mkdir(parents=True)
        try:
            repo, commit = self._fetch_repo(name, tag, url, tmp)
            ents = list_tree(repo, commit)
            if "project.toml" not in ents:
                raise ToolError(f"{name} {tag} has no project.toml")
            sha = ents["project.toml"][2]
            m = parse_toml(cat_blobs(repo, [sha])[sha].decode("utf-8", "replace"), f"project.toml of {name} {tag}")
            sel = select(list(ents), manifest_files(m), f"{name} {tag}")
            for p in sel:
                if ents[p][0] == "120000":
                    raise ToolError(f"{name} {tag}: {p} is a symlink; symlinks are never hashed or followed")
                if ents[p][1] != "blob":
                    raise ToolError(f"{name} {tag}: {p} is a submodule; submodules are not supported")
            check_paths(sel, f"{name} {tag}")
            blobs = cat_blobs(repo, [ents[p][2] for p in sel])
            tree = tmp / "tree"
            for p in sel:
                (tree / p).parent.mkdir(parents=True, exist_ok=True)
                (tree / p).write_bytes(blobs[ents[p][2]])
            t = stdout(git2("for-each-ref", f"refs/tags/{tag}", "--format=%(creatordate:unix)", cwd=repo)) \
                or stdout(git2("log", "-1", "--format=%ct", commit, cwd=repo))
            rmtree(repo)
            write_text(tmp / "meta.json", json.dumps({"time": int(t), "url": url, "commit": commit}))
            rmtree(final)
            os.replace(tmp, final)
        except BaseException:
            rmtree(tmp)
            raise
        return final / "tree"

    def get(self, name, tag, expects=(), url=None):
        """expects: [(source label, hash, commit-or-None)]. Every one must match."""
        k = self.key(name, tag)
        t = commit = None
        if (self.vendor / k).is_dir():
            d, where, label = self.vendor / k, "vendor/", f"vendor/{k}"
        elif (self.cache / k / "tree").is_dir():
            d, where, label = self.cache / k / "tree", "cache", f"cache copy of {name} {tag}"
        elif self.offline:
            raise ToolError(f"offline: {name} {tag} is not in vendor/ or the cache")
        else:
            d, where, label = self._fetch(name, tag, url or url_for(name)), "network", f"{name} {tag}"
        if where != "vendor/":
            meta = json.loads((self.cache / k / "meta.json").read_text())
            t, commit = meta.get("time"), meta.get("commit")
        h, m = verify_tree(d, label)
        for src, eh, ec in expects:
            if eh and h != eh:
                raise mismatch(name, tag, where, src, eh, h)
            if ec and commit and ec != commit:
                raise ToolError(f"{name} {tag}: the tag now points at commit {commit[:12]}, but {src} recorded {ec[:12]} "
                                "(the tag was moved; the content happens to match)")
        return Pkg(d, h, commit, where, t, m)

    def check_descends(self, name, tag, url, recorded):
        """Does tag's commit descend from `recorded`? Returns (ok, new_commit)."""
        self.cache.mkdir(parents=True, exist_ok=True)
        tmp = self.cache / ".descent.tmp"
        rmtree(tmp)
        tmp.mkdir(parents=True)
        try:
            repo, commit = self._fetch_repo(name, tag, url or url_for(name), tmp)
            r = git2("merge-base", "--is-ancestor", recorded, commit, cwd=repo, check=False)
            return r.returncode == 0, commit
        finally:
            rmtree(tmp)

    def age_hours(self, name, tag, url=None):
        f = self.get(name, tag, url=url)
        return float("inf") if f.time is None else (time.time() - f.time) / 3600


def pick_latest(store, name, major=None, allow_new=False, above=None, url=None):
    """Newest tag (optionally of one major, optionally newer than `above`) that is old enough.
    The age rule trusts the tagger date, which the publisher controls: a convenience, not a security check."""
    tags = sorted((t for t in store.tags(name, url) if major is None or sv(t)[0] == major), key=sv, reverse=True)
    if not tags:
        raise ToolError(f"{name} has no version tags like v1.2.3" + (f" for major {major}" if major else ""))
    for t in tags:
        if above and sv(t) <= sv(above):
            return None
        age = store.age_hours(name, t, url)
        if allow_new or age >= MIN_AGE_HOURS:
            return t
        note(f"{name} {t} skipped: tagged {fmt_age(age)} ago, under the {MIN_AGE_HOURS}h minimum age (use --allow-new to take it)")
    if above is None:
        raise ToolError(f"every version of {name} is under the {MIN_AGE_HOURS}h minimum age; use --allow-new")
    return None


def check_descent(store, name, tag, url, recorded, cur, force):
    if not recorded:
        raise ToolError(f"no commit is recorded for {name} {cur}, so {tag} cannot be checked against it; run `{PROG} tidy`")
    ok, newc = store.check_descends(name, tag, url, recorded)
    if ok:
        return
    msg = (f"{name} {tag} (commit {newc[:12]}) does not descend from the recorded {cur} (commit {recorded[:12]}): "
           "the history was rewritten or the repository was replaced")
    if not force:
        raise ToolError(msg + "\n  nothing was changed; pass --force only if the author really did this")
    warn(msg + "; accepted because of --force")


def vendor_audit(vendor, needed_keys):
    """vendor/ may hold exactly the build list: no extra project, no reserved name."""
    vendor = Path(vendor)
    if not vendor.is_dir():
        return
    for p in sorted(vendor.iterdir()):
        name = Store.unkey(p.name)
        if is_reserved(name):
            raise ToolError(f"vendor/{p.name}: {name!r} is reserved for the toolchain and can never be vendored")
        if p.name not in needed_keys:
            raise ToolError(f"vendor/{p.name} is not in the build list; run `{PROG} vendor` to refresh vendor/")


def vendor_copy(proj, items):
    """items: [(name, tag, srcdir)] -> proj/vendor/<key>/ (replaces the old vendor dir)."""
    new, old = Path(proj) / "vendor.new", Path(proj) / "vendor"
    rmtree(new)
    new.mkdir()
    for name, tag, src in items:
        shutil.copytree(src, new / Store.key(name, tag))
    rmtree(old)
    os.replace(new, old)
    print(f"vendored {len(items)} packages into vendor/")


# ================================================================ sum entries
def check_sum_table(raw, what):
    out = {}
    for k, e in (raw.get("sum") or {}).items():
        if not (isinstance(e, dict) and set(e) == {"hash", "commit"} and isinstance(e["hash"], str)
                and isinstance(e["commit"], str) and re.fullmatch(r"sha256:[0-9a-f]{64}", e["hash"])
                and re.fullmatch(r"[0-9a-f]{40,64}", e["commit"])):
            raise ToolError(f"{what}: entry {k!r} must have exactly a sha256 hash and a commit")
        out[k] = e
    if set(raw) - {"sum"}:
        raise ToolError(f"{what}: unexpected table(s) {sorted(set(raw) - {'sum'})}")
    return out


# ================================================================ C libraries as validated data
C_KEYS = {"version", "sources", "include", "defines", "link", "target"}
T_KEYS = {"sources", "include", "defines", "link"}
ABIS = ("msvc", "gnu", "darwin")


def _c_table(d, w, paths, files_desc, allowed):
    bad = set(d) - allowed
    if bad:
        raise ToolError(f"{w}: unsupported key(s) {sorted(bad)}; a C library may declare only sources, include, defines, link "
                        "(and per-ABI tables target.msvc / target.gnu / target.darwin)")
    res = {}
    for k in ("sources", "include", "defines", "link"):
        v = d.get(k, [])
        if not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            raise ToolError(f"{w}.{k} must be a list of strings")
        for x in v:
            if k in ("sources", "include"):
                safe_rel(x, f"{w}.{k}")
            if k == "sources" and not x.endswith(".c"):
                raise ToolError(f"{w}.sources: {x!r} must be a .c file")
            if k == "sources" and paths is not None and x not in paths:
                raise ToolError(f"{w}.sources: {x!r} is not in the package's hashed file set{files_desc}; "
                                "the compiler may read only hashed files")
            if k == "include" and paths is not None and not (x == "." or any(p.startswith(x + "/") for p in paths)):
                raise ToolError(f"{w}.include: {x!r} holds no file of the package's hashed file set{files_desc}")
            if k == "defines" and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(=[A-Za-z0-9_.+-]*)?", x):
                raise ToolError(f"{w}.defines: {x!r} must look like NAME or NAME=VALUE (letters, digits, _ . + -)")
            if k == "link" and not re.fullmatch(r"[A-Za-z0-9_+][A-Za-z0-9_+.-]*", x):
                raise ToolError(f"{w}.link: {x!r} is not a library name; link takes library names only "
                                "([A-Za-z0-9_+.-]+), never compiler or linker flags")
        res[k] = list(v)
    return res


def validate_c(m, label, paths=None, files=None):
    """Returns {lib: {version, base, target: {abi: table}}}. paths: the package's hashed file set (None for the root)."""
    c = m.get("c", {})
    if not isinstance(c, dict):
        raise ToolError(f"{label}: c must be a table of libraries")
    files_desc = f" (files = {files})" if files is not None else ""
    out = {}
    for lib, d in c.items():
        w = f"{label}: [c.{lib}]"
        if not re.fullmatch(r"[A-Za-z0-9_]+", lib) or not isinstance(d, dict):
            raise ToolError(f"{label}: [c.{lib}] must be a table named with letters, digits and _")
        if not isinstance(d.get("version", ""), str) or not re.fullmatch(r"[A-Za-z0-9_.+-]*", d.get("version", "")):
            raise ToolError(f"{w}.version must be a string of letters, digits and _ . + -")
        base = _c_table(d, w, paths, files_desc, C_KEYS)
        tg = d.get("target", {})
        if not isinstance(tg, dict) or set(tg) - set(ABIS):
            raise ToolError(f"{w}: target tables are keyed by ABI: {', '.join(ABIS)}")
        if any(not isinstance(t, dict) for t in tg.values()):
            raise ToolError(f"{w}.target entries must be tables")
        out[lib] = {"version": d.get("version", ""), "base": base,
                    "target": {abi: _c_table(t, f"{w}.target.{abi}", paths, files_desc, T_KEYS) for abi, t in tg.items()}}
    return out


def c_resolved(spec, abi):
    r = {k: list(v) for k, v in spec["base"].items()}
    for k, v in spec["target"].get(abi, {}).items():
        r[k] += v
    return r


def check_c_libs(items):
    """items: [(label, validated-c)]. One copy per C library name in the whole program."""
    seen = {}
    for label, c in items:
        for lib, spec in c.items():
            if lib in seen:
                a = seen[lib]
                raise ToolError(f"C library {lib!r} is declared twice; a program links one copy of each C library\n"
                                f"  {a[0]} declares {lib} version {a[1]['version'] or '?'}\n"
                                f"  {label} declares {lib} version {spec['version'] or '?'}\n"
                                f"  make both depend on one package that declares {lib}")
            seen[lib] = (label, spec)
    return seen


def cc_path():
    cc = shutil.which(os.environ.get("CC") or "clang")
    if not cc:
        raise ToolError("no C compiler: clang was not found (set CC)")
    return cc


def detect_abi(cc):
    if os.environ.get("DEPS_ABI"):
        return os.environ["DEPS_ABI"]
    r = subprocess.run([cc, "-dumpmachine"], capture_output=True, text=True)
    t = r.stdout.strip().lower()
    return "msvc" if "msvc" in t else "darwin" if ("apple" in t or "darwin" in t) else "gnu"


_SKIP_SYMS = {"_fltused", "@feat.00", "@comp.id"}


def nm_symbols(obj):
    """Defined external symbols of an object file, or None when no nm is available."""
    for tool, args in (("llvm-nm", ["-g", "--defined-only"]), ("nm", ["-g", "--defined-only"]), ("nm", ["-gU"])):
        exe = shutil.which(tool)
        if not exe:
            continue
        r = subprocess.run([exe, *args, str(obj)], capture_output=True, text=True)
        if r.returncode:
            continue
        syms = set()
        for line in r.stdout.splitlines():
            f = line.split()
            if len(f) >= 2 and f[-2] in ("T", "D", "B", "R", "S", "C") and f[-1] not in _SKIP_SYMS:
                syms.add(f[-1])
        return syms
    return None


def have_nm():
    return bool(shutil.which("llvm-nm") or shutil.which("nm"))


def c_build(units, out):
    """units: [(label, dir, validated-c)] in dependency order. Compiles every source with clang, refuses duplicate
    exported symbols (naming both packages), links, returns (executable, abi, symbol_check_ran)."""
    cc = cc_path()
    abi = detect_abi(cc)
    out = Path(out)
    rmtree(out / "obj")
    (out / "obj").mkdir(parents=True)
    incs = []
    for label, d, c in units:
        for spec in c.values():
            for i in c_resolved(spec, abi)["include"]:
                p = str(Path(d) / i)
                if p not in incs:
                    incs.append(p)
    objs, libs = [], []
    for label, d, c in units:
        for lib, spec in sorted(c.items()):
            r = c_resolved(spec, abi)
            for src in r["sources"]:
                obj = out / "obj" / f"{len(objs):02d}_{lib}_{Path(src).stem}.o"
                cmd = [cc, "-c", "-std=c11", "-O0", *["-I" + i for i in incs], *["-D" + x for x in r["defines"]],
                       str(Path(d) / src), "-o", str(obj)]
                p = subprocess.run(cmd, capture_output=True, text=True)
                if p.returncode:
                    raise ToolError(f"compiling {src} of {label} failed:\n{p.stderr.strip()}")
                objs.append((label, lib, obj))
            libs += [x for x in r["link"] if x not in libs]
    owner, checked = {}, True
    for label, lib, obj in objs:
        syms = nm_symbols(obj)
        if syms is None:
            checked = False
            continue
        for s in sorted(syms):
            if s in owner:
                l0, lib0, o0 = owner[s]
                raise ToolError(f"duplicate C symbol {s!r}: exported by two objects that would be linked into one program\n"
                                f"  {l0} (C library {lib0}, {o0.name})\n  {label} (C library {lib}, {obj.name})")
            owner[s] = (label, lib, obj)
    if not checked:
        note("no llvm-nm or nm found: the duplicate-symbol check was skipped")
    exe = out / ("app.exe" if os.name == "nt" else "app")
    p = subprocess.run([cc, *[str(o) for _, _, o in objs], "-o", str(exe), *["-l" + x for x in libs]],
                       capture_output=True, text=True)
    if p.returncode:
        raise ToolError("linking failed:\n" + p.stderr.strip())
    return exe, abi, checked


# ================================================================ toolchain directory and import resolution
def check_toolchain(tdir):
    """The toolchain directory ships std and extras; only here may a package declare dialect = true. Nothing
    in it may depend on a third-party package."""
    tdir = Path(tdir)
    if not tdir.is_dir():
        raise ToolError(f"toolchain directory {tdir} does not exist")
    for p in sorted(tdir.iterdir()):
        if not p.is_dir():
            continue
        mf = p / "project.toml"
        if not mf.is_file():
            raise ToolError(f"toolchain package {p.name} has no project.toml")
        m = read_toml(mf)
        ident = pkg_table(m).get("path") or pkg_table(m).get("name")
        if ident != p.name:
            raise ToolError(f"toolchain package {p.name} declares path {ident!r}")
        for t in ("requires", "indirect", "deps", "replace"):
            if m.get(t):
                raise ToolError(f"toolchain package {p.name} declares [{t}]; toolchain packages depend on nothing third-party")


def resolve_import(imp, keys, toolchain):
    """Longest prefix of imp (on a '/' boundary) among keys; returns (project, module dir or '')."""
    check_import_path(imp, "import")
    if is_reserved(imp):
        if not toolchain:
            raise ToolError(f"{imp}: reserved toolchain path, but no --toolchain directory was given")
        top, _, rest = imp.partition("/")
        if not (Path(toolchain) / top / "project.toml").is_file():
            raise ToolError(f"{imp}: the toolchain directory has no package {top!r}")
        if rest and not (Path(toolchain) / top / rest).is_dir():
            raise ToolError(f"{imp}: toolchain package {top} has no module directory {rest!r}")
        return "toolchain:" + top, rest
    best = None
    for k in keys:
        if (imp == k or imp.startswith(k + "/")) and (best is None or len(k) > len(best)):
            best = k
    if best is None:
        near = difflib.get_close_matches(imp, list(keys), 1, 0.6)
        raise ToolError(f"{imp}: no project in requires provides this import path"
                        + (f"\n  did you mean {near[0]}?" if near else ""))
    return best, imp[len(best) + 1:]


# ================================================================ output
def change_report(old, new):
    lines = []
    for p in sorted(set(old) | set(new)):
        o, n = old.get(p), new.get(p)
        if o == n:
            continue
        if o is None:
            lines.append(f"  added      {p} {n[0]} ({n[1]})")
        elif n is None:
            lines.append(f"  removed    {p} {o[0]} ({o[1]})")
        elif o[0] != n[0]:
            lines.append(f"  {'downgrade' if sv(n[0]) < sv(o[0]) else 'upgrade':10s} {p}: {o[0]} -> {n[0]} ({n[1]})")
        else:
            lines.append(f"  changed    {p} {o[0]}: {o[1]} -> {n[1]}")
    print("changes to the build list:" if lines else "no changes to the build list")
    for line in lines:
        print(line)


def report(order, kinds, hashes, clibs, extra=""):
    print("build list (dependencies first):")
    for i, label in enumerate(order, 1):
        h = hashes.get(label)
        print(f"  {i}. {label}  " + (f"{kinds.get(label, ''):9s} {h[:19]}..." if h else "(this project)"))
    if clibs:
        print("C libraries:")
        for lib, (label, spec) in sorted(clibs.items()):
            print(f"  {lib} {spec['version']} from {label}: sources={spec['base']['sources']}")
    print(f"ok: {len(hashes)} packages, all hashes verified" + extra)


# ================================================================ CLI
BOOL_FLAGS = {"--offline": "offline", "--allow-new": "allow_new", "--force": "force", "--yes": "yes"}
VAL_FLAGS = {"--dir": "dir", "--toolchain": "toolchain", "--out": "out", "--lang-version": "lang_version"}


class Ctx:
    def __init__(self, flags):
        self.proj = Path(flags["dir"]).resolve()
        cache = os.environ.get("DEPS_CACHE") or str(Path.home() / ".cache" / "deps-spike2")
        self.store = Store(cache, self.proj / "vendor", flags["offline"])
        self.allow_new, self.offline, self.force, self.yes = flags["allow_new"], flags["offline"], flags["force"], flags["yes"]
        self.toolchain, self.out, self.lang = flags["toolchain"], flags["out"], flags["lang_version"] or LANG_VERSION

    @property
    def mpath(self):
        return self.proj / "project.toml"

    def manifest(self):
        if not self.mpath.is_file():
            raise ToolError(f"no project.toml here; run `{PROG} init`")
        return read_toml(self.mpath)

    def save_manifest(self, m):
        write_text(self.mpath, dump_toml(m))

    def init(self, header):
        if self.mpath.exists():
            raise ToolError("project.toml already exists")
        write_text(self.mpath, header)
        print("created project.toml")


def main(cmds):
    args, flags, pos, i = sys.argv[1:], {v: False for v in BOOL_FLAGS.values()}, [], 0
    flags.update({v: None for v in VAL_FLAGS.values()})
    flags["dir"] = "."
    while i < len(args):
        a = args[i]
        if a in BOOL_FLAGS:
            flags[BOOL_FLAGS[a]] = True
        elif a in VAL_FLAGS:
            i += 1
            flags[VAL_FLAGS[a]] = args[i]
        else:
            pos.append(a)
        i += 1
    if not pos or pos[0] not in cmds:
        print(f"usage: {PROG} [--offline] [--allow-new] [--force] [--yes] [--dir D] [--toolchain D] [--out D] "
              f"{{{'|'.join(cmds)}}} ...", file=sys.stderr)
        return 2
    try:
        cmds[pos[0]](Ctx(flags), pos[1:])
        return 0
    except ToolError as e:
        print("error: " + str(e), file=sys.stderr)
        return 1
