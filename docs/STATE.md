# State

## For John (kept to 10 lines)

- **Now:** Phase 1 decisions, working down `docs/ROADMAP.md`. D8 (compiler implementation) is next.
- **Decided so far:** ADR-0001 Accepted (memory), ADR-0002 and ADR-0003, ADR-0004, ADR-0005, ADR-0006, ADR-0007 Accepted (no user generics; G3 read as user-definable templates, vetoable): owned values, parameter-only borrows, pool handles; no reference counts. Memory safety is required (P3 yes).
- **Needs you:** nothing. To steer or veto, open a GitHub issue.

## Next action

Roadmap item **D8** (Full tier). Follow `docs/PROCESS.md`. Decide host language, backend (LLVM vs C vs own), debug info (G8) and coverage (G9) on macOS, Windows, Linux (R9). Tools on this machine: gcc, clang, rustc 1.100 (stable; set with `rustup default stable`), python3; no Swift, Zig, Go. Do a spike: compile corpus 01 and 02 by hand through each candidate backend and measure what debug info and coverage each gives. Then write `docs/PLAN.md` (milestones M0-M7 in detail).

Then continue down `docs/ROADMAP.md`.

## Open questions

- ADR-0001 re-open trigger: two real programs needing a user-built refcount layer.

## Blocked

- Swift and Zig are not installed. ADR-0001 used Rust (Rc/RefCell) as a proxy for ARC.

## Log

- 2026-11-13: repo set up from the planning conversation.
- 2026-11-13: D1 done. chatsim in C plus three models; ADR-0001 Accepted (O9+).
- 2026-11-13: D2 done. ADR-0002 Accepted.
- 2026-11-13: D3 done. ADR-0003, ADR-0004, ADR-0005, ADR-0006, ADR-0007 Accepted.
- 2026-11-13: D4 done. ADR-0004 Accepted.
- 2026-11-13: D5 done. ADR-0005, ADR-0006, ADR-0007 Accepted.
- 2026-11-13: D6 done. ADR-0006 Accepted; ADR-0003 amended (scope). Corpus 01-12 written, unparsed.
- 2026-11-13: D7 done. ADR-0007 Accepted (receiver closures; G11 = syntax only for v1).
