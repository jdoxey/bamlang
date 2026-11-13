# State

## For John (kept to 10 lines)

- **Now:** finishing ADR-0001 (memory model). Nothing is built yet.
- **Decided so far:** nothing final. Your rulings are in `docs/RULINGS.md`.
- **Needs you:** nothing. To steer or veto, open a GitHub issue.

## Next action

Roadmap item **D1**, step 3 of the process: real examples.

1. Write `chatsim` in C from `docs/examples/chatsim/SPEC.md`. Run it under AddressSanitizer with a script that hits every listed case. Put it in `docs/examples/chatsim/c/`.
2. Write its `room` and `user` parts in three models, in the closest real language, and run the same script:
   - **O1 pure ARC:** Swift classes.
   - **O4 simplified ownership:** Rust, using moves plus `Rc` only where forced.
   - **O9 owned values plus pool handles:** Zig, or C with a generation-checked slot map.
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

## Blocked

Nothing.

## Log

- 2026-11-13: repo set up from the planning conversation.
