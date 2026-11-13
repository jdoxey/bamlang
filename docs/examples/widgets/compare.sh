#!/usr/bin/env bash
# Usage: compare.sh <command...>. Runs the command on script.txt and diffs against expected.txt.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
actual="$(mktemp)"
"$@" < "$here/script.txt" | tr -d '\r' > "$actual"
if diff <(tr -d '\r' < "$here/expected.txt") "$actual"; then
  echo "widgets output matches expected.txt"
  rm -f "$actual"
else
  echo "widgets output differs from expected.txt"
  rm -f "$actual"
  exit 1
fi
