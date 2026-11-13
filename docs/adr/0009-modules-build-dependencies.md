# ADR-0009: Modules, build and dependencies

- **Status:** Accepted
- **Date:** 2026-11-14
- **Tier:** Full (see `docs/PROCESS.md`)
- **Examples:** `docs/examples/build/deps` (B1+ in `b1plus/`; rival B2+ in `b2plus/`; loop-1 records `b1_mvs/`, `b2_pins/`, `b3_semver/`; scenarios in `scenarios/`)
- **Decided by:** Claude (ruling R7). John may veto by opening an issue.

## Context

G7 asks for "build and dependency management tools; third party libraries are just GitHub repos (maybe eventually not
just GitHub)". Earlier decisions set constraints:
- whole-program checks see every linked module (ADR-0003, ADR-0005);
- only the stdlib and `extras` may use the generic dialect (ADR-0002);
- programs are compiled to C by clang (ADR-0008);
- renaming a parameter breaks callers (ADR-0006 amendment 1).

Research (`0009-research/research-modules.md`) found:
- executable build files needed sandboxes (Swift) or were replaced (Python);
- install scripts spread worms (npm);
- Go's MVS needs no solver;
- hashes must pin content, with the URL treated only as a mirror (Zig).

## Charter

| Goal / problem | Effect | Why |
|---|---|---|
| G7 | serves | Dependencies are git repos named by path; `deps add/update/vendor/tidy/verify`; works offline from `vendor/` or the cache |
| G1 (R6) | serves | One data file lists every project in the build, with versions; one hash file; no code runs at fetch or build time |
| R9 | serves | Hashes come from git objects, so a checkout with CRLF settings verifies identically; the same scenarios pass on three OSes |
| G3 | serves | The generic dialect is accepted only under the toolchain's own directory |
| P-C | serves | C libraries are declared as validated data and compiled by clang with per-ABI keys; duplicate C symbols are refused |
| G7 install | strains | The interim toolchain is the system clang, which means Visual Studio Build Tools (6–7 GB) on Windows. See "Toolchain". |

## Criteria

From `0009-research/criteria.md`, written before the options.

**Gates:** G3 (the dialect), R9, and the whole-program checks.

| Criterion | Weight |
|---|---|
| Simplicity | 20 |
| Reproducibility and security | 20 |
| Transparency | 15 |
| Install story | 15 |
| FFI | 10 |
| Ecosystem scale | 10 |
| Implementation risk | 10 |

## Options considered

There were 10 dependency ideas and 4 toolchain ideas (`0009-research/ideas.md`, `analysis.md`).
- **Ruled out:**
  - vendor-only;
  - versions written in imports;
  - git submodules;
  - content-addressed code;
  - a curated list;
  - a bundled LLVM.
- **Finalists:**
  - **B1:** Go-like MVS.
  - **B2:** Zig-like exact pins.
  - **B3:** Cargo-like semver ranges plus a lockfile.
- **Loop 2:** B1+ and B2+, with the review's fixes.

## What the real examples taught

See `0009-research/lessons-and-scores.md`, `review-b1.md`, `docs/examples/build/deps/results.md` and
`results-loop1.md`. They are stdlib-Python prototypes over local git repos, run in CI on three OSes.

- **Loop 1.** All three passed the 10 basic scenarios. B2 needed manual pins on diamonds and couldn't build a major
  break. B3 was twice the code.
- **The review (Fable 5.2)** broke shared claims:
  - C sources weren't hashed;
  - checkout hashes differed under CRLF settings;
  - an emptied hash file was silently re-trusted;
  - C declarations accepted `../../etc/passwd` and `-fplugin`;
  - a forged tag date beat the 24-hour rule;
  - forks and monorepos failed;
  - the dialect gate didn't exist;
  - the "TOML subset" misread `"C:\new"`.
- **Loop 2.** B1+ and B2+ fix all of these. 22 new scenarios include every false accept as a regression, plus 39 TOML
  conformance cases. A real 3-file C library is compiled and linked with per-ABI keys on Linux, Windows (MSVC) and
  macOS. Remaining differences:
  - **Major break:** B1+ builds it; B2+ refuses it, and also refuses any `v0` diamond.
  - **Diamonds and transitive upgrades:** B1+ needs 4 and 6 commands, against B2+'s 6 and 8.
  - **Code size:** B1+ is 1181 lines and B2+ 1158, with shared code counted once.
  - **Known limit for both:** a forged date on an ordinary descendant commit still beats the age rule, and the tool
    says so.

## Decision

**Adopt B1+.** The rules a programmer learns:

1. **Words.** A **module** is a directory of source files (ADR-0005 visibility: `pub`, otherwise module-private). A
   **project** is a versioned git repo holding one or more modules. Its root has `project.toml`.
2. **Imports name paths.** `use github.com/ann/json` or `use github.com/ann/tools/csv`. An import resolves by the
   longest prefix against the projects in `project.toml`, with no network probing.
   - **Reserved paths:** those whose first segment has no dot (`std`, `extras`) belong to the toolchain.
   - **Coexisting majors:** a new major version is a new path (`…/json/v2`). Both majors may be in one build only if
     neither declares a C library.
   - **Separate types:** `json.Value` and `json/v2.Value` are different types, and errors print full paths. Bridging
     impls live in v2 (ADR-0005 rule 17).
   - **State:** module state is per major.
   - **Aliases:** `use …/json/v2 as json2`.
