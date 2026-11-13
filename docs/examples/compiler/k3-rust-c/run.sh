#!/usr/bin/env bash
# K3 spike (loop 2): Rust compiler -> C -> clang. Run from anywhere.
set -u
cd "$(dirname "$0")"
OS=$(uname -s)
EXE=""; WIN=0; MAC=0
case "$OS" in MINGW*|MSYS*|CYGWIN*) WIN=1; EXE=".exe"; export PATH="$PATH:/c/Program Files/LLVM/bin";; Darwin) MAC=1;; esac
command -v clang >/dev/null || { echo "clang not found"; exit 1; }
command -v cargo >/dev/null || { echo "cargo not found"; exit 1; }
mkdir -p build
fail() { echo "FAIL: $*"; exit 1; }
echo "clang: $(clang --version | head -1)"

# 1. build the compiler (Cargo package, zero dependencies)
S=$(date +%s)
cargo build --release --quiet || fail "compiler build"
echo "compiler build: $(( $(date +%s) - S ))s"
cp "target/release/k3c$EXE" "build/k3c$EXE"
cp ../spike.p3 ../spike2.p3 ../uncaught.p3 bench.p3 build/
K3=./k3c$EXE
lf() { tr -d "\r" < "$1" > "$1.lf" && mv "$1.lf" "$1"; }

# 2. compile and run the programs (debug info on; on Windows k3c adds -gcodeview, lld)
for P in spike spike2 uncaught; do ( cd build && $K3 $P.p3 -o $P$EXE ) || fail "k3c $P"; done
( cd build && ./spike$EXE > actual.txt ) || fail "spike run"
lf build/actual.txt
diff -u ../expected.txt build/actual.txt || fail "spike output differs from expected.txt"
echo "spike.p3: output matches expected.txt"
( cd build && ./spike2$EXE > actual2.txt ) || fail "spike2 run"
lf build/actual2.txt
diff -u ../expected2.txt build/actual2.txt || fail "spike2 output differs from expected2.txt"
echo "spike2.p3: output matches expected2.txt (enum, trap in drop, crew trap)"
# uncaught trap: stdout (a file here, so not a tty) keeps 'before'; stderr has message and trace; exit 101
( cd build && ./uncaught$EXE > unc_out.txt 2> unc_err.txt ); RC=$?
lf build/unc_out.txt; lf build/unc_err.txt
[ "$(cat build/unc_out.txt)" = "before" ] || fail "uncaught: stdout is not exactly 'before'"
grep -q 'trap: boom' build/unc_err.txt || fail "uncaught: stderr lacks 'trap: boom'"
grep -q -E 'inner|uncaught.p3:4' build/unc_err.txt || fail "uncaught: stderr lacks a trace naming inner or uncaught.p3:4"
[ "$RC" = 101 ] || fail "uncaught: exit code $RC, expected 101"
echo "uncaught.p3: stdout 'before', exit $RC, stderr:"; sed 's/^/  | /' build/unc_err.txt

# 3. debugger (G8)
debug_unix_gdb() { # prog, line, extra gdb commands...
  P=$1; L=$2; shift 2
  ARGS=(-batch -ex "break $P.p3:$L" -ex run); for C in "$@"; do ARGS+=(-ex "$C"); done
  ( cd build && gdb "${ARGS[@]}" ./$P ) 2>&1
}
LINE=$(grep -n 'total += p.x \* p.y' ../spike.p3 | head -1 | cut -d: -f1)
LINE2=$(grep -n 'let probe = 0' ../spike2.p3 | head -1 | cut -d: -f1)
if [ "$WIN" = 1 ]; then
  if command -v cdb >/dev/null; then
    ( cd build && cdb -c "bp \`spike.p3:$LINE\`; g; dx p; q" spike.exe ) 2>&1 | tee build/debug.txt
    ( cd build && cdb -c "bp \`spike2.p3:$LINE2\`; g; dx s; q" spike2.exe ) 2>&1 | tee build/debug2.txt
  elif command -v llvm-pdbutil >/dev/null; then
    # Windows: try a real lldb session on the PDB first; then check the PDB strictly.
    if command -v lldb >/dev/null; then
      for PR in "spike $LINE p" "spike2 $LINE2 s"; do
        set -- $PR
        ( cd "build" && lldb -b -o "breakpoint set -f $1.p3 -l $2" -o run -o "frame variable $3" "./$1.exe" ) > "build/lldb-win-$1.txt" 2>&1 || true
        echo "windows lldb, $1:"; grep -E ' = |stop reason|\.p3:' "build/lldb-win-$1.txt" | head -12
      done
    fi
    llvm-pdbutil dump -types "build/spike.pdb" > "build/pdb-types.txt" 2>&1
    grep -A3 'LF_STRUCTURE.*`Point`' "build/pdb-types.txt" | head -8
    grep -q 'LF_STRUCTURE.*`Point`' "build/pdb-types.txt" || { echo "PDB lacks struct Point"; exit 1; }
    grep -E 'LF_MEMBER \[name = `(x|y)`' "build/pdb-types.txt" | head -4
    llvm-pdbutil dump -types "build/spike2.pdb" > "build/pdb-types2.txt" 2>&1
    echo "PDB for spike2 (enum encoding):"
    grep -E 'LF_(STRUCTURE|UNION).*`(Shape|<unnamed-type-u>|__unnamed)' "build/pdb-types2.txt" | head -6
    grep -E 'LF_MEMBER \[name = `(tag|u|Circle|Rect|r|w|h)`' "build/pdb-types2.txt" | head -10
    grep -q 'LF_STRUCTURE.*`Shape`' "build/pdb-types2.txt" || { echo "PDB lacks struct Shape"; exit 1; }
  else echo "SKIP debug (cdb and llvm-pdbutil missing)"; fi
