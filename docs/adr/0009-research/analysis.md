# D9 analysis (Opus)

## Ruled out

| Idea | Why |
|---|---|
| S4 vendor-only | Every project carries copies of its dependencies; updates are manual. Kept as an option (`vendor/`). |
| S6 | It is S3 with a convenience; folded into S3 |
| X1 version in imports | The version is repeated in every file that imports, and a diamond is unreadable |
| X2 submodules | No hashes over the content of a declared file set; a poor experience for beginners |
| X3 content-addressed | A new paradigm; it fails G1 |
| X4 curated list | Fails G7 ("just GitHub repos") |
| T4 bundled LLVM | Makes us maintain a toolchain on three OSes |

## Kernels in every finalist

- **Directory = module.** Visibility follows ADR-0005 (`pub`), plus Go's `internal/` path rule for repo-private
  modules.
- **The manifest is data** (no code at fetch or build time). C libraries are declared as data: sources, flags, link
  libraries.
- **A mandatory hash file** over a declared file set. The URL is only a mirror. `vendor/` is optional and used
  automatically.
- **One copy per C library per program** (Cargo's `links` lesson). The generic dialect is allowed only in `std` and
  `extras` (ADR-0002).
- **New versions:** a minimum age of 24 hours before `update` picks one up (Deno), overridable.

## Finalists (step 3 builds a resolver prototype for each and runs shared scenarios)

| | **B1 = S1 (+S5 syntax)** | **B2 = S3** | **B3 = S2** |
|---|---|---|---|
| Version selection | MVS over tags | exact pins, chosen by the user | semver ranges plus a resolver |
| Two majors in one program | yes, by path (`/v2`) | no; error | yes, if the ranges differ by major |
| Lockfile | `deps.sum` (hashes only) | the hashes live in the manifest | `deps.lock` (versions plus hashes) |

**Toolchain finalists:** T1 and T2 (spike llvm-mingw on the Windows runner: cdb, coverage, crews), and T3 (spike
`zig cc`).

**Shared scenarios:**
- an app with a diamond;
- an upgrade of a transitive dependency;
- a major-version break;
- a deleted upstream repo (vendor and cache);
- a tampered tag (hash mismatch);
- a C library dependency;
- an offline build.

They use local bare git repos created by the test, run in CI on three OSes.
