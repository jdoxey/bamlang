#!/bin/sh
# Creates the GitHub repo from this folder and pushes it.
# Usage: ./bootstrap.sh <repo-name> [public|private]
set -e
NAME=${1:?usage: ./bootstrap.sh <repo-name> [public|private]}
VIS=${2:-public}
git init -q -b main
git add -A
git commit -q -m "Charter, rulings, decision process and ADR-0001 research

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NbS7G4RNbta4fgju1z1p81"
gh repo create "$NAME" "--$VIS" --source=. --push
gh label create needs-john --color D93F0B --description "Needs a yes/no from John" || true
echo "Done. Next: caffeinate -i claude --permission-mode auto"
