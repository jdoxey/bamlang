# D9 loop 2 notes: B1+ and B2+ (this section first; the loop-1 notes follow unchanged)

`./run.sh` runs the loop-1 scenarios (B1, B2, B3 untouched; output in `results-loop1.md`) and then the loop-2 scenarios
(`scenarios/run_scenarios2.py`, 22 scenarios x 2 tools, plus 39 TOML conformance cases; output in `results.md`).
Local run: Linux only (Python 3.13, git 2.47, clang with llvm-nm). Windows and macOS are left to CI. Things written
with them in mind: no OS symlinks (symlink, submodule and case-collision fixtures go straight into the git index),
`nm` probed as `llvm-nm`, `nm --defined-only`, `nm -gU`, link `m` only under the gnu/darwin target tables, and a skip
with a printed note when clang or nm is missing.

## Size (non-blank, non-comment lines of Python)

| Part | Lines |
|---|---|
| `common2.py` (shared: strict TOML ~230, git-object store and hashing ~270, C validation and build ~190, dialect gate, CLI) | 857 |
| B1+ `b1plus/tool.py` | 324 |
| B2+ `b2plus/tool.py` | 301 |
| loop 1 for comparison: `common.py` 381, B1 96, B2 95, B3 191 | |
| scenarios: `world2.py` 87, `run_scenarios2.py` 662, `toml_conformance.py` 70 | 819 |

Per tool with shared code counted once: B1+ 1181, B2+ 1158 (B1 was 477, B2 476). The fixes cost about 2.4x: most of it is
shared (hashing from git objects, validated C data, strict TOML), not specific to MVS or pins. B1+ and B2+ are within
2% of each other, so size does not separate them.

## What was hard

- **Hashing without a checkout.** `git fetch` of one tag into a bare repo, `ls-tree -r -z`, `cat-file --batch`; the
  cache and vendor then hold exactly the hashed set, so "files outside the set" is checkable by a plain directory walk.
  The `text=auto` fixture needed a real CRLF checkout to prove it is not vacuous (the scenario asserts the checkout differs
  from the blob). `GIT_CONFIG_COUNT` carries `core.autocrlf=true` and `core.eol=crlf` into the tool; the tool no longer
  forces `core.autocrlf=false`, because it never checks anything out.
- **Chained trust makes B1+ publish in dependency order,** like B2: a package's `deps.sum` needs its dependencies'
  hashes, so a dependency cannot be re-tagged without re-tagging dependents (that is the point). A package that has
  requirements but no `deps.sum` is refused.
- **Full build list in the root (B1+).** `build` needs only the listed versions, so superseded versions are no longer
  fetched or vendored; `tidy` (and so `add`/`update`) still reads superseded versions' requirements to compute the list,
  and checks them against the requirer's `deps.sum` without recording them.
- **TOML.** A character-level parser with line numbers was simpler than the old line-based one, and it is what made
  multi-line arrays, literal strings and the duplicate-table rule cheap. The writer escapes control characters.
- **C.** Per-ABI tables, validation, `-I`/`-D`/`-l` assembly and symbol checking are ~190 lines. COFF objects carry
  absolute symbols (`@feat.00`, `_fltused`) that look exported to `nm`; they are skipped by name.
- **Replace plus chained trust.** A replaced path cannot be checked against its requirers' recorded hashes (the fork's
  files differ on purpose), so the root records the fork's own hash (`deps.sum` in B1+, the root pin in B2+).

## Where this contradicts or refines the review

- **No silent downgrade, but also no downgrade.** With the whole list in the root manifest, a listed `C v1.4.0` acts as a
  requirement, so in S4 it stays (C v1.4.0 and C/v2 coexist). The review's fix assumed a downgrade would be printed; here
  it cannot happen without an explicit `add path <older>` (printed as `downgrade`, scenario N8).
- **The age rule stays defeatable.** A forged date on an ordinary descendant commit is accepted (N4b); the descent check
  stops only rewritten history. The tool prints that the age rule is a convenience.
- **B2+ `update` is atomic.** S4 now fails at `update B` and writes nothing (loop 1 failed at `build`).
- **B2+ still cannot build S4,** by design; B1+ can for pure modules and refuses it for a C wrapper (N11).
- **Commands typed:** S2 4 (B1+) against 6 (B2+); S3 6 against 8. Error recovery for B2+ is one command because the
  message prints the exact `tidy --yes` to type.

# D9 step 3 notes: three dependency-manager spikes

