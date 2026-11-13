#!/usr/bin/env bash
# K1 spike: Rust compiler -> textual LLVM IR -> clang. Linux, macOS, Windows (Git Bash).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SPEC="$(dirname "$HERE")"          # docs/examples/compiler (holds spike.p3, expected.txt)
B="$HERE/build"
mkdir -p "$B"

OS="$(uname -s)"
EXE=""; TARGET=""; CFLAGS="-O0 -g -Wno-override-module"; LINK="-lstdc++"; WIN=0
case "$OS" in
  MINGW*|MSYS*|CYGWIN*)
    WIN=1; EXE=".exe"; TARGET="x86_64-pc-windows-msvc"
    export PATH="$PATH:/c/Program Files/LLVM/bin"
    CFLAGS="-O0 -g -gcodeview -Wno-override-module --target=$TARGET"; LINK="-fuse-ld=lld" ;;
  Darwin) LINK="-lc++" ;;
esac
command -v clang >/dev/null || { echo "clang not found" >&2; exit 1; }

# 1. Build the compiler (single crate, std only).
t0=$(date +%s)
rustc -O --edition 2021 "$HERE/src/main.rs" -o "$B/p3c$EXE" 2>"$B/rustc.log" || { cat "$B/rustc.log"; exit 1; }
echo "compiler build: $(( $(date +%s) - t0 ))s"

# build NAME [--coverage]: p3c -> LLVM IR -> clang (+ runtime) -> executable
build() {
  local name="$1"; shift
  ( cd "$SPEC" && "$B/p3c$EXE" spike.p3 -o "$B/$name.ll" ${TARGET:+--target $TARGET} --covmap "$B/$name.covmap" "$@" )
  clang -x c++ $CFLAGS -c "$HERE/runtime.c" -o "$B/runtime.o"
  clang $CFLAGS -c "$B/$name.ll" -o "$B/$name.o"
  clang $CFLAGS "$B/$name.o" "$B/runtime.o" -o "$B/$name$EXE" $LINK
}

# 2. Compile spike.p3, run, diff.
build spike
"$B/spike$EXE" | tr -d '\r' > "$B/actual.txt"
diff -u "$SPEC/expected.txt" "$B/actual.txt"
echo "output matches expected.txt"

# 3. Debugger (G8): break in area at `total += p.x * p.y` (spike.p3:18) and show p.
LINE=$(grep -n 'total += p.x \* p.y' "$SPEC/spike.p3" | cut -d: -f1)
if [ "$WIN" = 1 ]; then
  if command -v cdb >/dev/null; then
    ( cd "$SPEC" && cdb -c "bp \`spike.p3:$LINE\`; g; dx p; dv; q" "$B/spike$EXE" ) | tee "$B/debug.txt" | tail -25
  elif command -v llvm-pdbutil >/dev/null; then
    llvm-pdbutil dump -types -lines "$B/spike.pdb" | tee "$B/debug.txt" | grep -E "Point|spike.p3|\bx\b|\by\b" | head -20
  else echo "SKIP debug (cdb and llvm-pdbutil missing)"; fi
elif [ "$OS" = Darwin ]; then
  if command -v lldb >/dev/null; then
    ( cd "$SPEC" && lldb -b -o "breakpoint set -f spike.p3 -l $LINE" -o run -o "frame variable" -o "bt" "$B/spike" ) | tee "$B/debug.txt"
    grep -q 'x = 3' "$B/debug.txt" && grep -q 'y = 4' "$B/debug.txt" || { echo "debug check failed"; exit 1; }
  else echo "SKIP debug (lldb missing)"; fi
else
  if command -v gdb >/dev/null; then
    ( cd "$SPEC" && gdb -batch -ex "break spike.p3:$LINE" -ex run -ex 'print p' -ex 'print scale' -ex 'print total' -ex 'info locals' -ex bt "$B/spike" ) 2>&1 | tee "$B/debug.txt"
    grep -q 'x = 3' "$B/debug.txt" && grep -q 'y = 4' "$B/debug.txt" || { echo "debug check failed"; exit 1; }
  else echo "SKIP debug (gdb missing)"; fi
fi

# 4. Coverage (G9). FALLBACK design: p3c emits per-line counters, the runtime dumps them, awk writes lcov.
#    (Not llvm-cov source-based coverage; see NOTES.md.)
build spike_cov --coverage
P3_COV_OUT="$B/spike.cov" "$B/spike_cov$EXE" >/dev/null
awk -v src="$SPEC/spike.p3" '
  FILENAME ~ /covmap$/ { if ($1=="fn") { nf++; fname[nf]=$2; fs[nf]=$3; fe[nf]=$4 } else if ($1=="line") ex[$2]=1; next }
  { cnt[$1]=$2 }
  END {
    print "TN:"; print "SF:" src
    for (i=1;i<=nf;i++) print "FN:" fs[i] "," fname[i]
    for (i=1;i<=nf;i++) { c=cnt[fs[i]]+0; print "FNDA:" c "," fname[i]; if (c>0) fh++ }
    print "FNF:" nf; print "FNH:" fh+0
    for (l=1;l<=1000;l++) if (l in ex) { c=cnt[l]+0; print "DA:" l "," c; lf++; if (c>0) lh++ }
    print "LF:" lf; print "LH:" lh+0; print "end_of_record"
  }' "$B/spike_cov.covmap" "$B/spike.cov" > "$B/spike.lcov"
echo "--- coverage (line counters; lcov in build/spike.lcov)"
awk -v src="$SPEC/spike.p3" '
  FILENAME ~ /covmap$/ { if ($1=="line") ex[$2]=1; next }
  FILENAME ~ /\.cov$/ { cnt[$1]=$2; next }
  { n++; printf "%4d | %6s | %s\n", n, (n in ex) ? cnt[n]+0 : "", $0 }' "$B/spike_cov.covmap" "$B/spike.cov" "$SPEC/spike.p3" | sed -n '14,24p'
awk '/^LF:/{lf=$0} /^LH:/{lh=$0} END{print "summary " lh " of " lf}' "$B/spike.lcov"
if command -v genhtml >/dev/null; then genhtml -q -o "$B/html" "$B/spike.lcov" >/dev/null && echo "html report: build/html/index.html"
else echo "SKIP genhtml (missing); lcov text report above"; fi

echo "k1 spike OK"
