# D9 ideas (Opus, 2026-11-14)

There are two axes. **Dependencies** (modules, manifest, versions) are hard to reverse once an ecosystem exists. The
**toolchain** (how users get clang) is cheaper to change and is decided alongside, with its own spike.

## Dependencies: sane

- **S1 Go-like.**
  - A directory is a module; imports are repo paths (`use github.com/ann/json`).
  - Versions are git tags; MVS selection; a new major is a new path (`/v2`).
  - A `deps.sum` file records a content hash per selected version; `vendor/` is optional.
- **S2 Cargo-like.** Semver ranges in the manifest, a resolver, and a lockfile with hashes. Dependencies are git URLs,
  and there is no registry.
- **S3 Zig-like exact pins.**
  - The manifest lists each direct dependency as URL plus tag plus content hash.
  - The program has one version per package: a diamond conflict is an error naming both paths, and the user pins one.
- **S4 Vendored only (Hare).** `get` copies the source into `vendor/` and records a hash. The build never touches the
  network.
- **S5 S1 with the manifest written in the language,** as a data literal using ADR-0007 clauses (`build.p3`),
  evaluated by a restricted const evaluator that allows no calls, no I/O and no loops beyond clauses.
- **S6 S3 with automatic tidy.** The tool suggests the highest pinned version in a diamond, and the user accepts it.

## Dependencies: crazy

- **X1 No manifest.** The version lives in the import: `use github.com/ann/json at v1.4.2`, and the tool writes only
  hashes.
- **X2 Git submodules as the dependency system.**
- **X3 Content-addressed definitions** (Unison): every function is identified by its hash.
- **X4 A curated central list** of approved packages, reviewed by people.

## Toolchain: options

- **T1 System clang everywhere,** with a preflight check that names the missing pieces (on Windows, the VS Build
  Tools, 6–7 GB).
- **T2 System clang on Linux and macOS (Xcode CLT), plus a pinned llvm-mingw on Windows,** downloaded on first use
  (182 MB, no MSVC).
- **T3 `zig cc` everywhere** (57–100 MB, pre-1.0, UBSan on by default; macOS still needs the SDK).
- **T4 A bundled, trimmed LLVM** (100–300 MB per OS; we become the toolchain maintainers).

## Combinations

- **S1 + S4 (MVS plus vendor-by-default).** This is the reproducibility kernel adopted by every finalist: `vendor/` is
  optional, but the hash file is mandatory.
- **S3 + S5.** Exact pins in a data-literal manifest.
