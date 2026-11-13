#!/bin/sh
# PreToolUse hook. Before every tool call: if the 5-hour or weekly allowance is
# at or over the cap, sleep until that window resets, then let the call through.
# bootstrap.sh installs this to ~/.claude/lang-budget/.
FILE="$HOME/.claude/lang-budget/usage.json"
CAP="${BUDGET_CAP:-85}"
cat >/dev/null            # discard the hook input
[ -r "$FILE" ] || exit 0
for win in seven_day five_hour; do
  pct=$(jq -r ".$win.used_percentage // 0 | floor" "$FILE" 2>/dev/null || echo 0)
  reset=$(jq -r ".$win.resets_at // 0 | floor" "$FILE" 2>/dev/null || echo 0)
  now=$(date +%s)
  if [ "$pct" -ge "$CAP" ] && [ "$reset" -gt "$now" ]; then
    echo "$(date '+%F %T') $win at ${pct}% (cap ${CAP}%). Paused until $(date -d "@$reset" '+%F %T')." \
      >> "$HOME/.claude/lang-budget/gate.log"
    sleep $(( reset - now + 60 ))
  fi
done
exit 0
