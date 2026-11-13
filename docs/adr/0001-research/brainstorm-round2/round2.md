# Round 2: crazy ideas only

Read `/home/claude/brainstorm/brief.md` first. It covers the problem, the six scenarios, the covered options and the rubric. The same problem and scenarios apply here, with different rules for this round.

## Rules for this round

- **Only crazy ideas.** Break at least one assumption that every sensible design keeps. Examples:
  - objects die when someone stops looking at them
  - the program reboots itself
  - memory is never freed
  - the compiler runs your program to find out
  - time runs backwards
- **Feasibility is not required.** It doesn't matter whether today's hardware, OSes or LLVM can do it.
- **Be concrete anyway.** An analyst will take it seriously and try to break it, so state the rules and the mechanism precisely.
- **You may break the brief's gates or assumptions (G2, G3, determinism, and so on).** If you do, say which ones and why.
- **Don't repeat round 1.** Ideas already proposed and analysed in round 1:
  - single owner plus auto-cleared non-owning refs: Tissues, Charge & Decay, Cascade Links, Circulation, Double-Entry Claims, Precedent-Bound, Leasehold
  - freeing deferred to the end of a turn or tick: Tick & World, Tide, Chronicle, Spaces
  - groupings that are freed whole (estates, homes, depots, scenes, habitats)
  - ancestor or dominator-relative references: Kinship, Dominion, Ground Plane
  - whole-program outlives proofs plus RC groups: Heap Plan
  - callbacks that become no-ops when their captures die

  Every round-1 idea scored 47–68, against O1 at 83 and O4 at 82. Sane variations have been exhausted. Go somewhere else.

## Output

Write `/home/claude/brainstorm2/ideas/NN-<short-kebab-name>.md` with these sections:

1. Name
2. The crazy premise: which sacred assumption it breaks
3. Pitch, in one paragraph
4. The rules: a numbered list of every rule a programmer must learn
5. Under the hood
6. Scenarios (a)–(f): short pseudo-code for each, labelled "illustrative only — not a syntax decision"
7. What is new
8. Why it might be less crazy than it sounds, or more
9. Known weaknesses

Keep it under about 200 lines. Do no web research. Don't read any other inventor's file, `/home/claude/brainstorm/ideas`, `/home/claude/brainstorm/analyses`, `research_notes` or `reviews`.
