#!/usr/bin/env python3
"""B1+: Go-like with the loop-2 fixes. project.toml records the FULL build list (direct in [requires], the
rest in [indirect]) and deps.sum records a hash and commit for each listed project. `build` is frozen:
it never writes either file; only add / update / tidy do. Each package ships its own deps.sum, and a
dependency's hash recorded by its requirer must match (chained trust). A project is a repository; a module
is a directory inside it, and imports resolve by longest prefix against [requires]."""
import re, sys, time
from collections import namedtuple
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common2 import *  # noqa: F401,F403

SUM = "deps.sum"
TOP = {"module", "requires", "indirect", "replace", "c"}
Node = namedtuple("Node", "path ver pkg m reqs sum src c replaced")


def split_major(path):
    m = re.fullmatch(r"(.*)/v(\d+)", path)
    return (m.group(1), int(m.group(2))) if m and int(m.group(2)) >= 2 else (path, 1)


def is_local(v):
    return v.startswith(("./", "../", "/")) or v in (".", "..") or ":" in v or "\\" in v


def load_sum(ctx):
    p = ctx.proj / SUM
    return check_sum_table(read_toml(p), SUM) if p.is_file() else {}


def save_sum(ctx, sums):
    write_text(ctx.proj / SUM, dump_toml({"sum": {k: sums[k] for k in sorted(sums)}}))


def check_req(tbl, what):
    for k, v in tbl.items():
        check_import_path(k, what)
        refuse_reserved(k, what)
        if not isinstance(v, str):
            raise ToolError(f"{what}: {k!r} must be a version string like \"v1.2.3\"")
        sv(v)


def parse_root(ctx):
    m = ctx.manifest()
    if set(m) - TOP:
        raise ToolError(f"project.toml: unsupported table(s) {sorted(set(m) - TOP)}")
    for t in ("module", "requires", "indirect", "replace", "c"):
        if not isinstance(m.get(t, {}), dict):
            raise ToolError(f"project.toml: {t} must be a table")
    me = m.get("module", {}).get("path", ctx.proj.name)
    if me in RESERVED:
        raise ToolError(f"project.toml: the project path {me!r} is reserved for the toolchain")
    check_dialect(m, "project.toml")
    check_lang(m, "project.toml", ctx.lang)
    direct, ind, repl = (dict(m.get(k, {})) for k in ("requires", "indirect", "replace"))
    check_req(direct, "[requires]")
    check_req(ind, "[indirect]")
    if set(direct) & set(ind):
        raise ToolError(f"project.toml lists {sorted(set(direct) & set(ind))} in both [requires] and [indirect]")
    for k, v in repl.items():
        check_import_path(k, "[replace]")
        refuse_reserved(k, "[replace]")
        if not isinstance(v, str):
            raise ToolError(f"[replace]: {k!r} must be a string (a directory or another project path)")
        if not is_local(v):
            check_import_path(v, "[replace]")
            refuse_reserved(v, "[replace]")
    if ctx.toolchain:
        check_toolchain(ctx.toolchain)
    return m, me, direct, ind, repl


def source_of(ctx, path, repl):
    r = repl.get(path)
    if r is None:
        return "net", repo_name(path)
    if is_local(r):
        return "local", (ctx.proj / r).resolve()
    return "net", repo_name(r)


def own_sum(pkg):
    p = Path(pkg.dir) / SUM
    return check_sum_table(read_toml(p), f"{SUM} of the dependency") if p.is_file() else None


def chain_check(path, ver, pkg, requirer):
    key = f"{path}@{ver}"
    who = f"{requirer.path} {requirer.ver}"
    if requirer.sum is None:
        raise ToolError(f"{who} requires {path} {ver} but ships no deps.sum, so its hash for {path} cannot be checked;\n"
                        f"  ask its author to run `{PROG} tidy` and publish a new tag")
    if key not in requirer.sum:
        raise ToolError(f"{who}: its own deps.sum has no entry for {key}; ask its author to run `{PROG} tidy`")
    e = requirer.sum[key]
    if pkg.hash != e["hash"]:
        raise mismatch(path, ver, pkg.where, f"{who}'s own deps.sum", e["hash"], pkg.hash)
    if pkg.commit and pkg.commit != e["commit"]:
        raise ToolError(f"{path} {ver}: the tag points at commit {pkg.commit[:12]}, but {who}'s own deps.sum recorded {e['commit'][:12]}")


