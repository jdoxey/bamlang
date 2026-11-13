#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p build
go build -o build/prog .
exe=build/prog; [ -f "$exe.exe" ] && exe="$exe.exe"
diff <(tr -d '\r' < ../expected.txt) <("./$exe" | tr -d '\r') && echo "generics output matches expected.txt"
