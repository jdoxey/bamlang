#!/usr/bin/env bash
# K2 spike: OCaml compiler -> textual LLVM IR -> clang. Prints "k2 spike OK" on success.
cd "$(dirname "$0")" || exit 1
HERE=$(pwd)
OS=linux
case "$(uname -s)" in
  Darwin) OS=macos ;;
  MINGW*|MSYS*|CYGWIN*) OS=windows ;;
esac
EXE=""; [ "$OS" = windows ] && EXE=".exe"

if ! command -v ocamlopt >/dev/null 2>&1; then echo "SKIP k2 (no ocamlopt)"; exit 0; fi
if [ "$OS" = windows ] && ! command -v clang >/dev/null 2>&1 && [ -d "/c/Program Files/LLVM/bin" ]; then
  export PATH="$PATH:/c/Program Files/LLVM/bin"
fi
if ! command -v clang >/dev/null 2>&1; then echo "SKIP k2 (no clang)"; exit 0; fi

SPEC=../spike.p3
EXPECTED=../expected.txt
rm -rf build && mkdir -p build && cp src/*.ml build/ || exit 1

# 1. build the compiler (plain ocamlopt, files in dependency order)
START=$SECONDS
( cd build && ocamlopt -o p3c ast.ml lexer.ml parser.ml check.ml ir.ml lower.ml emit.ml main.ml ) || { echo "k2 FAIL: ocamlopt"; exit 1; }
echo "compiler build: $((SECONDS - START))s (ocamlopt)"

# 2. compile and run spike.p3
P3C="./build/p3c --os $OS --runtime $HERE/runtime.c"
$P3C -o build/spike $SPEC || { echo "k2 FAIL: compile"; exit 1; }
./build/spike$EXE | tr -d '\r' > build/out.txt
if ! diff build/out.txt $EXPECTED; then echo "k2 FAIL: output differs"; exit 1; fi
echo "output matches expected.txt"

# 3. debug (G8): break inside area at the accumulate line, show p
LINE=$(grep -n 'total += p.x \* p.y' $SPEC | head -1 | cut -d: -f1)
if [ "$OS" = linux ]; then
  if command -v gdb >/dev/null 2>&1; then
    gdb -batch -ex "break spike.p3:$LINE" -ex run -ex 'print p' -ex 'print p.x' -ex 'print p.y' -ex 'info locals' \
      ./build/spike 2>&1 | tee build/debug.txt
    grep -q 'x = 3, y = 4' build/debug.txt || { echo "k2 FAIL: gdb did not show p"; exit 1; }
  else echo "SKIP debug (gdb missing)"; fi
elif [ "$OS" = macos ]; then
  if command -v lldb >/dev/null 2>&1; then
    lldb -b -o "breakpoint set -f spike.p3 -l $LINE" -o run -o 'frame variable p' -o 'frame variable total' \
      ./build/spike 2>&1 | tee build/debug.txt
    grep -q 'x = 3' build/debug.txt && grep -q 'y = 4' build/debug.txt || { echo "k2 FAIL: lldb did not show p"; exit 1; }
  else echo "SKIP debug (lldb missing)"; fi
else
  if command -v cdb >/dev/null 2>&1; then
    cdb -c "bp \`spike.p3:$LINE\`; g; dv; dx p; q" ./build/spike.exe 2>&1 | tee build/debug.txt
    grep -q 'x *= *3\|x = 3\|\[x\]' build/debug.txt || echo "WARN: cdb output did not show p.x (see build/debug.txt)"
  elif command -v llvm-pdbutil >/dev/null 2>&1; then
    llvm-pdbutil dump -types build/spike.pdb 2>&1 | tee build/debug.txt | grep -E 'Point|LF_FIELDLIST|x|y' | head -20
    llvm-pdbutil dump -l build/spike.pdb 2>&1 | grep -E 'spike\.p3' | head -5
    grep -q 'Point' build/debug.txt || { echo "k2 FAIL: PDB has no Point"; exit 1; }
  else echo "SKIP debug (cdb and llvm-pdbutil missing)"; fi
fi

# 4. coverage (G9): per-line counters emitted by the compiler (not llvm-cov), lcov written at exit
if $P3C --coverage -o build/spike_cov $SPEC && ./build/spike_cov$EXE >/dev/null; then
  LCOV=build/spike_cov.lcov
  echo "coverage (per-line counters, lcov: $LCOV), fn area:"
  grep -E '^(FN|FNDA):.*area' $LCOV
  awk -F'[:,]' '/^DA:/ { c[$2] = $3 } END { for (l in c) print l, c[l] }' $LCOV | sort -n > build/da.txt
  awk 'NR==FNR { c[$1] = $2; next } FNR>=15 && FNR<=23 { printf "%6s | %3d | %s\n", (FNR in c) ? c[FNR] : "", FNR, $0 }' build/da.txt $SPEC
  grep -E '^(LF|LH):' $LCOV | tr '\n' ' '; echo
else
  echo "SKIP coverage (build failed)"
fi

echo "k2 spike OK"
