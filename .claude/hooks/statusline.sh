#!/bin/sh
# Status line. Saves the account's usage so budget-gate.sh can read it.
# bootstrap.sh installs this to ~/.claude/lang-budget/.
DIR="$HOME/.claude/lang-budget"
CAP="${BUDGET_CAP:-85}"
in=$(cat)
rl=$(printf '%s' "$in" | jq -c '.rate_limits // empty' 2>/dev/null)
if [ -n "$rl" ]; then
  mkdir -p "$DIR"
  printf '%s' "$rl" > "$DIR/usage.json.tmp" && mv "$DIR/usage.json.tmp" "$DIR/usage.json"
  five=$(printf '%s' "$rl" | jq -r '.five_hour.used_percentage // "?" | if type=="number" then floor else . end')
  week=$(printf '%s' "$rl" | jq -r '.seven_day.used_percentage // "?" | if type=="number" then floor else . end')
  echo "5h ${five}% · week ${week}% · cap ${CAP}%"
else
  echo "usage: no data yet · cap ${CAP}%"
fi