def fetch_node(ctx, path, ver, sums, repl, requirer):
    base, major = split_major(path)
    want = max(sv(ver)[0], 1)
    if want != major:
        fix = base + (f"/v{want}" if want >= 2 else "")
        raise ToolError(f"{path} {ver}: a v{sv(ver)[0]} tag belongs to module path {fix}, not {path}")
    key, replaced = f"{path}@{ver}", path in repl
    kind, src = source_of(ctx, path, repl)
    if kind == "local":
        if not (src / "project.toml").is_file():
            raise ToolError(f"[replace] {path}: {src} has no project.toml")
        m = read_toml(src / "project.toml")
        pkg = Pkg(src, None, None, "replace", None, m)
        paths = select(disk_files(src, skip_git=True), manifest_files(m), path)
    else:
        expects = [("deps.sum", sums[key]["hash"], sums[key]["commit"])] if key in sums else []
        pkg = ctx.store.get(src, ver, expects)
        m, paths = pkg.manifest, disk_files(pkg.dir)
        if requirer is not None and not replaced:
            chain_check(path, ver, pkg, requirer)
    label = f"{path} {ver}"
    if set(m) - TOP:
        raise ToolError(f"{label}: unsupported table(s) {sorted(set(m) - TOP)}")
    declared = m.get("module", {}).get("path")
    if isinstance(declared, str) and is_reserved(declared):
        raise ToolError(f"{label} declares module path {declared!r}, a reserved toolchain name; reserved names live only in "
                        f"the toolchain directory, never in a dependency")
    check_dialect(m, label)
    allowed = {path} | ({repl[path]} if replaced and not is_local(repl[path]) else set())
    if declared not in allowed:
        raise ToolError(f"{base} {ver} declares module path {declared!r}, but it was required as {path!r}"
                        + ("" if replaced else f"\n  a fork needs a root-only [replace] \"{path}\" = \"<fork path>\""))
    check_lang(m, label, ctx.lang)
    reqs = dict(m.get("requires", {}))
    check_req(reqs, f"{label}: [requires]")
    if m.get("replace"):
        note(f"{label} has a [replace] table; replace is honoured only in the root project")
    c = validate_c(m, label, set(paths), manifest_files(m))
    return Node(path, ver, pkg, m, reqs, own_sum(pkg), src, c, replaced)


def explore(ctx, roots, repl, sums):
    """Every (path, version) reachable from roots, superseded versions included (MVS reads them all)."""
    nodes, requests = {}, {}
    queue = [(p, v, None) for p, v in sorted(roots.items())]
    while queue:
        p, v, req = queue.pop(0)
        requests.setdefault(p, {}).setdefault(v, []).append(f"{req.path} {req.ver}" if req else "project.toml")
        if (p, v) not in nodes:
            n = fetch_node(ctx, p, v, sums, repl, req)
            nodes[(p, v)] = n
            queue += [(rp, rv, n) for rp, rv in sorted(n.reqs.items())]
        elif req is not None and p not in repl:
            chain_check(p, v, nodes[(p, v)].pkg, req)
    return nodes, requests


def tidy_resolve(ctx, direct, ind, repl, sums):
    ind = dict(ind)
    for _ in range(25):
        nodes, requests = explore(ctx, {**ind, **direct}, repl, sums)
        needed = {rp for n in nodes.values() for rp in n.reqs}
        keep = {p: v for p, v in ind.items() if p in needed}
        if keep == ind:
            break
        ind = keep
    sel = {}
    for p, v in nodes:
        if p not in sel or sv(v) > sv(sel[p]):
            sel[p] = v
    return nodes, requests, sel, {p: sel[p] for p in direct}, {p: v for p, v in sel.items() if p not in direct}


def analyse(ctx, final, requests, root_c):
    """final: {path: Node}. Checks that need the whole build list."""
    byb = {}
    for n in final.values():
        byb.setdefault(split_major(n.path)[0], []).append(n)
    for base, ns in byb.items():
        if len(ns) > 1 and any(n.c for n in ns):
            names = " and ".join(f"{n.path} {n.ver}" for n in sorted(ns, key=lambda n: n.path))
            libs = ", ".join(sorted({lib for n in ns for lib in n.c}))
            raise ToolError(f"{names} are two majors of one project and wrap C ({libs}); majors coexist only for pure modules,\n"
                            "  because a program links one copy of each C library")
    clibs = check_c_libs([(f"{n.path} {n.ver}", n.c) for n in sorted(final.values(), key=lambda n: n.path)]
                         + [("project.toml", root_c)])
    for p, vs in sorted(requests.items()):
        mins = {(sv(v)[0], sv(v)[1]) for v in vs if sv(v)[0] == 0}
        if mins and (len(mins) > 1 or any(sv(v)[0] >= 1 for v in vs)):
            who = "; ".join(f"{', '.join(sorted(set(w)))} needs {v}" for v, w in sorted(vs.items(), key=lambda kv: sv(kv[0])))
            warn(f"{p}: v0 minors are treated as incompatible and v0 promises nothing about v1; {who}; building with {final[p].ver}")
    return clibs


