# Decision process

Use this for every design decision (ruling R8). Claude may edit this file to improve it; log each change at the bottom.

## Pick a tier first

| Tier | Use when | Budget |
|---|---|---|
| **Light** | Cheap to reverse later (naming, tool flags, file layout) | One pass, no subagents, ADR under 60 lines |
| **Full** | Hard to reverse once code or users depend on it (semantics, syntax, type system) | The five steps below, at most 2 loops |

## The five steps (Full tier)

1. **Research.**
   - Find how 4–8 real languages or tools solved it, and what went wrong for them. Cite URLs.
   - Save notes in `docs/adr/NNNN-research/`.
2. **Ideas.**
   - Write the criteria *before* generating options. Derive them from the charter and `docs/RULINGS.md`. Always include run-time transparency (R6).
   - Generate options from different angles: at least 6 sane and 4 crazy. Give each inventor a different starting lens.
   - Also consider **combinations** of options. The best candidate in ADR-0001 was a combination nobody had listed.
3. **Real examples.**
   - Write real, compiled, run code for the top 3 options. If our language can't run it yet, model each option in the closest existing language (for example Swift for ARC, Rust for moves, C for manual memory and handles).
   - Use the shared benchmark program in `docs/examples/` where it fits, so decisions can be compared.
   - Record what the code taught: line counts, bugs hit, what was awkward, what was hidden.
4. **Review and decide.**
   - A separate reviewer who did not invent the option tries to break it with concrete counterexamples.
   - Score against the criteria. Treat a gap under 5 points as a tie, and break ties using the examples from step 3, not the scores.
   - If nothing is clearly best, loop back to step 2 once. After 2 loops, pick the most reversible option and say so.
   - Write the ADR from `docs/adr/TEMPLATE.md`. Keep it under 300 lines; the research folder holds the rest.
5. **Retro.**
   - Add one line to "Lessons" below if the process could have been cheaper or caught something sooner.

## Which model does what

- **Opus (the main session):** criteria, choosing between options, reviews, writing ADRs, and any compiler code where a bug would be silent.
- **Sonnet (subagents, `model: sonnet`):** research and note-taking, generating option write-ups, writing example programs to a spec you give, test scripts, CI fixes and other mechanical edits.
- **Reviewer subagents use Opus.** A weaker reviewer misses the counterexamples.
- When unsure, ask whether a mistake would be caught by a compiler or test. If yes, Sonnet. If no, Opus.

## Budget rules (Pro plan)

- A hook caps usage at 85% of the 5-hour and weekly allowances. Usage is only measured between main-session replies, so a burst of subagents can overshoot. Keep bursts small.

- At most **5 subagents per step**, run in one batch. Two 20-agent rounds each used a whole 5-hour window.
- Subagents return their text to the coordinator, and the coordinator saves it. Subagents sometimes can't write files.
- Stop a step early when the last two results added nothing new.

## Lessons so far

- **Scores carry less than they seem to.** Weights invented by the model and one analyst per idea produce false precision. A 1-point gap is noise.
- **Agreement between agents is weak evidence.** They are the same model with the same priors. Compiled code and counterexamples are stronger.
- **Inventors overrate their own ideas** by about 15 points. Always use a separate analyst.
- **Define "simple" before scoring.** ADR-0001 counted rules to learn and missed hidden run-time work until John clarified (R6).
- **Write real code early.** Forty prose ideas taught less than one concrete program would have.
- **Check for an existing answer in the findings.** Both brainstorms kept pointing at pools and handles, and it was filed as a library detail.
- **Run a second, differently shaped example before the review closes.** In ADR-0001 the widgets program found eight rule gaps that the reviewer missed, because chatsim had no hierarchies and used global pools.
- **A GUI example is too big.** Use a small scripted simulation that has the same lifetimes (see `docs/examples/chatsim/SPEC.md`).

## Changelog

- 2026-11-13: lesson from ADR-0001's retro (second example).

- 2026-11-13: first version, written from the ADR-0001 work.
- 2026-11-13: added the 85% usage cap and the Debian and three-OS CI notes.
- 2026-11-13: Swift is installed, so it is the ARC model language (issue #1). Issues are checked before each roadmap step and after every push.
- 2026-11-13: first autonomous run (Sonnet) reached ADR 6 in two hours with no example code. Added the model split, the no-skipping rule and a CI check that blocks Accepted Full-tier ADRs without runnable examples.
