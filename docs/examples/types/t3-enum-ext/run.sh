#!/bin/sh
# Builds and runs this option; compares stdout (CR stripped) with ../expected.txt.
set -e
cd "$(dirname "$0")"
cargo build --quiet --release --target-dir build
exe=build/release/types
[ -f "$exe.exe" ] && exe="$exe.exe"
"$exe" | tr -d '\r' > build/out.txt
tr -d '\r' < ../expected.txt | diff - build/out.txt
echo "types output matches expected.txt"
