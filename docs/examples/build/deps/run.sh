#!/usr/bin/env bash
# Runs the loop-1 scenarios (B1, B2, B3) and the loop-2 scenarios (B1+, B2+, incl. TOML conformance and a real
# clang build when clang is on PATH) in temp dirs. Needs bash, python3 (or python), git; clang and nm are optional.
# Prints "deps spikes OK" when every expectation holds. Results: results.md (loop 2), results-loop1.md (loop 1).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
py=python3
command -v python3 >/dev/null 2>&1 && python3 -c 'import sys' >/dev/null 2>&1 || py=python
"$py" "$here/scenarios/run_scenarios.py" "$@"
"$py" "$here/scenarios/run_scenarios2.py"
echo "deps spikes OK"
