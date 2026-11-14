#!/usr/bin/env bash
# Owner-only file. The tour may have at most BUDGET concept headings (ruling R19).
set -euo pipefail
BUDGET=25
f=docs/TOUR.md
[ -f "$f" ] || { echo "tour-check: no $f yet"; exit 0; }
n=$(grep -cE '^## C[0-9]+\. ' "$f" || true)
echo "tour-check: $n concepts (budget $BUDGET)"
[ "$n" -le "$BUDGET" ] || { echo "FAIL: the tour has $n concepts; the budget is $BUDGET"; exit 1; }
