"""Builds local bare git repos (the scenario 'internet') for one tool flavour (b1, b2 or b3)."""
import shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import content_hash, dump_toml, git, rmtree, sv, url_for, write_text
import os

OLD = "2020-01-01T00:00:00+0000"


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime())


class World:
    def __init__(self, root, flavor):
        self.root, self.flavor = Path(root), flavor
        self.host, self.work, self.hashes = self.root / "host-root", self.root / "work", {}
        os.environ["DEPS_HOST"] = str(self.host)

    def modpath(self, name, tag):
        return name + (f"/v{sv(tag)[0]}" if sv(tag)[0] >= 2 else "")

    def manifest(self, name, tag, deps, clib, files):
        pkg = {"files": files} if files else {}
        c = {"c": {lib: dict(d, sources=["csrc/%s.c" % lib], include=["csrc"], link=["m"]) for lib, d in clib.items()}} if clib else {}
        if self.flavor == "b1":
            return {"module": {"path": self.modpath(name, tag), **pkg},
                    "requires": {self.modpath(n, t): t for n, t in deps}, **c}
        if self.flavor == "b2":
            return {"package": {"name": name, **pkg},
                    "deps": {n: {"url": url_for(n), "tag": t, "hash": self.hashes[(n, t)]} for n, t in deps}, **c}
        v = sv(tag)
        return {"package": {"name": name, "version": tag[1:], **pkg},
                "deps": {n: "^%d.%d" % sv(t)[:2] for n, t in deps}, **c}

    def publish(self, name, tag, deps=(), clib=None, date=OLD, restrict=False, marker=""):
        """Commit a new tree, tag it (annotated, tag date = date) and push. Same tag again = a moved tag."""
        w, bare = self.work / name, self.host / (name + ".git")
        if not bare.exists():
            bare.mkdir(parents=True)
            git("init", "--bare", "-q", "-b", "main", cwd=bare)
            w.mkdir(parents=True)
            git("init", "-q", "-b", "main", cwd=w)
            git("remote", "add", "origin", str(bare), cwd=w)
        for p in w.iterdir():
            if p.name != ".git":
                rmtree(p) if p.is_dir() else p.unlink()
        files = (["src"] + (["csrc"] if clib else [])) if restrict else None
        last = name.split("/")[-1]
        (w / "src").mkdir()
        write_text(w / "src" / (last + ".lang"), f"// {name} {tag} {marker}\nfn {last}() {{}}\n")
        write_text(w / "README.md", f"# {name}\nnot part of the hash when files = [src]\n")
        for lib in (clib or {}):
            (w / "csrc").mkdir(exist_ok=True)
            write_text(w / "csrc" / (lib + ".c"), f"/* {lib} for {name} {tag} */\n")
        write_text(w / "project.toml", dump_toml(self.manifest(name, tag, deps, clib, files)))
        env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        git("add", "-A", cwd=w)
        git("commit", "-q", "--allow-empty", "-m", f"{name} {tag}", cwd=w, env=env)
        git("tag", "-a", "-f", tag, "-m", tag, cwd=w, env=env)
        git("push", "-q", "--force", "origin", "main", f"refs/tags/{tag}", cwd=w)
        self.hashes[(name, tag)] = content_hash(w, files)

    def delete(self, name):
        rmtree(self.host / (name + ".git"))
