# A new programming language, built mostly by Claude

- **Goals:** `docs/CHARTER.md`
- **Owner's rulings:** `docs/RULINGS.md`
- **Where things stand:** `docs/STATE.md`
- **What comes next:** `docs/ROADMAP.md`
- **How decisions are made:** `docs/PROCESS.md`
- **Decisions:** `docs/adr/`

## Running the autonomous session

```sh
caffeinate -i claude --permission-mode auto
```

Then paste:

```
/goal Every item in docs/ROADMAP.md is ticked, shown by printing the file. Follow CLAUDE.md. After each finished step, update docs/STATE.md, commit and push.
```

To resume after closing the terminal: `caffeinate -i claude --continue --permission-mode auto`.

To steer or veto: open a GitHub issue.
