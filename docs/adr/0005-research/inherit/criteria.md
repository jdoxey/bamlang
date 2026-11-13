# ADR-0005 amendment 1 (issue #5): criteria, written before the options

John's issue #5: "Preference is to just use inheritance instead of something like protocols in swift, or extensions in
ruby. This means we don't have 'final' classes, even for built-in classes … The reason … is to make it easy to find
where things are implemented. If you want to find the implementation of a function, it is either on this class, or one
of the classes inherited from." It also adds the **3 am test** to G1 (see `docs/PROCESS.md`).

**Gate (fixed by John):** implementation inheritance is the way to share and extend behaviour. There are no
protocols, extensions or monkey patching, and no `final` classes, built-ins included. Options that keep `iface`/`impl`
as a parallel mechanism fail the gate. Abstract methods on classes are allowed.

| Criterion | Weight | What a 5 means |
|---|---|---|
| 3 am findability | 25 | For any call `x.m()`, a half-awake reader finds every body that can run in at most 2 steps, which the rubric states: first the static type and its ancestors (upward), then, only where the call is visibly dynamic, the list of overrides (downward) |
| Owner fit | 20 | Inheritance as John describes it; nothing is final; built-ins can be subclassed |
| Safety (R6, ADR-0001) | 15 | No slicing, no fragile-base-class surprises in the built-ins, no hidden dynamic dispatch, ownership rules unchanged |
| Simplicity | 15 | Few rules; one way to model "a kind of"; the existing rules (methods in the type, `self.x`) kept |
| Extensibility (G7, G11) | 10 | Third parties add widget kinds, including containers, as ADR-0005's T3+ example required |
| Fit with earlier ADRs | 10 | ADR-0001 (owned values), ADR-0002 (no user type parameters), ADR-0003 and ADR-0005 whole-program checks, ADR-0006 named arguments, ADR-0008 C output |
| Implementation risk | 5 | vtables in C, type descriptors, debugger display |
