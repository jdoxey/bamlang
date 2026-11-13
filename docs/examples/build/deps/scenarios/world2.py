"""Builds local bare git repos (the scenario 'internet') for the B1+ and B2+ flavours (b1p, b2p)."""
import os, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import git, rmtree, write_text, sv, url_for  # noqa: E402
from common2 import dump_toml, list_tree, cat_blobs, hash_items, select, manifest_files, parse_toml  # noqa: E402

OLD = "2020-01-01T00:00:00+0000"


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime())


def modpath(name, tag):
    return name + (f"/v{sv(tag)[0]}" if sv(tag)[0] >= 2 else "")


class World:
    def __init__(self, root, flavor):
        self.root, self.flavor = Path(root), flavor
        self.host, self.work, self.hashes = self.root / "host-root", self.root / "work", {}
        os.environ["DEPS_HOST"] = str(self.host)

    def c_table(self, clib):
        return {lib: {"version": d.get("version", "1.0"), "sources": [f"csrc/{lib}.c"], "include": ["csrc"],
                      "target": {"gnu": {"link": ["m"]}, "darwin": {"link": ["m"]}}} for lib, d in clib.items()}

    def manifest(self, name, tag, deps, c, files, module_path, mod_extra):
        pkg = dict({"files": files} if files else {}, **mod_extra)
        if self.flavor == "b1p":
            return {"module": {"path": module_path or modpath(name, tag), **pkg},
                    "requires": {modpath(n, t): t for n, t in deps}, **({"c": c} if c else {})}
        pins = {n: {"url": url_for(n), "tag": t, "hash": self.hashes[(n, t)][0], "commit": self.hashes[(n, t)][1]} for n, t in deps}
        return {"package": {"name": module_path or name, **pkg}, "deps": pins, **({"c": c} if c else {})}

    def publish(self, name, tag, deps=(), clib=None, date=OLD, restrict=False, marker="", extra=None, fresh=False,
                files=None, c=None, patch=None, module_path=None, mod_extra=None, index=(), attrs=None, no_sum=False):
        """Commit a new tree, tag it (annotated, tag date = date) and push. Same tag again = a moved tag.
        extra: {path: str|bytes}; index: [(mode, blob-bytes-or-None, path)] entries added straight to the index
        (symlinks, submodules, case collisions without needing OS support); fresh: unrelated history."""
        os.environ["DEPS_HOST"] = str(self.host)
        w, bare = self.work / name.replace("/", "__"), self.host / (name + ".git")
        if not bare.exists():
            bare.mkdir(parents=True)
            git("init", "--bare", "-q", "-b", "main", cwd=bare)
        if fresh and w.exists():
            rmtree(w)
        if not w.exists():
            w.mkdir(parents=True)
            git("init", "-q", "-b", "main", cwd=w)
            git("remote", "add", "origin", str(bare), cwd=w)
        for p in w.iterdir():
            if p.name != ".git":
                rmtree(p) if p.is_dir() else p.unlink()
        if files is None and restrict:
            files = ["src"] + (["csrc"] if clib else [])
        last = name.split("/")[-1]
        (w / "src").mkdir()
        write_text(w / "src" / (last + ".lang"), f"// {name} {tag} {marker}\nfn {last}() {{}}\n")
        write_text(w / "README.md", f"# {name}\nnot part of the hash when files = [src]\n")
        if attrs:
            write_text(w / ".gitattributes", attrs)
        for lib in (clib or {}):
            (w / "csrc").mkdir(exist_ok=True)
            write_text(w / "csrc" / (lib + ".c"), f"/* {lib} for {name} {tag} */\nint {lib}_marker(void) {{ return 1; }}\n")
        for rel, data in (extra or {}).items():
            (w / rel).parent.mkdir(parents=True, exist_ok=True)
            (w / rel).write_bytes(data if isinstance(data, bytes) else data.encode())
        m = self.manifest(name, tag, deps, c if c is not None else (self.c_table(clib) if clib else None), files,
                          module_path, mod_extra or {})
        if patch:
            patch(m)
        write_text(w / "project.toml", dump_toml(m))
        if self.flavor == "b1p" and deps and not no_sum:
            write_text(w / "deps.sum", dump_toml({"sum": {f"{modpath(n, t)}@{t}": {"hash": self.hashes[(n, t)][0], "commit": self.hashes[(n, t)][1]}
                                                          for n, t in sorted(deps)}}))
        env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        git("add", "-A", cwd=w)
        for mode, data, path in index:
            if mode == "160000":
                sha = "1" * 40
            else:
                sha = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=w, input=data, capture_output=True).stdout.decode().strip()
            git("update-index", "--add", "--cacheinfo", f"{mode},{sha},{path}", cwd=w)
        git("commit", "-q", "--allow-empty", "-m", f"{name} {tag}", cwd=w, env=env)
        git("tag", "-a", "-f", tag, "-m", tag, cwd=w, env=env)
        git("push", "-q", "--force", "origin", "main", f"refs/tags/{tag}", cwd=w)
        commit = git("rev-parse", "HEAD", cwd=w).stdout.strip()
        if not index:
            ents = list_tree(w, commit)
            sel = select(list(ents), manifest_files(parse_toml((w / "project.toml").read_text(), "m")), name)
            blobs = cat_blobs(w, [ents[p][2] for p in sel])
            self.hashes[(name, tag)] = (hash_items([(p, blobs[ents[p][2]]) for p in sel]), commit)
        return commit

    def delete(self, name):
        rmtree(self.host / (name + ".git"))
