#!/usr/bin/env bash
# K1: Rust compiler -> textual LLVM IR -> clang. Linux, macOS, Windows (Git Bash).
# Runs spike.p3 (output, debugger, coverage), spike2.p3 (enum, trap in drop, crew trap) and uncaught.p3.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SPEC="$(dirname "$HERE")"          # docs/examples/compiler (holds the .p3 programs and expected files)
B="$HERE/build"
mkdir -p "$B"

OS="$(uname -s)"
EXE=""; TARGET=""; CFLAGS="-O0 -g -Wno-override-module"; LINK="-pthread"; WIN=0
case "$OS" in
  MINGW*|MSYS*|CYGWIN*)
    WIN=1; EXE=".exe"; TARGET="x86_64-pc-windows-msvc"
    export PATH="$PATH:/c/Program Files/LLVM/bin"
    CFLAGS="-O0 -g -gcodeview -Wno-override-module --target=$TARGET"; LINK="-fuse-ld=lld" ;;
  Darwin) LINK="" ;;
esac
command -v clang >/dev/null || { echo "clang not found" >&2; exit 1; }
command -v cargo >/dev/null || { echo "cargo not found" >&2; exit 1; }
echo "clang: $(clang --version | head -1)"

# Find an LLVM tool: PATH, then xcrun / Homebrew on macOS.
tool() {
  if command -v "$1" >/dev/null 2>&1; then command -v "$1"; return 0; fi
  if [ "$OS" = Darwin ]; then
    xcrun --find "$1" 2>/dev/null && return 0
    for d in /opt/homebrew/opt/llvm/bin /usr/local/opt/llvm/bin; do [ -x "$d/$1" ] && { echo "$d/$1"; return 0; }; done
  fi
  return 1
}

# 1. Build the compiler (Cargo package, no dependencies).
t0=$(date +%s)
export CARGO_TARGET_DIR="$HERE/target"
cargo build --release --quiet --manifest-path "$HERE/Cargo.toml"
P3C="$CARGO_TARGET_DIR/release/p3c$EXE"
echo "compiler build: $(( $(date +%s) - t0 ))s"

# Target triple and datalayout come from clang itself (an empty C file), so the IR matches the toolchain (S3).
: > "$B/empty.c"
IRINFO="$(clang ${TARGET:+--target=$TARGET} -x c -S -emit-llvm -o - "$B/empty.c" | tr -d '\r')"
TRIPLE="$(printf '%s\n' "$IRINFO" | sed -n 's/^target triple = "\(.*\)"$/\1/p')"
DATALAYOUT="$(printf '%s\n' "$IRINFO" | sed -n 's/^target datalayout = "\(.*\)"$/\1/p')"
echo "triple: $TRIPLE"
echo "datalayout: $DATALAYOUT"

# The C runtime (no C++ runtime: forced unwind on Linux/macOS, SEH on Windows).
clang -std=gnu11 $CFLAGS -funwind-tables -c "$HERE/runtime.c" -o "$B/runtime.o"

# build SRC NAME [--coverage]: p3c -> LLVM IR -> clang (+ runtime) -> executable.
build() {
  local src="$1" name="$2" prof=""; shift 2
  [ "${1:-}" = "--coverage" ] && prof="-fprofile-instr-generate -fprofile-update=atomic"
  ( cd "$SPEC" && "$P3C" "$src" -o "$B/$name.ll" --triple "$TRIPLE" --datalayout "$DATALAYOUT" "$@" )
  clang $CFLAGS $prof -c "$B/$name.ll" -o "$B/$name.o"
  clang $CFLAGS $prof "$B/$name.o" "$B/runtime.o" -o "$B/$name$EXE" $LINK
}

# 2. spike.p3: compile, run, diff.
build spike.p3 spike
"$B/spike$EXE" | tr -d '\r' > "$B/actual.txt"
diff -u "$SPEC/expected.txt" "$B/actual.txt"
echo "spike.p3: output matches expected.txt"

