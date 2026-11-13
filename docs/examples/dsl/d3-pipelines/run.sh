#!/bin/sh
# Parses the d3 benchmark corpus, checks the bad files, and re-parses the P3n corpus against ../../syntax/p3n/expected.
PY=$(command -v python3 || command -v python)
cd "$(dirname "$0")" || exit 1
fail=0
tmp=$(mktemp -d 2>/dev/null || echo "${TMPDIR:-/tmp}/dsld3.$$"); mkdir -p "$tmp"
for f in corpus/*.d3; do
  if ! "$PY" parser.py "$f" >"$tmp/out" 2>"$tmp/err"; then echo "FAIL $f: $(cat "$tmp/err")"; fail=1; fi
done
for f in corpus/bad/*.d3; do
  exp=$(head -1 "$f" | sed -n 's/^# expect: *\([0-9]*\): *\(.*\)$/\1 \2/p' | tr -d '\r')
  line=${exp%% *}; sub=${exp#* }
  if "$PY" parser.py "$f" >/dev/null 2>"$tmp/err"; then echo "FAIL $f: parsed, expected an error"; fail=1; continue; fi
  msg=$(tr -d '\r' < "$tmp/err")
  case "$msg" in
    *":$line:"*"$sub"*) ;;
    *) echo "FAIL $f: expected line $line containing '$sub', got: $msg"; fail=1 ;;
  esac
done
# strict extension: the P3n corpus must still give the P3n ASTs byte for byte
P3N=../../syntax/p3n
for n in chatsim widgets errors types tricky; do
  if ! "$PY" parser.py "$P3N/corpus/$n.p3" 2>"$tmp/err" | tr -d '\r' > "$tmp/$n.out"; then :; fi
  if [ -s "$tmp/err" ]; then echo "FAIL p3n $n: $(cat "$tmp/err")"; fail=1; continue; fi
  if ! tr -d '\r' < "$P3N/expected/$n.ast" | diff - "$tmp/$n.out" > "$tmp/diff"; then
    echo "FAIL p3n $n: AST differs from p3n/expected/$n.ast"; head -20 "$tmp/diff"; fail=1
  fi
done
for f in "$P3N"/corpus/bad/*.p3; do
  if "$PY" parser.py "$f" >/dev/null 2>&1; then echo "FAIL p3n $f: parsed, expected an error"; fail=1; fi
done
rm -rf "$tmp"
if [ $fail -ne 0 ]; then exit 1; fi
"$PY" ../metrics.py corpus/*.d3
echo "d3 dsl corpus OK"
