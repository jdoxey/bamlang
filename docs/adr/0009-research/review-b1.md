# Adversarial review of B1 (Fable 5.2 reviewer, 2026-11-14; condensed)

**Verdict:** B1's direction stands, but loop back for one more round of examples. With the review's scores:
- B1 as proposed: 65;
- B2: 70;
- B3: 62;
- B1+ (the fixes below): 73, a tie with B2.

Probes are in the session scratchpad (`attack.py`). Most findings hit `common.py`, so they apply to all three
prototypes.

## Fatal as written

- **F1. The hash doesn't cover the compiled files.** C `sources` outside `files` aren't hashed; a re-tagged `png.c`
  built "ok". `vendor/` extras pass too.
  - **Fix:** the compiler reads only hashed files, and anything else in vendor or the cache is rejected.
- **F2. Hashes differ per OS.** A `text=auto` dependency checked out with `core.eol=crlf` gives "hash mismatch".
  Symlinks are hashed by following them.
  - **Fix:** hash git objects, never the checkout; reject symlinks, case collisions and submodules; record the commit
    SHA.
- **F3. Two coexisting majors are undefined.**
  - A C library wrapped by v1 and v2 is refused, so S4 works only for pure modules.
  - `c.Token` and `c/v2.Token` are different types.
  - The orphan rule bridges the two only from v2.
  - Module state is duplicated.
  - The last import segment is `v2`.
  - **Fix:** write these rules down and add a C-wrapping S4.

## Serious

1. **The 24-hour rule is void.** A forged tagger date beats it.
   - **Fix:** don't claim it for security. Require the new tag's commit to descend from the recorded one.
2. **Trust on first use with no frozen mode.** An emptied `deps.sum` is silently rewritten by `build`.
   - **Fix:** `build` never writes it.
   - **Chaining:** hash each package's own `deps.sum` and check first fetches against it (B2-style chaining without a
     server).
3. **C declarations aren't validated:** `../../etc/passwd`, absolute includes, and `link = ["-fplugin=…"]` were all
   accepted. `m` doesn't exist on MSVC. Self-chosen library names miss real collisions. No prototype compiles C.
   - **Fix:** relative in-package paths only; library names only; per-target keys by ABI; detect duplicate symbols at
     link; `configure`-style libraries are out of scope.
4. **The S4 downgrade is silent.**
   - **Fix:** the root manifest records the full build list (Go 1.17 style), and every version change is printed.
     This also removes the cost of superseded versions.
5. **Named arguments make parameter renames breaking, so `/vN` matters more,** and authors don't bump majors.
   - **Fix:** `deps api-diff`, plus a warning on same-major API removals; `v0` minors count as incompatible.
6. **Identity is location:** forks, monorepos and moves fail.
   - **Fix:** root-only `[replace]`; one project per repo; longest-prefix import resolution; the words "module"
     (directory) and "project" (repo).
7. **The ADR-0002 dialect gate is not built.**
   - **Fix:** `std`/`extras` ship with the toolchain; the dialect is allowed only under the toolchain directory; import
     paths without a dot are reserved; `replace` and `vendor` of them are refused.
   - **Version floor:** a `lang = "x.y"` minimum.
8. **The "TOML subset" is a silent-misreading dialect** (`"C:\new"`, merged duplicate tables). It can't be changed
   later, because old manifests are read forever.
   - **Fix:** strict TOML 1.0 subset with conformance tests.
9. **Toolchain:** T1 breaks no charter goal, so it is not a `needs-john` issue. The spike never ran, so record T1 as
   interim with a revisit trigger. Put a yes/no line in STATE. The Windows ABI leaks into manifests (`m`).

## Minor

10. `internal/` is path magic.
11. Show the owner and first-tag date on `add` (typosquats).
12. Add a `verify` command.
13. Specify cache-key escaping.
14. Folded into fix 4.

## Next examples must show (CI, three OSes)

1. git-object hashing with `text=auto`;
2. a frozen build plus the requirer-sum check;
3. a real C library compiled and linked with per-target keys;
4. the full build list in the manifest with a change report;
5. a root `[replace]`, a multi-module repo, and the dialect rule;
6. false-accept regression tests.

**Fallback:** B2 with automatic tidy.
