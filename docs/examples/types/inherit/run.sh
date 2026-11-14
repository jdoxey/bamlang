#!/bin/sh
# Inheritance finalists H1/H2/H3 (ADR-0005 amendment 1, step 3). Run: bash run.sh   (Linux, macOS, Git Bash on Windows)
# 1 parse the corpora and the p3n corpus  2 checker bad files  3 3 am resolver + pinned table  4 C models vs expected
PY=$(command -v python3 || command -v python)
CC=${CC:-clang}
here=$(cd "$(dirname "$0")" && pwd) || exit 1
cd "$here" || exit 1
P3N=../../syntax/p3n
EXE=
case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) EXE=.exe ;; esac
fail=0
tmp=$(mktemp -d 2>/dev/null || echo "${TMPDIR:-/tmp}/inherit.$$"); mkdir -p "$tmp"
# the python scripts print LF but Windows text mode may add CR: every comparison strips CR
nocr() { tr -d '\r'; }

# 1. parse -------------------------------------------------------------------
for h in h1 h2 h3; do
  if "$PY" parser.py "$h/types.p3" 2>"$tmp/err" | nocr > "$tmp/$h.ast" && [ ! -s "$tmp/err" ]; then
    echo "parse $h/types.p3: $(wc -l < "$h/types.p3" | tr -d ' ') lines, $(wc -l < "$tmp/$h.ast" | tr -d ' ') AST lines"
  else echo "FAIL parse $h/types.p3: $(nocr < "$tmp/err")"; fail=1; fi
done
# the four p3n corpus files that don't use iface/impl keep byte-identical ASTs; types.p3 must now fail on `iface`
for n in chatsim widgets errors tricky; do
  "$PY" parser.py "$P3N/corpus/$n.p3" 2>"$tmp/err" | nocr > "$tmp/$n.out"
  if [ -s "$tmp/err" ] || ! nocr < "$P3N/expected/$n.ast" | diff - "$tmp/$n.out" >/dev/null; then
    echo "FAIL p3n corpus $n: AST differs from $P3N/expected/$n.ast"; fail=1
  fi
done
if "$PY" parser.py "$P3N/corpus/types.p3" >/dev/null 2>"$tmp/err"; then echo "FAIL p3n types.p3 should fail (iface)"; fail=1
else case "$(nocr < "$tmp/err")" in *"is removed"*) echo "p3n corpus: 4 files identical, types.p3 rejected (iface)" ;; *) echo "FAIL p3n types.p3: wrong error"; fail=1 ;; esac; fi

# 2. bad files ---------------------------------------------------------------
nbad=0
for f in bad/*.p3; do
  b=$(basename "$f")
  hdr=$(head -1 "$f" | nocr)
  nbad=$((nbad + 1))
  case "$b" in
    parse_*)
      exp=$(printf '%s' "$hdr" | sed -n 's/^# expect: *\([0-9]*\): *\(.*\)$/\1 \2/p'); line=${exp%% *}; sub=${exp#* }
      if "$PY" parser.py "$f" >/dev/null 2>"$tmp/err"; then echo "FAIL $f: parsed, expected an error"; fail=1; continue; fi
      case "$(nocr < "$tmp/err")" in *":$line:"*"$sub"*) ;; *) echo "FAIL $f: expected line $line '$sub', got: $(nocr < "$tmp/err")"; fail=1 ;; esac ;;
    *)
      rules=${b%%_*}
      case "$hdr" in
        "# expect: "*)
          sub=${hdr#"# expect: "}
          if "$PY" resolve.py --rules "$rules" "$f" >/dev/null 2>"$tmp/err"; then echo "FAIL $f: accepted, expected an error"; fail=1; continue; fi
          case "$(nocr < "$tmp/err")" in *"$sub"*) ;; *) echo "FAIL $f: expected '$sub', got: $(nocr < "$tmp/err")"; fail=1 ;; esac ;;
        "# expect-warning: "*)
          sub=${hdr#"# expect-warning: "}
          if ! "$PY" resolve.py --rules "$rules" "$f" > "$tmp/out" 2>"$tmp/err"; then echo "FAIL $f: rejected: $(nocr < "$tmp/err")"; fail=1; continue; fi
          case "$(nocr < "$tmp/out")" in *"warning:"*"$sub"*) ;; *) echo "FAIL $f: no warning '$sub'"; fail=1 ;; esac ;;
        "# expect-clean:"*)
          if ! "$PY" resolve.py --rules "$rules" "$f" > "$tmp/out" 2>"$tmp/err"; then echo "FAIL $f: rejected: $(nocr < "$tmp/err")"; fail=1; continue; fi
          case "$(nocr < "$tmp/out")" in *"warning:"*) echo "FAIL $f: unexpected warning"; fail=1 ;; esac ;;
        *) echo "FAIL $f: no '# expect' header"; fail=1 ;;
      esac ;;
  esac
done
echo "bad files: $nbad checked"

# 3. the 3 am resolver ---------------------------------------------------------
"$PY" resolve.py --all . > "$tmp/res" 2>"$tmp/reserr"; rc=$?
nocr < "$tmp/res" > "$tmp/res.lf"
if [ $rc -ne 0 ]; then echo "FAIL resolve --all: $(nocr < "$tmp/reserr")"; fail=1; fi
grep -v 'warning:' "$tmp/res.lf" > "$tmp/table"
if diff expected/table.txt "$tmp/table" >/dev/null; then cat "$tmp/table"; else echo "FAIL resolver table differs from expected/table.txt"; diff expected/table.txt "$tmp/table"; fail=1; fi
# warnings: H1 has none (open recursion); H2 and H3 each warn once (CountedNames.push is bypassed by LoggedAll.push_all)
for h in h1:0 h2:1 h3:1; do
  n=$(grep -c "^${h%%:*}: warning:" "$tmp/res.lf")
  if [ "$n" != "${h#*:}" ]; then echo "FAIL ${h%%:*}: $n warnings, expected ${h#*:}"; fail=1; fi
done

# 4. C models -------------------------------------------------------------------
for n in h1 h2 h3; do
  if ! "$CC" -std=c11 -Wall -Wextra -D_CRT_SECURE_NO_WARNINGS -o "$tmp/$n$EXE" "cmodel/$n.c" 2>"$tmp/cc"; then echo "FAIL build $n: $(cat "$tmp/cc")"; fail=1; continue; fi
  [ -s "$tmp/cc" ] && echo "note: $n compiled with warnings: $(head -3 "$tmp/cc")"
  "$tmp/$n$EXE" 2>&1 | nocr > "$tmp/$n.txt"
  if nocr < "cmodel/$n.txt" | diff - "$tmp/$n.txt" >/dev/null; then echo "cmodel $n: transcript matches ($(wc -l < "$tmp/$n.txt" | tr -d ' ') lines)"
  else echo "FAIL cmodel $n: transcript differs"; nocr < "cmodel/$n.txt" | diff - "$tmp/$n.txt" | head -10; fail=1; fi
done
rm -rf "$tmp"
if [ $fail -ne 0 ]; then exit 1; fi
echo "inherit examples OK"
