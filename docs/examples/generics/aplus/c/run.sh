#!/usr/bin/env bash
# Builds the C model of A+ and checks: output == ../expected-aplus.txt, its first lines == ../../expected.txt,
# and the trap tests (F3 stale Handle, S1 borrow count, S5 foreign Id, S6 two-phase, S7 whole-Map borrow). Works on Linux, macOS and Windows Git Bash (MinGW gcc).
set -euo pipefail
cd "$(dirname "$0")"
CC="${CC:-$(command -v cc || command -v gcc || command -v clang)}"
mkdir -p build
extra=()
case "$(uname -s)" in Linux*|Darwin*) extra+=(-pthread) ;; esac
san=()
if [ "${SANITIZE:-0}" = 1 ]; then san+=(-fsanitize=address,undefined -fno-omit-frame-pointer); fi
"$CC" -std=c11 -Wall -Wextra -Werror -O1 -g "${san[@]}" -o build/aplus aplus.c "${extra[@]}"

./build/aplus | tr -d '\r' > build/actual.txt
tr -d '\r' < ../expected-aplus.txt > build/expected-aplus.txt
if ! diff build/expected-aplus.txt build/actual.txt; then echo "aplus: output differs from expected-aplus.txt"; exit 1; fi
n=$(tr -d '\r' < ../../expected.txt | wc -l)
if ! diff <(tr -d '\r' < ../../expected.txt) <(head -n "$n" build/actual.txt); then echo "aplus: Parts 1-3 differ from ../expected.txt"; exit 1; fi

# Trap tests. No signals: a trap prints "TRAP: ..." to stdout and exits 70. Leak checks are off for them (exit skips drops).
export ASAN_OPTIONS=detect_leaks=0
trap_test() {  # name, expected message fragment, optional last stdout line that must precede the trap
  set +e; ./build/aplus "--$1" 2>build/t.err | tr -d '\r' > "build/$1.txt"; rc=${PIPESTATUS[0]}; set -e
  [ "$rc" -eq 70 ] || { echo "aplus: --$1 should exit 70, got $rc"; exit 1; }
  grep -q "^TRAP: .*$2" "build/$1.txt" || { echo "aplus: --$1 should print TRAP: $2"; cat "build/$1.txt"; exit 1; }
}
ok_test() {  # name, expected line
  ./build/aplus "--$1" | tr -d '\r' > "build/$1.txt"
  grep -qx "$2" "build/$1.txt" || { echo "aplus: --$1 should print: $2"; cat "build/$1.txt"; exit 1; }
}
# F3: a forgotten slots-removal is a stale Handle: get takes the else branch, a later put traps.
./build/aplus --f3 | tr -d '\r' > build/f3.txt
grep -qx 'profiles get 1/1 miss' build/f3.txt || { echo "aplus: F3 lookup should take the stale else branch"; exit 1; }
trap_test f3-put 'stale Handle'
grep -qx 'profiles get 1/1 miss' build/f3-put.txt || { echo "aplus: F3 put test lost its lookup line"; exit 1; }
# S1: push from another function while a block borrow of the list is live traps; after the borrow ends it works.
trap_test s1 'push on a List while 1 block borrow'
ok_test s1-ok 's1: pushed after the borrow ended, len=2'
# S7: removing from a Map whose element is block-borrowed traps (borrow covers the whole Map).
trap_test s7 'remove from a Map while 1 block borrow'
# S5: a foreign Id or Handle always traps; a stale one on its own pool takes else (handle -> 0).
trap_test s5 'foreign Id'
trap_test s5-at 'foreign Handle'
grep -qx 's5: stale id on its own pool takes else: handle(id) -> 0' build/s5.txt || { echo "aplus: S5 stale Id should take else"; exit 1; }
# S6: arguments are evaluated before the receiver place (two-phase); the naive order is caught by S1.
./build/aplus --s6 | tr -d '\r' > build/s6.txt
printf 's6: a=[x w]\ns6: b=[y]\ns6: a=[x w from-grow]\n' | diff - build/s6.txt || { echo "aplus: S6 two-phase result wrong"; exit 1; }
trap_test s6-naive 'insert of a new key into a Map while 1 block borrow'
echo "aplus: output matches expected-aplus.txt; Parts 1-3 match ../expected.txt; F3, S1, S5, S6, S7 checks pass"
