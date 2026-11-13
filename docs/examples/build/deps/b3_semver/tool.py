#!/usr/bin/env python3
"""B3: Cargo-like. project.toml lists semver ranges (^1.2); a backtracking resolver picks versions;
deps.lock records versions, hashes and the resolved graph. Two majors of a package may coexist."""
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import *

LOCK = "deps.lock"


class Range:
    def __init__(self, s):
        m = re.fullmatch(r"([\^~=]?)(\d+)(?:\.(\d+))?(?:\.(\d+))?", s.strip())
        if not m:
            raise ToolError(f"bad version range {s!r}; write ^1.2, ~1.2.3 or =1.2.3")
        self.text, self.op = s.strip(), m.group(1) or "^"
        self.parts = [int(x) for x in m.groups()[1:] if x is not None]
        p = self.parts
        self.lo = tuple(p + [0] * (3 - len(p)))
        if self.op == "=":
            if len(p) != 3:
                raise ToolError(f"{s!r}: = needs a full version")
            self.hi = (p[0], p[1], p[2] + 1)
        elif self.op == "~":
            self.hi = (p[0] + 1, 0, 0) if len(p) == 1 else (p[0], p[1] + 1, 0)
        elif p[0] > 0 or len(p) == 1:
            self.hi = (p[0] + 1, 0, 0)
        elif p[1] > 0 or len(p) == 2:
            self.hi = (0, p[1] + 1, 0)
        else:
            self.hi = (0, 0, p[2] + 1)

    def matches(self, v):
        return self.lo <= v < self.hi

    def slot(self):
        return slot_of(self.lo)


def slot_of(v):
    """Versions in one slot are interchangeable: major (or 0.minor) - Cargo's compatibility rule."""
    return str(v[0]) if v[0] else f"0.{v[1]}"


class Resolver:
    def __init__(self, ctx, prefer, expect):
        self.ctx, self.prefer, self.expect, self.tagmemo, self.fetched, self.failure = ctx, prefer, expect, {}, {}, None

    def fetch(self, name, v):
        if (name, v) not in self.fetched:
            tag = "v%d.%d.%d" % v
            f = self.ctx.store.get(name, tag, expect=self.expect.get(f"{name}@{tag[1:]}"), source=LOCK)
            m = read_toml(f.dir / "project.toml")
            pk = m.get("package", {})
            if pk.get("name") != name or pk.get("version") != tag[1:]:
                raise ToolError(f"{name} {tag} declares itself as {pk.get('name')} {pk.get('version')}; it must match its name and tag")
            self.fetched[(name, v)] = (f, m)
        return self.fetched[(name, v)]

    def eligible(self, name, v):
        if self.ctx.allow_new or self.prefer.get((name, slot_of(v))) == v:
            return True
        age = self.ctx.store.age_hours(name, "v%d.%d.%d" % v)
        if age < MIN_AGE_HOURS:
            note(f"{name} {'%d.%d.%d' % v} skipped: tagged {fmt_age(age)} ago, under the {MIN_AGE_HOURS}h minimum age (use --allow-new to take it)")
        return age >= MIN_AGE_HOURS

    def search(self, chosen, cons, order):
        todo = next((s for s in order if s not in chosen), None)
        if todo is None:
            return chosen
        name, slot = todo
        if name not in self.tagmemo:
            self.tagmemo[name] = [sv(t) for t in self.ctx.store.tags(name)]
        tags = self.tagmemo[name]
        ok = sorted((v for v in tags if slot_of(v) == slot and all(r.matches(v) for r, _ in cons[todo])), reverse=True)
        pref = self.prefer.get(todo)
        if pref in ok:
            ok.remove(pref)
            ok.insert(0, pref)
        reasons = "\n".join(f"  {r.text} (required by {via})" for r, via in cons[todo])
        if not ok:
            have = ", ".join("%d.%d.%d" % v for v in tags) or "none"
            self.failure = f"no version of {name} satisfies every requirement:\n{reasons}\n  versions available: {have}"
        for v in ok:
            if not self.eligible(name, v):
                continue
            deps = self.fetch(name, v)[1].get("deps", {})
            new, bad = {k: list(x) for k, x in cons.items()}, None
            label = "%s %d.%d.%d" % (name, *v)
            for dn, rs in deps.items():
                r = Range(rs)
                new.setdefault((dn, r.slot()), []).append((r, label))
                if (dn, r.slot()) in chosen and not r.matches(chosen[(dn, r.slot())]):
                    bad = (dn, r.slot())
            if bad:
                self.failure = f"no version of {bad[0]} satisfies every requirement:\n" + "\n".join(
                    f"  {r.text} (required by {via})" for r, via in new[bad])
                continue
            res = self.search({**chosen, todo: v}, new, order + [(dn, Range(rs).slot()) for dn, rs in deps.items()])
            if res:
                return res
        return None


def lock_id(name, v):
    return "%s@%d.%d.%d" % (name, *v)


def parse_id(i):
    n, v = i.rsplit("@", 1)
    return n, tuple(int(x) for x in v.split("."))


