# D9 research: modules, build files, dependencies (Sonnet researcher, 2026-11-14; condensed)

[unverified] marks claims without a fetched source. The Elm, Nimble and Odin collection details are weak.

## By system

- **Go** (https://go.dev/ref/mod):
  - **Modules and imports.** A directory is a package; a module is a tree with `go.mod`; import paths are repo
    URLs.
  - **`internal/`** limits imports by path (https://go.dev/doc/go1.4#internalpackages).
  - **MVS** (https://research.swtch.com/vgo-mvs): it picks the highest of the declared minimums, is deterministic,
    runs in linear time, needs no lockfile and never upgrades unasked.
  - **Major versions** change the path (`/v2`, https://go.dev/blog/versioning-proposal), so two majors can coexist
    and diamonds of incompatible majors go away. SAT-style resolution has many valid answers.
  - **Integrity and mirrors.** `go.sum` hashes are trust-on-first-use; the sumdb (a transparency log) and a proxy
    survive deletion upstream (https://go.dev/blog/module-mirror-launch).
  - **`vendor/`** is used automatically when present.
- **Cargo:**
  - **Features** unify across the graph and must be additive
    (https://doc.rust-lang.org/cargo/reference/features.html).
  - **Resolution.** A backtracking resolver gives one version per semver-compatible range, and duplicate majors make
    distinct types (https://doc.rust-lang.org/cargo/reference/resolver.html).
  - **`links`:** one crate per native library.
  - **`build.rs`** runs arbitrary code and is the C-building path
    (https://doc.rust-lang.org/cargo/reference/build-scripts.html).
  - **Yank** is not a security tool.
  - **Typosquatting:** `rustdecimal` (https://blog.rust-lang.org/2022/05/10/malicious-crate-rustdecimal/).
- **Zig:**
  - `build.zig` is code (https://zig.guide/build-system/zig-build/).
  - `build.zig.zon` is data: URL plus content hash over the declared `paths`, where the hash is the truth and the URL
    a mirror. A `fingerprint` gives each package its identity. There is no registry
    (https://github.com/ziglang/zig/blob/master/doc/build.zig.zon.md).
- **SwiftPM:**
  - `Package.swift` is code that has to be sandboxed
    (https://docs.swift.org/package-manager/PackageDescription/PackageDescription.html).
  - Dependencies are git URLs plus semver, recorded in `Package.resolved`. There are system-library and binary
    targets.
- **Deno:**
  - It started with URL imports: long URLs, no semver, duplicates, and the least reliable host decided reliability
    (https://deno.com/blog/http-imports). It added the JSR registry and import maps.
  - `deno.lock` holds hashes. Its guidance: a frozen lockfile in CI and a 24-hour minimum age for new versions
    (https://docs.deno.com/runtime/packages/supply_chain/).
- **Odin and Hare:**
  - **Odin:** a directory is a package, imported as `collection:path` (https://odin-lang.org/docs/overview/).
  - **Hare:** a directory is a module, found through `HAREPATH`; it has no package manager and relies on distros or
    vendoring (https://harelang.org/documentation/usage/modules.html).
- **npm and Python:**
  - **npm:** the lockfile records integrity hashes (https://docs.npmjs.com/cli/v10/configuring-npm/package-lock-json).
    Install scripts (https://docs.npmjs.com/cli/v10/using-npm/scripts) spread the Shai-Hulud worm (2025), and
    left-pad (2016) broke builds by unpublishing.
  - **Python:** PEP 517 moved from `setup.py` code to declarative `pyproject.toml` (https://peps.python.org/pep-0517/).

## Lessons

1. **The manifest is data.** Executable build files need sandboxes and are slow and unauditable.
2. **Pin content, not names:** a hash over the declared files, with the URL as a mirror.
3. **MVS plus "a new major means a new path"** needs no solver and has a clean answer for diamonds.
4. **Whole-program and FFI constraints:** one copy per native library, and decide early whether two majors may
   coexist in one link.
5. **Git alone isn't an availability story.** Plan for vendoring and a cache.
6. **Forbid install-time code.** Build C dependencies from declared data. Consider a minimum age for new versions.
