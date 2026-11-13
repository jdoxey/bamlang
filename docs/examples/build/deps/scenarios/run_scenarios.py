#!/usr/bin/env python3
"""Runs the ten shared scenarios against B1, B2 and B3 and asserts the expected outcomes.
usage: run_scenarios.py [--write RESULTS.md] [--only S2,S5]"""
import os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from common import rmtree
from world import World, now

TOOLS = {"b1": ROOT / "b1_mvs" / "tool.py", "b2": ROOT / "b2_pins" / "tool.py", "b3": ROOT / "b3_semver" / "tool.py"}
FAILS, SAMPLES = [], {}
JSON, LOG, A, B, C = "host/ann/json", "host/bob/log", "host/ann/a", "host/bob/b", "host/bob/c"


class T:
    def __init__(self, sid, flavor, base):
        self.sid, self.flavor = sid, flavor
        self.box = base / f"{sid}-{flavor}"
        self.box.mkdir()
        self.world = World(self.box, flavor)
        self.cache, self.app, self.cmds, self.base = self.box / "cache", self.box / "app", 0, base
        self.app.mkdir()

    def run(self, *args, app=None, cache=None, count=True):
        env = dict(os.environ, DEPS_HOST=str(self.world.host), DEPS_CACHE=str(cache or self.cache), PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, str(TOOLS[self.flavor]), "--dir", str(app or self.app), *args], env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.cmds += count
        return r.returncode, r.stdout, r.stderr

    def expect(self, cond, text):
        if not cond:
            FAILS.append(f"[{self.sid}/{self.flavor}] {text}")

    def clean(self, s):
        for x in (self.base.as_uri(), self.base.as_posix(), str(self.base)):
            s = s.replace(x, "<tmp>" if not x.startswith("file:") else "file://<tmp>")
        s = re.sub(r"<tmp>[^ \n\"]*?/(?=host/)", "<tmp>/", s)  # drop per-scenario sandbox dir names
        return re.sub(r"<tmp>/[A-Za-z0-9]+-b\d/(host-root/)?", "<tmp>/", s)

    def row(self, label, status, msg="", note="", app=None, cmds=None, out=""):
        app = app or self.app
        files = {f: (app / f).stat().st_size for f in ("project.toml", "deps.sum", "deps.lock") if (app / f).is_file()}
        return dict(label=label, status=status, msg=self.clean(msg.strip()), note=note, files=files,
                    cmds=self.cmds if cmds is None else cmds, out=self.clean(out), flavor=self.flavor)

    def sample(self, key):
        SAMPLES[(key, self.flavor)] = {f: self.clean((self.app / f).read_text()) for f in ("project.toml", "deps.sum", "deps.lock")
                                       if (self.app / f).is_file()}


def ver(t, v):  # how each tool prints version v
    return re.escape(v) if t.flavor != "b3" else re.escape(v[1:])


def has(t, out, name, v):
    return re.search(re.escape(name) + r"[ @]v?" + re.escape(v.lstrip("v")) + r"\b", out) is not None


def basic(t):
    t.world.publish(JSON, "v1.4.0", restrict=True)
    t.world.publish(LOG, "v1.0.0")
    for a in (("init",), ("add", JSON), ("add", LOG)):
        t.expect(t.run(*a)[0] == 0, f"{a} failed")
    rc, out, err = t.run("build")
    t.expect(rc == 0, "basic build failed: " + err)


def diamond(t):
    w = t.world
    w.publish(C, "v1.2.0"), w.publish(C, "v1.4.0")
    w.publish(A, "v1.0.0", deps=[(C, "v1.2.0")]), w.publish(B, "v1.0.0", deps=[(C, "v1.4.0")])
    t.run("init"), t.run("add", A), t.run("add", B)
    first = t.run("build")
    if t.flavor == "b2":
        t.expect(first[0] != 0 and A in first[2] and B in first[2] and f"add {C} v1.4.0" in first[2], "B2 diamond error should name both paths and the pin")
        t.run(*first[2].strip().splitlines()[-1].split()[1:])  # type exactly what the error suggests
        rc, out, err = t.run("build")
    else:
        rc, out, err = first
    t.expect(rc == 0 and has(t, out, C, "v1.4.0") and not has(t, out, C, "v1.2.0"), "diamond should end with C v1.4.0: " + err + out)
    return first, (rc, out, err)


