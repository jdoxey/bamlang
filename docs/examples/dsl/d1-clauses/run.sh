#!/bin/sh
# Parses the d1 benchmark corpus, checks the bad files, and re-parses the P3 corpus against ../../syntax/p3/expected.
PY=$(command -v python3 || command -v python)
cd "$(dirname "$0")" || exit 1
fail=0
tmp=$(mktemp -d 2>/dev/null || echo "${TMPDIR:-/tmp}/dsld1.$$"); mkdir -p "$tmp"
for f in corpus/*.d1; do
  if ! "$PY" parser.py "$f" >"$tmp/out" 2>"$tmp/err"; then echo "FAIL $f: $(cat "$tmp/err")"; fail=1; fi
done
for f in corpus/bad/*.d1; do
  exp=$(head -1 "$f" | sed -n 's/^# expect: *\([0-9]*\): *\(.*\)$/\1 \2/p' | tr -d '\r')
  line=${exp%% *}; sub=${exp#* }
  if "$PY" parser.py "$f" >/dev/null 2>"$tmp/err"; then echo "FAIL $f: parsed, expected an error"; fail=1; continue; fi
  msg=$(tr -d '\r' < "$tmp/err")
  case "$msg" in
    *":$line:"*"$sub"*) ;;
    *) echo "FAIL $f: expected line $line containing '$sub', got: $msg"; fail=1 ;;
  esac
done
# strict extension: the P3 corpus must still give the P3 ASTs byte for byte
for n in chatsim widgets errors types tricky; do
  if ! "$PY" parser.py "../../syntax/p3/corpus/$n.p3" 2>"$tmp/err" | tr -d '\r' > "$tmp/$n.out"; then :; fi
  if [ -s "$tmp/err" ]; then echo "FAIL p3 $n: $(cat "$tmp/err")"; fail=1; continue; fi
  if ! tr -d '\r' < "../../syntax/p3/expected/$n.ast" | diff - "$tmp/$n.out" > "$tmp/diff"; then
    echo "FAIL p3 $n: AST differs from p3/expected/$n.ast"; head -20 "$tmp/diff"; fail=1
  fi
done
for f in ../../syntax/p3/corpus/bad/*.p3; do
  if "$PY" parser.py "$f" >/dev/null 2>&1; then echo "FAIL p3 $f: parsed, expected an error"; fail=1; fi
done
rm -rf "$tmp"
if [ $fail -ne 0 ]; then exit 1; fi
"$PY" ../metrics.py corpus/*.d1
echo "d1 dsl corpus OK"
