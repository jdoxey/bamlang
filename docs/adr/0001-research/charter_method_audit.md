# Charter-compliance and methodology audit: ADR-0001 Memory management model

**Reviewed:** `/home/claude/reports/Memory management model ADR.md` against `docs/CHARTER.md` and `docs/adr/TEMPLATE.md`. Line numbers refer to the draft ADR unless prefixed `CHARTER:` or `TEMPLATE:`.

**Verdict.** The arithmetic is correct. The process and the rubric are not sound. The ADR proposes charter edits inside an ADR, which the charter forbids. Two scoring inconsistencies would each change the winner on their own. The fragility of the result is understated, and the ADR decides things that belong to the DSL, concurrency, stdlib and syntax ADRs. O3 may well be the right answer, but this draft does not show it.

**Arithmetic check (script-verified).** Every raw sum (385/335/390/380/295/330/380/270), every total, and all 70 cells of the weight-sensitivity table match to one decimal place. The winner named in each row is also correct. The errors are in the prose claims; see M6 and M9.

---

## Blocker

### B1. The ADR proposes charter edits and binding goal interpretations, outside the `needs-john` process
- **Where:** Q1 (line 551) drafts a new charter goal ("no use-after-free, double free or data race outside code explicitly marked unsafe"). Decision item 9 (line 523) puts a G2 definition on record "in the ADR". Q2(a) (line 552) and Q4(b) (line 554) settle what G2 and G3 mean.
- **Why it blocks:** CHARTER lines 6–8 say agents must not "propose edits to it inside other changes", and that a goal is challenged by opening a `needs-john` issue. CHARTER 11–12 and TEMPLATE 18–19 say that a decision which *would break* a goal is escalated, not made. If John answers no to Q2(a), meaning RC counts as a GC run, then O1, O2, O3, O4 and O7 all fail G2, because O2's CoW buffers are reference-counted too. If he answers no to Q4(b), every option fails G3. Either way the ADR cannot stand, so both questions are preconditions, not open questions. The ADR also never says what happens if either answer is no.
- **Fix:** Open three `needs-john` issues: the G2 meaning of RC and of an optional collector, the G3 status of built-in parameterised containers, and the missing memory-safety goal. Cite their numbers in the Charter table. Delete Decision item 9: if John accepts a definition, he writes it into the charter's Amendments table, and the ADR cites the charter. Remove Q1's draft goal wording. Add one sentence for each "no" outcome, e.g. "If RC is ruled a GC run, only O6 and O8 remain and this ADR is withdrawn."

---

## Major

### M1. The G3 gate is restated more loosely than the charter
- **Where:** Line 349 says the model "must not *require* templated types, macros or annotations". CHARTER line 26 says the language "Must not *have*" them.
- **Effect:** The word "require" is what lets O6 pass cleanly with an optional region-annotation path (line 438). It also gives O7 a pass-with-caveat on an optional `{.acyclic.}` (line 452), and lets O3 defer how "may escape" is expressed (line 519).
- **Fix:** Quote the charter's wording verbatim as the gate. If "required by the model" is the test the ADR wants, include it in the G3 `needs-john` issue from B1.

### M2. The proposed G2 definition does not clearly exclude O7, and leaves other cases open
- **Where:** Lines 348, 523 and 552(a): "no component reclaims memory by periodically scanning or tracing the heap independently of program points."
- **Problems:**
  1. ORC-style trial deletion runs synchronously inside a refcount decrement once the candidate-roots buffer passes a threshold. That *is* a program point, and the definition doesn't say what "periodically" means. Read literally, the definition arguably passes O7, yet line 451 says O7 "fails under the proposed definition".
  2. The definition drops the charter's word "*require*" (CHARTER 23). The charter's wording arguably permits an optional collector, so the definition is stricter than the charter on O7. Q2(b) half-acknowledges this.
  3. Two parts of the recommended design are never tested against the definition. Decision item 7 defers freeing of large graphs, which means a queue drained later. Decision item 4 adds an exit-time cycle report, which traces the heap but doesn't reclaim.