3. **`project.toml`** (strict TOML 1.0 subset; anything unsupported is rejected, never misread):
   - `name`, and `lang = "x.y"` (the minimum toolchain);
   - `[requires]`, which lists **every** project in the build with its version, direct and indirect (indirect ones
     marked);
   - `[c.<lib>]` declarations;
   - a root-only `[replace]`.

   Nothing changes version without a visible diff in this file.
4. **Version selection:** Minimal Version Selection over git tags (`vMAJOR.MINOR.PATCH`). `update` prints every
   change, including downgrades. The `v0` minors are treated as incompatible (warning). `deps api-diff` compares `pub`
   signatures, including parameter names, and `update` warns when a same-major version removes or renames anything.
5. **`deps.sum`** records, for every project version, the commit SHA and a SHA-256 over the git *objects* of its
   declared files.
   - **Rejected outright:** symlinks, case-fold collisions and submodules.
   - **First fetch:** checked against the hash recorded by the project that requires it (chained trust).
   - **`build` is frozen:** it never writes `deps.sum`, and a missing or extra entry is an error. Only `add`,
     `update` and `tidy` write it.
   - **`verify`:** refetches everything and rechecks.
6. **Only hashed files are read.** The compiler and clang read only files in a project's hashed set. Extra files in
   `vendor/` or the cache are an error. `vendor/` is used automatically when present.
7. **No code runs at fetch or build time.**
   - **C libraries are data:** `sources`, `include`, `defines`, and `link` (library names only); per-ABI tables
     (`target.msvc`, `target.gnu`, `target.darwin`); relative in-project paths.
   - **One copy per symbol:** a duplicate exported C symbol at link is refused, naming both projects.
   - **Out of scope:** libraries that need `configure` or generated headers. Commit the generated files.
8. **`update` guards.** It requires the new tag's commit to descend from the recorded one (`--force` to override).
   Tags younger than 24 hours are skipped as a convenience (`--allow-new`); this is not a security claim.
9. **`[replace]` applies only in the root project** (a fork URL or a local directory, the latter flagged as
   unhashed). It is refused for reserved paths.
10. **The dialect gate.** `std` and `extras` ship with the toolchain. The generic dialect is accepted only in files
    under the toolchain directory; anything else is refused, including `replace` or `vendor` of reserved paths.
11. **Commands:** `new`, `build`, `run`, `test`, `deps add | update | tidy | vendor | verify | api-diff`. `add`
    shows the owner, the first-tag date and the tag count, to help spot typosquats.

### Toolchain (interim)

The system clang is the v1 default:
- **Linux:** `clang` from the distro;
- **macOS:** `xcode-select --install`;
- **Windows:** the LLVM installer plus the VS Build Tools.

A preflight check (`doctor`) names every missing piece. The spike that would test llvm-mingw or `zig cc` as a
no-Visual-Studio option on Windows was blocked by the session's permissions (see STATE). **Revisit when John allows
the download.** The Windows ABI already appears in manifests (`target.msvc`), so switching to the GNU ABI later
would affect manifest keys.

### Scores (`0009-research/scores.py`)

| Option | Simple | Repro | Transp | Install | FFI | Eco | Impl | Total |
|---|---|---|---|---|---|---|---|---|
| **B1+ (loop 2)** | 3.5 | 4.5 | 4.5 | 2.5 | 4 | 4 | 3.5 | **76** |
| B2+ (loop 2) | 3.5 | 4.5 | 4.5 | 2.5 | 4 | 2.5 | 3.5 | 73 |
| B3 (review) | 3 | 3.5 | 3.5 | 2.5 | 2.5 | 3.5 | 3 | 62 |

**The result is a tie** (a gap of 3), and equal at 77 with transparency weighted 25 and ecosystem 0. The examples
break it, as PROCESS says:
- B1+ builds the major-break scenario, which B2+ refuses;
- B1+ needs fewer commands on diamonds and upgrades.

Neither option is more reversible than the other, because old manifests are read forever in both.

## Consequences

**Easier:**
- One file shows everything in the build.
- Reproducible across OSes and offline.
- Forks and monorepos work.
- C libraries need no scripts.
- Tampering and rewritten history are caught.

**Harder:**
- **Publish order:** projects must be published in dependency order, because each `deps.sum` is chained.
- **Majors:** they matter more, because parameter names are API; `api-diff` helps.
- **Two majors with C:** they can't coexist.
- **Windows:** users need the VS Build Tools until the toolchain is revisited.

**Ruled out:**
- build scripts;
- install hooks;
- semver range solving;
- a registry in v1;
- per-dependency `replace`.

**Passed on:**
- **M7:** implement `deps` in the Rust toolchain from `b1plus/` and `common2.py`, with every scenario as a test.
- **D11:** `test` and `cover` commands.
- **D12:** the tool's name.

## Syntax budget impact

`use … as alias` (`as` is already a contextual word in ADR-0006). There are no new keywords.

## Adversarial review log

| Review | Findings | Outcome |
|---|---|---|
| `0009-research/review-b1.md` (Fable 5.2) | F1 hash coverage; F2 per-OS hashes; F3 majors undefined; 1 the age rule; 2 trust on first use; 3 C validation; 4 silent downgrade; 5 renames and majors; 6 identity equals location; 7 the dialect gate; 8 the TOML dialect; 9 toolchain; minor 10–14 | All fixed in B1+ and B2+ (loop 2), with regressions. Majors with C refused. The age rule kept as a convenience only. Toolchain recorded as interim. |
