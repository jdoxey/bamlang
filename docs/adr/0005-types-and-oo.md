# ADR-0005: Types, methods and interfaces

- **Status:** Accepted
- **Date:** 2026-11-13
- **Tier:** Full (see `docs/PROCESS.md`)
- **Examples:** `docs/examples/types` (T3+ in `t3plus/`; rivals in `t1-records/`, `t2-modules/`, `t3-enum-ext/`)
- **Decided by:** Claude (ruling R7). John may veto by opening an issue.

## Context

The charter asks for native OO (P-C) without Python's explicit `self` (P-PY), Swift's feature zoo (P-SWIFT) or C++'s
complexity (P-CPP). Earlier ADRs fixed owned values and pools (0001), sum types with no user type parameters (0002),
crews (0003) and `fails` (0004). This ADR decides:
- methods and `self`;
- interfaces and dispatch;
- inheritance;
- construction;
- visibility.

Research (`0005-research/research.md`) found the main harms are implementation inheritance (the fragile base class,
slicing) and dispatch that the reader can't see (Go, Java, Swift extensions).

## Charter

| Goal / problem | Effect | Why |
|---|---|---|
| P-C | avoids | Methods, interfaces and encapsulation are native |
| P-PY | avoids | `self` is never written as a parameter. The header says only the receiver mode, and bodies use `self.x`. |
| P-SWIFT, P-CPP | avoids | One struct kind, one enum kind, one interface kind. No classes, inheritance, overloading, extensions or overridable defaults. |
| G1 (R6) | serves, with a strain | Dynamic dispatch is visible in the types (`dyn`). A choosing rule removes "many ways". 16 rules. |
| G3 | serves | `iface`, `impl`, `pub` and `is` are keywords, not annotations. No type parameters. |
| G7, G11 | serves | Third parties add kinds through `impl I for T` and `dyn I`, including containers. `pub` fields with defaults allow declarative literals. |
| G8 | serves | Every vtable points at a type descriptor, so the debugger shows `dyn Shape = Hexagon{…}`. |

## Criteria

From `0005-research/criteria.md`, written before the options:

| Criterion | Weight |
|---|---|
| Transparency of dispatch | 20 |
| Simplicity | 20 |
| Extensibility | 15 |
| Invariants | 15 |
| Syntax | 10 |
| Fit | 10 |
| Implementation risk | 5 |
| Performance | 5 |

## Options considered

There were 14 ideas (`0005-research/ideas.md`, `analysis.md`).
- **Ruled out:** no methods (P-C); structural interfaces (errors far from the cause); single-level inheritance
  (fragile base class); behaviour tables, tag dispatch, capability handles and validator type-states (fatal flaws).
- **The finalists:**
  - **T1:** interfaces as records filled at conversion.
  - **T2:** module = type, `dyn` only in pools.
  - **T3:** enum methods plus one `Ext` variant.
- **The combination T3+** (T3's closed enums, plus T1's interfaces with declared conformance and no hand-built records)
  was attacked and then fixed.

## What the real examples taught

See `0005-research/lessons-and-scores.md` and `review-t3plus.md`. All versions are in Rust, with design-only lines
marked `RUST-ONLY`.
- **T1's fill-at-conversion:** a misspelled method compiled, then overflowed the stack. Its hand-built records bypassed
  constructor checks.
- **T2:** every call and every `close` needed the pool.
- **T3:** the clearest to read, with the `Ext` arm as the only dynamic call. But plugins couldn't add container
  widgets, which fails G11 as a gate.
- **T3+** (loop 2, `t3plus/`, Rust model plus pseudo-syntax):
  - It prints the shared expected output, with 10 `RUST-ONLY` lines.
  - The plugin container `Tabs` took 21 lines; T1 and T3 can't write it at all.
  - Slider needed no stubs, because `focus_next` is provided.
  - Dynamic calls are visible only in types. The `Ext` arm is the only one written in the core.
  - The four expected compile errors are proposals, recorded for the M-phase conformance tests.

## Decision

**Adopt T3+.** The rules a programmer learns:

1. **Methods live inside the type** (struct or enum). The header gives the receiver mode, `self`, `mut self` or
   `take self`, and `self` is never written as a parameter. A function with no receiver is called as `Type.f()`.
2. **Fields and methods are reached as `self.x` and `self.m()`.** There are no bare names.
3. **`take self` moves the receiver.** It can't be called on a borrowed place; use `take_out` or `remove_at`.
4. **`mut self` on a pool entry** is a run-time-checked exclusive borrow. Reaching the same entry again through the
   pool traps (ADR-0001 rule 4).
5. **In a `mut self` match,** arm bindings are places, and `self = V` replaces the value.
6. **Interfaces.** An `iface` lists required signatures, matched exactly (receiver mode and `fails`). It may also hold
   provided functions: they have bodies, can call required methods, are never overridable, and resolve statically.
   `iface I is copy, equals, show` requires built-ins.
7. **Conformance.** `impl I for T` declares conformance in T's or I's module and is checked there. A type can't
   satisfy two interfaces whose same-named methods differ. A field and a method can't share a name.
