# CLAUDE.md

You are helping John design **bam**, a programming language. John owns it.

## Current phase: Explore

The compiler is paused. John is exploring the language and making tweaks. Read `docs/EXPLORE.md`; it replaces `docs/PROCESS.md` for now.

- **Do exactly what John's prompt asks, then stop.** Don't carry on to other work, and don't work down the roadmap.
- **End every reply with a summary of at most 10 lines:** what changed, the concept count, and anything John must decide.
- **Don't touch `compiler/` or `tests/`.** They are parked until John ends this phase.
- **`docs/TOUR.md` is the single description of the language.** Where an ADR disagrees with it, the tour wins. ADRs are history.

## Every session

1. Read `docs/STATE.md` and `docs/EXPLORE.md`.
2. Run `gh issue list --state open`. When you handle an issue from John, comment on it with what you did and close it.
3. Commit and push to `main` when the prompt's work is done. Check CI with `gh run list` and fix failures.

## Binding documents (never edit these)

- `docs/CHARTER.md`: goals G1–G11 and problems P-*.
- `docs/RULINGS.md`: John's rulings. They override anything else except the charter.
- `.claude/settings.json`, `.claude/hooks/`, `~/.claude/lang-budget/`, `ci/adr-check.sh`, `ci/tour-check.sh` and `.github/workflows/charter-guard.yml`.

Don't use shell commands to get around this. If one of them looks wrong, say so in your summary.

## Working rules

- Push straight to `main`. Don't open pull requests. Never force-push.
- Keep documents short. Prefer a code example to a paragraph.
- If a tool or install is blocked, say so in your summary and under "Blocked" in `docs/STATE.md`.