# debug_check NAME SRC LINE-PATTERN VAR EXPECT...: break at the line, print VAR, assert every EXPECT appears (G8).
debug_check() {
  local name="$1" src="$2" pat="$3" var="$4"; shift 4
  local line; line=$(grep -n "$pat" "$SPEC/$src" | head -1 | cut -d: -f1)
  local out="$B/debug-$name.txt" e
  if [ "$WIN" = 1 ]; then
    if command -v cdb >/dev/null; then
      ( cd "$SPEC" && cdb -c "bp \`$src:$line\`; g; dx $var; dv; q" "$B/$name$EXE" ) > "$out" 2>&1 || true
      cat "$out" | tail -25
      if [ "$name" = spike ]; then   # cdb must show p as a Point value, not a bad pointer (Win64 by-reference ABI)
        grep -q ': 3 \[Type: __int64\]' "$out" && grep -q ': 4 \[Type: __int64\]' "$out" || { echo "cdb: p is not shown as Point {x: 3, y: 4}"; exit 1; }
      fi
      for e in "$@"; do grep -q "$e" "$out" || { echo "debug check failed ($name: $e)"; exit 1; }; done
    elif command -v llvm-pdbutil >/dev/null; then
      # No cdb on the runner: try a real lldb session on the PDB, then check the PDB itself.
      if command -v lldb >/dev/null; then
        ( cd "$SPEC" && lldb -b -o "breakpoint set -f $src -l $line" -o run -o "frame variable $var" "$B/$name$EXE" ) > "$B/lldb-win-$name.txt" 2>&1 || true
        local ok=1; for e in "$@"; do grep -q "$e" "$B/lldb-win-$name.txt" || ok=0; done
        if [ "$ok" = 1 ]; then echo "windows lldb shows $var:"; grep -E "stop reason|$src:|$(printf '%s|' "$@" | sed 's/|$//')" "$B/lldb-win-$name.txt" | head -8
        else echo "windows lldb did not show $var (first lines follow)"; head -12 "$B/lldb-win-$name.txt"; fi
      fi
      llvm-pdbutil dump -types "$B/$name.pdb" > "$B/pdb-types-$name.txt" 2>&1
      llvm-pdbutil dump -l "$B/$name.pdb" > "$B/pdb-lines-$name.txt" 2>&1
      grep -q "$src" "$B/pdb-lines-$name.txt" || { echo "PDB has no line records for $src"; exit 1; }
      echo "PDB line records mention $src ($(grep -c "$src" "$B/pdb-lines-$name.txt") lines)"
      if [ "$name" = spike ]; then
        grep -q 'LF_STRUCTURE.*`Point`' "$B/pdb-types-$name.txt" || { echo "PDB lacks struct Point"; exit 1; }
        grep -E 'LF_MEMBER \[name = `(x|y)`' "$B/pdb-types-$name.txt" | head -4
      else
        grep -q 'LF_STRUCTURE.*`Shape`' "$B/pdb-types-$name.txt" || { echo "PDB lacks struct Shape"; exit 1; }
        grep -E 'LF_UNION|LF_ENUM|name = `(tag|payload|Rect|Circle)`' "$B/pdb-types-$name.txt" | head -8
      fi
    else echo "SKIP debug (cdb and llvm-pdbutil missing)"; fi
  elif [ "$OS" = Darwin ]; then
    if command -v lldb >/dev/null; then
      ( cd "$SPEC" && lldb -b -o "breakpoint set -f $src -l $line" -o run -o "frame variable $var" -o "bt" "$B/$name" ) 2>&1 | tee "$out"
      for e in "$@"; do grep -q "$e" "$out" || { echo "debug check failed ($name: $e)"; exit 1; }; done
    else echo "SKIP debug (lldb missing)"; fi
  else
    if command -v gdb >/dev/null; then
      ( cd "$SPEC" && gdb -batch -ex "break $src:$line" -ex run -ex "print $var" -ex 'info locals' -ex bt "$B/$name" ) 2>&1 | tee "$out"
      for e in "$@"; do grep -q "$e" "$out" || { echo "debug check failed ($name: $e)"; exit 1; }; done
    else echo "SKIP debug (gdb missing)"; fi
  fi
}

