# Explore phase

John is shaping the language by reading it, trying it on real programs and asking for changes (ruling R20). Nothing here is final until he says so. This file replaces `docs/PROCESS.md` during the phase.

## The three things that matter

| File | What it is |
|---|---|
| `docs/TOUR.md` | The whole language in one read. At most **25 concepts** (R19). The single source of truth. |
| `examples/*.bam` | Real programs written in the language as the tour describes it. They change whenever the tour does. |
| `docs/explore/tweaks/NNN-name.md` | One card per change John asks for. |

## The tour's format

- One heading per concept, written `## C7. Handles and pools`. CI counts these headings and fails above 25.
- Under each: what it is in two or three sentences, one example of at most 15 lines, and "what can go wrong" (the compile errors and traps this concept adds).
- A concept is something a programmer must hold in their head to read or write code. A sub-rule counts toward its concept, so keep each concept to at most 4 sub-rules. If a concept needs more, the design is too complicated: simplify it, don't split it.
- No rule may live outside the tour. If the examples need a rule the tour doesn't state, that is a gap to report.

## How a tweak works

John asks for a change, in a prompt or an issue. Then:

1. **Write the card** (at most 40 lines):
   - what John asked for, in his words;
   - before and after, as code from `examples/`;
   - the concept count before and after;
   - what it costs: safety lost, things that can no longer be written, run-time work added;
   - other parts of the tour it touches;
   - your recommendation, or two alternatives if there is a better way to get what John wants.
2. **If the prompt says "apply",** or the change is plainly what John wants and costs nothing: update the tour and every example, and run the checks. Otherwise stop and let John choose.
3. **Never apply a tweak that takes the tour over 25 concepts.** Say what would have to go.

A tweak doesn't need ten options, scores or an ADR. It does need the real before-and-after code.

## When a rule has to go (R21)

Most of the current rules exist to close a safety hole. When cutting one, prefer the first of these that works:

1. **A simpler, stricter rule that makes the unsafe thing impossible to write.** For example, threads may only be given moved or copied data.
2. **An explicit `else`** at the place it can fail.
3. **A compile error a reader can check within one function.**
4. **A run-time trap,** listed under the concept's "what can go wrong".

Never use a check that needs the whole program to understand, an inferred hidden flag, or undefined behaviour. Those fail the 3 am test (R13). Show what was lost with an example program that can no longer be written.

## Checks

- **Count:** `ci/tour-check.sh` fails if the tour has more than 25 concept headings.
- **Consistency:** after any change, reread every example against the tour. An example using something the tour doesn't describe is a failure.
- **A hostile read, for changes that affect safety:** one reviewer subagent tries to write a short program that the tour allows and that corrupts memory, races or leaks. Use Fable 5.2 while John's account has it, then Opus.

## Models and budget

- The main session is Opus. Use Sonnet subagents only for mechanical rewrites of examples.
- At most 3 subagents per prompt. The 85% usage cap still applies.

## Ending the phase

When John says the language is right: freeze the tour into `docs/SPEC.md`, write one passing and one failing test program per rule, regenerate `tests/`, and only then resume `docs/PLAN.md`.

## Prompts John can paste

**1. Consolidate (run once, first).**

```
Follow docs/EXPLORE.md. Do these, then stop:
1. Rename the language to bam (.bam) in docs going forward (R16). Leave compiler/ and tests/ as they are. Delete committed build output under docs/examples (target/ folders and binaries) and add them to .gitignore.
2. Write docs/explore/inventory.md: every rule in ADR-0001 to ADR-0009, including both amendments, in one table. For each: keep (in which concept), merge, or cut, and what is lost if cut.
3. Write docs/TOUR.md in the format EXPLORE.md gives: the best language you can make from those decisions in at most 25 concepts. Inheritance replaces interfaces everywhere (R12, R14, R15). Replace every whole-program or inferred check with something a reader can check in one function. For each run-time trap, decide whether it can become impossible to write, an explicit else, or a local compile error, and keep it as a trap only if not.
4. Write docs/explore/cuts.md: the 10 cuts that cost the most, each with before/after code and what was traded (R21).
5. Have one Fable reviewer attack the tour for contradictions, for rules the examples would need that it doesn't state, and for memory-safety holes. Fix what it finds without going over 25.
Finish with the summary EXPLORE.md asks for.
```

**2. Examples (run once, after you've read the tour).**

```
Follow docs/EXPLORE.md. Write examples/*.bam to match docs/TOUR.md exactly: chatsim, widgets, and four new programs of 80–150 lines each: a command-line word-frequency tool, a bank-account ledger with transfers and an audit log, a small HTTP-style request router with worker threads, and a subclass of List and of Str that does something useful. For every place the tour was not enough to write the program, add a line to docs/explore/gaps.md saying what was missing. Don't change the tour. Then stop.
```

**3. A tweak (as often as you like).**

```
Follow docs/EXPLORE.md. Tweak: <say what you want changed, or what feels wrong>. Write the card and stop.
```

Add "and apply it" to have it change the tour and examples in the same run.

**4. Make it runnable (optional, once the tour settles).**

```
Follow docs/EXPLORE.md. Build a throwaway interpreter in Python under proto/ that runs examples/*.bam, reusing docs/examples/syntax/p3n/parser.py where it helps. It must enforce every run-time trap in the tour; it need not enforce compile-time rules. Add a run.sh so CI runs every example on all three OSes. It is a toy for trying the language, not the compiler. Then stop.
```

**5. End the phase.**

```
I'm happy with the language. Follow "Ending the phase" in docs/EXPLORE.md.
```
