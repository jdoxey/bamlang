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
| R10 | 2026-11-13 | **G3 and built-in containers (issue #3):** built-in parameterised types such as `List of T` are allowed. Only the standard library and `extras` may declare type parameters; user code may not. |
| R11 | 2026-11-14 | **Every argument is labelled (issue #4):** calls are written `f(name: value)`. |
| R12 | 2026-11-14 | **Inheritance, not protocols (issue #5):** "inheritance instead of something like protocols in swift, or extensions in ruby … we don't have 'final' classes, even for built-in classes", so that the implementation of a function "is either on this class, or one of the classes inherited from". |
| R13 | 2026-11-14 | **The 3 am test is part of "simple" (issue #5):** someone half awake, reading code they have never seen, must quickly find where a called function is implemented and how it works. |
| R14 | 2026-11-14 | **No extra abstract-only parents (issue #6).** A type has one parent. |
| R15 | 2026-11-14 | **Programmers can subclass built-in classes, including `List` and `Str`.** |
| R16 | 2026-11-14 | **The language is named `bam`, and source files end in `.bam`.** This replaces ADR-0012. |
| R17 | 2026-11-14 | **By version 1.0, installing bam is enough.** Programmers must not need to install LLVM, clang or another compiler separately. |
| R18 | 2026-11-14 | **CI may download a SHA-pinned llvm-mingw on Windows.** |
| R19 | 2026-11-14 | **Concept budget: 25.** A programmer should need about 25 core concepts to hold the whole language in their head. |
| R20 | 2026-11-14 | **Explore before building.** "We've jumped to creating the compiler way too soon. I want to explore the language and make tweaks at this point." Compiler work is paused until John ends the Explore phase. |
| R21 | 2026-11-14 | **When cutting a rule would cost a safety guarantee,** Claude analyses the options and picks the best one, and shows John what was traded. |
