#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v cargo >/dev/null || { echo "cargo not found"; exit 1; }
CARGO_TARGET_DIR=build cargo build --release --quiet
bin=build/release/errors
[ -x "$bin" ] || bin=build/release/errors.exe
./"$bin" | tr -d '\r' > build/actual.txt
if diff <(tr -d '\r' < ../expected.txt) build/actual.txt; then
  echo "errors output matches expected.txt"
else
  echo "errors output differs from expected.txt"
  exit 1
fi
