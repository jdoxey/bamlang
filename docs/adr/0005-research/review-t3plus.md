# Adversarial review of T3+ (Opus reviewer, 2026-11-13; condensed) and decisions

**Verdict:** accept conditionally.
- **Scores:** T3+ as proposed is 79 (+4 over T2, so a tie). With fixes it is 81.5 (+6.5 over T2, +8.5 over T1).
- **Plain T3 (82)** fails a gate: a plugin can't add a container widget (G11), so it doesn't count as a winner.
- **Tie-break:** T3+ wins on reversibility. Provided functions, downcasts and `pub` can be added later without
  breaking programs.
- **Example required:** a T3+ example must exist before acceptance.

| # | Severity | Finding | Decision |
|---|---|---|---|
| F1 | fatal | A `dyn` call hides the call graph that ADR-0001 rule 6 and ADR-0003 rules 4–5 depend on. A plugin impl touching module state is reached from a crew child. | **Adopt.** A call on `dyn I` counts as a call to every `impl I` in the linked program. The check is whole-program at final link, and the error names the offending impl. |
| S1 | serious | Bare field names get shadowed, re-bound when a field is added, and silently captured by closures | **Adopt.** Fields and methods are reached only as `self.x` and `self.m()`. The `self` parameter itself (P-PY's complaint) is still never written. |
| S2 | serious | A `dyn I` parameter would force a move or a copy plus an allocation | **Adopt.** A `dyn I` parameter borrows any conforming value (a pointer plus vtable, no allocation). Boxing happens only at store sites (field, container, pool, payload, `take`). |
| S3 | serious | No defaults and no embedding: about 10 stubs per widget; adding a method breaks every library | **Adopt.** An interface may contain **provided functions**, which have bodies, can call required methods, can never be overridden, and resolve statically. Toolkits keep the required set small and return capabilities as data. Adding a *required* method is a breaking change; this is recorded. |
| S4 | serious | Four ways to do polymorphism (P-SWIFT); conflicts with ADR-0002 rule 5 | **Adopt.** This amends ADR-0002 rule 5 with one choosing rule: a closed set you own is an enum; a set others extend is an `iface` + `dyn`; both is an enum with one `Ext(dyn I)` variant; a single callback is a closure field. Records of functions are no longer an extension pattern. |
| S5 | serious | `dyn` has no copy, equality, hash or print; nothing to show in a debugger | **Adopt.** An interface may require built-ins (`iface Shape is copy, equals, show`), and a derived version satisfies them where ADR-0002 allows. Every vtable points at a type descriptor (name plus layout) for the debugger and a debug `show`. |
| S6 | serious | Receiver modes on pool entries, list elements and enum variants | **Adopt.** `take self` on a borrowed place is a compile error pointing to `take_out` or `remove_at`. Re-entering the same pool entry through the pool inside a `mut self` method is a documented trap (ADR-0001 rule 4). In a `mut self` match, arm bindings are places, and `self = V` replaces the value, dropping the old one. |
| S7 | serious | Construction is painful for declarative layout (G11) | **Adopt.** `pub` fields and field defaults. A literal is legal outside the module only if every field is `pub` and is either given or defaulted. No zero values; every field named. Pool-registered constructors return `Handle of T`. |
| S8 | serious | Where methods live is ambiguous | **Adopt.** Methods live only inside the type. `impl I for T` is a one-line conformance declaration, in T's or I's module, checked there (retroactive conformance only for existing methods). Two interfaces with conflicting signatures for the same name can't both be satisfied. |
| Minor | — | orphan wrapper; exact `fails` and receiver matching; no field and method with the same name; enum payloads built only in their module; naming convention (`Shape` / `ShapeKind`); tests belong to their module; a `dyn` moves into crews | **All adopted.** |

The honest rule count is 16 for D5, about 60 for the language so far.
