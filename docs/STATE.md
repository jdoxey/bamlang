# State

## For John (kept to 10 lines)

- **Now:** finishing ADR-0001 (memory model). Nothing is built yet.
- **Decided so far:** nothing final. Your rulings are in `docs/RULINGS.md`.
- **Needs you:** nothing. To steer or veto, open a GitHub issue.

## Next action

Roadmap item **D1**, step 3 of the process: real examples.

1. ~~Write `chatsim` in C from `docs/examples/chatsim/SPEC.md`. Put it in `docs/examples/chatsim/c/` with a `run.sh` that builds it and runs a script hitting every listed case. CI runs every `run.sh` on Linux, Windows and macOS, so use portable threads (Windows has no pthreads). Locally, also run it under AddressSanitizer.~~ Done 2026-11-13: `docs/examples/chatsim/c/`, green on all three OSes; clean under ASan, UBSan, LSan and TSan.
2. Write its `room` and `user` parts in three models, in the closest real language, and run the same script:
   - **O1 pure ARC:** C++ with `shared_ptr` and `weak_ptr` for every object (Swift isn't packaged for Debian).
   - **O4 simplified ownership:** Rust, using moves plus `Rc` only where forced.
   - **O9 owned values plus pool handles:** C with a generation-checked slot map.
3. Record what each taught, against the cases in `docs/adr/0001-research/memory-cases.md`. Pay most attention to cases 12, 14, 20 and 25.
4. Add a run-time transparency criterion (R6) to the rubric, re-score O1, O4 and O9, and have a separate reviewer attack the winner.
5. Decide. Rewrite `docs/adr/0001-memory-management.md` down to under 300 lines with Status "Accepted", moving the history into `0001-research/`.

Then continue down `docs/ROADMAP.md`.

## Open questions inside ADR-0001 (decide them as part of D1 or the item named)

- **P2, built-in generic containers under G3:** decide in D2.
- **P3, is memory safety required:** R6 says "more helpful and safe than C". Decide in D1.
- **Q5, weights:** set them yourself from the charter and rulings.
- **Q11, closures and `self`**, and **Q14, implicit or explicit copies:** decide in D1.
- **Q15, is G11 syntax only:** decide in D7. Until then, assume syntax only for v1.

## Environment

- This machine runs Debian 13. Installed: `build-essential`, `clang`, `rustc`, `cargo`, `jq`, `gh`. There is no `sudo` in the session; if another package is needed, list it under Blocked.
- CI runs `ci/run.sh` on `ubuntu-24.04`, `windows-2025` and `macos-26`. Keep all three green. If a runner label stops working, look up the current one and update `ci.yml`.
- A hook pauses the session at 85% of the account's usage. A long pause before a tool call is that hook, not a fault.

## Blocked

Nothing.

## Log

- 2026-11-13: repo set up from the planning conversation.
- 2026-11-13: chatsim C reference, `script.txt` and `expected.txt` committed. Ports O1/O4/O9 in progress.
- 2026-11-13: first run on Sonnet skipped the real-examples step. John reset `main`; that work is on the `sonnet-attempt` branch for reference only. Don't merge it or treat its ADRs as decided.
