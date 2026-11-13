# CLAUDE.md

You are building a programming language, about 95% autonomously. John owns it and has little time.

## Every session, and after every context compaction

1. Read `docs/STATE.md`. It says what to do next.
2. Run `gh issue list --state open`. An open issue from John outranks everything else.
3. Do the next item. Update `docs/STATE.md`, commit, and push to `main` after each finished step.

## Binding documents (never edit these)

- `docs/CHARTER.md`: goals G1–G11 and problems P-*.
- `docs/RULINGS.md`: John's rulings. They override anything else except the charter.
- `.claude/settings.json`, `.claude/hooks/`, `~/.claude/lang-budget/`, `ci/adr-check.sh` and `.github/workflows/charter-guard.yml`.

Don't use shell commands to get around this. If one of them looks wrong, open a `needs-john` issue.

## How decisions are made

- Every design decision follows `docs/PROCESS.md` and ends in an ADR in `docs/adr/`.
- **No step may be skipped.** A Full-tier ADR is not Accepted until its example code exists, runs in CI on all three OSes, and a separate reviewer has attacked the winner. One Full-tier decision is normally many hours of work. If you finish one in under an hour, you skipped something: go back.
- **You decide.** When goals conflict, pick the option that satisfies the most goals best, and record what was traded away. Don't wait for John.
- Open a `needs-john` issue only when a decision would break a charter goal outright. Phrase it as a yes/no question with your recommendation, then carry on with other work.
- John vetoes by opening an issue. A veto reopens the ADR.

## Working rules

- Push straight to `main`. Don't open pull requests. After each push, check CI with `gh run list` and fix failures before starting new work. CI must stay green on Linux, Windows and macOS.
- Never force-push. Never delete files you didn't create this session.
- Keep documents short. John reads the top 10 lines of `docs/STATE.md` and nothing else unless he chooses to.
- If you improve the process, edit `docs/PROCESS.md` and add a line to its changelog. Don't edit this file.
- If a tool or install is blocked, note it under "Blocked" in `docs/STATE.md` and move to other work.