elif [ "$MAC" = 1 ]; then
  if command -v lldb >/dev/null; then
    ( cd build && lldb -b -o "breakpoint set -f spike.p3 -l $LINE" -o run -o "frame variable p" -o "p p" ./spike ) 2>&1 | tee build/debug.txt
    grep -q 'x = 3' build/debug.txt && grep -q 'y = 4' build/debug.txt || fail "lldb did not show p.x=3 p.y=4"
    ( cd build && lldb -b -o "breakpoint set -f spike2.p3 -l $LINE2" -o run -o "frame variable s" -o "p s" ./spike2 ) 2>&1 | tee build/debug2.txt
    grep -q 'w = 3' build/debug2.txt && grep -q 'h = 4' build/debug2.txt || fail "lldb did not show s with w = 3, h = 4"
  else echo "SKIP debug (lldb missing)"; fi
else
  if command -v gdb >/dev/null; then
    debug_unix_gdb spike "$LINE" 'print p' 'print p.x' 'info locals' bt | tee build/debug.txt
    grep -q 'x = 3' build/debug.txt && grep -q 'y = 4' build/debug.txt || fail "gdb did not show p.x=3 p.y=4"
    echo "--- enum in gdb (break at 'let probe = 0' in describe, spike2.p3:$LINE2)"
    debug_unix_gdb spike2 "$LINE2" 'print s' 'print s.tag' 'print s.u.Rect' 'info args' bt | tee build/debug2.txt
    grep -q 'w = 3' build/debug2.txt && grep -q 'h = 4' build/debug2.txt || fail "gdb did not show s with w = 3, h = 4"
  else echo "SKIP debug (gdb missing)"; fi
fi

# 4. coverage (G9): instrumented build, llvm-cov export (JSON) of the generated C, remapped through
#    the compiler's #line table (spike_cov.c.map) to spike.p3: lcov file plus a text report.
COV=llvm-cov; PROF=llvm-profdata
if ! command -v $COV >/dev/null || ! command -v $PROF >/dev/null; then
  if [ "$MAC" = 1 ] && command -v xcrun >/dev/null; then COV="xcrun llvm-cov"; PROF="xcrun llvm-profdata"; fi
fi
if $COV --version >/dev/null 2>&1 && $PROF --version >/dev/null 2>&1; then
  ( cd build && $K3 --coverage spike.p3 -o spike_cov$EXE && \
    LLVM_PROFILE_FILE=spike.profraw ./spike_cov$EXE >/dev/null && \
    $PROF merge -sparse spike.profraw -o spike.profdata && \
    $COV report ./spike_cov$EXE -instr-profile=spike.profdata spike_cov.c > coverage-c.txt && \
    $COV export -format=text ./spike_cov$EXE -instr-profile=spike.profdata spike_cov.c > spike_cov.json && \
    $K3 --cov-remap spike_cov.json spike_cov.c.map spike.p3 spike.lcov > coverage.txt ) 2>&1 || fail "coverage"
  lf build/coverage.txt
  echo "llvm-cov report of the generated C (clang ignores #line, so this is not against spike.p3):"
  sed -n '1,4p' build/coverage-c.txt | cut -c1-140
  echo "remapped to spike.p3 (full report: build/coverage.txt, lcov: build/spike.lcov):"
  A=$(grep -n '^fn area' ../spike.p3 | head -1 | cut -d: -f1)
  sed -n "$((A+1)),$((A+9))p" build/coverage.txt; tail -1 build/coverage.txt
  grep -q 'DA:19,2' build/spike.lcov || fail "remapped coverage: area's loop body is not 2"
  grep -q 'BRDA:18,0,0,2' build/spike.lcov || fail "remapped coverage: loop branch count missing"
else echo "SKIP coverage (llvm-cov/llvm-profdata missing)"; fi

# 5. cost of the setjmp/cleanup-stack design on the non-trap path (informational, never fails)
NOW=$(date +%s%N 2>/dev/null || echo x)
case "$NOW" in *[!0-9]*|"") echo "SKIP bench (date +%s%N unavailable)";; *)
  bench() { # label, k3 flags...
    L=$1; shift; D=build/bench_$L; mkdir -p $D
    ( cd build && ./k3c$EXE "$@" bench.p3 -o bench_$L/bench$EXE ) || { echo "bench build $L failed"; return; }
    BEST=999999999999
    for _ in 1 2 3 4 5 6 7; do
      T0=$(date +%s%N); ./$D/bench$EXE > $D/out.txt; T1=$(date +%s%N)
      [ $((T1 - T0)) -lt $BEST ] && BEST=$((T1 - T0))
    done
    echo "$L $BEST"
  }
  for V in "O0_registered" "O0_direct --no-cleanup" "O2_registered --opt --no-inline" "O2_direct --opt --no-inline --no-cleanup" "O2inlined_registered --opt" "O2inlined_direct --opt --no-cleanup"; do
    set -- $V; bench "$@"
  done | while read L NS; do
    echo "bench $L: best of 7 = $(( NS / 1000000 )) ms for 10M calls = $(( NS / 10000000 )).$(( (NS / 1000000) % 10 )) ns/call (includes ~1-2 ms process start)"
  done;;
esac

echo "k3 spike OK"