8. **`dyn I` values.** A `dyn I` is an owned box, created by a move at a store site (field, container, pool, enum
   payload, `take`). A `dyn I` parameter borrows any conforming value without boxing.
9. **Calls on `dyn` are dynamic.** For the thread and module-state checks (ADR-0001 rule 6, ADR-0003 rules 4–5), such a
   call counts as a call to every `impl I` in the linked program. The error names the impl.
10. **`dyn` capabilities.** A `dyn` supports copy, equals, hash and show only if its interface requires them. Every
    vtable points at a type descriptor (G8).
11. **No inheritance and no overriding.** Shared behaviour is a provided function or a plain function.
12. **Visibility.** Fields are module-private unless marked `pub`. A literal outside the module is allowed only when
    every field is `pub` and is either given or has a default. There are no zero values and no partially initialised
    structs. Test files belong to the module they test.
13. **Constructors** are ordinary (usually `fails`) functions. Pool-registered types return `Handle of T`.
14. **Enum payloads** are built only in their module and matched anywhere.
15. **Choosing between them** (this amends ADR-0002 rule 5): a closed set you own is an `enum`. A set others extend is
    an `iface` plus `dyn`. Both together is an `enum` with one `Ext(dyn I)` variant, named `Shape` / `ShapeKind`. A
    single callback is a closure field. Records of functions are no longer an extension pattern.
16. **Clarifications from the T3+ example** (`docs/examples/types/t3plus/NOTES.md`):
    - Enums as well as structs may declare `impl I for E`, and so use provided functions.
    - A validated type keeps private fields. A DSL builds it through a constructor with named arguments and
      defaults (D6), not a separate `pub` "spec" type.
    - Built-in containers of your type (`Pool of Account`) get no user methods. Relational operations are functions in
      the type's module: `Account.transfer(pool, a, b, m)`.
    - Code isn't loaded dynamically in v1 (dependencies are linked from source, G7), so rule 9's whole-program check is
      sound. It is re-run at every link, and false positives are accepted; the escape is `Mutex` or `Atomic` state.
    - `s.intersects(s)` with `mut self` is an overlapping-argument error (ADR-0001 rule 4).
    - An enum with an `Ext(dyn I)` variant can derive `show`, `equals` and `hash` only if `I` requires them.
17. **Orphans.** Only T's or I's module can declare `impl I for T`. Otherwise, write a wrapper type.

### Scores (`0005-research/scores.py`, then the review's corrections)

| Option | Transp | Simp | Ext | Invar | Syntax | Fit | Impl | Perf | Total |
|---|---|---|---|---|---|---|---|---|---|
| **T3+ with fixes** | 4 | 3.5 | 4.5 | 4 | 4 | 4.5 | 4 | 5 | **81.5** |
| T3 as built (fails the G11 container gate) | 5 | 4 | 2 | 4 | 4 | 5 | 5 | 5 | 82 |
| T2 | 3 | 3 | 4 | 5 | 3 | 5 | 4 | 4 | 75 |
| T1 | 4 | 4 | 4 | 2 | 4 | 4 | 3 | 4 | 73 |

T3+ leads the eligible options by 6.5. The lead is thin, so it is also backed by reversibility. Provided functions,
`pub`, downcasts and more `is` capabilities can all be added later without breaking programs; removing interfaces
could not.

## Consequences

**Easier:**
- Dispatch is visible in types.
- Plugins add any kind of widget, including containers.
- Invariants hold through module privacy and `fails` constructors.
- The debugger shows the concrete type behind a `dyn`.

**Harder:**
- Adding a required interface method is a breaking change.
- Interfaces mean vtables and type descriptors in codegen.
- The check for F1 (rule 9) is whole-program at link time, so adding a plugin can break a crew far away; the error
  names the impl.
- `self.` appears in method bodies.

**Ruled out:**
- Inheritance and overriding.
- Structural interfaces.
- Hand-built vtables as a pattern.
- Bare field names.

**Changes to earlier ADRs:**
- ADR-0002 rule 5 (the choosing rule).
- ADR-0003's call-graph checks now include `dyn` impls.

**Passed on:**
- D6: spellings of `iface`, `impl`, `dyn`, `pub`, `is` and `self`.
- D7: DSL literals with `pub` and defaults.
- D8: vtables, type descriptors and the link-time check.

## Syntax budget impact

| Item | Count |
|---|---|
| Keywords | `iface`, `impl`, `dyn`, `pub`, `self`, `is` (receiver modes reuse `mut` and `take`) |
| Grammar | method declarations inside type bodies; the interface body; field defaults |

17 rules.

## Adversarial review log

| Review | Findings | Outcome |
|---|---|---|
| `0005-research/review-t3plus.md` | F1 `dyn` hides the call graph (fatal); S1 bare names; S2 boxing `dyn` parameters; S3 no defaults; S4 four polymorphism forms; S5 `dyn` lacks copy, equality and printing; S6 receiver modes; S7 construction for DSLs; S8 where methods live; plus minor points | All adopted as rules 1–16 |
