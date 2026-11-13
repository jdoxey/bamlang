#!/usr/bin/env python3
"""B2+: Zig-like exact pins with the loop-2 fixes. project.toml pins every direct dependency (url, tag, hash,
commit); transitive pins are embedded in each dependency's own project.toml and checked when it is fetched
(chained trust). One version per package. `build` is frozen and never writes: a same-major diamond is an error
that `tidy` fixes (it proposes the highest pin; `--yes` writes it); a different-major diamond is an error that
names both paths."""
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common2 import *  # noqa: F401,F403

TOP = {"package", "deps", "replace", "c"}
PIN_KEYS = {"url", "tag", "hash", "commit", "indirect"}


def is_local(v):
    return v.startswith(("./", "../", "/")) or v in (".", "..") or ":" in v or "\\" in v


def source_of(ctx, name, repl):
    r = repl.get(name)
    if r is None:
        return "net", name
    if is_local(r):
        return "local", (ctx.proj / r).resolve()
    return "net", repo_name(r)


def check_pin(name, pin, what, repl, root):
    check_import_path(name, what)
    refuse_reserved(name, what)
    if not isinstance(pin, dict) or set(pin) - PIN_KEYS:
        raise ToolError(f"{what}: pin for {name} must be a table with url, tag, hash and commit")
    for k in ("url", "tag", "hash", "commit"):
        if not isinstance(pin.get(k), str) or not pin[k]:
            raise ToolError(f"{what}: pin for {name} is missing {k!r}; a build never records or fills in a hash, "
                            f"`{PROG} add` does")
    sv(pin["tag"])
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", pin["hash"]) or not re.fullmatch(r"[0-9a-f]{40,64}", pin["commit"]):
        raise ToolError(f"{what}: pin for {name} has a malformed hash or commit")
    if not isinstance(pin.get("indirect", False), bool):
        raise ToolError(f"{what}: indirect must be true or false")
    if root and name in repl:
        want = url_for(repo_name(repl[name])) if not is_local(repl[name]) else None
    else:
        want = url_for(name)
    if want and pin["url"] != want:
        raise ToolError(f"{what}: pin for {name} points at {pin['url']}, but its location is {want}\n"
                        f"  a pin cannot redirect a package; use a root-only [replace] \"{name}\" = \"<other project path>\"")


def parse_root(ctx):
    m = ctx.manifest()
    if set(m) - TOP:
        raise ToolError(f"project.toml: unsupported table(s) {sorted(set(m) - TOP)}")
    for t in TOP:
        if not isinstance(m.get(t, {}), dict):
            raise ToolError(f"project.toml: {t} must be a table")
    me = m.get("package", {}).get("name", ctx.proj.name)
    if me in RESERVED:
        raise ToolError(f"project.toml: the project name {me!r} is reserved for the toolchain")
    check_dialect(m, "project.toml")
    check_lang(m, "project.toml", ctx.lang)
    repl = dict(m.get("replace", {}))
    for k, v in repl.items():
        check_import_path(k, "[replace]")
        refuse_reserved(k, "[replace]")
        if not isinstance(v, str):
            raise ToolError(f"[replace]: {k!r} must be a string")
        if not is_local(v):
            check_import_path(v, "[replace]")
            refuse_reserved(v, "[replace]")
    deps = dict(m.get("deps", {}))
    for n, p in deps.items():
        check_pin(n, p, "project.toml", repl, True)
    if ctx.toolchain:
        check_toolchain(ctx.toolchain)
    return m, me, deps, repl


def pin_for(ctx, name, tag, repl):
    kind, src = source_of(ctx, name, repl)
    if kind == "local":
        raise ToolError(f"{name} is replaced by a local directory; nothing to pin")
    url = url_for(src)
    p = ctx.store.get(src, tag, url=url)
    check_identity(name, p.manifest, repl)
    return {"url": url, "tag": tag, "hash": p.hash, "commit": p.commit}


def check_identity(name, mm, repl):
    ident = mm.get("package", {}).get("name")
    if isinstance(ident, str) and is_reserved(ident):
        raise ToolError(f"{name} declares package name {ident!r}, a reserved toolchain name; reserved names live only in "
                        "the toolchain directory, never in a dependency")
    if ident != name and not (name in repl and ident == repl[name]):
        raise ToolError(f"the package at {name} calls itself {ident!r}, not {name!r}"
                        + ("" if name in repl else f"\n  a fork needs a root-only [replace] \"{name}\" = \"<fork path>\""))


