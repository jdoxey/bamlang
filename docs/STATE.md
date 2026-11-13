# State

## For John (kept to 10 lines)

- **Now:** Phase 1 decisions, working down `docs/ROADMAP.md`. D2 (generics and containers) is next.
- **Decided so far:** ADR-0001 Accepted: owned values, parameter-only borrows, pool handles; no reference counts. Memory safety is required (P3 yes).
- **Needs you:** nothing. To steer or veto, open a GitHub issue.

## Next action

Roadmap item **D2** (Full tier). Follow `docs/PROCESS.md`. Inputs: ADR-0001 needs built-in `List of T`, `Map of K,V`, `Pool of T`, `Handle of T`, `Optional of T`, `Mutex of T`. Decide whether built-in parameterised types satisfy G3 (P2) and whether users can write generic code. Use `docs/examples/chatsim/` as the example program.

Then continue down `docs/ROADMAP.md`.

## Open questions

- **P2, built-in generic containers under G3:** decide in D2.
- **Q15, is G11 syntax only:** decide in D7. Assume syntax only for v1.
- ADR-0001 re-open trigger: two real programs needing a user-built refcount layer.

## Blocked

- Swift and Zig are not installed. ADR-0001 used Rust (Rc/RefCell) as a proxy for ARC.

## Log

- 2026-11-13: repo set up from the planning conversation.
- 2026-11-13: D1 done. chatsim in C plus three models; ADR-0001 Accepted (O9+).
