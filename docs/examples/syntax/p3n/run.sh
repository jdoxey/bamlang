#!/bin/sh
# Runs the P3n (fully labelled) parser over the corpus; compares with expected/*.ast; checks every bad file's error.
PY=$(command -v python3 || command -v python)
cd "$(dirname "$0")" || exit 1
fail=0
tmp=$(mktemp -d 2>/dev/null || echo "${TMPDIR:-/tmp}/p3run.$$"); mkdir -p "$tmp"
for n in chatsim widgets errors types tricky; do
  if ! "$PY" parser.py "corpus/$n.p3" 2>"$tmp/err" | tr -d '\r' > "$tmp/$n.out"; then :; fi
  if [ -s "$tmp/err" ]; then echo "FAIL $n: $(cat "$tmp/err")"; fail=1; continue; fi
  if tr -d '\r' < "expected/$n.ast" | diff - "$tmp/$n.out" > "$tmp/diff"; then :; else
    echo "FAIL $n: AST differs from expected/$n.ast"; head -20 "$tmp/diff"; fail=1
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
# meaning check: the labelled AST must equal the unlabelled P3 AST up to labels (see same_meaning.py)
for n in chatsim widgets errors types tricky; do
  if ! "$PY" same_meaning.py "../p3/expected/$n.ast" "expected/$n.ast" > "$tmp/sm.$n"; then
    echo "FAIL $n: labelled AST differs in meaning from ../p3/expected/$n.ast"; grep '^DIFF' "$tmp/sm.$n" | head; fail=1
  else tail -1 "$tmp/sm.$n" | sed "s/^/$n: /"; fi
done
# same_meaning.py must reject its known false-accept cases (sm_tests/*.old.ast vs *.new.ast); ok_* must pass
for o in sm_tests/*.old.ast; do
  t=${o%.old.ast}; b=$(basename "$t")
  if "$PY" same_meaning.py "$o" "$t.new.ast" >/dev/null 2>&1; then rc=0; else rc=1; fi
  case "$b" in
    ok_*) if [ $rc -ne 0 ]; then echo "FAIL sm_tests/$b: should be accepted"; fail=1; fi ;;
    *) if [ $rc -eq 0 ]; then echo "FAIL sm_tests/$b: should be rejected"; fail=1; fi ;;
  esac
done
# labels versus declarations (rules 1, 6, 7)
for n in chatsim widgets errors types tricky; do
  if ! "$PY" check_labels.py "corpus/$n.p3" > "$tmp/cl" 2>&1; then echo "FAIL $n: check_labels"; cat "$tmp/cl"; fail=1
  else sed "s/^/$n: /" "$tmp/cl"; fi
done
for f in check_bad/*.p3; do
  exp=$(head -1 "$f" | sed -n 's/^# expect: *\(.*\)$/\1/p' | tr -d '\r')
  if "$PY" check_labels.py "$f" >/dev/null 2>"$tmp/err"; then echo "FAIL $f: accepted, expected an error"; fail=1; continue; fi
  case "$(cat "$tmp/err")" in
    *"$exp"*) ;;
    *) echo "FAIL $f: expected '$exp', got: $(cat "$tmp/err")"; fail=1 ;;
  esac
done
rm -rf "$tmp"
if [ $fail -ne 0 ]; then exit 1; fi
echo "p3n syntax corpus OK"