def resolve(ctx, me, deps, repl):
    """First request wins and root pins are queued first. Returns chosen, requests, requested-by-a-dependency."""
    queue = [(n, p, me, me) for n, p in sorted(deps.items())]
    chosen, requests, edges, requested = {}, {}, {me: set()}, set()
    while queue:
        name, pin, prefix, parent = queue.pop(0)
        if parent != me and name in repl and (name in deps or not is_local(repl[name])):
            continue  # replaced: only the root's pin counts (a local directory needs none)
        via = f"{prefix} -> {name} {pin['tag']}"
        requests.setdefault(name, []).append((pin, via))
        edges.setdefault(parent, set()).add(name)
        if parent != me:
            requested.add(name)
        if name in chosen:
            continue
        kind, src = source_of(ctx, name, repl)
        label = f"{name} {pin['tag']}"
        if kind == "local":
            if not (src / "project.toml").is_file():
                raise ToolError(f"[replace] {name}: {src} has no project.toml")
            mm = read_toml(src / "project.toml")
            pkg = Pkg(src, None, None, "replace", None, mm)
            paths = select(disk_files(src, skip_git=True), manifest_files(mm), name)
        else:
            who = "project.toml" if parent == me else f"{parent}'s project.toml"
            pkg = ctx.store.get(src, pin["tag"], [(who, pin["hash"], pin["commit"])], url=pin["url"])
            mm, paths = pkg.manifest, disk_files(pkg.dir)
        if set(mm) - TOP:
            raise ToolError(f"{label}: unsupported table(s) {sorted(set(mm) - TOP)}")
        check_identity(name, mm, repl)
        check_dialect(mm, label)
        check_lang(mm, label, ctx.lang)
        sub = dict(mm.get("deps", {}))
        for dn, dp in sub.items():
            check_pin(dn, dp, f"{label}: [deps]", repl, False)
        if mm.get("replace"):
            note(f"{label} has a [replace] table; replace is honoured only in the root project")
        c = validate_c(mm, label, set(paths), manifest_files(mm))
        chosen[name] = (pin, mm, pkg, c)
        via_next = f"{prefix} -> {name} {pin['tag']}"
        queue += [(dn, dp, via_next, name) for dn, dp in sorted(sub.items())]
    return chosen, requests, edges, requested


def compat(tag):
    """v0 minors count as different majors: v0.1 and v0.9 promise nothing about each other."""
    v = sv(tag)
    return (0, v[1]) if v[0] == 0 else (v[0],)


def conflicts_of(deps, requests):
    """Raises on different majors / different hashes; returns {name: highest requested tag} for same-major diamonds."""
    out = {}
    for name, reqs in sorted(requests.items()):
        tags, hashes = {p["tag"] for p, _ in reqs}, {p["hash"] for p, _ in reqs}
        lines = "\n".join("  " + v for _, v in reqs)
        if len({compat(t) for t in tags}) > 1:
            raise ToolError(f"incompatible versions of {name}\n{lines}\n"
                            "these are different major versions (v0 minors count as different majors) and a program has one version of each package;\n"
                            "no pin can satisfy both. Upgrade or replace one of the dependents.")
        if len(tags) == 1 and len(hashes) > 1:
            raise ToolError(f"{name} {next(iter(tags))} is pinned with different hashes\n{lines}")
        if len(tags) > 1:
            if name in deps:
                note(f"{name}: the pin in project.toml ({deps[name]['tag']}) overrides {sorted(tags - {deps[name]['tag']})}")
            else:
                out[name] = (max(tags, key=sv), lines)
    return out


def check_frozen(ctx, me, deps, repl):
    chosen, requests, edges, requested = resolve(ctx, me, deps, repl)
    conf = conflicts_of(deps, requests)
    problems = [f"[replace] lists {n}, but project.toml has no pin for it; run `{PROG} add {n} <tag>`"
                for n, v in sorted(repl.items()) if not is_local(v) and n not in deps]
    for name, (tag, lines) in conf.items():
        problems.append(f"conflicting versions of {name}\n{lines}\n"
                        f"  project.toml has no pin for it; `{PROG} tidy` proposes {name} {tag}")
    for n, p in sorted(deps.items()):
        if p.get("indirect") and n not in requested:
            problems.append(f"project.toml pins {n} {p['tag']} as indirect, but no dependency requires it")
    if problems:
        raise ToolError("\n".join(problems) + f"\n  `{PROG} build` never changes project.toml; run `{PROG} tidy --yes` to write the pins")
    return chosen, requests, edges, requested


