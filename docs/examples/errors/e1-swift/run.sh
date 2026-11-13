#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) echo "SKIP e1-swift on Windows: no Swift toolchain"; exit 0 ;; esac
command -v swiftc >/dev/null || { echo "swiftc not found"; exit 1; }
mkdir -p build
swiftc -O -swift-version 6 -o build/errors main.swift
./build/errors | tr -d '\r' > build/actual.txt
if diff <(tr -d '\r' < ../expected.txt) build/actual.txt; then
  echo "errors output matches expected.txt"
else
  echo "errors output differs from expected.txt"
  exit 1
fi
