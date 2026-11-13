"""Shared helpers for the D9 dependency-manager spikes (stdlib only, ASCII output)."""
import difflib, hashlib, json, os, re, shutil, stat, subprocess, sys, time
from collections import namedtuple
from pathlib import Path

PROG = "deps"
MIN_AGE_HOURS = 24


class ToolError(Exception):
    pass


def note(msg):
    print("note: " + msg, file=sys.stderr)


# ---------------------------------------------------------------- TOML subset
# Tables, "key = value" lines, strings, ints, bools, single-line string arrays,
# comments. No arrays of tables, no inline tables, no multi-line values.
_BARE = re.compile(r"[A-Za-z0-9_-]+")


def _qs(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _key(k):
    return k if _BARE.fullmatch(k) else _qs(k)


def _scan_string(s, i):
    out, i = [], i + 1
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            out.append(s[i + 1]); i += 2; continue
        if c == '"':
            return "".join(out), i + 1
        out.append(c); i += 1
    raise ValueError("unterminated string")


def _scan_key(s, i):
    while i < len(s) and s[i] in " \t":
        i += 1
    if i < len(s) and s[i] == '"':
        return _scan_string(s, i)
    m = _BARE.match(s, i)
    if not m:
        raise ValueError("expected a key")
    return m.group(0), m.end()


def _strip_comment(line):
    in_s, i = False, 0
    while i < len(line):
        c = line[i]
        if in_s and c == "\\":
            i += 2; continue
        if c == '"':
            in_s = not in_s
        elif c == "#" and not in_s:
            return line[:i]
        i += 1
    return line


def _value(s):
    s = s.strip()
    if s.startswith('"'):
        v, i = _scan_string(s, 0)
        if s[i:].strip():
            raise ValueError("junk after string")
        return v
    if s in ("true", "false"):
        return s == "true"
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if s.startswith("[") and s.endswith("]"):
        items, i, body = [], 0, s[1:-1]
        while True:
            while i < len(body) and body[i] in " \t,":
                i += 1
            if i >= len(body):
                return items
            if body[i] != '"':
                raise ValueError("arrays hold quoted strings only")
            v, i = _scan_string(body, i)
            items.append(v)
    raise ValueError("cannot read value " + s)


def parse_toml(text, what="file"):
    root, cur = {}, None
    cur = root
    for n, raw in enumerate(text.splitlines(), 1):
        try:
            line = _strip_comment(raw).strip()
            if not line:
                continue
            if line.startswith("["):
                if not line.endswith("]") or line.startswith("[["):
                    raise ValueError("bad table header")
                body, i, keys = line[1:-1], 0, []
                while True:
                    k, i = _scan_key(body, i)
                    keys.append(k)
                    while i < len(body) and body[i] in " \t":
                        i += 1
                    if i >= len(body):
                        break
                    if body[i] != ".":
                        raise ValueError("bad table header")
                    i += 1
                cur = root
                for k in keys:
                    cur = cur.setdefault(k, {})
                    if not isinstance(cur, dict):
                        raise ValueError("table name clashes with a value")
            else:
                k, i = _scan_key(line, 0)
                rest = line[i:].strip()
                if not rest.startswith("="):
                    raise ValueError("expected '='")
                if k in cur:
                    raise ValueError("duplicate key " + k)
                cur[k] = _value(rest[1:])
        except ValueError as e:
            raise ToolError(f"{what}:{n}: {e}")
    return root


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
    return parse_toml(Path(path).read_text(encoding="utf-8"), Path(path).name)


def write_text(path, text):
    Path(path).write_bytes(text.encode("utf-8"))  # always LF


# ---------------------------------------------------------------- hashing
def _chmod_retry(func, path, *_):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def rmtree(p):
    if not Path(p).exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(p, onexc=_chmod_retry)
    else:
        shutil.rmtree(p, onerror=_chmod_retry)


def manifest_files(m):
    return (m.get("module") or m.get("package") or {}).get("files")


def content_hash(root, files=None):
    """SHA-256 over sorted (path, bytes). files=None: every file; else the listed
    files/dirs plus project.toml. Paths are POSIX-style, relative to root."""
    root = Path(root)
    sel = set()
    if files is None:
        cands = [p for p in root.rglob("*") if p.is_file()]
    else:
        cands = []
        for f in list(files) + ["project.toml"]:
            p = root / f
            if p.is_dir():
                cands += [q for q in p.rglob("*") if q.is_file()]
            elif p.is_file():
                cands.append(p)
            else:
                raise ToolError(f"project.toml lists {f!r} in files, but it does not exist in {root.name}")
    for p in cands:
        rel = p.relative_to(root).parts
        if ".git" not in rel:
            sel.add("/".join(rel))
    h = hashlib.sha256()
    for rel in sorted(sel):
        data = (root / rel).read_bytes()
        h.update(rel.encode("utf-8") + b"\0" + str(len(data)).encode() + b"\0" + data)
    return "sha256:" + h.hexdigest()


def tree_hash(root):
    mf = Path(root) / "project.toml"
    if not mf.is_file():
        raise ToolError(f"{Path(root).name} has no project.toml")
    return content_hash(root, manifest_files(read_toml(mf)))


# ---------------------------------------------------------------- git, URLs, versions
def git(*args, cwd=None, check=True, env=None):
    cmd = ["git", "-c", "core.autocrlf=false", "-c", "advice.detachedHead=false",
           "-c", "protocol.file.allow=always", "-c", "user.name=spike", "-c", "user.email=spike@example.invalid",
           *args]
    e = dict(os.environ, GIT_TERMINAL_PROMPT="0", **(env or {}))
    r = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode:
        raise ToolError("git " + " ".join(args[:2]) + " failed: " + r.stderr.strip())
    return r


SEMVER = re.compile(r"v(\d+)\.(\d+)\.(\d+)")


def sv(tag):
    m = SEMVER.fullmatch(tag)
    if not m:
        raise ToolError(f"{tag!r} is not a version tag like v1.2.3")
    return tuple(int(x) for x in m.groups())


def repo_name(path):
    """host/ann/json/v2 -> host/ann/json (a new major lives in the same repo)."""
    return re.sub(r"/v\d+$", "", path)


def url_for(name):
    """Stand-in for https://<name>: $DEPS_HOST/<name>.git as a file URL (file:///C:/... on Windows)."""
    host = os.environ.get("DEPS_HOST")
    if not host:
        raise ToolError("DEPS_HOST is not set (the spikes map names to local bare repos)")
    return (Path(host) / (repo_name(name) + ".git")).resolve().as_uri()


def fmt_age(h):
    return f"{int(h * 60)}m" if h < 1 else f"{int(h)}h"


Fetched = namedtuple("Fetched", "dir hash where time")


class Store:
    """vendor/ first, then the cache, then the network (unless offline)."""

    def __init__(self, cache, vendor, offline=False):
        self.cache, self.vendor, self.offline = Path(cache), Path(vendor), offline

    @staticmethod
    def key(name, tag):
        return name.replace("/", "__") + "@" + tag

    def known_names(self):
        names = set()
        for base in (self.cache, self.vendor):
            if base.is_dir():
                names |= {p.name.split("@")[0].replace("__", "/") for p in base.iterdir() if "@" in p.name}
        return names

    def _missing(self, name, url, fetching=False):
        msg = f"cannot find {name}: no repository at {url}"
        if fetching:
            msg += f"\n  the upstream may have been deleted; `{PROG} vendor` keeps a copy inside your project"
        near = difflib.get_close_matches(name, self.known_names(), 1, 0.8)
        return msg + (f"\n  did you mean {near[0]}?" if near else "")

    def tags(self, name, url=None):
        if self.offline:
            raise ToolError(f"offline: cannot list the versions of {name}")
        url = url or url_for(name)
        r = git("ls-remote", "--tags", "--refs", url, check=False)
        if r.returncode:
            raise ToolError(self._missing(name, url))
        tags = [m.group(1) for line in r.stdout.splitlines()
                if (m := re.search(r"refs/tags/(v\d+\.\d+\.\d+)$", line))]
        return sorted(tags, key=sv)

    def _fetch(self, name, tag, url):
        url = url or url_for(name)
        final, tmp = self.cache / self.key(name, tag), self.cache / (self.key(name, tag) + ".tmp")
        rmtree(tmp)
        tmp.mkdir(parents=True)
        r = git("clone", "--quiet", "--depth", "1", "--branch", tag, url, str(tmp / "tree"), check=False)
        if r.returncode:
            rmtree(tmp)
            if git("ls-remote", "--tags", "--refs", url, check=False).returncode:
                raise ToolError(self._missing(name, url, fetching=True))
            raise ToolError(f"{name} has no tag {tag} (tags: {', '.join(self.tags(name, url)) or 'none'})")
        tree = tmp / "tree"
        t = git("for-each-ref", f"refs/tags/{tag}", "--format=%(creatordate:unix)", cwd=tree).stdout.strip() \
            or git("log", "-1", "--format=%ct", cwd=tree).stdout.strip()
        rmtree(tree / ".git")
        write_text(tmp / "meta.json", json.dumps({"time": int(t), "url": url}))
        rmtree(final)
        os.replace(tmp, final)
        return final / "tree"

    def get(self, name, tag, expect=None, source="the lock file", url=None):
        k = self.key(name, tag)
        t, where = None, None
        if (self.vendor / k).is_dir():
            d, where = self.vendor / k, "vendor/"
        elif (self.cache / k / "tree").is_dir():
            d, where = self.cache / k / "tree", "cache"
            t = json.loads((self.cache / k / "meta.json").read_text())["time"]
        elif self.offline:
            raise ToolError(f"offline: {name} {tag} is not in vendor/ or the cache")
        else:
            d, where = self._fetch(name, tag, url), "network"
            t = json.loads((self.cache / k / "meta.json").read_text())["time"]
        h = tree_hash(d)
        if expect and h != expect:
            raise ToolError(f"hash mismatch for {name} {tag} (from {where})\n  expected {expect} (recorded in {source})\n"
                            f"  got      {h}\n  the tag was moved or the files were changed; this copy is not trusted")
        return Fetched(d, h, where, t)

    def age_hours(self, name, tag, url=None):
        f = self.get(name, tag, url=url)
        return float("inf") if f.time is None else (time.time() - f.time) / 3600


def pick_latest(store, name, major=None, allow_new=False, above=None, url=None):
    """Newest tag (optionally of one major, optionally newer than `above`) that is old enough."""
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


# ---------------------------------------------------------------- shared checks and output
def check_c_libs(items):
    """items: [(label, manifest)]. One copy per C library name in the whole program."""
    seen = {}
    for label, m in items:
        for lib, d in (m.get("c") or {}).items():
            for field in ("sources", "include", "link"):
                if not isinstance(d.get(field, []), list):
                    raise ToolError(f"{label}: c.{lib}.{field} must be a list of strings")
            if lib in seen:
                a = seen[lib]
                raise ToolError(f"C library {lib!r} is declared twice; a program links one copy of each C library\n"
                                f"  {a[0]} declares {lib} version {a[1].get('version', '?')}\n"
                                f"  {label} declares {lib} version {d.get('version', '?')}\n"
                                f"  make both depend on one package that declares {lib}")
            seen[lib] = (label, d)
    return seen


def topo(graph):
    """graph: node -> [deps]. Dependencies first; ties broken by name."""
    out, state = [], {}

    def visit(n, path):
        if state.get(n) == 2:
            return
        if state.get(n) == 1:
            raise ToolError("dependency cycle: " + " -> ".join(path + [n]))
        state[n] = 1
        for d in sorted(graph.get(n, [])):
            visit(d, path + [n])
        state[n] = 2
        out.append(n)

    for n in sorted(graph):
        visit(n, [])
    return out


def report(order, hashes, clibs):
    print("build list (dependencies first):")
    for i, label in enumerate(order, 1):
        h = hashes.get(label)
        print(f"  {i}. {label}  " + (h[:19] + "..." if h else "(this project)"))
    if clibs:
        print("C libraries:")
        for lib, (label, d) in sorted(clibs.items()):
            print(f"  {lib} {d.get('version', '')} from {label}: sources={d.get('sources', [])} "
                  f"include={d.get('include', [])} link={d.get('link', [])}")
    print(f"ok: {len(hashes)} packages, all hashes verified")


def vendor_copy(proj, items):
    """items: [(name, tag, srcdir)] -> proj/vendor/<name>@<tag>/ (replaces the old vendor dir)."""
    new, old = Path(proj) / "vendor.new", Path(proj) / "vendor"
    rmtree(new)
    for name, tag, src in items:
        shutil.copytree(src, new / Store.key(name, tag))
    rmtree(old)
    os.replace(new, old)
    print(f"vendored {len(items)} packages into vendor/")


# ---------------------------------------------------------------- CLI
class Ctx:
    def __init__(self, flags):
        self.proj = Path(flags["dir"]).resolve()
        cache = os.environ.get("DEPS_CACHE") or str(Path.home() / ".cache" / "deps-spike")
        self.store = Store(cache, self.proj / "vendor", flags["offline"])
        self.allow_new, self.offline = flags["allow_new"], flags["offline"]

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
    args, flags, pos, i = sys.argv[1:], {"offline": False, "allow_new": False, "dir": "."}, [], 0
    while i < len(args):
        a = args[i]
        if a == "--offline":
            flags["offline"] = True
        elif a == "--allow-new":
            flags["allow_new"] = True
        elif a == "--dir":
            i += 1
            flags["dir"] = args[i]
        else:
            pos.append(a)
        i += 1
    if not pos or pos[0] not in cmds:
        print(f"usage: {PROG} [--offline] [--allow-new] [--dir D] {{{'|'.join(cmds)}}} ...", file=sys.stderr)
        return 2
    try:
        cmds[pos[0]](Ctx(flags), pos[1:])
        return 0
    except ToolError as e:
        print("error: " + str(e), file=sys.stderr)
        return 1
