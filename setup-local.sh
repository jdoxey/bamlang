#!/bin/sh
# Run once on the laptop, from the repo folder. Installs the 85% usage cap.
set -e
command -v jq >/dev/null || { echo "Install jq first: sudo apt install -y jq"; exit 1; }
D="$HOME/.claude/lang-budget"; S="$HOME/.claude/settings.json"
mkdir -p "$D"
cp .claude/hooks/statusline.sh .claude/hooks/budget-gate.sh "$D/"
chmod +x "$D/"*.sh
[ -f "$S" ] || echo '{}' > "$S"
cp "$S" "$S.bak"
jq --arg c "$D/statusline.sh" '.statusLine = {type:"command", command:$c}' "$S.bak" > "$S"
echo "Installed. Restart claude; the status line should show: 5h NN% · week NN% · cap 85%"