def s1(t):
    basic(t)
    rc, out, err = t.run("build")  # (basic already ran init/add/add/build; count them as the scenario)
    t.cmds = 4
    t.expect(has(t, out, JSON, "v1.4.0") and has(t, out, LOG, "v1.0.0"), "S1 build list")
    t.sample("S1")
    return [t.row("1", "ok", out=out)]


def s2(t):
    first, last = diamond(t)
    t.sample("S2")
    if t.flavor == "b2":
        return [t.row("2", "error, then ok after 1 pin", first[2], "after the suggested pin: C v1.4.0", out=last[1])]
    return [t.row("2", "ok", note="C v1.4.0 selected", out=last[1])]


def s3(t):
    diamond(t)
    t.world.publish(C, "v1.5.0")
    rc, out, err = t.run("update", C)
    t.expect(rc == 0, "update failed: " + err)
    rc, out, err = t.run("build")
    t.expect(rc == 0 and has(t, out, C, "v1.5.0"), "S3 should select C v1.5.0: " + err + out)
    t.sample("S3")
    return [t.row("3", "ok", note="C v1.5.0 selected", out=out)]


def s4(t):
    diamond(t)
    t.world.publish(C, "v2.0.0")
    t.world.publish(B, "v1.1.0", deps=[(C, "v2.0.0")])
    rc, out, err = t.run("update", B)
    t.expect(rc == 0, "S4 update failed: " + err)
    rc, out, err = t.run("build")
    if t.flavor == "b2":
        t.expect(rc != 0 and "incompatible" in err and A in err and B in err, "B2 must refuse two majors: " + err)
        return [t.row("4", "error", err, "no pin can fix it; one dependent must change", out=out)]
    v1 = re.search(r"host/bob/c[ @]v?1\.(\d+)\.0", out)
    v2 = has(t, out, C + "/v2", "v2.0.0") if t.flavor == "b1" else has(t, out, C, "v2.0.0")
    t.expect(rc == 0 and v1 and v2, "B1/B3 should link both majors of C: " + err + out)
    t.sample("S4")
    # B1 falls back to the minimum A needs (C v1.2.0): MVS never keeps a version nobody asks for.
    # B3 keeps the locked C 1.4.0 (the lock is sticky).
    t.expect(v1 and v1.group(1) == ("2" if t.flavor == "b1" else "4"), "S4 C v1 minor: " + out)
    return [t.row("4", "ok", note="C v1.%s and C v2.0.0 both in the build" % v1.group(1), out=out)]


def s5(t):
    basic(t)
    base, nov = t.cmds, t.box / "app_novendor"
    shutil.copytree(t.app, nov)
    t.run("vendor")
    withv = t.cmds
    for n in (JSON, LOG):
        t.world.delete(n)
    rows = []
    t.cmds = base
    rc, out, err = t.run("build", app=nov, cache=t.box / "cache2")
    t.expect(rc != 0 and "no repository" in err, "5a should fail: " + err)
    rows.append(t.row("5a", "error", err, "no vendor, empty cache", app=nov))
    t.cmds = base
    rc, out, err = t.run("build", app=nov)
    t.expect(rc == 0, "5b warm cache should build: " + err)
    rows.append(t.row("5b", "ok", note="no vendor, warm cache", app=nov))
    t.cmds = withv
    rc, out, err = t.run("build", cache=t.box / "cache3")
    t.expect(rc == 0 and "vendor" not in err, "5c vendor should build: " + err)
    rows.append(t.row("5c", "ok", note="vendor/, empty cache", cmds=t.cmds))
    return rows


