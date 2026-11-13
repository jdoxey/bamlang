#!/usr/bin/env bash
# Builds the C model of A+ and checks: output == ../expected-aplus.txt, its first lines == ../../expected.txt,
# and the F3 stale-Id checks. Works on Linux, macOS and Windows Git Bash (MinGW gcc).
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

# F3 check: a forgotten slots-removal is caught as a stale Id (else branch, then a trap on put).
./build/aplus --f3 | tr -d '\r' > build/f3.txt
grep -qx 'profiles get 1/1 miss' build/f3.txt || { echo "aplus: F3 lookup should take the stale else branch"; exit 1; }
set +e
ASAN_OPTIONS=detect_leaks=0 ./build/aplus --f3-put > build/f3put.txt 2> build/f3put.err; rc=$?
set -e
[ "$rc" -ne 0 ] && grep -q 'stale Id' build/f3put.err || { echo "aplus: F3 put should trap on a stale Id"; exit 1; }
echo "aplus: output matches expected-aplus.txt; Parts 1-3 match ../expected.txt; F3 stale-Id checks pass"
