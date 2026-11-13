# D9 step 3 lessons and pre-review scores (Opus)

Example: `docs/examples/build/deps/` holds three prototype tools (stdlib Python) over ten shared scenarios that use
local git repos. CI 43493656506 is green on Linux, Windows Git Bash and macOS. Results are in `results.md`.

## What the prototypes taught

- **Everything tied except the diamond and the major break.** All three handled the simple case, upgrades, a deleted
  upstream (cache or vendor), tampering (hash mismatch), offline builds, typos, the 24-hour age rule, and a C library
  declared twice.
- **B2 (exact pins)** needs a manual pin on every diamond and every transitive update (2 more commands each). It
  can't build S4 at all (B moves to C v2 while A stays on v1), and packages must be published in dependency order,
  because manifests embed their dependencies' hashes.
- **B1 (MVS)** builds S4 with C v1 and C/v2 side by side. Surprise: when B leaves v1, MVS *drops* C v1.4 back to v1.2,
  the highest remaining minimum. That is correct but surprising. MVS also fetches the manifests of superseded versions,
  so `deps.sum` has 4 lines for 2 dependencies.
- **B3 (semver)** is twice B1's code (191 lines, against 96 and 95), and on failure the backtracking resolver reports
  only the last conflict.
- **One TOML subset** serves the manifest and the hash and lock files, so there is one parser.

## Scores (`scores.py`)

| Option | Simple | Repro | Transp | Install | FFI | Eco | Impl | Total |
|---|---|---|---|---|---|---|---|---|
| **B1 MVS** | 4 | 5 | 4 | 3 | 4 | 4 | 4.5 | **82** |
| B2 exact pins | 3.5 | 5 | 5 | 3 | 3.5 | 2 | 4.5 | 78 |
| B3 semver | 3.5 | 4 | 3.5 | 3 | 4 | 4.5 | 3 | 72.5 |

**B1 and B2 tie** (a gap of 4). The examples break it for B1, because B2 can't build the major-break scenario and
costs extra commands per diamond. Install is scored equal because the Windows toolchain spike is blocked (STATE).

## Loop 2 (B1+ against B2+)

- **Scores:** 76 against 73, a tie, broken by the examples (S4, and the number of commands). Details are in ADR-0009.
- **macOS:** Mach-O prefixes C symbols with `_`, so the duplicate-symbol check failed there until names were
  normalised (CI 43498805004). Platform naming belongs in the toolchain layer, not in the manifest.