# 3. Debugger (G8): break in area at `total += p.x * p.y` and show p.
debug_check spike spike.p3 'total += p.x \* p.y' p 'x = 3' 'y = 4'

# 4. Coverage (G9, F4): real LLVM source-based coverage. p3c emits llvm.instrprof.increment calls and the
#    __covrec_* / __llvm_coverage_mapping globals; clang lowers them with -fprofile-instr-generate.
build spike.p3 spike_cov --coverage
rm -f "$B/spike.profraw"
LLVM_PROFILE_FILE="$B/spike.profraw" "$B/spike_cov$EXE" >/dev/null
if PROFDATA="$(tool llvm-profdata)" && COV="$(tool llvm-cov)"; then
  "$PROFDATA" merge -sparse "$B/spike.profraw" -o "$B/spike.profdata"
  echo "--- llvm-cov report (spike.p3)"
  ( cd "$SPEC" && "$COV" report "$B/spike_cov$EXE" -instr-profile="$B/spike.profdata" spike.p3 ) | tr -d '\r' | tee "$B/cov-report.txt"
  ( cd "$SPEC" && "$COV" show "$B/spike_cov$EXE" -instr-profile="$B/spike.profdata" -show-branches=count spike.p3 ) | tr -d '\r' > "$B/cov-show.txt"
  ( cd "$SPEC" && "$COV" export -format=lcov "$B/spike_cov$EXE" -instr-profile="$B/spike.profdata" spike.p3 ) | tr -d '\r' > "$B/spike.lcov"
  echo "--- llvm-cov show (lines of area)"
  sed -n '/fn area/,/^ *[0-9]* *| *[0-9]* *|}/p' "$B/cov-show.txt" | head -24
  AL=$(grep -n 'total += p.x \* p.y' "$SPEC/spike.p3" | cut -d: -f1)
  SL=$(grep -n 'print(text: "small")' "$SPEC/spike.p3" | cut -d: -f1)
  grep -q "^DA:$AL,2\$" "$B/spike.lcov" || { echo "coverage: expected line $AL to run 2 times"; grep "^DA:" "$B/spike.lcov" | head -30; exit 1; }
  grep -q "^DA:$SL,0\$" "$B/spike.lcov" || { echo "coverage: expected line $SL (never taken) to be 0"; exit 1; }
  grep -q '^BRDA:' "$B/spike.lcov" || { echo "coverage: no branch records"; exit 1; }
  echo "coverage OK: line $AL ran 2 times, line $SL 0 times, $(grep -c '^BRDA:' "$B/spike.lcov") branch records"
else echo "SKIP coverage (llvm-cov/llvm-profdata missing)"; fi

# 5. spike2.p3: enum in the debugger, trap inside a drop, trap in a crew child.
build spike2.p3 spike2
"$B/spike2$EXE" | tr -d '\r' > "$B/actual2.txt"
diff -u "$SPEC/expected2.txt" "$B/actual2.txt"
echo "spike2.p3: output matches expected2.txt"
debug_check spike2 spike2.p3 'let probe = 0' s 'w = 3' 'h = 4'

# 6. uncaught.p3: stdout survives, stderr has the message and a trace, non-zero exit.
build uncaught.p3 uncaught
set +e; "$B/uncaught$EXE" > "$B/uncaught.out" 2> "$B/uncaught.err"; RC=$?; set -e
tr -d '\r' < "$B/uncaught.out" | diff -u <(echo before) - || { echo "uncaught: stdout lost"; exit 1; }
grep -q 'trap: boom' "$B/uncaught.err" || { echo "uncaught: no 'trap: boom' on stderr"; cat "$B/uncaught.err"; exit 1; }
grep -Eq 'inner|uncaught.p3:4' "$B/uncaught.err" || { echo "uncaught: no trace"; cat "$B/uncaught.err"; exit 1; }
[ "$RC" -ne 0 ] || { echo "uncaught: exit status 0"; exit 1; }
echo "uncaught.p3: exit $RC, stderr:"; cat "$B/uncaught.err"

echo "k1 spike OK"