- **Fix:** Offer John a crisper candidate in the `needs-john` issue, for example: *"No component traces the object graph to discover unreachable objects. Every free happens at a point determined by the source: scope exit, a last reference dropped, or an explicit reset."* Then state how O7, deferred freeing and the debug cycle report each fare under it.

### M3. Gate results are inconsistent across options
- **O5 (line 424)** fails G3 partly because of `Send` "trait markers" and `Rc<RefCell<T>>` wrappers. But line 416 credits O4 because Rust's `Send` "is auto-derived", and line 410 passes O4 because RC is made "a built-in kind rather than a generic wrapper". O5 could get the same treatment. The only robust G3 failure for O5 is lifetime parameters on types (`Parser<'a>`). Narrow the justification to that.
- **O7 gets a caveat asterisk (line 490) but O3 does not.** O7's G3 pass depends on inferring acyclicity rather than annotating it. O3's G3 pass depends on two inferences that are at least as uncertain:
  - "may escape" must be a type form, not an attribute. Swift's is the attribute `@escaping`.
  - sendability must be inferred with no annotations. Swift needed `Sendable` and `@MainActor`.

  O6's optional region-annotation path likewise passes without a caveat.
- **Fix:** Apply one rule. Either every pass that depends on an unproven inference gets an asterisk (O3, O6, O7, and O1's Sendable layer at line 374), or none does.

### M4. The same property is counted in several criteria
- **Cycles and `weak`** are scored in Simplicity, Safety and Expressiveness for O1 (lines 369–371), O3 (397–399) and O7 (453–455). O7 earns 5/5/5, which is 55 of its 76 points, mostly from one property: "no `weak` needed".
- **O2's need to restructure graphs and callbacks** costs it in both Simplicity (line 383, "hit a wall and must be restructured") and Expressiveness (line 385).
- **O8's lack of closures** is likewise penalised in Simplicity (line 467) and Expressiveness (line 469).
- **Fix:** Define each criterion's scope in the criteria table, then rescore:
  - **Simplicity:** the number of concepts and rules a user must learn.
  - **Expressiveness:** which scenarios (a)–(f) can be written directly.
  - **Safety:** memory-safety violations only, with leaks either here or nowhere.

### M5. Scores on the decisive criteria are inconsistent. Each of the first two alone flips the winner to O1
- **Simplicity, O1 = O3 = 4.** O3's own justification (line 397) lists everything in O1 plus more: two meanings of `=`, `inout`, and `weak` for the identity subset. The Syntax budget (line 547) says O3 costs more than O1. Either O3 → 3 (O1 wins 77 to 73) or O1 → 5 (O1 wins 82 to 78). The Decision then uses G1 to break the O3/O4 tie (line 526), while the scoring gives O3 no G1 penalty against O1.
- **Implementation risk, O3 = 4 vs O6 = 3.** Line 507 says the notes rank "MVS + CoW" third, *behind* Inko-style owned values, and the ADR places Inko-style under O6 (line 47). So the approach the notes rank second scores lower than the one they rank third. O3's justification (line 400) also leaves out the runtime exclusivity check for `inout` on identity fields, which Consequences admits (line 532).
- **Safety, O1 = O3 = O4 = 4.** Line 398 argues that O3 confines leaks to a subset, but the score doesn't reflect it. O5 gets 5 despite `Rc` leaks and `unsafe`.
- **Performance & predictability, O3 = O2 = O6 = 4.** O3's main stated con is unpredictability: "silent O(n) copy", and "performance depends on code elsewhere". O6 has a measured +10.84% overhead and 16-byte references, yet scores the same.
- **Fix:** Put each criterion's scores for all options side by side and rescore. State the result plainly even if O1 wins.

### M6. The ADR understates how fragile the result is
- **Line 507** lists six single-step changes that flip the winner. The real list is longer:
  - *Any* one-step downgrade of *any* of O3's seven scores hands the win to O1. Performance, concurrency or tooling 4→3 leaves O3 at 76 against O1's 77.
  - *Any* one-step upgrade of any of O1's non-5 scores does the same.
  - O4's safety 4→5 or expressiveness 3→4 makes O4 the winner at 79, and O4's concurrency 4→5 ties it with O3 at 78. None of these is listed.
- **Line 9** says the gap is "smaller than a one-step change in any single disputed score". It is smaller than a one-step change in roughly 15 cells, not just the disputed ones.
- **The weight sensitivity is one-sided.** Every variant raises a weight; none lowers one. Two lowered variants would change the picture:
  - Concurrency, which has no charter anchor (line 360), dropped to 5: O1 and O3 tie at 78.9. Dropped to 0: O1 wins, 81.1 to 80.0. The criterion the charter never mentions is the one keeping O3 ahead of O1.
  - Simplicity at 15: O3 and O4 tie at 77.8.
- **Line 492:** "(5 for the halved variants)" refers to variants that don't exist, and the "all equal" row is not a +10 variant. Fix the header.
- **Fix:** Replace the flip list with one sentence: "Any single one-step change against O3 or in favour of O1 reverses the result." Add lowered-weight variants for Concurrency and Simplicity.

### M7. A quarter of the weight has no charter anchor, while charter goals go unscored
- **Where:** Criteria table, lines 353–361.
- **Problem:** Implementation risk (15) and Concurrency (10) are anchored to "—". Concurrency appears nowhere in the charter. Meanwhile:
  - **G4** (clean syntax) isn't scored, although the syntax budgets differ between options.
  - **G11**, which line 11 calls the crux, shares one 15-point bucket with graphs, shared state, OO, P-C and P-PY.
  - **G6, G9 and G10** are only folded into Tooling.
- **Fix:** Either tie each criterion to a charter ID or label it "project constraint, not charter". Ask John whether 25 discretionary points is acceptable (see M13). Consider scoring the syntax budget (G4) as its own criterion, or explicitly inside Simplicity.

### M8. Where the weights came from is asserted but not established, and the scoring knew the prior
- **Where:** Line 351 says the rubric is "the one given in the brief". Line 507 says "the base weights, which John set". Lines 9 and 509 say "the coordinator's O3 hypothesis".
- **Problem:** Nothing in the charter sets weights. If the brief was written by the coordinator rather than John, the claim in line 507 is false, and the recommendation loses its main legitimacy argument. The scores were also written knowing O3 was the prior, and both scores the ADR calls disputed lean toward O3 (M5).
- **Fix:** Confirm who set the weights, or delete "which John set". Add one sentence disclosing the anchoring risk. Drop the internal terms "brief" and "coordinator".

### M9. Q1's stated consequence is wrong
- **Where:** Line 551: "memory safety's weight of 15 should drop, and O8 … moves from last place toward the middle."
- **Recomputed:** With Safety at 5, O8 scores 55.6. With Safety at 0, it scores 56.5. Either way it stays 7th of 8, ahead only of the gated O5, and **last among recommendable options**. O3 still wins.
- **Fix:** Say that the answer doesn't change the ranking, and move the question itself to a `needs-john` issue (B1).

### M10. Charter "Problems" are applied inconsistently, and the P-SWIFT check is thin
- **O8** is marked "Recommendable? Yes" (line 488), although line 338 says it "reintroduces P-C". CHARTER 56–58 requires an ADR to show that an adopted feature *doesn't* bring back the listed problem. Mark O8 "No (P-C)", or argue the point.
- **The P-SWIFT guard** (Decision item 10, line 524) mostly lists exclusions G3 already enforces: macros, property wrappers, result-builder attributes, and `Sendable`/`@MainActor` attributes. It never lists what O3 *does* bring over from Swift:
  - the value/class split
  - `inout` with call-site `&`
  - `weak`
  - the escaping/non-escaping distinction
  - dynamic exclusivity traps
  - CoW
  - `mutating`-style methods (see M12)

  The charter's test is "too many features", so the honest check is a two-column table of what is kept versus excluded, with a count.

### M11. Scope creep into other ADRs and into decisions that belong to John
- **G11 / DSL (John's call):** Consequences (line 534) says flatly that the ADR "commits the G11 DSL to views as values…", and Context (line 11) builds on that. Meanwhile Q4(a) asks John for exactly this. Make it conditional, and state what changes if Q4(a) is no: O3's G11 strain then matches O1's, so the O3/O1 tie-break gets weaker.
- **Closures:** Decision item 5 sets non-escaping as the default and defers the escape marker to "the DSL ADR". Closure typing is a type-system or syntax matter, not DSL design.
- **Concurrency:** Decision item 6 decides sendability inference and move-on-send. Only the atomic vs non-atomic count is an ABI-level decision for this ADR (Q3). Defer the rest to the concurrency ADR.
- **Stdlib and G3:** Decision item 8 makes `Arena` and a handle store built-in containers. That is a G6 stdlib decision, and it quietly enlarges the G3 exemption that Q4(b) asks about.
- **Permanent bans:** Decision item 10 says "Permanently excluded", which binds future ADRs. Result builders are DSL (G11) territory. Only the charter binds permanently. Reword as "this ADR introduces none of…".
- **Unlabelled syntax:** `List[T]`, `Map[K,V]` (line 554) and `onTap = { save() }` (lines 552 and 554) appear in prose without the "illustrative only" label, and the square-bracket generics clash with `List<Node>` at line 262. The labelling of the code blocks themselves is fine (lines 83, 93, 155, 166, 203, 213).

### M12. The Syntax budget section leaves things out and contradicts the Decision
The budget (lines 538–547) omits several items the decision implies:
- **Mutating methods on value types.** Swift needs `mutating`, and Hylo uses an `inout` receiver. O3 needs one of these. It is not listed.
- **Scoped projections.** Line 534 rules out "returned references *outside a scoped projection*", which implies projections exist, i.e. a `yield`/accessor construct. Either count it or exclude it explicitly.
- **The weak-capture form.** Decision item 10 permits "a single weak-capture form", but line 545 says capture lists are "Not added". These contradict each other. It is a grammar production, so count it.
- **Identity-type declaration.** This is a new declaration production, not only a keyword.
- **Weak-reference unwrapping.** Every use of a `weak` field needs optional unwrapping, a G4 cost that depends on the optional-type ADR. Note the dependency.
- **Semantic rules users must learn.** These are where the G1 cost actually lives:
  - two meanings of `=`
  - inout exclusivity ("can't pass x twice")
  - `inout` can't be captured by an escaping closure
  - non-escaping closures borrow, while escaping closures copy values and strongly capture identity objects
  - runtime exclusivity traps on identity fields
  - the self-capture cycle lint
  - weak zeroing

  Add a "Rules users must learn" line.
- **The comparison at line 547 is skewed.** O1 also needs the weak-capture form and a Sendable/actor layer (lines 98, 374). O4's `shared` probably *replaces* the identity keyword rather than adding to it.

### M13. The open questions are mis-ordered, one lacks consequences, and some are missing
- **Order by impact:** Q5, the actual decision, should come first. Then the G2 and G3 preconditions, which become `needs-john` issues (B1), then Q4(a), then Q3, then Q6.
- **Q4(a)** has no stated consequence for "no" (see M11).
- **Missing questions:**
  1. Did you set these weights, and are the 25 points with no charter anchor (implementation risk, concurrency) acceptable? (M7, M8)
  2. Is concurrency in scope for v1? Lowering its weight flips the winner. (M6)
  3. Should charter Problems (P-*) act as gates? This decides O8's status. (M10)
  4. Do you accept that, under the stage-1 fallback, `List` semantics may still flip before the first public release? This bears directly on the main tie-breaker (M14).

### M14. The main tie-breaker contradicts the Fallback section
- **Where:** Lines 11 and 526 call `List`/`Map` value semantics "the one choice here that can't be undone later" and "must be fixed in v1". Line 536 makes O1, which switches `List` to reference semantics, the documented fallback "before any public release".
- **Problem:** So the choice *is* reversible through stage 1, and the strongest of the three judgement arguments is overstated.
- **Second problem:** The second judgement argument (staging removes O1's implementation-risk advantage) re-argues a score outside the rubric. If it's true, rescore Implementation risk. If not, drop the argument.
- **Fix:** Say "irreversible after the first public release" and weigh the argument with that in mind.

### M15. The Charter table fails the template in four places
- **G4 and G9 strains are never justified.** They are marked "strains" (lines 28 and 33), but the "worth accepting" paragraph (line 43) covers only G1, G11 and P-SWIFT. TEMPLATE 18 requires a justification for every strain.
- **G3 is marked "serves".** It should be "neutral" or "at risk pending the issue". A decision doesn't serve a prohibition by not violating it, and here it depends on built-in parameterised types that strain the charter's wording.
- **The effect values don't match the template.** "serves (pending John, Q2)" and "strains (mildly)" aren't among the template's allowed values. Use the template's values and put the qualifiers in the Why column.
- **The metadata is inconsistent.** Line 5 says the decision touches G1–G5, but the Charter table rates G5 neutral. Say "G1–G4, G11".

---

## Minor

1. **Template structure (lines 344–509).** The scoring and score-summary sections sit between Options and Decision. Order is preserved, but these are about 165 lines. Nest them under Options considered, or move them to an appendix after Syntax budget.
2. **Context holds the decision (lines 9–11).** TEMPLATE 9 says Context answers "what problem forces a decision now". Move the bottom line into a 3–5 line Summary above Context or into Decision. John will want it first, so a top summary is the right place.
3. **Scenarios (a)–(f) are never defined.** They are used from line 55 onward, but the list lives in the brief. Define the six scenarios in one table in Context.
4. **References readers can't follow.** "cross-cutting notes §6", "ownership notes Q2", "MVS notes Q5" and "regions notes Q5" (lines 47, 372, 389, 424, 441) point to notes John may not have. The key implementation-risk claims rest on them. Link them in the repo or summarise inline.
5. **"Rust (verified)" snippets (lines 192, 230, 241).** These are excerpts that won't compile standalone (`big`, `data`, `thread`, and the struct definitions are missing). Label them "excerpt from a verified program". Line 570 cites E0373 and E0277, which appear nowhere in the ADR.
6. **Score summary (line 484).** O7's "Recommendable?" should read "No, until G2 *and* G3 rulings", given the asterisk.
7. **Q2(b) (line 552).** "O7 would then tie O3 if simplicity were weighted 35" is true, but O7 also ties O3 at Safety 25 and Expressiveness 25, and trails by 2 at base weights. Give the base-weight result.
8. **Line 47** says "All eight options in the brief". Drop the process reference.

---

## Readability: what to cut (target under half the current length)

- **Options (lines 51–338):** Show the `onTap` callback scenario (c) for *every* option in one side-by-side block, since it is the crux. Keep at most one other snippet per option, and cut the rest. Six Zig and Nim blocks for options that are gated or last place is too many.
- **Per-option score tables (lines 363–473):** Collapse them into the single summary matrix with a one-line reason per cell, and move the full justifications to an appendix.
- **Evidence quality (line 17):** One sentence is enough: "No study measures learnability across these models; the scores are judgements."
- **Sources (lines 558–570):** These duplicate the inline links. Drop the section, or move it to an appendix.
- **Bottom line (line 9):** Replace the run of numbers with a three-row table (O3 78, O1 77, O4 76) and one sentence: "within one step of any score; Q5 decides."