def graph_order(me, final, direct):
    lab = {p: f"{p} {n.ver}" for p, n in final.items()}
    g = {me: sorted(lab[p] for p in direct)}
    for p, n in final.items():
        g[lab[p]] = sorted(lab[rp] for rp in n.reqs)
    return topo(g), lab


def lists(direct, ind):
    return {**{p: (v, "direct") for p, v in direct.items()}, **{p: (v, "indirect") for p, v in ind.items()}}


def apply_tidy(ctx, m, me, old, direct, ind, repl, sums):
    """Resolve (reading every reachable version), then write project.toml and deps.sum."""
    sums = {k: v for k, v in sums.items() if k.rsplit("@", 1)[0] not in repl}  # replaced paths are re-recorded
    nodes, requests, sel, direct, ind = tidy_resolve(ctx, direct, ind, repl, sums)
    final = {p: nodes[(p, v)] for p, v in sel.items()}
    analyse(ctx, final, requests, validate_c(m, "project.toml"))
    new_sums = {}
    for p, n in final.items():
        if n.pkg.hash is None:
            continue
        key = f"{p}@{n.ver}"
        new_sums[key] = {"hash": n.pkg.hash, "commit": n.pkg.commit or sums.get(key, {}).get("commit", "0" * 40)}
        if key not in sums and set(requests[p][n.ver]) == {"project.toml"}:
            note(f"{key}: hash recorded on first use (nothing else vouches for it yet)")
    out = {}
    for k in ("module", "requires", "indirect", "replace", "c"):
        v = {"requires": dict(sorted(direct.items())), "indirect": dict(sorted(ind.items()))}.get(k, m.get(k))
        if v:
            out[k] = v
    if "module" not in out:
        out = {"module": {"path": me}, **out}
    ctx.save_manifest(out)
    save_sum(ctx, new_sums)
    change_report(old, lists(direct, ind))
    return final, requests


def cmd_init(ctx, a):
    ctx.init(f'[module]\npath = "{ctx.proj.name}"\n')


def cmd_add(ctx, a):
    if not a:
        raise ToolError(f"usage: {PROG} add <project-path> [version]")
    path = a[0]
    m, me, direct, ind, repl = parse_root(ctx)
    check_import_path(path, "add")
    refuse_reserved(path, "add")
    old, sums = lists(direct, ind), load_sum(ctx)
    base, major = split_major(path)
    kind, src = source_of(ctx, path, repl)
    if len(a) > 1:
        ver = a[1]
        sv(ver)
    elif kind == "local":
        raise ToolError(f"{path} is replaced by a local directory; give a version: `{PROG} add {path} v0.0.0`")
    elif path in direct:
        raise ToolError(f"{path} is already required at {direct[path]}; use `{PROG} update {path}`")
    else:
        ver = pick_latest(ctx.store, src, major, ctx.allow_new)
    direct[path] = ver
    ind.pop(path, None)
    final, _ = apply_tidy(ctx, m, me, old, direct, ind, repl, sums)
    n = final[path]
    when = time.strftime("%Y-%m-%d", time.gmtime(n.pkg.time)) if n.pkg.time else "?"
    print(f"added {path} {n.ver}\n  owner: {path.split('/')[1] if '/' in path else path}; {n.ver} tagged {when}; check this is the project you meant")


def cmd_update(ctx, a):
    m, me, direct, ind, repl = parse_root(ctx)
    old, sums = lists(direct, ind), load_sum(ctx)
    if a:
        if a[0] not in old:
            raise ToolError(f"{a[0]} is not in the build list; use `{PROG} add {a[0]}`")
        targets = {a[0]: old[a[0]][0]}
    else:
        targets = dict(direct)
    taken = False
    for p, cur in targets.items():
        base, major = split_major(p)
        kind, src = source_of(ctx, p, repl)
        if kind == "local":
            print(f"{p}: replaced by a local directory, skipped")
            continue
        new = pick_latest(ctx.store, src, major, ctx.allow_new, above=cur)
        if not new:
            print(f"{p}: {cur} is the newest eligible version")
            continue
        check_descent(ctx.store, src, new, None, sums.get(f"{p}@{cur}", {}).get("commit"), cur, ctx.force)
        (direct if p in direct else ind)[p] = new
        taken = True
    if taken:
        note("the 24h minimum age trusts the tag date, which the publisher sets; it is a convenience, not a security check")
    apply_tidy(ctx, m, me, old, direct, ind, repl, sums)


def cmd_tidy(ctx, a):
    m, me, direct, ind, repl = parse_root(ctx)
    apply_tidy(ctx, m, me, lists(direct, ind), direct, ind, repl, load_sum(ctx))


