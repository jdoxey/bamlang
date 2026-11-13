# State

## For John (kept to 10 lines)

- **Now:** Phase 1 decisions, working down `docs/ROADMAP.md`. D4 (errors and absence) is next.
- **Decided so far:** ADR-0001 Accepted (memory), ADR-0002 and ADR-0003 Accepted (no user generics; G3 read as user-definable templates, vetoable): owned values, parameter-only borrows, pool handles; no reference counts. Memory safety is required (P3 yes).
- **Needs you:** nothing. To steer or veto, open a GitHub issue.

## Next action

Roadmap item **D4** (Full tier). Follow `docs/PROCESS.md`. Inputs: ADR-0001 (`pool.get` returns an optional; stale handles are values not crashes), ADR-0002 (`Optional of T`, `Result of T,E` built-in), ADR-0003 (thread panic reported at join). Use chatsim cases 10, 14, 15 as examples. Decide exceptions vs results vs error values, and whether anything can be null.

Then continue down `docs/ROADMAP.md`.

## Open questions

- **Q15, is G11 syntax only:** decide in D7. Assume syntax only for v1.
- ADR-0001 re-open trigger: two real programs needing a user-built refcount layer.

## Blocked

- Swift and Zig are not installed. ADR-0001 used Rust (Rc/RefCell) as a proxy for ARC.

## Log

- 2026-11-13: repo set up from the planning conversation.
- 2026-11-13: D1 done. chatsim in C plus three models; ADR-0001 Accepted (O9+).
- 2026-11-13: D2 done. ADR-0002 Accepted.
- 2026-11-13: D3 done. ADR-0003 Accepted.
