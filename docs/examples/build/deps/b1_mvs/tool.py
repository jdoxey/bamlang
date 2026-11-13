#!/usr/bin/env python3
"""B1: Go-like. project.toml lists minimum versions; MVS over git tags; a new major is a new
path (host/ann/json/v2); deps.sum records a content hash for every module version read."""
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import *

SUM = "deps.sum"


def split_major(path):
    m = re.fullmatch(r"(.*)/v(\d+)", path)
    return (m.group(1), int(m.group(2))) if m and int(m.group(2)) >= 2 else (path, 1)


def load_sum(ctx):
    p = ctx.proj / SUM
    return read_toml(p).get("sum", {}) if p.is_file() else {}


def save_sum(ctx, sums):
    write_text(ctx.proj / SUM, dump_toml({"sum": dict(sorted(sums.items()))}))


def resolve(ctx, m, sums):
    """MVS: walk every requirement of every version seen; each module gets the highest minimum."""
    requires = m.get("requires", {})
    nodes, queue = {}, list(requires.items())
    while queue:
        path, ver = queue.pop(0)
        if (path, ver) in nodes:
            continue
        base, major = split_major(path)
        want = max(sv(ver)[0], 1)
        if want != major:
            fix = base + (f"/v{want}" if want >= 2 else "")
            raise ToolError(f"{path} {ver}: a v{sv(ver)[0]} tag belongs to module path {fix}, not {path}")
        f = ctx.store.get(base, ver, expect=sums.get(f"{path}@{ver}"), source=SUM)
        mm = read_toml(f.dir / "project.toml")
        declared = mm.get("module", {}).get("path")
        if declared != path:
            raise ToolError(f"{base} {ver} declares module path {declared!r}, but it was required as {path!r}")
        nodes[(path, ver)] = (mm, f)
        queue += list(mm.get("requires", {}).items())
    sel = {}
    for p, v in nodes:
        if p not in sel or sv(v) > sv(sel[p]):
            sel[p] = v
    me = m.get("module", {}).get("path", "app")
    graph = {me: sorted(f"{p} {sel[p]}" for p in requires)}
    for p, v in sel.items():
        graph[f"{p} {v}"] = sorted(f"{rp} {sel[rp]}" for rp in nodes[(p, v)][0].get("requires", {}))
    hashes = {f"{p} {v}": nodes[(p, v)][1].hash for p, v in sel.items()}
    clibs = check_c_libs([(f"{p} {v}", nodes[(p, v)][0]) for p, v in sorted(sel.items())])
    return dict(nodes=nodes, sel=sel, order=topo(graph), hashes=hashes, clibs=clibs,
                sums={f"{p}@{v}": f.hash for (p, v), (_, f) in nodes.items()})


def cmd_init(ctx, a):
    ctx.init(f'[module]\npath = "{ctx.proj.name}"\n')


def cmd_add(ctx, a):
    if not a:
        raise ToolError(f"usage: {PROG} add <module-path> [version]")
    path, m = a[0], ctx.manifest()
    if path in m.get("requires", {}):
        raise ToolError(f"{path} is already required at {m['requires'][path]}; use `{PROG} update {path}`")
    base, major = split_major(path)
    ver = a[1] if len(a) > 1 else pick_latest(ctx.store, base, major, ctx.allow_new)
    m.setdefault("requires", {})[path] = ver
    r = resolve(ctx, m, load_sum(ctx))
    ctx.save_manifest(m)
    save_sum(ctx, r["sums"])
    print(f"added {path} {ver}")


def cmd_update(ctx, a):
    m = ctx.manifest()
    r = resolve(ctx, m, load_sum(ctx))
    reqs = m.setdefault("requires", {})
    if a:
        if a[0] not in r["sel"]:
            raise ToolError(f"{a[0]} is not in the build list; use `{PROG} add {a[0]}`")
        targets = {a[0]: r["sel"][a[0]]}
    else:
        targets = dict(reqs)
    for path, cur in targets.items():
        base, major = split_major(path)
        new = pick_latest(ctx.store, base, major, ctx.allow_new, above=cur)
        if new:
            reqs[path] = new
            print(f"{path}: {cur} -> {new}")
        else:
            print(f"{path}: {cur} is the newest eligible version")
    r = resolve(ctx, m, load_sum(ctx))  # new versions are trusted on first use, then recorded
    ctx.save_manifest(m)
    save_sum(ctx, r["sums"])


def cmd_build(ctx, a):
    m, sums = ctx.manifest(), load_sum(ctx)
    r = resolve(ctx, m, sums)
    new = {k: h for k, h in r["sums"].items() if k not in sums}
    if new:
        note(f"recorded {len(new)} new hashes in {SUM} (first use)")
        save_sum(ctx, {**sums, **new})
    report(r["order"], r["hashes"], r["clibs"])


def cmd_vendor(ctx, a):
    r = resolve(ctx, ctx.manifest(), load_sum(ctx))
    # every version read is vendored, including superseded ones: MVS needs their manifests offline.
    vendor_copy(ctx.proj, [(split_major(p)[0], v, f.dir) for (p, v), (_, f) in sorted(r["nodes"].items())])


if __name__ == "__main__":
    sys.exit(main({"init": cmd_init, "add": cmd_add, "update": cmd_update, "build": cmd_build, "vendor": cmd_vendor}))