def analyse(chosen, root_c):
    return check_c_libs([(f"{n} {c[0]['tag']}", c[3]) for n, c in sorted(chosen.items())] + [("project.toml", root_c)])


def listing(deps, chosen):
    return {n: (c[0]["tag"], "indirect" if deps.get(n, {}).get("indirect") or n not in deps else "direct")
            for n, c in chosen.items()}


def save(ctx, m, deps):
    out = {}
    for k in ("package", "deps", "replace", "c"):
        v = dict(sorted(deps.items())) if k == "deps" else m.get(k)
        if v:
            out[k] = v
    ctx.save_manifest(out)


def cmd_init(ctx, a):
    ctx.init(f'[package]\nname = "{ctx.proj.name}"\n')


def cmd_add(ctx, a):
    if not a:
        raise ToolError(f"usage: {PROG} add <name> [tag]")
    name = a[0]
    m, me, deps, repl = parse_root(ctx)
    check_import_path(name, "add")
    refuse_reserved(name, "add")
    old = listing(deps, resolve(ctx, me, deps, repl)[0])
    if len(a) > 1:
        tag = a[1]
    elif name in deps and not deps[name].get("indirect"):
        raise ToolError(f"{name} is already pinned at {deps[name]['tag']}; use `{PROG} update {name}`")
    else:
        kind, src = source_of(ctx, name, repl)
        tag = pick_latest(ctx.store, src, None, ctx.allow_new)
    deps[name] = pin_for(ctx, name, tag, repl)
    chosen, requests, _, _ = resolve(ctx, me, deps, repl)
    conf = conflicts_of(deps, requests)
    analyse(chosen, validate_c(m, "project.toml"))
    save(ctx, m, deps)
    print(f"pinned {name} {tag}")
    change_report(old, listing(deps, chosen))
    if conf:
        print(f"note: {', '.join(conf)} now needs a pin; build will say so, `{PROG} tidy --yes` writes it")


def cmd_update(ctx, a):
    m, me, deps, repl = parse_root(ctx)
    chosen, requests, _, _ = resolve(ctx, me, deps, repl)
    old = listing(deps, chosen)
    if a:
        name = a[0]
        if name not in chosen:
            raise ToolError(f"{name} is not a dependency; use `{PROG} add {name}`")
        targets = {name: chosen[name][0]}
    else:
        targets = {n: p for n, p in deps.items() if not p.get("indirect")}
    taken = False
    for name, pin in targets.items():
        kind, src = source_of(ctx, name, repl)
        new = pick_latest(ctx.store, src, sv(pin["tag"])[0], ctx.allow_new, above=pin["tag"], url=pin["url"])
        if not new:
            print(f"{name}: {pin['tag']} is the newest eligible version")
            continue
        check_descent(ctx.store, src, new, pin["url"], pin["commit"], pin["tag"], ctx.force)
        flag = deps.get(name, {}).get("indirect", name not in deps)
        deps[name] = dict(pin_for(ctx, name, new, repl), **({"indirect": True} if flag else {}))
        taken = True
    if taken:
        note("the 24h minimum age trusts the tag date, which the publisher sets; it is a convenience, not a security check")
    chosen, requests, _, _ = resolve(ctx, me, deps, repl)  # different majors raise here: nothing is written
    conflicts_of(deps, requests)
    save(ctx, m, deps)
    change_report(old, listing(deps, chosen))


def wants(via, pin):
    parts = via.split(" -> ")
    return f"{parts[-2] if len(parts) > 2 else 'project.toml'} wants {pin['tag']}"


