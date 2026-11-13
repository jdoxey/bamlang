# D9 research: toolchain distribution and the C compiler (Sonnet researcher, 2026-11-14; condensed)

[unverified] marks claims without a fetched source.

## By system

- **Zig `zig cc`** (https://andrewkelley.me/post/zig-cc-powerful-drop-in-replacement-gcc-clang.html):
  - bundles clang and ships libc *source* (musl, glibc `.abilist` stubs, mingw-w64), built lazily and cached;
  - 0.17.1 downloads (https://ziglang.org/download/index.json): Linux 57 MB, Windows 100 MB, macOS 54 MB;
  - no MSVC on Windows (the GNU ABI);
  - macOS still needs an Apple SDK for frameworks (https://github.com/rust-cross/cargo-zigbuild);
  - UBSan is on by default (https://github.com/uber/hermetic_cc_toolchain), and Zig is pre-1.0;
  - the profile runtime for coverage is [unverified].
- **Rust on Windows** needs the MSVC build tools plus the Windows SDK
  (https://rust-lang.github.io/rustup/installation/windows-msvc.html), about 6–7 GB
  (https://users.rust-lang.org/t/installing-microsoft-c-build-tools/133170).
- **Go** needs no C toolchain unless cgo is used. On Windows, cgo's "gcc not found" is a common failure
  (https://go.dev/wiki/WindowsCrossCompiling).
- **Odin** requires MSVC plus the SDK on Windows, the Xcode CLT on macOS, and clang/LLVM on Linux
  (https://odin-lang.org/docs/install/).
- **Crystal on Windows** is still a preview and needs VS build tools or MSYS2 (https://crystal-lang.org/install/on_windows/).
- **V** bundles tcc for development builds and uses clang, gcc or MSVC for `-prod` (https://github.com/vlang/v).
- **The pattern:** every language that leaves the C toolchain to the user gets "install Visual Studio" friction on
  Windows.
- **llvm-mingw** (https://github.com/mstorsjo/llvm-mingw, LLVM 23.1.5):
  - Windows zip 182 MiB;
  - the UCRT and GNU ABI, so no MSVC or SDK;
  - PDBs via `-gcodeview -g -Wl,--pdb=`;
  - the profile runtime is [unverified];
  - whether cdb loads its PDBs is untested.
- **Full LLVM release assets** are 0.9–1.9 GB (https://github.com/llvm/llvm-project/releases/latest). The licence is
  Apache-2.0 with the LLVM exception (https://llvm.org/LICENSE.txt). A trimmed bundle is maybe 100–300 MB
  [unverified], and makes us a toolchain maintainer.
- **The macOS SDK can't be redistributed** (https://developer.apple.com/forums/thread/114179 declined to interpret
  the terms), so require `xcode-select --install`.
- **tcc** has stabs debug info only, no coverage, and weak x64 Windows support (https://bellard.org/tcc/tcc-doc.html).
  It fails G8 and G9.

## Risks

1. Windows: system clang means a 6–7 GB Visual Studio install. llvm-mingw avoids that, but its cdb support and
   coverage runtime are unproven.
2. macOS always needs the Xcode CLT.
3. Coverage needs the matching `libclang_rt.profile` plus `llvm-cov`/`llvm-profdata`, so version skew with a system
   clang is a risk.
4. Bundling full LLVM is too big. A trimmed one is a maintenance burden.
5. Zig's differences from stock clang would break ADR-0008's "clang everywhere".

**Researcher's lean:** system clang with a preflight check, plus a pinned llvm-mingw downloaded on demand on Windows.
Spike llvm-mingw's PDB and coverage support, and zig cc. Drop tcc.