def load_frozen(ctx):
    """The build list exactly as written. Never writes. Anything missing or extra is an error."""
    m, me, direct, ind, repl = parse_root(ctx)
    sums = load_sum(ctx)
    lst = {**ind, **direct}
    local = {p for p in lst if p in repl and is_local(repl[p])}
    need = {f"{p}@{v}" for p, v in lst.items() if p not in local}
    if need != set(sums):
        miss, extra = sorted(need - set(sums)), sorted(set(sums) - need)
        raise ToolError("deps.sum does not match project.toml\n"
                        + (f"  missing: {', '.join(miss)}\n" if miss else "") + (f"  extra:   {', '.join(extra)}\n" if extra else "")
                        + f"  `{PROG} build` never writes deps.sum and never records a hash; if you trust these versions, run `{PROG} tidy`")
    keys = {Store.key(source_of(ctx, p, repl)[1], v) for p, v in lst.items() if p not in local}
    vendor_audit(ctx.proj / "vendor", keys)
    nodes = {p: fetch_node(ctx, p, v, sums, repl, None) for p, v in sorted(lst.items())}
    problems, requests = [], {}
    for p, n in nodes.items():
        for rp, rv in n.reqs.items():
            requests.setdefault(rp, {}).setdefault(rv, []).append(f"{n.path} {n.ver}")
            if rp not in lst:
                problems.append(f"{n.path} {n.ver} requires {rp} {rv}, which is missing from project.toml")
            elif sv(lst[rp]) < sv(rv):
                problems.append(f"{n.path} {n.ver} requires {rp} {rv}, but project.toml lists {lst[rp]}")
            elif lst[rp] == rv and rp not in repl:
                chain_check(rp, rv, nodes[rp].pkg, n)
    for p in sorted(ind):
        if not any(p in n.reqs for n in nodes.values()):
            problems.append(f"[indirect] lists {p} {ind[p]}, which nothing requires")
    if problems:
        raise ToolError("project.toml is not a complete build list:\n  " + "\n  ".join(problems)
                        + f"\n  `{PROG} build` never changes it; run `{PROG} tidy` to update it and review the diff")
    for p, v in lst.items():
        requests.setdefault(p, {}).setdefault(v, []).append("project.toml")
    clibs = analyse(ctx, nodes, requests, validate_c(m, "project.toml"))
    order, lab = graph_order(me, nodes, direct)
    return dict(m=m, me=me, direct=direct, final=nodes, order=order, lab=lab, clibs=clibs, repl=repl)


def cmd_build(ctx, a):
    r = load_frozen(ctx)
    kinds = {r["lab"][p]: "direct" if p in r["direct"] else "indirect" for p in r["final"]}
    hashes = {r["lab"][p]: n.pkg.hash or "local-dir-not-hashed" for p, n in r["final"].items()}
    report(r["order"], kinds, hashes, r["clibs"], "; project.toml and deps.sum unchanged")


def cmd_vendor(ctx, a):
    r = load_frozen(ctx)
    vendor_copy(ctx.proj, [(n.src, n.ver, n.pkg.dir) for _, n in sorted(r["final"].items()) if n.pkg.hash])


def cmd_which(ctx, a):
    if not a:
        raise ToolError(f"usage: {PROG} which <import-path>")
    m, me, direct, ind, repl = parse_root(ctx)
    proj, rest = resolve_import(a[0], direct, ctx.toolchain)
    if proj.startswith("toolchain:"):
        print(f"{a[0]} -> toolchain package {proj[10:]}, module directory {rest or '.'}")
        return
    n = fetch_node(ctx, proj, direct[proj], load_sum(ctx), repl, None)
    if rest and not any(p.startswith(rest + "/") for p in disk_files(n.pkg.dir, skip_git=True)):
        raise ToolError(f"project {proj} {n.ver} has no module directory {rest!r}")
    print(f"{a[0]} -> project {proj} {n.ver}, module directory {rest or '.'}")


def cmd_ccbuild(ctx, a):
    if not ctx.out:
        raise ToolError("usage: ccbuild --out <dir>")
    r = load_frozen(ctx)
    units = [(f"{p} {r['final'][p].ver}", r["final"][p].pkg.dir, r["final"][p].c) for p in
             (q for q in (lbl.rsplit(" ", 1)[0] for lbl in r["order"] if lbl != r["me"])) if r["final"][p].c]
    units.append(("project.toml", ctx.proj, validate_c(r["m"], "project.toml")))
    exe, abi, checked = c_build(units, ctx.out)
    print(f"linked {exe.name} (abi {abi}; duplicate-symbol check {'ran' if checked else 'skipped'})")


if __name__ == "__main__":
    sys.exit(main({"init": cmd_init, "add": cmd_add, "update": cmd_update, "tidy": cmd_tidy, "build": cmd_build,
                   "vendor": cmd_vendor, "which": cmd_which, "ccbuild": cmd_ccbuild}))
