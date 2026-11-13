#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
CXX="${CXX:-$(command -v c++ || command -v g++ || command -v clang++)}"
mkdir -p build
extra=()
case "$(uname -s)" in Linux*|Darwin*) extra+=(-pthread) ;; MINGW*|MSYS*|CYGWIN*) extra+=(-static) ;; esac
"$CXX" -std=c++17 -Wall -Wextra -Werror -O1 -g -o build/chatsim chatsim.cpp "${extra[@]}"
bash ../compare.sh ./build/chatsim
