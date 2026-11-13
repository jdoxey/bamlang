#!/usr/bin/env bash
# Runs every scenario against all three dependency-manager spikes in a temp dir.
# Needs bash, python3 (or python) and git. Prints "deps spikes OK" when every expectation holds.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
py=python3
command -v python3 >/dev/null 2>&1 && python3 -c 'import sys' >/dev/null 2>&1 || py=python
"$py" "$here/scenarios/run_scenarios.py" "$@"
echo "deps spikes OK"
