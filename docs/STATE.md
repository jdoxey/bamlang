# State

## For John (kept to 10 lines)

- **Now:** Phase 1 decisions, working down `docs/ROADMAP.md`. D7 (DSL and declarative layout) is next.
- **Decided so far:** ADR-0001 Accepted (memory), ADR-0002 and ADR-0003, ADR-0004, ADR-0005, ADR-0006 Accepted (no user generics; G3 read as user-definable templates, vetoable): owned values, parameter-only borrows, pool handles; no reference counts. Memory safety is required (P3 yes).
- **Needs you:** nothing. To steer or veto, open a GitHub issue.

## Next action

Roadmap item **D7** (Full tier). Follow `docs/PROCESS.md`. Inputs: G11 (DSL / declarative layout without macros or annotations), ADR-0006 (trailing closures, copyable closures, field defaults), ADR-0001 (callbacks hold handles). Decide the mechanism and whether G11 is syntax-only for v1 (Q15; assume yes). Write a UI-like example (a view tree with a button that bumps a counter) and a config-like DSL as new conformance programs 13+ (append-only).

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
- 2026-11-13: D3 done. ADR-0003, ADR-0004, ADR-0005, ADR-0006 Accepted.
- 2026-11-13: D4 done. ADR-0004 Accepted.
- 2026-11-13: D5 done. ADR-0005, ADR-0006 Accepted.
- 2026-11-13: D6 done. ADR-0006 Accepted; ADR-0003 amended (scope). Corpus 01-12 written, unparsed.
