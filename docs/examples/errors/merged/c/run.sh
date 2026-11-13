#!/usr/bin/env bash
# Builds the C model of the merged errors design, diffs its output against ../../expected.txt, then runs --selftest.
# SAN=1 builds with -fsanitize=address,undefined.
set -euo pipefail
cd "$(dirname "$0")"
CC="${CC:-$(command -v cc || command -v gcc || command -v clang)}"
mkdir -p build
extra=()
case "$(uname -s)" in Linux*|Darwin*) extra+=(-pthread) ;; esac
if [ "${SAN:-0}" = 1 ]; then extra+=(-fsanitize=address,undefined -fno-omit-frame-pointer); export ASAN_OPTIONS="${ASAN_OPTIONS:-detect_stack_use_after_return=0}"; fi
"$CC" -std=c11 -Wall -Wextra -Werror -O1 -g -o build/errors errors.c "${extra[@]}"
cd build
HERE="$(pwd -W 2>/dev/null || pwd)"      # native path on MSYS/MinGW, so the selftest can re-exec itself
./errors | tr -d '\r' > actual.txt
if diff <(tr -d '\r' < ../../../expected.txt) actual.txt; then
  echo "errors output matches expected.txt"
else
  echo "errors output differs from expected.txt"; exit 1
fi
"$HERE/errors" --selftest | tr -d '\r'
test "${PIPESTATUS[0]}" -eq 0
