#!/bin/sh
# Runs the P1 parser over the corpus; compares with ../expected/*.ast; checks every bad file's error.
PY=$(command -v python3 || command -v python)
cd "$(dirname "$0")" || exit 1
fail=0
tmp=$(mktemp -d 2>/dev/null || echo "${TMPDIR:-/tmp}/p3run.$$"); mkdir -p "$tmp"
for n in chatsim widgets errors types tricky; do
  if ! "$PY" parser.py "corpus/$n.p3" 2>"$tmp/err" | tr -d '\r' > "$tmp/$n.out"; then :; fi
  if [ -s "$tmp/err" ]; then echo "FAIL $n: $(cat "$tmp/err")"; fail=1; continue; fi
  if tr -d '\r' < "../expected/$n.ast" | diff - "$tmp/$n.out" > "$tmp/diff"; then :; else
    echo "FAIL $n: AST differs from ../expected/$n.ast"; head -20 "$tmp/diff"; fail=1
  fi
done
# CRLF: the lexer must give the same AST for CRLF line ends (and a lone CR)
for n in chatsim tricky; do
  sed 's/$/\r/' "corpus/$n.p3" > "$tmp/crlf.p3"
  "$PY" parser.py "$tmp/crlf.p3" 2>&1 | tr -d '\r' > "$tmp/crlf.out"
  if ! diff "$tmp/crlf.out" "$tmp/$n.out" >/dev/null; then echo "FAIL $n: CRLF variant differs"; fail=1; fi
done
for f in corpus/bad/*.p3; do
  exp=$(head -1 "$f" | sed -n 's/^# expect: *\([0-9]*\): *\(.*\)$/\1 \2/p' | tr -d '\r')
  line=${exp%% *}; sub=${exp#* }
  if "$PY" parser.py "$f" >/dev/null 2>"$tmp/err"; then echo "FAIL $f: parsed, expected an error"; fail=1; continue; fi
  msg=$(tr -d '\r' < "$tmp/err")
  case "$msg" in
    *":$line:"*"$sub"*) ;;
    *) echo "FAIL $f: expected line $line containing '$sub', got: $msg"; fail=1 ;;
  esac
done
rm -rf "$tmp"
if [ $fail -ne 0 ]; then exit 1; fi
echo "p3 syntax corpus OK"
