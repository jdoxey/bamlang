#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
cargo build --quiet --release --target-dir build
exe=build/release/threads; [ -f "$exe.exe" ] && exe="$exe.exe"
diff <(tr -d '\r' < ../expected.txt) <("./$exe" | tr -d '\r') && echo "threads output matches expected.txt"
"./$exe" --selftest