def s6(t):
    basic(t)
    base, nov = t.cmds, t.box / "app_novendor"
    shutil.copytree(t.app, nov)
    t.run("vendor")
    f = next(t.app.glob("vendor/host__ann__json@v1.4.0/src/json.lang"))
    f.write_bytes(f.read_bytes() + b"// evil\n")
    rows = []
    rc, out, err = t.run("build")
    t.expect(rc != 0 and "hash mismatch" in err, "6b vendor tampering must be detected: " + err + out)
    rows.append(t.row("6b", "error", err, "vendor/ file edited"))
    t.world.publish(JSON, "v1.4.0", restrict=True, marker="moved")
    t.cmds = base
    rc, out, err = t.run("build", app=nov, cache=t.box / "cache2")
    t.expect(rc != 0 and "hash mismatch" in err, "6a moved tag must be detected: " + err + out)
    rows.append(t.row("6a", "error", err, "tag moved upstream, fresh cache", app=nov))
    return rows[::-1]


def s7(t):
    w = t.world
    w.publish("host/ann/p", "v1.0.0", clib={"png": {"version": "1.6.0"}}, restrict=True)
    w.publish("host/bob/q", "v1.0.0", clib={"png": {"version": "1.5.0"}}, restrict=True)
    t.run("init"), t.run("add", "host/ann/p")
    rc, out, err = t.run("build")
    t.expect(rc == 0 and "png" in out, "S7 first build should show the png C library: " + err)
    rc, out2, err = t.run("add", "host/bob/q")
    where = "refused at `add`"
    if rc == 0:
        rc, out2, err = t.run("build")
        where = "refused at `build`"
    t.expect(rc != 0 and "png" in err and "host/ann/p" in err and "host/bob/q" in err, "S7 must reject two png copies: " + err + out2)
    return [t.row("7", "error", err, where + "; first build with one png was ok", out=out)]


def s8(t):
    basic(t)
    base, rows = t.cmds, []
    rc, out, err = t.run("build", "--offline")
    t.expect(rc == 0, "8a: " + err)
    rows.append(t.row("8a", "ok", note="warm cache", out=out))
    t.cmds = base
    rc, out, err = t.run("build", "--offline", cache=t.box / "cache2")
    t.expect(rc != 0 and "offline" in err, "8b: " + err)
    rows.append(t.row("8b", "error", err, "empty cache, no vendor"))
    t.cmds = base
    t.run("vendor")
    rc, out, err = t.run("build", "--offline", cache=t.box / "cache3")
    t.expect(rc == 0, "8c: " + err)
    rows.append(t.row("8c", "ok", note="vendor/, empty cache", out=out))
    return rows


def s9(t):
    basic(t)
    rows = []
    rc, out, err = t.run("add", "host/ann/jsno")
    t.expect(rc != 0 and "did you mean host/ann/json" in err, "9a should suggest json: " + err)
    rows.append(t.row("9a", "error", err, "json already in the cache"))
    app2 = t.box / "app2"
    app2.mkdir()
    t.cmds = 0
    t.run("init", app=app2, cache=t.box / "cache2")
    rc, out, err = t.run("add", "host/ann/jsno", app=app2, cache=t.box / "cache2")
    t.expect(rc != 0 and "no repository" in err and "did you mean" not in err, "9b: " + err)
    rows.append(t.row("9b", "error", err, "fresh machine: no suggestion possible", app=app2))
    return rows


def s10(t):
    w = t.world
    w.publish(C, "v1.4.0"), w.publish(C, "v1.5.0", date=now())
    t.run("init")
    rc, out, err = t.run("add", C)
    t.expect(rc == 0 and "minimum age" in err, "10: add should skip the fresh tag: " + err)
    rc, out, err = t.run("update", C)
    t.expect(rc == 0 and "minimum age" in err, "10: update should skip the fresh tag: " + err)
    first = err
    rc, out, err = t.run("build")
    t.expect(rc == 0 and has(t, out, C, "v1.4.0") and not has(t, out, C, "v1.5.0"), "10: still v1.4.0: " + out)
    rc, out, err = t.run("update", "--allow-new", C)
    t.expect(rc == 0, "10: allow-new update: " + err)
    rc, out, err = t.run("build")
    t.expect(rc == 0 and has(t, out, C, "v1.5.0"), "10: --allow-new should reach v1.5.0: " + out + err)
    return [t.row("10", "ok", first, "stayed on v1.4.0 until --allow-new", out=out)]


