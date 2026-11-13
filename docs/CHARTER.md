# Project Charter

**Owner:** John. **Status:** Binding.

This file holds the project's non-negotiable goals. Only the owner can change it.
Automated agents (Claude included) must not edit it, propose edits to it inside
other changes, or work around it. To challenge a goal, open an issue labelled
`needs-john` and explain the conflict.

Every ADR must cite the goal IDs below that it serves or strains (see
`docs/adr/TEMPLATE.md`). If a decision would break a goal, it is not made.
It is escalated.

Goal IDs are permanent. If a goal is retired, it is struck through, not
renumbered, so old ADR references stay valid.

---

## Goals

**G1. Simplicity.** Must be much simpler than most programming languages today.

**G2. No garbage collector.** Must have memory management that doesn't require a
garbage collection run (like Java and Go do).

**G3. No templates, macros or annotations.** Must not have templated types, macros
or annotations. These make code hard to understand.

**G4. Clean syntax.** Syntax must be as clean and simple as possible (non-verbose).
In the early stages we should be refactoring to make sure this stays true as
features get added.

**G5. No significant whitespace, no mandatory semicolons.** Syntax must not be
indentation dependent (like Python), and must not require semicolons at the end
of every statement like Java, C, C++.

**G6. Standard library.** Must have a good standard library with Lists, Arrays,
Time, Calendar, etc.

**G7. Build and dependencies.** Must include build and dependency management
tools; third party libraries are just GitHub repos (maybe eventually not just
GitHub).

**G8. Debugging.** Must include debugging tools.

**G9. Coverage.** Must include code coverage tools.

**G10. Unit testing.** Must include unit testing support.

**G11. DSLs.** Must have good DSL / declarative layout support.

---

## Problems in other languages we want to address

These are the reference points for design trade-offs. An ADR that adopts a
feature from one of these languages must show it doesn't bring back the problem
listed here.

| ID | Language | Problem |
|----|----------|---------|
| P-PY | Python | Not a compiled language, too slow; and passing `self` makes OO weird; indentation based syntax is awkward |
| P-C | C | Great but unsafe and no native OO support |
| P-CPP | C++ | OK, but things like .h files, templated types and macros make it too complicated to read |
| P-SWIFT | Swift | Overly complicated, too many features |
| P-GO | Go | Decent except for garbage collection, and tendency to over-shorten everything |
| P-RUST | Rust | Too steep a learning curve |
| P-JAVA | Java | Decent but garbage collection and the JVM are a pain — let's go native |

---

## Amendments

| Date | Change | By |
|------|--------|----|
| 2026-11-07 | Initial charter | John |