def solve(ctx, m, old, unlock):
    """Resolve m's ranges, preferring the versions in `old` unless their package is unlocked."""
    prefer = {}
    for i in old.get("locked", {}):
        n, v = parse_id(i)
        if n not in unlock:
            prefer[(n, slot_of(v))] = v
    expect = {i: d["hash"] for i, d in old.get("locked", {}).items()}
    rs = Resolver(ctx, prefer, expect)
    me = m.get("package", {}).get("name", "app")
    cons, order = {}, []
    for n, r in m.get("deps", {}).items():
        r = Range(r)
        cons.setdefault((n, r.slot()), []).append((r, me))
        order.append((n, r.slot()))
    res = rs.search({}, cons, order)
    if res is None:
        raise ToolError(rs.failure or "no solution")
    lock = {"root": {"deps": sorted(lock_id(n, v) for (n, s), v in res.items() if (n, s) in order)}, "locked": {}}
    for (n, s), v in res.items():
        f, mm = rs.fetch(n, v)
        ds = sorted(lock_id(dn, res[(dn, Range(r).slot())]) for dn, r in mm.get("deps", {}).items())
        lock["locked"][lock_id(n, v)] = {"hash": f.hash, "deps": ds}
    return lock


def stale(m, lock):
    ids = lock.get("root", {}).get("deps", [])
    deps = m.get("deps", {})
    names = [parse_id(i)[0] for i in ids]
    return sorted(names) != sorted(deps) or any(not Range(deps[n]).matches(parse_id(i)[1]) for i, n in zip(ids, names))


def load_lock(ctx):
    p = ctx.proj / LOCK
    return read_toml(p) if p.is_file() else {}


def save_lock(ctx, lock):
    write_text(ctx.proj / LOCK, dump_toml({"root": lock["root"], "locked": dict(sorted(lock["locked"].items()))}))


def current(ctx, m):
    """The lock for m: reuse deps.lock when it still satisfies project.toml, else re-resolve."""
    lock = load_lock(ctx)
    if lock and not stale(m, lock):
        return lock
    lock = solve(ctx, m, lock, set())
    save_lock(ctx, lock)
    return lock


def materialise(ctx, lock):
    fetched = {}
    for i, d in lock["locked"].items():
        n, v = parse_id(i)
        f = ctx.store.get(n, "v%d.%d.%d" % v, expect=d["hash"], source=LOCK)
        fetched[i] = (f, read_toml(f.dir / "project.toml"))
    return fetched


def cmd_init(ctx, a):
    ctx.init(f'[package]\nname = "{ctx.proj.name}"\n')


def cmd_add(ctx, a):
    if not a:
        raise ToolError(f"usage: {PROG} add <name> [range]")
    name, m = a[0], ctx.manifest()
    if name in m.get("deps", {}):
        raise ToolError(f"{name} is already a dependency ({m['deps'][name]})")
    if len(a) > 1:
        rng = a[1]
    else:
        v = sv(pick_latest(ctx.store, name, None, ctx.allow_new))
        rng = f"^{v[0]}.{v[1]}" if v[0] else f"^0.{v[1]}.{v[2]}"
    m.setdefault("deps", {})[name] = rng
    lock = solve(ctx, m, load_lock(ctx), set())
    check_c_libs([(i, mm) for i, (_, mm) in sorted(materialise(ctx, lock).items())])
    ctx.save_manifest(m)
    save_lock(ctx, lock)
    print(f"added {name} {rng}")


def cmd_update(ctx, a):
    m, old = ctx.manifest(), load_lock(ctx)
    names = {parse_id(i)[0] for i in old.get("locked", {})}
    if a and a[0] not in names:
        raise ToolError(f"{a[0]} is not in {LOCK}; use `{PROG} add {a[0]}`")
    new = solve(ctx, m, old, {a[0]} if a else names)
    save_lock(ctx, new)
    before, after = set(old.get("locked", {})), set(new["locked"])
    for i in sorted(before - after):
        print(f"removed {i}")
    for i in sorted(after - before):
        print(f"{'updated' if parse_id(i)[0] in {parse_id(j)[0] for j in before} else 'added'} {i}")
    if before == after:
        print("nothing newer is eligible")


def cmd_build(ctx, a):
    m = ctx.manifest()
    lock = current(ctx, m)
    fetched = materialise(ctx, lock)
    me = m.get("package", {}).get("name", "app")
    graph = {me: lock["root"]["deps"], **{i: d["deps"] for i, d in lock["locked"].items()}}
    report(topo(graph), {i: f.hash for i, (f, _) in fetched.items()},
           check_c_libs([(i, mm) for i, (_, mm) in sorted(fetched.items())]))


def cmd_vendor(ctx, a):
    lock = current(ctx, ctx.manifest())
    vendor_copy(ctx.proj, [(parse_id(i)[0], "v%d.%d.%d" % parse_id(i)[1], f.dir) for i, (f, _) in sorted(materialise(ctx, lock).items())])


if __name__ == "__main__":
    sys.exit(main({"init": cmd_init, "add": cmd_add, "update": cmd_update, "build": cmd_build, "vendor": cmd_vendor}))
