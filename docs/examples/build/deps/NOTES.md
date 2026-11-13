# D9 step 3 notes: three dependency-manager spikes

Run `./run.sh` (bash, python3 >= 3.9, git). Output is in `results.md`. Windows and macOS were not run locally; the
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