SCENARIOS = [
    ("S1", "simple app, two deps", s1), ("S2", "diamond: A->C v1.2, B->C v1.4", s2),
    ("S3", "upgrade transitive C when v1.5 is tagged", s3), ("S4", "major break: B moves to C v2", s4),
    ("S5", "upstream deleted", s5),
    ("S6", "tampered tag", s6),
    ("S7", "two packages declare C library png at different versions", s7),
    ("S8", "offline build", s8), ("S9", "typo'd dependency name", s9),
    ("S10", "24h minimum age for new tags on update", s10),
]


def table(results):
    def cell(r):
        f = ", ".join(f"{k} {v} B" for k, v in r["files"].items()) or "-"
        return f"{r['status'].upper() if r['status'].startswith('error') and ',' not in r['status'] else r['status']}; {r['cmds']} cmds; {f}"
    lines = ["| Scenario | B1 (MVS) | B2 (pins) | B3 (semver) |", "|---|---|---|---|"]
    for sid, desc, _ in SCENARIOS:
        subs = sorted({r["label"] for (s, fl), rs in results.items() if s == sid for r in rs})
        for lab in subs:
            cells = []
            for fl in ("b1", "b2", "b3"):
                r = next((x for x in results.get((sid, fl), []) if x["label"] == lab), None)
                cells.append(cell(r) if r else "-")
            r1 = next(x for fl in ("b1", "b2", "b3") for x in results.get((sid, fl), []) if x["label"] == lab)
            text = desc if lab == subs[0] else r1["note"]
            lines.append(f"| {lab}. {text} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_results(path, results):
    out = ["# D9 step 3: dependency-manager spike results", "",
           "Generated by `scenarios/run_scenarios.py --write`. Every cell: outcome; commands typed (from an empty project, "
           "including `init`, `add`, `build`; setup of the upstream repos is not counted); sizes of the files the tool wrote. "
           "B2 manifest sizes include temp-dir file URLs, so they vary a little per run.", "", table(results), "",
           "## Error messages (exact text, temp paths shown as `<tmp>`)", ""]
    for sid, desc, _ in SCENARIOS:
        for fl in ("b1", "b2", "b3"):
            for r in results.get((sid, fl), []):
                if r["msg"]:
                    out += [f"**{r['label']} {fl.upper()}** ({r['note']})", "```", r["msg"], "```", ""]
    out += ["## Build output, scenarios 2 and 4", ""]
    for key in ("S2", "S4"):
        for fl in ("b1", "b2", "b3"):
            rs = [r for r in results.get((key, fl), []) if r["out"]]
            if rs:
                out += [f"**{key} {fl.upper()}**", "```", rs[0]["out"].strip(), "```", ""]
    out += ["## File formats (after S2; S4 for the two-majors case)", ""]
    for key in ("S2", "S4"):
        for fl in ("b1", "b2", "b3"):
            for fn, text in SAMPLES.get((key, fl), {}).items():
                out += [f"**{key} {fl.upper()} {fn}**", "```toml", text.rstrip(), "```", ""]
    Path(path).write_text("\n".join(out) + "\n", encoding="utf-8")


def main():
    args = sys.argv[1:]
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    base = Path(tempfile.mkdtemp(prefix="deps-spike-")).resolve()
    results = {}
    try:
        for sid, desc, fn in SCENARIOS:
            if only and sid not in only:
                continue
            for fl in ("b1", "b2", "b3"):
                t = T(sid, fl, base)
                try:
                    results[(sid, fl)] = fn(t)
                except Exception as e:  # a crash is a failure, not a hidden skip
                    FAILS.append(f"[{sid}/{fl}] crashed: {type(e).__name__}: {e}")
                print(f"{sid} {fl}: " + ("ok" if not any(f.startswith(f"[{sid}/{fl}]") for f in FAILS) else "FAILED"), flush=True)
        if "--write" in args:
            write_results(args[args.index("--write") + 1], results)
    finally:
        rmtree(base)
    for f in FAILS:
        print("FAIL " + f, file=sys.stderr)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