def cmd_tidy(ctx, a):
    m, me, deps, repl = parse_root(ctx)
    new, props = dict(deps), []
    for _ in range(10):
        chosen, requests, _, requested = resolve(ctx, me, new, repl)
        conf = conflicts_of(new, requests)
        extra = [n for n, p in new.items() if p.get("indirect") and n not in requested]
        if not conf and not extra:
            break
        for name, (tag, lines) in conf.items():
            pin = next(p for p, _ in requests[name] if p["tag"] == tag)
            new[name] = {"url": pin["url"], "tag": tag, "hash": pin["hash"], "commit": pin["commit"], "indirect": True}
            props.append(f"  pin     {name} {tag} (indirect): " + "; ".join(sorted(wants(v, p) for p, v in requests[name])))
        for n in extra:
            props.append(f"  unpin   {n} {new[n]['tag']}: no dependency requires it")
            del new[n]
    if not props:
        print("nothing to tidy: project.toml already holds every pin")
        return
    print("tidy proposes:")
    print("\n".join(props))
    if not ctx.yes:
        raise ToolError(f"tidy changed nothing; rerun with --yes to write these {len(props)} change(s) to project.toml")
    save(ctx, m, new)
    print(f"wrote {len(props)} change(s) to project.toml")


def load_frozen(ctx):
    m, me, deps, repl = parse_root(ctx)
    chosen, requests, edges, _ = check_frozen(ctx, me, deps, repl)
    vendor_audit(ctx.proj / "vendor", {Store.key(source_of(ctx, n, repl)[1], c[0]["tag"]) for n, c in chosen.items()
                                       if source_of(ctx, n, repl)[0] != "local"})
    clibs = analyse(chosen, validate_c(m, "project.toml"))
    lab = {n: f"{n} {c[0]['tag']}" for n, c in chosen.items()}
    g = {lab[n]: sorted(lab[d] for d in ds if d in lab) for n, ds in edges.items() if n in lab}
    g.update({me: sorted(lab[d] for d in edges[me])})
    g.update({lab[n]: [] for n in chosen if lab[n] not in g})
    return dict(m=m, me=me, deps=deps, chosen=chosen, lab=lab, order=topo(g), clibs=clibs, repl=repl)


def cmd_build(ctx, a):
    r = load_frozen(ctx)
    kinds = {r["lab"][n]: "direct" if n in r["deps"] and not r["deps"][n].get("indirect") else "indirect" for n in r["chosen"]}
    hashes = {r["lab"][n]: c[2].hash or "local-dir-not-hashed" for n, c in r["chosen"].items()}
    report(r["order"], kinds, hashes, r["clibs"], "; project.toml unchanged")


def cmd_vendor(ctx, a):
    r = load_frozen(ctx)
    vendor_copy(ctx.proj, [(source_of(ctx, n, r["repl"])[1], c[0]["tag"], c[2].dir) for n, c in sorted(r["chosen"].items())
                           if c[2].hash])


def cmd_which(ctx, a):
    if not a:
        raise ToolError(f"usage: {PROG} which <import-path>")
    m, me, deps, repl = parse_root(ctx)
    proj, rest = resolve_import(a[0], [n for n, p in deps.items() if not p.get("indirect")], ctx.toolchain)
    if proj.startswith("toolchain:"):
        print(f"{a[0]} -> toolchain package {proj[10:]}, module directory {rest or '.'}")
        return
    chosen = resolve(ctx, me, deps, repl)[0]
    pkg = chosen[proj][2]
    if rest and not any(p.startswith(rest + "/") for p in disk_files(pkg.dir, skip_git=True)):
        raise ToolError(f"project {proj} {chosen[proj][0]['tag']} has no module directory {rest!r}")
    print(f"{a[0]} -> project {proj} {chosen[proj][0]['tag']}, module directory {rest or '.'}")


def cmd_ccbuild(ctx, a):
    if not ctx.out:
        raise ToolError("usage: ccbuild --out <dir>")
    r = load_frozen(ctx)
    units = [(r["lab"][n], c[2].dir, c[3]) for lbl in r["order"] for n, c in r["chosen"].items()
             if r["lab"][n] == lbl and c[3]]
    units.append(("project.toml", ctx.proj, validate_c(r["m"], "project.toml")))
    exe, abi, checked = c_build(units, ctx.out)
    print(f"linked {exe.name} (abi {abi}; duplicate-symbol check {'ran' if checked else 'skipped'})")


if __name__ == "__main__":
    sys.exit(main({"init": cmd_init, "add": cmd_add, "update": cmd_update, "tidy": cmd_tidy, "build": cmd_build,
                   "vendor": cmd_vendor, "which": cmd_which, "ccbuild": cmd_ccbuild}))
