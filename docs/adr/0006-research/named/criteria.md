# Amendment 1 to ADR-0006: named arguments (issue #4). Criteria, written before the options

John's issue #4: "named function parameters similar to Swift. But much simpler than Swift i.e. every parameter has a
name, and there is no difference in internal / external names." Today 406 of 464 call arguments in the P3 corpus are
positional.

**Gate:** a parameter has exactly one name, used both inside the body and at call sites. Options with Swift's `_` or
separate external labels fail.

| Criterion | Weight | What a 5 means |
|---|---|---|
| Owner fit | 25 | Every call names every argument, as issue #4 asks, with no exemptions to learn |
| Simplicity (R6) | 20 | Fewest rules and exceptions; the parser alone can tell if a call is well formed |
| Readability | 20 | A reader of a call knows which value goes to which parameter without opening the declaration |
| Brevity (G4, P-GO) | 15 | Few extra characters per call on the corpus; no stutter like `push(item: item)` |
| Evolution | 10 | Adding a defaulted parameter, or renaming one, breaks few callers and is caught at compile time |
| Implementation risk | 10 | Function types, lambdas, enum payloads and the checker stay simple |
