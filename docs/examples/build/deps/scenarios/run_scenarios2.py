#!/usr/bin/env python3
"""Loop-2 scenarios for B1+ (b1p) and B2+ (b2p): the ten shared scenarios plus the review's attacks.
usage: run_scenarios2.py [--write RESULTS2.md] [--only S2,N4]"""
import os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from common import rmtree, write_text  # noqa: E402
from common2 import dump_toml, read_toml, have_nm  # noqa: E402
from world2 import World, now  # noqa: E402
import toml_conformance  # noqa: E402

TOOLS = {"b1p": ROOT / "b1plus" / "tool.py", "b2p": ROOT / "b2plus" / "tool.py"}
FL = ("b1p", "b2p")
FAILS, SAMPLES, PROBES = [], {}, {}
JSON, LOG, A, B, C = "ex.test/ann/json", "ex.test/bob/log", "ex.test/ann/a", "ex.test/bob/b", "ex.test/bob/c"
NOTES = []  # things worth saying in NOTES.md that only a run can tell (skips)


class T:
    def __init__(self, sid, flavor, base, world=None):
        self.sid, self.flavor, self.base = sid, flavor, base
        self.box = base / f"{sid}-{flavor}"
        self.box.mkdir()
        self.world = world or World(self.box, flavor)
        self.cache, self.app, self.cmds = self.box / "cache", self.box / "app", 0
        self.app.mkdir()
        self.b1 = flavor == "b1p"

    def run(self, *args, app=None, cache=None, count=True, env=None):
        e = dict(os.environ, DEPS_HOST=str(self.world.host), DEPS_CACHE=str(cache or self.cache), PYTHONIOENCODING="utf-8",
                 PYTHONDONTWRITEBYTECODE="1", **(env or {}))
        r = subprocess.run([sys.executable, str(TOOLS[self.flavor]), "--dir", str(app or self.app), *args], env=e,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.cmds += count
        return r.returncode, r.stdout, r.stderr

    def expect(self, cond, text):
        if not cond:
            FAILS.append(f"[{self.sid}/{self.flavor}] {text}")

    def clean(self, s):
        for x in (self.base.as_uri(), self.base.as_posix(), str(self.base)):
            s = s.replace(x, "<tmp>" if not x.startswith("file:") else "file://<tmp>")
        s = re.sub(r"<tmp>[^ \n\"]*?/(?=ex\.test)", "<tmp>/", s)
        return re.sub(r"<tmp>/[A-Za-z0-9]+-b[12]p/(host-root/)?", "<tmp>/", s)

    def row(self, label, status, msg="", note="", app=None, cmds=None, out=""):
        app = app or self.app
        files = {f: (app / f).stat().st_size for f in ("project.toml", "deps.sum") if (app / f).is_file()}
        return dict(kind=self.sid[0], label=label, status=status, msg=self.clean(msg.strip()), note=note, files=files,
                    cmds=self.cmds if cmds is None else cmds, out=self.clean(out), flavor=self.flavor)

    def sample(self, key):
        SAMPLES[(key, self.flavor)] = {f: self.clean((self.app / f).read_text()) for f in ("project.toml", "deps.sum")
                                       if (self.app / f).is_file()}

    def snap(self, app=None):
        app = app or self.app
        return {f: (app / f).read_bytes() if (app / f).is_file() else None for f in ("project.toml", "deps.sum")}

    def rejects(self, what, args, needle, probe=None, **kw):
        """Run a command that must fail with a message containing needle (a string or a tuple of alternatives)."""
        before = self.snap(kw.get("app"))
        rc, out, err = self.run(*args, **kw)
        needles = needle if isinstance(needle, tuple) else (needle,)
        self.expect(rc != 0 and any(n in err for n in needles), f"{what}: expected a refusal mentioning {needle!r}, got rc={rc}: {err.strip()[:300]}{out[:200]}")
        self.expect(self.snap(kw.get("app")) == before, f"{what}: a refused command changed project.toml or deps.sum")
        if probe:
            lines = [x.strip() for x in err.splitlines() if x.strip() and not x.startswith(("note:", "warning:"))]
            PROBES[(probe, self.flavor)] = self.clean(" | ".join(lines)) if lines else "(no message)"
        return err


def ver(v):
    return re.escape(v)


def has(out, name, v):
    return re.search(re.escape(name) + r"[ @]v?" + re.escape(v.lstrip("v")) + r"\b", out) is not None


def edit(app, fn):
    m = read_toml(app / "project.toml")
    fn(m)
    write_text(app / "project.toml", dump_toml(m))


def basic(t):
    t.world.publish(JSON, "v1.4.0", restrict=True)
    t.world.publish(LOG, "v1.0.0")
    for a in (("init",), ("add", JSON), ("add", LOG)):
        rc, out, err = t.run(*a)
        t.expect(rc == 0, f"{a} failed: {err}")
    rc, out, err = t.run("build")
    t.expect(rc == 0, "basic build failed: " + err)
    return out


def diamond(t):
    w = t.world
    w.publish(C, "v1.2.0"), w.publish(C, "v1.4.0")
    w.publish(A, "v1.0.0", deps=[(C, "v1.2.0")]), w.publish(B, "v1.0.0", deps=[(C, "v1.4.0")])
    t.run("init"), t.run("add", A)
    rc, addb, err = t.run("add", B)
    t.expect(rc == 0, "add B failed: " + err)
    first = t.run("build")
    if not t.b1:
        t.expect(first[0] != 0 and A in first[2] and B in first[2] and "tidy --yes" in first[2], "B2+ diamond error should name both paths and say `tidy --yes`: " + first[2])
        t.rejects("tidy without --yes", ("tidy",), "rerun with --yes", count=False)
        t.run("tidy", "--yes")
        rc, out, err = t.run("build")
    else:
        t.expect("upgrade" in addb and C in addb and "v1.2.0 -> v1.4.0" in addb, "B1+ add B should print the C change: " + addb)
        rc, out, err = first
    t.expect(rc == 0 and has(out, C, "v1.4.0") and not has(out, C, "v1.2.0"), "diamond should end with C v1.4.0: " + err + out)
    return first, (rc, out, err), addb


# ---------------------------------------------------------------- the ten shared scenarios
def s1(t):
    out = basic(t)
    t.expect(has(out, JSON, "v1.4.0") and has(out, LOG, "v1.0.0"), "S1 build list")
    t.sample("S1")
    return [t.row("1", "ok", out=out)]


def s2(t):
    first, last, addb = diamond(t)
    if t.b1:
        t.expect("[indirect]" in (t.app / "project.toml").read_text() and "indirect" in last[1], "B1+ manifest should list C as indirect")
    t.sample("S2")
    if t.b1:
        return [t.row("2", "ok", note="C v1.4.0 selected; manifest diff printed at `add`", out=last[1])]
    return [t.row("2", "error, then ok after 1 tidy", first[2], "after `tidy --yes`: C v1.4.0 pinned (indirect)", out=last[1])]


def s3(t):
    diamond(t)
    t.world.publish(C, "v1.5.0")
    before = t.snap()
    rc, out, err = t.run("update", C)
    t.expect(rc == 0 and "v1.4.0 -> v1.5.0" in out, "update C failed or printed no change: " + err + out)
    t.expect(t.snap()["project.toml"] != before["project.toml"], "update must change project.toml (a visible diff)")
    rc, out, err = t.run("build")
    t.expect(rc == 0 and has(out, C, "v1.5.0"), "S3 should select C v1.5.0: " + err + out)
    t.sample("S3")
    return [t.row("3", "ok", note="C v1.5.0 selected", out=out)]


def s4(t):
    diamond(t)
    t.world.publish(C, "v2.0.0")
    t.world.publish(B, "v1.1.0", deps=[(C, "v2.0.0")])
    if not t.b1:
        err = t.rejects("S4 update", ("update", B), "incompatible versions", probe="two majors (B2+)")
        t.expect(A in err and B in err, "B2+ must name both paths: " + err)
        return [t.row("4", "error", err, "update refused, nothing written; one dependent must change")]
    rc, out, err = t.run("update", B)
    t.expect(rc == 0 and "added      ex.test/bob/c/v2 v2.0.0" in out and "v1.0.0 -> v1.1.0" in out, "S4 update should print B and the new C/v2: " + out + err)
    rc, out, err = t.run("build")
    v1 = re.search(r"ex\.test/bob/c v1\.(\d+)\.0", out)
    t.expect(rc == 0 and v1 and has(out, C + "/v2", "v2.0.0"), "B1+ should link both majors of C: " + err + out)
    t.expect(v1 and v1.group(1) == "4", "S4: the listed C v1.4.0 stays (no silent downgrade): " + out)
    t.sample("S4")
    return [t.row("4", "ok", note="C v1.4.0 and C/v2 v2.0.0 both in the build; no downgrade, the listed v1.4.0 stays", out=out)]


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
    f = next(t.app.glob("vendor/*json@v1.4.0/src/json.lang"))
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
    w.publish("ex.test/ann/p", "v1.0.0", clib={"png": {"version": "1.6.0"}}, restrict=True)
    w.publish("ex.test/bob/q", "v1.0.0", clib={"png": {"version": "1.5.0"}}, restrict=True)
    t.run("init"), t.run("add", "ex.test/ann/p")
    rc, out, err = t.run("build")
    t.expect(rc == 0 and "png" in out, "S7 first build should show the png C library: " + err)
    err = t.rejects("S7 add q", ("add", "ex.test/bob/q"), "declared twice")
    t.expect("png" in err and "ex.test/ann/p" in err and "ex.test/bob/q" in err, "S7 must name png and both packages: " + err)
    return [t.row("7", "error", err, "refused at `add` (nothing written); first build with one png was ok", out=out)]


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
    rc, out, err = t.run("add", "ex.test/ann/jsno")
    t.expect(rc != 0 and "did you mean ex.test/ann/json" in err, "9a should suggest json: " + err)
    rows.append(t.row("9a", "error", err, "json already in the cache"))
    app2 = t.box / "app2"
    app2.mkdir()
    t.cmds = 0
    t.run("init", app=app2, cache=t.box / "cache2")
    rc, out, err = t.run("add", "ex.test/ann/jsno", app=app2, cache=t.box / "cache2")
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
    t.expect(rc == 0 and "minimum age" not in err.replace("under the 24h minimum age", ""), "10: update has nothing newer: " + err)
    first = err
    rc, out, err = t.run("build")
    t.expect(rc == 0 and has(out, C, "v1.4.0") and not has(out, C, "v1.5.0"), "10: still v1.4.0: " + out)
    rc, out, err = t.run("update", "--allow-new", C)
    t.expect(rc == 0 and "convenience, not a security check" in err, "10: allow-new update should say the age rule is a convenience: " + err)
    rc, out, err = t.run("build")
    t.expect(rc == 0 and has(out, C, "v1.5.0"), "10: --allow-new should reach v1.5.0: " + out + err)
    return [t.row("10", "ok", first, "stayed on v1.4.0 until --allow-new", out=out)]


# ---------------------------------------------------------------- the review's attacks and requirements
def n1(t):
    """git-object hashing: same hash whatever the checkout settings (text=auto, core.autocrlf, core.eol)."""
    w = t.world
    w.publish(JSON, "v1.0.0", attrs="* text=auto\n", extra={"src/crlf.lang": b"line1\r\nline2\r\n"})
    naive = t.box / "naive"
    subprocess.run(["git", "-c", "core.autocrlf=true", "-c", "core.eol=crlf", "-c", "protocol.file.allow=always", "clone", "-q", "--branch", "v1.0.0",
                    (w.host / (JSON + ".git")).resolve().as_uri(), str(naive)], check=True, capture_output=True)
    checkout = (naive / "src" / "crlf.lang").read_bytes()
    blob = subprocess.run(["git", "show", "HEAD:src/crlf.lang"], cwd=naive, capture_output=True).stdout
    t.expect(b"\r\n" in checkout and b"\r" not in blob, "N1 setup: a crlf checkout must differ from the stored blob")
    t.run("init"), t.run("add", JSON)
    rc, out, err = t.run("build")
    t.expect(rc == 0, "N1 build: " + err)
    manifest = (t.app / ("deps.sum" if t.b1 else "project.toml")).read_text()
    t.expect(w.hashes[(JSON, "v1.0.0")][0] in manifest, "N1: the recorded hash is the git-object hash")
    cfg = {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "core.autocrlf", "GIT_CONFIG_VALUE_0": "true",
           "GIT_CONFIG_KEY_1": "core.eol", "GIT_CONFIG_VALUE_1": "crlf"}
    rc, out2, err = t.run("build", cache=t.box / "cold-crlf", env=cfg)
    t.expect(rc == 0 and out2 == out, "N1: cold cache under core.autocrlf=true / core.eol=crlf must give the same hash: " + err)
    cached = next((t.box / "cold-crlf").glob("*json@v1.0.0/tree/src/crlf.lang")).read_bytes()
    t.expect(b"\r" not in cached, "N1: the cache holds the stored (LF) bytes, not a checkout")
    return [t.row("N1", "ok", note="text=auto dependency: the crlf checkout differs, the hash does not")]


def n2(t):
    """Frozen build: build never writes; missing or extra entries are errors; only add/update/tidy write."""
    basic(t)
    ok = t.snap()
    rc, out, err = t.run("build")
    t.expect(rc == 0 and t.snap() == ok, "N2: a successful build must not touch project.toml or deps.sum")
    rows = []
    if t.b1:
        write_text(t.app / "deps.sum", "")
        err = t.rejects("N2 emptied sum", ("build",), "deps.sum does not match", probe="emptied deps.sum, build re-trusts")
        t.expect((t.app / "deps.sum").read_text() == "", "N2: build must leave the emptied deps.sum alone")
        rows.append(t.row("N2a", "error", err, "deps.sum emptied: build refuses and writes nothing"))
        write_text(t.app / "deps.sum", ok["deps.sum"].decode())
        s = read_toml(t.app / "deps.sum")
        s["sum"]["ex.test/zzz/none@v1.0.0"] = next(iter(s["sum"].values()))
        write_text(t.app / "deps.sum", dump_toml(s))
        err = t.rejects("N2 extra sum entry", ("build",), "extra:")
        rows.append(t.row("N2b", "error", err, "extra deps.sum entry"))
        write_text(t.app / "deps.sum", ok["deps.sum"].decode())
        t.world.publish("ex.test/ann/extra", "v1.0.0")
        t.run("add", "ex.test/ann/extra")
        edit(t.app, lambda m: (m["indirect"].update({"ex.test/ann/extra": m["requires"].pop("ex.test/ann/extra")}) if "indirect" in m
                               else m.update(indirect={"ex.test/ann/extra": m["requires"].pop("ex.test/ann/extra")})))
        err = t.rejects("N2 extra indirect", ("build",), "which nothing requires")
        rows.append(t.row("N2c", "error", err, "[indirect] entry nothing requires"))
        rc, out, err = t.run("tidy")
        t.expect(rc == 0 and "removed" in out, "N2: tidy should drop the extra entry: " + err + out)
        rc, out, err = t.run("build")
        t.expect(rc == 0, "N2: build after tidy: " + err)
        write_text(t.app / "deps.sum", "")
        rc, out, err = t.run("tidy")
        t.expect(rc == 0 and "hash recorded on first use" in err, "N2: only tidy may re-record, and it says so: " + err)
    else:
        def drop(m):
            del m["deps"][JSON]["hash"]
        edit(t.app, drop)
        err = t.rejects("N2 missing hash", ("build",), "missing 'hash'", probe="emptied deps.sum, build re-trusts")
        rows.append(t.row("N2a", "error", err, "a pin without a hash: build refuses and writes nothing"))
        write_text(t.app / "project.toml", ok["project.toml"].decode())
        t.world.publish("ex.test/ann/extra", "v1.0.0")
        t.run("add", "ex.test/ann/extra")
        edit(t.app, lambda m: m["deps"]["ex.test/ann/extra"].update(indirect=True))
        err = t.rejects("N2 extra pin", ("build",), "no dependency requires it")
        rows.append(t.row("N2c", "error", err, "indirect pin nothing requires"))
        t.rejects("N2 tidy needs --yes", ("tidy",), "rerun with --yes")
        rc, out, err = t.run("tidy", "--yes")
        t.expect(rc == 0 and "unpin" in out, "N2: tidy --yes should drop the extra pin: " + err + out)
        rc, out, err = t.run("build")
        t.expect(rc == 0, "N2: build after tidy: " + err)
    return rows


def n3(t):
    """Chained trust: a dependency's recorded hash for its own dependencies is checked on first fetch."""
    w = t.world
    w.publish(C, "v1.2.0"), w.publish(A, "v1.0.0", deps=[(C, "v1.2.0")])
    w.publish(C, "v1.2.0", marker="moved after A recorded its hash")
    t.run("init")
    err = t.rejects("N3 chained", ("add", A), "hash mismatch for ex.test/bob/c v1.2.0", probe="moved tag under a dependency")
    t.expect(("own deps.sum" if t.b1 else "project.toml") in err and A in err, "N3 must say whose record disagrees: " + err)
    rows = [t.row("N3a", "error", err, "C v1.2.0 moved after A recorded its hash; a fresh project adding A is refused")]
    if t.b1:
        w.publish("ex.test/ann/nosum", "v1.0.0", deps=[(C, "v1.2.0")], no_sum=True)
        err = t.rejects("N3 no deps.sum", ("add", "ex.test/ann/nosum"), "ships no deps.sum")
        rows.append(t.row("N3b", "error", err, "a package with requirements but no deps.sum"))
    return rows


def n4(t):
    """24h rule is a convenience; the descent check is the defence against rewritten history."""
    w = t.world
    w.publish(JSON, "v1.0.0")
    t.run("init"), t.run("add", JSON)
    w.publish(JSON, "v1.0.1", fresh=True, marker="EVIL, history rewritten, tag date forged to 2020")
    err = t.rejects("N4 rewritten history", ("update",), "does not descend", probe="forged tag date (rewritten history)")
    rows = [t.row("N4a", "error", err, "forged 2020 date passes the age rule; the descent check refuses")]
    rc, out, err = t.run("update", "--force")
    t.expect(rc == 0 and "accepted because of --force" in err, "N4 --force: " + err)
    rc, out, err = t.run("build")
    t.expect(rc == 0 and has(out, JSON, "v1.0.1"), "N4 forced update: " + out + err)
    w.publish(JSON, "v1.0.2", marker="honest-looking descendant with a forged date")
    rc, out, err = t.run("update")
    t.expect(rc == 0 and "v1.0.1 -> v1.0.2" in out and "convenience, not a security check" in err, "N4: a descendant with a forged date is accepted, and the tool says the age rule is not a defence: " + err + out)
    rows.append(t.row("N4b", "ok (known limit)", note="a forged date on a normal descendant commit is accepted; the output says so"))
    return rows


def n5(t):
    """The hashed set is everything the build reads."""
    w, rows = t.world, []
    w.publish("ex.test/ann/p", "v1.0.0", clib={"png": {}}, files=["src"])
    t.run("init")
    err = t.rejects("N5 C source outside files", ("add", "ex.test/ann/p"), "not in the package's hashed file set", probe="C sources outside the hashed files")
    rows.append(t.row("N5a", "error", err, "csrc/png.c is not in files = [src]"))
    basic_t = T("N5b", t.flavor, t.base)  # its own world: basic() publishes json and log
    basic(basic_t)
    basic_t.run("vendor")
    vd = next(basic_t.app.glob("vendor/*json@v1.4.0"))
    write_text(vd / "evil.lang", "fn evil() {}\n")
    err = basic_t.rejects("N5 vendor extra file", ("build",), "outside the hashed set", probe="vendor/ with an extra file")
    rows.append(t.row("N5b", "error", err, "extra file in vendor/ outside files = [src]"))
    (vd / "evil.lang").unlink()
    (basic_t.app / "vendor" / "ex.test%2Fevil%2Fx@v1.0.0").mkdir()
    err = basic_t.rejects("N5 vendor extra project", ("build",), "not in the build list")
    rows.append(t.row("N5c", "error", err, "extra project directory in vendor/"))
    shutil.rmtree(basic_t.app / "vendor")
    cd = next(basic_t.cache.glob("*json@v1.4.0/tree"))
    write_text(cd / "evil.lang", "fn evil() {}\n")
    err = basic_t.rejects("N5 cache extra file", ("build",), "outside the hashed set")
    rows.append(t.row("N5d", "error", err, "extra file in the cache tree"))
    for tag, label, kw, needle in (
            ("v1.0.0", "symlink", {"index": [("120000", b"/etc/hostname", "src/host.lang")]}, "is a symlink"),
            ("v1.0.1", "case collision", {"index": [("100644", b"x", "src/Q.lang")]}, "differ only by case"),
            ("v1.0.2", "submodule", {"index": [("160000", None, "src/sub")]}, "is a submodule")):
        w.publish("ex.test/ann/q", tag, **kw)
        err = t.rejects(f"N5 {label}", ("add", "ex.test/ann/q", tag), needle)
        rows.append(t.row("N5" + "efg"[("symlink", "case collision", "submodule").index(label)], "error", err, label + " in a package"))
    return rows


def n6(t):
    """C declarations are validated data."""
    rows = []
    cases = [
        ("passwd", lambda c: c.update(sources=["../../../../etc/passwd"]), "relative path inside the package", "C source ../../etc/passwd"),
        ("abs-source", lambda c: c.update(sources=["/abs/evil.c"]), "relative path inside the package", None),
        ("abs-include", lambda c: c.update(include=["/usr/include"]), "relative path inside the package", None),
        ("drive", lambda c: c.update(include=["C:/x"]), "relative path inside the package", None),
        ("plugin", lambda c: c.update(link=["-fplugin=./evil.so"]), "not a library name", "link = -fplugin"),
        ("wrap", lambda c: c.update(link=["-Wl,--wrap=malloc"]), "not a library name", None),
        ("flag-key", lambda c: c.update(cflags=["-O3"]), "unsupported key", None),
        ("define", lambda c: c.update(defines=["X;rm -rf"]), "defines", None),
        ("header-as-source", lambda c: c.update(sources=["csrc/png.h"]), "must be a .c file", None),
        ("bad-abi", lambda c: c.update(target={"linux": {"link": ["m"]}}), "keyed by ABI", None),
        ("target-key", lambda c: c.update(target={"gnu": {"cflags": ["-x"]}}), "unsupported key", None),
    ]
    for i, (name, edit_c, needle, probe) in enumerate(cases):
        pn = f"ex.test/ann/c{i}"
        t.world.publish(pn, "v1.0.0", clib={"png": {}}, patch=lambda m, f=edit_c: f(m["c"]["png"]))
        if i == 0:
            t.run("init")
        err = t.rejects(f"N6 {name}", ("add", pn), needle, probe=probe)
        rows.append(t.row("N6" + "abcdefghijk"[i], "error", err, name))
    return rows


C_H = ("#ifndef CKSUM_H\n#define CKSUM_H\nunsigned int cksum_fnv1a(const char *s);\nunsigned int cksum_adler32(const char *s);\n"
       "void cksum_hex(unsigned int v, char *out);\ndouble cksum_rms(double a, double b);\n#endif\n")
C_SRC = {
    "csrc/cksum.h": C_H,
    "csrc/cksum.c": ('#include "cksum.h"\nunsigned int cksum_fnv1a(const char *s) {\n  unsigned int h = 2166136261u;\n'
                     '  for (; *s; s++) { h ^= (unsigned char)*s; h *= 16777619u; }\n  return h;\n}\n'
                     'unsigned int cksum_adler32(const char *s) {\n  unsigned int a = 1, b = 0;\n'
                     '  for (; *s; s++) { a = (a + (unsigned char)*s) % 65521u; b = (b + a) % 65521u; }\n  return (b << 16) | a;\n}\n'),
    "csrc/hex.c": ('#include "cksum.h"\nvoid cksum_hex(unsigned int v, char *out) {\n  static const char d[] = "0123456789abcdef";\n'
                   '  for (int i = 0; i < 8; i++) out[i] = d[(v >> (28 - 4 * i)) & 15];\n  out[8] = 0;\n}\n'),
    "csrc/ratio.c": '#include <math.h>\n#include "cksum.h"\ndouble cksum_rms(double a, double b) { return sqrt((a * a + b * b) / 2.0); }\n',
}
C_MAIN = ('#include <stdio.h>\n#include "cksum.h"\nint main(void) {\n  char h[9];\n  volatile double a = 6.0, b = 8.0;\n'
          '  cksum_hex(cksum_fnv1a("hello"), h); printf("fnv1a=%s\\n", h);\n  cksum_hex(cksum_adler32("hello"), h); printf("adler32=%s\\n", h);\n'
          '  printf("rms=%.2f\\n", cksum_rms(a, b));\n  return 0;\n}\n')
CKSUM = "ex.test/ann/cksum"


def cksum_c(lib="cksum", defines=()):
    return {lib: {"version": "1.0", "sources": ["csrc/cksum.c", "csrc/hex.c", "csrc/ratio.c"], "include": ["csrc"],
                  "defines": list(defines),
                  "target": {"msvc": {"defines": ["CKSUM_ABI_MSVC=1"]}, "gnu": {"link": ["m"]}, "darwin": {"link": ["m"]}}}}


def n7(t):
    """Compile and link a real C library and a C app shim with clang; duplicate exported symbols are refused."""
    if not shutil.which(os.environ.get("CC") or "clang"):
        NOTES.append("N7 skipped: clang not found")
        print("note: N7 skipped, no clang on PATH", file=sys.stderr)
        return [t.row("N7", "skipped (no clang)")]
    w = t.world
    w.publish(CKSUM, "v1.0.0", c=cksum_c(), extra=C_SRC)
    t.run("init"), t.run("add", CKSUM)
    write_text(t.app / "main.c", C_MAIN)
    edit(t.app, lambda m: m.update(c={"app": {"version": "1", "sources": ["main.c"]}}))
    out_dir = t.box / "out"
    rc, out, err = t.run("ccbuild", "--out", str(out_dir))
    t.expect(rc == 0, "N7 ccbuild failed: " + err + out)
    exe = out_dir / ("app.exe" if os.name == "nt" else "app")
    ran = subprocess.run([str(exe)], capture_output=True, text=True).stdout if exe.exists() else ""
    t.expect("fnv1a=4f9f2cab" in ran and "adler32=062c0215" in ran and "rms=7.07" in ran, "N7 program output: " + ran)
    rows = [t.row("N7a", "ok", note="3-file C library + main.c compiled and linked by clang; ran: " + ran.replace("\n", " ").strip(), out=out)]
    w.publish("ex.test/bob/zl", "v1.0.0", c={"zl": {"version": "1", "sources": ["csrc/zl.c"], "include": ["csrc"]}},
              extra={"csrc/zl.c": "unsigned int cksum_adler32(const char *s) { (void)s; return 7; }\n"})
    t.run("add", "ex.test/bob/zl")
    if have_nm():
        err = t.rejects("N7 duplicate symbol", ("ccbuild", "--out", str(out_dir)), "duplicate C symbol 'cksum_adler32'", probe="same C symbol from two packages")
        t.expect(CKSUM in err and "ex.test/bob/zl" in err, "N7 must name both packages: " + err)
        rows.append(t.row("N7b", "error", err, "two packages export cksum_adler32 under different C library names"))
    else:
        NOTES.append("N7b skipped: no nm or llvm-nm")
        print("note: N7b skipped, no nm/llvm-nm on PATH", file=sys.stderr)
        rc, out, err = t.run("ccbuild", "--out", str(out_dir))
        t.expect(rc != 0, "N7b: the linker itself must still refuse a duplicate symbol")
        rows.append(t.row("N7b", "error (linker only; nm missing)", err))
    return rows


def n8(t):
    """Version changes are always printed, downgrades included."""
    w = t.world
    w.publish(A, "v0.9.0"), w.publish(A, "v1.0.0")
    t.run("init"), t.run("add", A, "v1.0.0")
    rc, out, err = t.run("add", A, "v0.9.0")
    t.expect(rc == 0 and "downgrade" in out and "v1.0.0 -> v0.9.0" in out, "N8: a downgrade must be printed: " + out + err)
    return [t.row("N8", "ok", note="downgrade printed: " + [x for x in out.splitlines() if "downgrade" in x][0].strip(), out=out)]


def n9(t):
    """Root-only [replace]: a fork, a local directory, reserved paths refused."""
    w, rows = t.world, []
    FORK = "ex.test/me/json"
    w.publish(JSON, "v1.0.0"), w.publish(A, "v1.0.0", deps=[(JSON, "v1.0.0")])
    w.publish(FORK, "v1.0.0", module_path=JSON, marker="fork")
    t.run("init")
    err = t.rejects("N9 fork without replace", ("add", FORK), "[replace]", probe="fork under another path")
    rows.append(t.row("N9a", "error", err, "a fork is refused unless the root says [replace]"))
    edit(t.app, lambda m: m.update(replace={JSON: FORK}))
    if not t.b1:
        t.run("add", JSON, "v1.0.0")
    rc, out, err = t.run("add", A)
    t.expect(rc == 0, "N9 add A with replace: " + err)
    rc, out, err = t.run("build")
    t.expect(rc == 0 and w.hashes[(FORK, "v1.0.0")][0][:19] in out and w.hashes[(JSON, "v1.0.0")][0][:19] not in out, "N9: the build must use the fork: " + out + err)
    rows.append(t.row("N9b", "ok", note="the fork's files are built wherever the graph says " + JSON, out=out))
    t2 = T("N9c", t.flavor, t.base, w)
    (t2.box / "localjson" / "src").mkdir(parents=True)
    write_text(t2.box / "localjson" / "project.toml", dump_toml({("module" if t.b1 else "package"): {("path" if t.b1 else "name"): JSON}}))
    write_text(t2.box / "localjson" / "src" / "json.lang", "fn json() {}\n")
    t2.run("init")
    edit(t2.app, lambda m: m.update(replace={JSON: "../localjson"}))
    rc, out, err = t2.run("add", A)
    t2.expect(rc == 0, "N9 local replace add: " + err)
    rc, out, err = t2.run("build")
    t2.expect(rc == 0 and "local-dir-not-hashe" in out, "N9 local replace build: " + out + err)
    rows.append(t.row("N9c", "ok", note="local directory replace (flagged as not hashed)"))
    t3 = T("N9d", t.flavor, t.base, w)
    t3.run("init")
    edit(t3.app, lambda m: m.update(replace={"std": FORK}))
    err = t3.rejects("N9 replace std", ("build",), "reserved for the toolchain", probe="replace of a toolchain path")
    rows.append(t.row("N9d", "error", err, "[replace] of std"))
    edit(t3.app, lambda m: m.update(replace={JSON: "extras"}))
    err = t3.rejects("N9 replace to extras", ("build",), "reserved for the toolchain")
    rows.append(t.row("N9e", "error", err, "[replace] to extras"))
    return rows


def n10(t):
    """One project per repo, several modules inside: imports resolve by longest prefix against requires."""
    w, rows = t.world, []
    TOOLS_P = "ex.test/ann/tools"
    w.publish(TOOLS_P, "v1.0.0", extra={"json/json.lang": "fn json() {}\n", "csv/csv.lang": "fn csv() {}\n"})
    w.publish(TOOLS_P + "/json", "v1.0.0", extra={"x/x.lang": "fn x() {}\n"})
    t.run("init")
    err = t.rejects("N10 subdirectory as project", ("add", TOOLS_P + "/csv"), "is a project (a repository)", probe="monorepo subdirectory module")
    rows.append(t.row("N10a", "error", err, "csv/ is a module (directory), not a project; the hint says what to require"))
    t.run("add", TOOLS_P), t.run("add", TOOLS_P + "/json")
    for imp, want in ((TOOLS_P + "/csv", f"project {TOOLS_P} v1.0.0, module directory csv"),
                      (TOOLS_P + "/json/x", f"project {TOOLS_P}/json v1.0.0, module directory x"),
                      (TOOLS_P, f"project {TOOLS_P} v1.0.0, module directory .")):
        rc, out, err = t.run("which", imp)
        t.expect(rc == 0 and want in out, f"N10 which {imp}: {out}{err}")
    t.rejects("N10 no such module", ("which", TOOLS_P + "/xml"), "has no module directory")
    err = t.rejects("N10 not on a segment boundary", ("which", TOOLS_P + "x/y"), "no project in requires provides")
    rows.append(t.row("N10b", "ok", note="longest prefix wins: tools/csv -> tools, tools/json/x -> tools/json; tools/xml and toolsx/y refused"))
    return rows


def n11(t):
    """Majors coexist only for pure modules; v0 minors are incompatible."""
    w, rows = t.world, []
    w.publish(C, "v1.2.0", clib={"sqlite": {}}), w.publish(C, "v2.0.0", clib={"sqlite": {}})
    w.publish(A, "v1.0.0", deps=[(C, "v1.2.0")]), w.publish(B, "v1.0.0", deps=[(C, "v2.0.0")])
    t.run("init"), t.run("add", A)
    err = t.rejects("N11 C at two majors", ("add", B), ("wrap C", "incompatible versions"), probe="C-wrapping package at two majors")
    rows.append(t.row("N11a", "error", err, "C-wrapping project at v1 and v2"))
    t2 = T("N11b", t.flavor, t.base, w)
    w.publish("ex.test/bob/z", "v0.1.0"), w.publish("ex.test/bob/z", "v0.9.0")
    w.publish("ex.test/ann/a0", "v1.0.0", deps=[("ex.test/bob/z", "v0.1.0")]), w.publish("ex.test/bob/b0", "v1.0.0", deps=[("ex.test/bob/z", "v0.9.0")])
    t2.run("init"), t2.run("add", "ex.test/ann/a0")
    rc, out, err = t2.run("add", "ex.test/bob/b0")
    if t.b1:
        t.expect(rc == 0 and "v0 minors are treated as incompatible" in err, "N11 v0 warning: " + out + err)
        rows.append(t.row("N11b", "warning", err, "A wants v0.1.0, B wants v0.9.0: builds with v0.9.0 and warns"))
    else:
        t.expect(rc != 0 and "incompatible versions" in err and "v0 minors" in err, "N11 v0 error: " + out + err)
        rows.append(t.row("N11b", "error", err, "v0.1 and v0.9 count as different majors"))
    return rows


def n12(t):
    """Dialect gate (ADR-0002): reserved first segments, toolchain directory only."""
    w, rows = t.world, []
    tc = t.box / "tc"
    key = "module" if t.b1 else "package"
    nk = "path" if t.b1 else "name"
    for n, extra in (("std", {}), ("extras", {"dialect": True})):
        (tc / n / "io").mkdir(parents=True)
        write_text(tc / n / "io" / "io.lang", "fn io() {}\n")
        write_text(tc / n / "project.toml", dump_toml({key: dict({nk: n}, **extra)}))
    t.run("init")
    rc, out, err = t.run("--toolchain", str(tc), "which", "std/io")
    t.expect(rc == 0 and "toolchain package std" in out, "N12 std/io: " + out + err)
    t.rejects("N12 std without toolchain", ("which", "std/io"), "no --toolchain")
    t.rejects("N12 std/nope", ("--toolchain", str(tc), "which", "std/nope"), "no module directory")
    t.rejects("N12 requires std", ("build",), "reserved for the toolchain") if False else None
    edit(t.app, lambda m: m.update(**({"requires": {"std": "v1.0.0"}} if t.b1 else {"deps": {"std": {"url": "x", "tag": "v1.0.0", "hash": "x", "commit": "x"}}})))
    err = t.rejects("N12 requiring std", ("build",), "reserved for the toolchain", probe="dependency on a toolchain path")
    rows.append(t.row("N12a", "error", err, "requiring std"))
    t.run("init", app=t.box / "app2") if (t.box / "app2").mkdir() is None else None
    app2 = t.box / "app2"
    edit(app2, lambda m: m[key].update(dialect=True))
    err = t.rejects("N12 project dialect", ("build",), "dialect = true", app=app2)
    rows.append(t.row("N12b", "error", err, "the project itself declares dialect = true", app=app2))
    w.publish("ex.test/evil/dia", "v1.0.0", mod_extra={"dialect": True})
    t3 = T("N12c", t.flavor, t.base, w)
    t3.run("init")
    err = t3.rejects("N12 third-party dialect", ("add", "ex.test/evil/dia"), "dialect = true", probe="third-party dialect")
    rows.append(t.row("N12c", "error", err, "third-party package declaring dialect = true"))
    w.publish("ex.test/evil/extras", "v1.0.0", module_path="extras")
    err = t3.rejects("N12 claims extras", ("add", "ex.test/evil/extras"), "reserved toolchain name", probe="third party claims to be extras")
    rows.append(t.row("N12d", "error", err, "a third-party package claiming the name extras"))
    t4 = T("N12e", t.flavor, t.base)
    basic(t4)
    (t4.app / "vendor").mkdir(exist_ok=True)
    (t4.app / "vendor" / "std@v1.0.0").mkdir()
    err = t4.rejects("N12 vendor std", ("build",), "reserved for the toolchain and can never be vendored")
    rows.append(t.row("N12e", "error", err, "vendor/std@v1.0.0 present"))
    bad = t.box / "tc-bad"
    shutil.copytree(tc, bad)
    edit(bad / "std", lambda m: m.update(**({"requires": {C: "v1.0.0"}} if t.b1 else {"deps": {C: {"url": "x"}}})))
    err = t3.rejects("N12 toolchain package with a dependency", ("--toolchain", str(bad), "which", "std/io"), "depend on nothing third-party")
    rows.append(t.row("N12f", "error", err, "a toolchain package with a third-party dependency"))
    w.publish("ex.test/ann/new", "v1.0.0", mod_extra={"lang": "9.9"})
    err = t3.rejects("N12 lang floor", ("add", "ex.test/ann/new"), "needs lang 9.9")
    rc, out, err2 = t3.run("--lang-version", "9.9", "add", "ex.test/ann/new")
    t.expect(rc == 0, "N12 --lang-version 9.9 should accept: " + err2)
    rows.append(t.row("N12g", "error", err, "a package needing a newer lang than the toolchain"))
    return rows


SCENARIOS = [
    ("S1", "simple app, two deps", s1), ("S2", "diamond: A->C v1.2, B->C v1.4", s2),
    ("S3", "upgrade transitive C when v1.5 is tagged", s3), ("S4", "major break: B moves to C v2", s4),
    ("S5", "upstream deleted", s5), ("S6", "tampered tag", s6),
    ("S7", "two packages declare C library png", s7), ("S8", "offline build", s8),
    ("S9", "typo'd dependency name", s9), ("S10", "24h minimum age for new tags on update", s10),
    ("N1", "text=auto dependency under crlf checkout settings", n1), ("N2", "frozen build", n2),
    ("N3", "chained trust", n3), ("N4", "rewritten history and forged tag date", n4),
    ("N5", "hashed file set", n5), ("N6", "C declarations rejected", n6),
    ("N7", "real C library compiled and linked", n7), ("N8", "downgrade is printed", n8),
    ("N9", "root-only [replace]", n9), ("N10", "multi-module repo", n10),
    ("N11", "majors with C; v0 minors", n11), ("N12", "dialect gate and lang floor", n12),
]


def cell(r):
    f = ", ".join(f"{k} {v} B" for k, v in r["files"].items()) or "-"
    return f"{r['status']}; {r['cmds']} cmds; {f}" if r["kind"] == "S" else r["status"]


def table(results):
    lines = ["| Scenario | B1+ (full list + sum) | B2+ (pins + tidy) |", "|---|---|---|"]
    for sid, desc, _ in SCENARIOS:
        subs = sorted({r["label"] for (s, fl), rs in results.items() if s == sid for r in rs})
        for lab in subs:
            cells = []
            for fl in FL:
                r = next((x for x in results.get((sid, fl), []) if x["label"] == lab), None)
                cells.append(cell(r) if r else "-")
            r1 = next(x for fl in FL for x in results.get((sid, fl), []) if x["label"] == lab)
            lines.append(f"| {lab}. {desc if lab == subs[0] else r1['note']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_results(path, results):
    out = ["# D9 loop 2: B1+ vs B2+ results", "",
           "Generated by `scenarios/run_scenarios2.py --write`. Every cell: outcome; commands typed (from an empty project, setup of "
           "the upstream repos not counted); sizes of the files the tool wrote. B2+ project.toml sizes include temp-dir file URLs. "
           "The loop-1 results for B1, B2 and B3 are in `results-loop1.md` (unchanged).", "", table(results), "",
           "## False accepts from the review (probe, then the exact first line of each tool's refusal)", "",
           "| Probe | B1+ | B2+ |", "|---|---|---|"]
    names = sorted({k[0] for k in PROBES})
    for n in names:
        out.append(f"| {n} | `{PROBES.get((n, 'b1p'), '-')}` | `{PROBES.get((n, 'b2p'), '-')}` |")
    out += ["", "## Error messages (exact text, temp paths shown as `<tmp>`)", ""]
    for sid, desc, _ in SCENARIOS:
        for fl in FL:
            for r in results.get((sid, fl), []):
                if r["msg"]:
                    out += [f"**{r['label']} {'B1+' if fl == 'b1p' else 'B2+'}** ({r['note']})", "```", r["msg"], "```", ""]
    out += ["## Build output, scenarios 2 and 4", ""]
    for key in ("S2", "S4"):
        for fl in FL:
            rs = [r for r in results.get((key, fl), []) if r["out"]]
            if rs:
                out += [f"**{key} {'B1+' if fl == 'b1p' else 'B2+'}**", "```", rs[0]["out"].strip(), "```", ""]
    out += ["## File formats (after S2; S4 for the two-majors case)", ""]
    for key in ("S2", "S4"):
        for fl in FL:
            for fn, text in SAMPLES.get((key, fl), {}).items():
                out += [f"**{key} {'B1+' if fl == 'b1p' else 'B2+'} {fn}**", "```toml", text.rstrip(), "```", ""]
    Path(path).write_text("\n".join(out) + "\n", encoding="utf-8")


def main():
    args = sys.argv[1:]
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    base = Path(tempfile.mkdtemp(prefix="deps-spike2-")).resolve()
    results = {}
    try:
        if not only:
            for f in toml_conformance.run():
                FAILS.append(f)
            print("toml conformance: " + ("ok" if not FAILS else "FAILED"), flush=True)
        for sid, desc, fn in SCENARIOS:
            if only and sid not in only:
                continue
            for fl in FL:
                t = T(sid, fl, base)
                try:
                    results[(sid, fl)] = fn(t)
                except Exception as e:  # a crash is a failure, not a hidden skip
                    import traceback
                    FAILS.append(f"[{sid}/{fl}] crashed: {type(e).__name__}: {e}\n{traceback.format_exc()}")
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
