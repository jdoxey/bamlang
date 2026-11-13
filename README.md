# A new programming language, built mostly by Claude

- **Goals:** `docs/CHARTER.md`
- **Owner's rulings:** `docs/RULINGS.md`
- **Where things stand:** `docs/STATE.md`
- **What comes next:** `docs/ROADMAP.md`
- **How decisions are made:** `docs/PROCESS.md`
- **Decisions:** `docs/adr/`

## Running the autonomous session

```sh
systemd-inhibit --what=sleep:idle:handle-lid-switch claude --permission-mode auto
```

Then paste:

```
/goal Every item in docs/ROADMAP.md is ticked, shown by printing the file and a green three-OS CI run. Follow CLAUDE.md and every step of docs/PROCESS.md. After each finished step, update docs/STATE.md, commit and push.
```

To resume after closing the terminal, run the same command with `--continue` added.

## Usage cap

The session pauses when the Claude account's 5-hour or weekly usage reaches 85%, and resumes when that window resets. The status line shows `5h NN% · week NN% · cap 85%`. To change the cap, start with `BUDGET_CAP=70` in front of the command. Pauses are logged in `~/.claude/lang-budget/gate.log`.

To steer or veto: open a GitHub issue.
