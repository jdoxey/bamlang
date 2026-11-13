#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) echo "SKIP o1-swift on Windows: the CI image has no Swift toolchain (see NOTES.md)"; exit 0 ;; esac
command -v swiftc >/dev/null || { echo "swiftc not found"; exit 1; }
mkdir -p build
swiftc -O -g -swift-version 6 -o build/chatsim chatsim.swift
bash ../compare.sh ./build/chatsim
