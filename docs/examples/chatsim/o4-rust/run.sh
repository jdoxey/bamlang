#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
cargo build --quiet --release --target-dir build
exe=build/release/chatsim
[ -f "$exe.exe" ] && exe="$exe.exe"
bash ../compare.sh "./$exe"
