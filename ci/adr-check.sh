#!/usr/bin/env bash
# Owner-only file. An ADR may not be marked Accepted on the Full tier unless it
# names a folder of real example code that has at least one run.sh in it.
set -euo pipefail
fail=0
for adr in docs/adr/[0-9]*.md; do
  [ -f "$adr" ] || continue
  head -12 "$adr" | grep -q 'Status:\*\* Accepted' || continue
  head -12 "$adr" | grep -q 'Tier:\*\* Full' || continue
  dir=$(head -12 "$adr" | sed -n 's/.*Examples:\*\* `\([^`]*\)`.*/\1/p' | head -1)
  if [ -z "$dir" ] || [ ! -d "$dir" ] || [ -z "$(find "$dir" -name run.sh | head -1)" ]; then
    echo "FAIL $adr: Accepted on the Full tier without runnable examples (Examples: '$dir')"
    fail=1
  fi
done
exit $fail
