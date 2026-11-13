#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v go >/dev/null || { echo "go not found"; exit 1; }
mkdir -p build
go vet ./...
go build -o build/errors .
./build/errors | tr -d '\r' > build/actual.txt
if diff <(tr -d '\r' < ../expected.txt) build/actual.txt; then
  echo "errors output matches expected.txt"
else
  echo "errors output differs from expected.txt"
  exit 1
fi
