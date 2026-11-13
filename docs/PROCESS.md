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
   - Write real, compiled, run code for the top 3 options. If our language can't run it yet, model each option in the closest existing language (for example Swift for ARC, Rust for moves, Zig or C for manual and handles).
   - Use the shared benchmark program in `docs/examples/` where it fits, so decisions can be compared.
   - Record what the code taught: line counts, bugs hit, what was awkward, what was hidden.
4. **Review and decide.**
   - A separate reviewer who did not invent the option tries to break it with concrete counterexamples.
   - Score against the criteria. Treat a gap under 5 points as a tie, and break ties using the examples from step 3, not the scores.
   - If nothing is clearly best, loop back to step 2 once. After 2 loops, pick the most reversible option and say so.
   - Write the ADR from `docs/adr/TEMPLATE.md`. Keep it under 300 lines; the research folder holds the rest.
5. **Retro.**
   - Add one line to "Lessons" below if the process could have been cheaper or caught something sooner.

## Budget rules (Pro plan)

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
- **A GUI example is too big.** Use a small scripted simulation that has the same lifetimes (see `docs/examples/chatsim/SPEC.md`).

## Changelog

- 2026-11-13: first version, written from the ADR-0001 work.
