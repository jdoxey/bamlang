#!/usr/bin/env python3
"""B2: Zig-like exact pins. project.toml pins each direct dependency (url, tag, hash); transitive
pins come from each dependency's own project.toml. One version per package; conflicts are errors,
and a pin in the root project.toml overrides a transitive pin of the same major."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import *


def check_identity(name, url, mm):
    ident = mm.get("package", {}).get("name")
    if ident != name:
        raise ToolError(f"the package at {url} calls itself {ident!r}, not {name!r}")


def pin_for(ctx, name, tag):
    url = url_for(name)
    f = ctx.store.get(name, tag, url=url)
    check_identity(name, url, read_toml(f.dir / "project.toml"))
    return {"url": url, "tag": tag, "hash": f.hash}


def resolve(ctx, m):
    root = m.get("deps", {})
    me = m.get("package", {}).get("name", "app")
    queue = [(n, p, me, me) for n, p in root.items()]  # (name, pin, chain-so-far, parent)
    chosen, requests, edges = {}, {}, {me: set()}
    while queue:
        name, pin, prefix, parent = queue.pop(0)
        via = f"{prefix} -> {name} {pin['tag']}"
        requests.setdefault(name, []).append((pin, via))
        edges.setdefault(parent, set()).add(name)
        if name in chosen:  # first request wins; root pins are queued first
            continue
        src = "project.toml" if parent == me else f"{parent}'s project.toml"
        f = ctx.store.get(name, pin["tag"], expect=pin["hash"], source=src, url=pin["url"])
        mm = read_toml(f.dir / "project.toml")
        check_identity(name, pin["url"], mm)
        chosen[name] = (pin, mm, f)
        queue += [(dn, dp, via, name) for dn, dp in mm.get("deps", {}).items()]
    for name, reqs in sorted(requests.items()):
        tags, hashes = {p["tag"] for p, _ in reqs}, {p["hash"] for p, _ in reqs}
        lines = "\n".join("  " + v for _, v in reqs)
        if len({sv(t)[0] for t in tags}) > 1:
            raise ToolError(f"incompatible versions of {name}\n{lines}\n"
                            "these are different major versions and a program has one version of each package;\n"
                            "no pin can satisfy both. Upgrade or replace one of the dependents.")
        if len(tags) == 1 and len(hashes) > 1:
            raise ToolError(f"{name} {next(iter(tags))} is pinned with different hashes\n{lines}")
        if len(tags) > 1 and name in root:
            note(f"{name}: the pin in project.toml ({root[name]['tag']}) overrides {sorted(tags - {root[name]['tag']})}")
        elif len(tags) > 1:
            raise ToolError(f"conflicting versions of {name}\n{lines}\n"
                            "a program has one version of each package. Pick one and pin it in project.toml:\n"
                            f"  {PROG} add {name} {max(tags, key=sv)}")
    labels = {n: f"{n} {chosen[n][0]['tag']}" for n in chosen} | {me: me}
    graph = {labels[n]: sorted(labels[d] for d in ds) for n, ds in edges.items()}
    graph.update({labels[n]: [] for n in chosen if labels[n] not in graph})
    return dict(chosen=chosen, order=topo(graph), hashes={labels[n]: c[2].hash for n, c in chosen.items()},
                clibs=check_c_libs([(labels[n], chosen[n][1]) for n in sorted(chosen)]))


def cmd_init(ctx, a):
    ctx.init(f'[package]\nname = "{ctx.proj.name}"\n')


def cmd_add(ctx, a):
    if not a:
        raise ToolError(f"usage: {PROG} add <name> [tag]")
    name, m = a[0], ctx.manifest()
    tag = a[1] if len(a) > 1 else pick_latest(ctx.store, name, None, ctx.allow_new)
    m.setdefault("deps", {})[name] = pin_for(ctx, name, tag)
    ctx.save_manifest(m)
    print(f"pinned {name} {tag}")


def cmd_update(ctx, a):
    m = ctx.manifest()
    reqs = m.setdefault("deps", {})
    if a:
        name = a[0]
        if name in reqs:
            cur = reqs[name]["tag"]
        else:
            ch = resolve(ctx, m)["chosen"]  # a transitive package: the update becomes a root pin
            if name not in ch:
                raise ToolError(f"{name} is not a dependency; use `{PROG} add {name}`")
            cur = ch[name][0]["tag"]
        targets = {name: cur}
    else:
        targets = {n: p["tag"] for n, p in reqs.items()}
    for name, cur in targets.items():
        new = pick_latest(ctx.store, name, sv(cur)[0], ctx.allow_new, above=cur)
        if new:
            reqs[name] = pin_for(ctx, name, new)
            print(f"{name}: {cur} -> {new}")
        else:
            print(f"{name}: {cur} is the newest eligible version")
    ctx.save_manifest(m)


def cmd_build(ctx, a):
    r = resolve(ctx, ctx.manifest())
    report(r["order"], r["hashes"], r["clibs"])


def cmd_vendor(ctx, a):
    r = resolve(ctx, ctx.manifest())
    vendor_copy(ctx.proj, [(n, p["tag"], f.dir) for n, (p, _, f) in sorted(r["chosen"].items())])


if __name__ == "__main__":
    sys.exit(main({"init": cmd_init, "add": cmd_add, "update": cmd_update, "build": cmd_build, "vendor": cmd_vendor}))
