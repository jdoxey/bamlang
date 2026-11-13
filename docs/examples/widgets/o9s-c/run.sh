#!/usr/bin/env bash
# Builds the O9-S C model of widgets and traps, checks widgets output against ../expected.txt, checks each trap.
set -euo pipefail
cd "$(dirname "$0")"
CC="${CC:-$(command -v cc || command -v gcc || command -v clang)}"
mkdir -p build
"$CC" -std=c11 -Wall -Wextra -Werror -O1 -g -o build/widgets widgets.c
"$CC" -std=c11 -Wall -Wextra -Werror -O1 -g -o build/traps traps.c
bash ../compare.sh ./build/widgets

fail=0
# expect <name> <exit code> <text that must appear> <args...>
expect() {
  local name="$1" want="$2" text="$3"; shift 3
  local rc=0 out
  out="$(./build/traps "$@")" || rc=$?
  out="${out//$'\r'/}"
  if [ "$rc" -ne "$want" ] || ! grep -qF -- "$text" <<<"$out"; then
    echo "FAIL $name: exit $rc (want $want), output:"; echo "$out"; fail=1
  else
    echo "ok   $name (exit $rc)"
  fi
}
expect "in-process checks (deferred drop, add-while-borrowed, cascade, retire)" 0 "all in-process checks passed"
expect "double mutable borrow traps" 70 "TRAP: exclusivity: mutable borrow" double-borrow
expect "wrong-pool handle traps" 70 "TRAP: handle from pool" wrong-pool
expect "stale pool[h] traps" 70 "TRAP: pool['things'] with a stale handle" stale-at
expect "expect_empty traps on a zombie" 70 "TRAP: pool 'things' not empty" zombie
[ "$fail" -eq 0 ] && echo "all widgets checks passed"
exit "$fail"
