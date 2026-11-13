#!/usr/bin/env bash
# K3 spike: Rust compiler -> C -> clang. Run from anywhere.
set -u
cd "$(dirname "$0")"
OS=$(uname -s)
EXE=""; WIN=0; MAC=0
case "$OS" in MINGW*|MSYS*|CYGWIN*) WIN=1; EXE=".exe"; export PATH="$PATH:/c/Program Files/LLVM/bin";; Darwin) MAC=1;; esac
command -v clang >/dev/null || { echo "clang not found"; exit 1; }
mkdir -p build
OUT=$PWD/build
fail() { echo "FAIL: $*"; exit 1; }

# 1. build the compiler (rustc directly, no crates)
S=$(date +%s)
rustc -O --edition 2021 src/main.rs -o "build/k3c$EXE" || fail "compiler build"
echo "compiler build: $(( $(date +%s) - S ))s"

# 2. compile and run spike.p3 (debug info on; on Windows k3c adds -gcodeview, lld)
cp ../spike.p3 build/spike.p3
( cd build && ./k3c$EXE spike.p3 -o spike$EXE ) || fail "k3c"
( cd build && ./spike$EXE > actual.txt ) || fail "spike run"
diff -u ../expected.txt build/actual.txt || fail "output differs from expected.txt"
echo "output matches expected.txt"

# 3. debugger (G8): break at the statement inside area, show p
LINE=$(grep -n 'total += p.x \* p.y' ../spike.p3 | head -1 | cut -d: -f1)
if [ "$WIN" = 1 ]; then
  if command -v cdb >/dev/null; then
    ( cd build && cdb -c "bp \`spike.p3:$LINE\`; g; dx p; q" spike.exe ) 2>&1 | tee build/debug.txt
  elif command -v llvm-pdbutil >/dev/null; then
    ( cd build && llvm-pdbutil dump -types -lines spike.pdb ) > build/debug.txt 2>&1
    grep -E 'Point|spike\.p3' build/debug.txt | head -20
    grep -q 'Point' build/debug.txt && grep -q 'spike.p3' build/debug.txt || fail "PDB lacks Point or spike.p3 lines"
  else echo "SKIP debug (cdb and llvm-pdbutil missing)"; fi
elif [ "$MAC" = 1 ]; then
  if command -v lldb >/dev/null; then
    ( cd build && lldb -b -o "breakpoint set -f spike.p3 -l $LINE" -o run -o "frame variable p" -o "p p" ./spike ) 2>&1 | tee build/debug.txt
    grep -q 'x = 3' build/debug.txt && grep -q 'y = 4' build/debug.txt || fail "lldb did not show p.x=3 p.y=4"
  else echo "SKIP debug (lldb missing)"; fi
else
  if command -v gdb >/dev/null; then
    ( cd build && gdb -batch -ex "break spike.p3:$LINE" -ex run -ex 'print p' -ex 'print p.x' -ex 'info locals' -ex bt ./spike ) 2>&1 | tee build/debug.txt
    grep -q 'x = 3' build/debug.txt && grep -q 'y = 4' build/debug.txt || fail "gdb did not show p.x=3 p.y=4"
  else echo "SKIP debug (gdb missing)"; fi
fi

# 4. coverage (G9)
COV=llvm-cov; PROF=llvm-profdata
if ! command -v $COV >/dev/null || ! command -v $PROF >/dev/null; then
  if [ "$MAC" = 1 ] && command -v xcrun >/dev/null; then COV="xcrun llvm-cov"; PROF="xcrun llvm-profdata"; fi
fi
if $COV --version >/dev/null 2>&1 && $PROF --version >/dev/null 2>&1; then
  ( cd build && ./k3c$EXE --coverage spike.p3 -o spike_cov$EXE && \
    LLVM_PROFILE_FILE=spike.profraw ./spike_cov$EXE >/dev/null && \
    $PROF merge -sparse spike.profraw -o spike.profdata && \
    $COV report ./spike_cov$EXE -instr-profile=spike.profdata spike_cov.c && \
    $COV show ./spike_cov$EXE -instr-profile=spike.profdata spike_cov.c ) > build/coverage.txt 2>&1 || { cat build/coverage.txt; fail "coverage"; }
  cat build/coverage.txt
else echo "SKIP coverage (llvm-cov/llvm-profdata missing)"; fi

echo "k3 spike OK"
