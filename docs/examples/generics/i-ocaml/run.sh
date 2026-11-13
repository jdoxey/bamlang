#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v ocamlopt >/dev/null || { echo "SKIP i-ocaml: no OCaml toolchain on this runner"; exit 0; }
mkdir -p build
ocamlopt -o build/prog main.ml   # add flags only if needed
exe=build/prog; [ -f "$exe.exe" ] && exe="$exe.exe"
diff <(tr -d '\r' < ../expected.txt) <("./$exe" | tr -d '\r') && echo "generics output matches expected.txt"
