#!/usr/bin/env bash
# The single CI entry point. It must pass on Linux, Windows (Git Bash) and macOS.
set -euo pipefail

echo "OS: $(uname -s)"

# 1. Required documents exist.
for f in docs/CHARTER.md docs/RULINGS.md docs/PROCESS.md docs/ROADMAP.md docs/STATE.md; do
  [ -f "$f" ] || { echo "missing $f"; exit 1; }
done

# 2. No ADR is Accepted on the Full tier without runnable examples.
bash ci/adr-check.sh

# 3. Every example that has a run.sh builds and passes.
for d in docs/examples/*/*/; do
  if [ -f "${d}run.sh" ]; then
    echo "== ${d}"
    (cd "$d" && bash run.sh)
  fi
done

echo "OK"