Run `./run.sh` (bash, python3 >= 3.9, git). Output is in `results-loop1.md`. Windows and macOS were not run locally; the
code uses `Path.as_uri()` (gives `file:///C:/...`), `core.autocrlf=false`, LF-only writes and a chmod-retry `rmtree`
for the read-only git objects Windows keeps.

## Size (non-blank, non-comment lines of Python)

| Part | Lines |
|---|---|
| `common.py` (shared: TOML subset ~100, git store and cache ~110, hashing, vendor, checks, CLI) | 381 |
| B1 `b1_mvs/tool.py` | 96 |
| B2 `b2_pins/tool.py` | 95 |
| B3 `b3_semver/tool.py` | 191 |
| scenarios (`world.py` 57, `run_scenarios.py` 278) | 335 |

Per tool, counting the shared code once, B1 and B2 are about the same size; B3 is about twice as large (ranges,
backtracking resolver, lock staleness check).

## Manifest format: a TOML subset

Chosen: tables, `key = value`, strings, ints, bools, single-line string arrays, comments. No arrays of tables, no
inline tables, no multi-line values. The parser and writer are about 100 lines. Why not JSON: no comments, and the
files are read and diffed by people. Why not a language literal (S5): it would need the const evaluator before the
tool can run; it can replace this format later because nothing else depends on the syntax. Quoted keys keep
paths with `/` readable: `"host/ann/json" = "v1.4.0"`. The same format is used for the manifest, `deps.sum` and
`deps.lock`, so there is one parser.

## What was awkward

- **B1.** Pure MVS reads the requirements of every version it meets, including versions that lose to a newer one.
  Those versions must be fetched, hashed (so `deps.sum` has 4 lines for a 2-dependency app) and vendored too. Go
  hashes only their manifest; that is an extra rule we did not build. `update C` on a transitive dependency has to write C
  into the root `requires`, so the manifest grows. `build` records missing hashes on first use (trust on first use).
- **B2.** Every package's manifest holds the URL and hash of each dependency, so a package must be hashed before
  anything that depends on it can be published (the scenario builder has to publish in dependency order). The root
  manifest is the largest (451 to 650 bytes, because of URLs and hashes). A diamond costs the user 2 extra commands
  (one `add` pin, one `build`), and every transitive update (S3) also becomes a root pin. `add` does not check for
  conflicts; only `build` does. Without root pins overriding same-major conflicts the tool would be unusable, so this
  rule was added (the root pin wins; a different major is always an error).
- **B3.** The resolver is the largest piece. Details that cost lines: `0.x` compatibility, `~` and `=` ranges, lock
  staleness, preferring locked versions, and error text after backtracking. It prints only the last failed
  constraint set, which is not always the one a user would blame.
- **All.** Tag dates: annotated tags carry a tagger date; lightweight tags fall back to the commit date. A host API
  would be a better source in a real tool. A warm cache hides a moved tag by design (cached copies are immutable and
  checked against the recorded hash); detection needs a cold cache, which is what CI has, or a changed vendor copy.
  The typo suggestion only knows names already in the cache or vendor, so on a fresh machine there is none.

## Surprises

- S4 (B moves to C v2): B1 builds `host/bob/c v1.2.0` and `host/bob/c/v2 v2.0.0`. C drops from v1.4.0 to v1.2.0
  because nobody asks for v1.4.0 any more. That is correct MVS but may surprise people. B3 keeps C 1.4.0 because the
  lock is sticky. B2 rejects the program.
- B2 with a root pin for a transitive dependency still reports a different-major conflict, listing the root pin as
  one of the paths; the message is clear but there is no fix a pin can supply.
- B1 refused the second C-library declaration already at `add` (resolve runs the check); B3 was changed to do the same;
  B2 reports it at `build`.

## Which is simplest for a beginner (factual)

- Commands to the same outcome: B1 = B3 in S1 to S4 and S10. B2 needs 2 more commands on a diamond and 2 more per
  transitive update, because the user writes the pins.
- Concepts the user must learn: B1 has "minimum version" and "`/v2` means a different module"; B2 has "one version
  per package, pin it yourself"; B3 has "version ranges" and "lock file" (two files to commit and keep in sync).
- Files in the project: B1 and B3 have manifest plus a generated file; B2 has only the manifest (hashes inside it).
- Error text: B2's diamond error names both dependency paths and prints the command to run; B1 and B3 never raise it
  because they resolve the diamond themselves. B3's failure text (no version satisfies the ranges) names the
  requirers; B1 has no version-conflict errors at all.
- Code to maintain: B2 is the smallest and has the fewest behaviours; B3 is the largest.
