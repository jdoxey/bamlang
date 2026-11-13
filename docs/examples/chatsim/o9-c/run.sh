#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
CC="${CC:-$(command -v cc || command -v gcc || command -v clang)}"
mkdir -p build
extra=()
case "$(uname -s)" in Linux*|Darwin*) extra+=(-pthread) ;; esac
"$CC" -std=c11 -Wall -Wextra -Werror -O1 -g -o build/chatsim chatsim.c "${extra[@]}"
bash ../compare.sh ./build/chatsim
