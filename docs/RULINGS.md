# Rulings

**Owner:** John. Agents must not edit this file. These rulings bind every ADR.

| # | Date | Ruling |
|---|---|---|
| R1 | 2026-11-09 | **Threads are in v1.** |
| R2 | 2026-11-09 | **Reference counting is not garbage collection under G2**, "as a general rule — one is targeted, the other a blunt instrument". |
| R3 | 2026-11-11 | **The G2 test:** work done when a count reaches zero must be proportional to what is freed, and must never inspect live objects. Anything that examines live objects to decide whether they are alive is a GC run. Cycle collectors therefore fail G2. |
| R4 | 2026-11-11 | **Debug- and test-only tracing is allowed** (leak checks, exit reports). It must reclaim nothing and never ship in release builds. |
| R5 | 2026-11-11 | **Long free cascades in release builds are acceptable.** An incremental free queue is optional. |
| R6 | 2026-11-11 | **What "simple" means (G1):** the goal is "being more helpful and safe than C, without having too many different things for programmers to try to remember ... not necessarily simple to write with all the complexity hidden away, but simple rules which make it easy to reason about how the program is working while it is running". |
| R7 | 2026-11-13 | **Autonomy:** decisions are made by Claude using `docs/PROCESS.md`. "Even though some of these goals will conflict, please find the best approach that will satisfy as many of them, the best way possible." |
| R8 | 2026-11-13 | **The process:** for each question, (1) research, (2) generate many ideas from different angles, including crazy ones, (3) explore real, well-formed examples and learn from them, (4) repeat if necessary, (5) improve the process itself at any step. |
| R9 | 2026-11-08 | **Targets:** macOS, Windows and Linux, the most common version of each, tested with GitHub Actions. |
