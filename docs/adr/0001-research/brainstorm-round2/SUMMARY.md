# Round 2 brainstorm: 20 "crazy" memory-management ideas compared with O1 and O4

**Inputs:** `brief.md`, `round2.md`, `CHARTER.md`, `ideas/01–20`, `analyses/01–20`, round 1's `SUMMARY.md`, and ADR-0001.

**Method:**
- Every score is the analyst's.
- A script recomputed every total as Σ weight × score / 5, and all 20 analyst totals match.
- K1–K11 are round 1's kernels. N1–N8 are new in this round.

---

## 1. Bottom line

- **No crazy idea beat O1 (83), O4 (82) or round 1's best (68).**
  - The range was 45–63, with a mean of 54.0.
  - The best idea, Tape & Keepsake (03, 63), fails G2. Four of the top five fail G2 or lean towards failing it.
  - The best idea with a clean G2 pass is Underworld (17, 62).
- **The gap has the same cause as in round 1.** Implementation risk and Simplicity make up 61% of the average 29-point gap to O1.
  - 19 of 20 ideas scored 1 or 2 on implementation risk.
  - No idea beat O1's Simplicity score of 4.
  - The three that matched it (08, 16, 18) are hint-free reachability maintenance, which is a collector under another name.
- **What breaking the assumptions taught:** the lifetime fact can't be recovered from the pointer graph, from access patterns, from a clock, from a forecast or from tests.
  - Three analyses derived results that rule out whole families of designs (08, 11, 15).
  - Every design that dropped reachability semantics failed by losing data (15 of 20). The rest failed by leaking.
  - So the information has to come from the programmer (`weak`, `shared`, moves) or from a type system.
- **The useful output is tooling and framework conventions, not a new model.**
  - **N1:** scoped leak expectations, with tests that fail on a leak. Proposed by 13 of the 20 analyses.
  - **N2:** callbacks owned by an anchor, so closing a window releases its callbacks. This is an alternative to K1 with no silent skips.
- **The decision is unchanged: O1 83.0, O4 82.0.**
  - The kernels help O1 qualitatively.
  - One conditional risk for O4: re-entrant `shared` traps would put O4 at 79.0.
  - Stop generating models and run the spike.

## 2. Ranked table

Every verdict was "kernel worth stealing", so the Kernel column names the part worth keeping.

| # | Idea (file) | Assumption broken | Analyst | Self | Kernel kept | What it is | Fatal flaw |
|---|---|---|---|---|---|---|---|
| 1 | Tape & Keepsake (03) | A program must reclaim memory as it runs | **63** | 71 | Phase region with a reference-free exit (N5); a never-free debug allocator | Nothing is freed within a life. Only reference-free `keep` values survive a re-run of `main`. | Fails G2: rebirth is a copying collector. Edits that aren't kept are lost. Batch jobs run out of memory. |
| 2 | Underworld (17) | A dangling reference is a bug | 62 | 74 | Death certificates (K2); `retire` (N6) | The first store owns the object. Other references become ghosts, and using one "haunts", which can be caught. | Graves set by the first store form cycles, so its own scenario (b) leaks. Overwrites silently delete data. Every dereference can be a non-local exit. |
| 3 | Seniority & Runoff (16) | Reference strength is a static choice | 61 | 79 | Age-inversion detector and `recall` (N3) | References from old objects to young ones are counted "votes". Back-edges are "petitions". A local runoff runs when a count drops to zero. | G2 leans fail (trial deletion). Four holes in the spec, including a use-after-free. O(n²) walks with a cursor. No way to say a reference is non-owning. |
| 4 | Terrain (08) | Memory has no geometry | 60 | 72 | Leak detection at the moment of the cut (N1) | A 3D grid heap bounds how many references an object can have, so each object can recompute its own liveness. | Decremental reachability has no bounded cost per store. G2 leans fail. Ordinary `join` deadlocks. |
| 5 | Actuary (18) | Death is a fact, not a forecast | 58 | 76 | Test-time tracer (N1); cohort allocation (N8) | A trained life table predicts each object's death tick. Stores only ever push predictions later. | A concurrent tracing collector scheduled by forecast (G2 fail recommended). Two use-after-free races. Untrained sites leak. |
| 6 | Standing Calls (09) | Objects are heap data | 57 | 67 | Re-entrancy test (§6) | Each object is a suspended call on its own stack, reached through non-owning "doors". | It is O2 plus actors. Synchronous callbacks fail with `busy`, which silently loses updates in (c). |
| 7 | Dreamed Regions (11) | Lifetime placement is fixed by the source | 56 | 75 | Cycle-site test report (N1, N3) | A "dream" pass learns which region each allocation goes in. Regions are freed whole. | Cyclic graphs that churn must either leak or bloat under any placement per allocation site. Training changes semantics. |
| 8= | Everything Is a Path (14) | A reference means one object's identity | 55 | 74 | Debug heap browser; `x.owner` for O4 (K8) | The heap is a filesystem tree, and non-owning references are paths looked up again on each use. | Index paths point at a different object after a delete, so the wrong email gets deleted. Callbacks wired in a constructor are dead on arrival. |
| 8= | Dress Rehearsal (05) | Compiling depends only on the source | 55 | 70 | Teardown-leak tests (N1); a tool that suggests where `weak` goes (N3) | A SAT solve over traced test runs decides which slots own and which borrow. | Test coverage becomes the safety boundary. A thread path never rehearsed corrupts the reference counts. |
| 10= | Witnesses (01) | References keep things alive | 53 | 65 | Teardown when an anchor ends (N2); a leak check when an anchor closes (N1) | An object lives while some external "witness" (window, request, turn) can see it. | Removing an object doesn't free it until its witness ends. Use-after-free across `await`. |
| 10= | Reincarnation (04) | The process heap persists | 53 | 64 | Event-generation leak audit (N1) | Each event runs in a disposable arena. Only a pointer-free MVCC store survives. | Memory grows with total allocation. I/O is unsound when an event is re-run. A save can be reported before it fails. |
| 10= | Whereabouts (12) | A program holds references | 53 | 68 | Live-object registry (K2) | Variables hold queries. A query that matches nothing silently does nothing. | Writes to a missing record vanish (lost money). Adding a log line moves a transaction boundary. |
| 10= | Slow Match (13) | Objects live while referenced | 53 | 65–72 | Subscriptions owned by an event (N2); TTL cache (N4) | A tree of fuses rooted in scopes, timers and events. The first store anchors an object. | Fuse cycles leak its own (b) and (c). An idle fuse burns data that is still in use. |
| 10= | PIDs (19) | Objects share one address space | 53 | 71 | Leak report by creation tree (N1) | Every object is an isolated cell with a monitor, and its creator is its parent. | Anything a factory makes dies with the factory. `gone` cascades. Nested monitors deadlock. |
| 15 | Tempo (15) | Lifetime is reachability, owner or scope | 52 | 68 | Expectations on domain clocks (N1); TTL map (N4) | Objects expire on domain clocks, and each reference is a ticket with an expiry. | `renew` can't reach existing tickets, so its own (d) breaks. Short tickets wrap around into a use-after-free. |
| 16 | Amnesia (20) | Freed means gone | 50 | 64 | `Memo` with a chaos mode (N4); callbacks addressed by key | State is an acyclic RC tree. Everything else is evictable memo data. | Cache snapshots prevent in-place mutation. Memory is bounded by history, not by the budget. |
| 17= | Scent Trails (07) | Reachable implies alive | 48 | 62 | Staleness report clocked by allocation (N1) | An object that hasn't been read for W bytes of allocation is freed even though it's still reachable. | Deselecting an item deletes it (data loss). Generation counters wrap around into a use-after-free. |
| 17= | Spreadsheet Heap (06) | A held reference is in memory | 48 | 64 | `Memo` (N4) | References are recipes stored in an evictable table, and state is positional. | Recipes dangle or need a GC. Eviction can make `fib` exponential. A missing `key` writes doc1 into doc2. |
| 19= | Unhappen (02) | Freeing goes forward and stores are permanent | 45 | 63 | Registrations owned by their owner (N2) | Acts are retracted, and stores made into them are undone back to their earlier values. | Reverting a value can bring back an old session. Use-after-free on publication. |
| 19= | Antiprogram (10) | Making and freeing are separate acts | 45 | 66 | Un-registration by identity on close (N2); `open;close` tests | The compiler writes an inverse: `close` replays `open`'s undo log. | Undoing values is unsound when spans don't nest. Swaps destroy elements. |

**Self-scores:** 19 inventors gave one, and every one overrated their idea, by 8 to 21 points (mean +15.1; round 1's mean was +17).

## 3. What the crazy premises taught

**L1. The lifetime fact is intent, and nothing the program does recovers it.**
- **Tests can't recover it.** One slot used two ways gives an unsatisfiable solve (05).
- **Access patterns can't.** Reachability gives false positives (leaks), and recent use gives false negatives (data loss) (07).
- **Telemetry can't.** It is evidence, never authority (11).
- **A forecast can't.** It only schedules the collector (18).
- **Implicit owner selection is the worst point in the design space.** It infers ownership and then hides it. 16 ideas across both rounds tried it, and all 16 hit action at a distance.

**L2. Three results rule out whole families of designs.**

| Source | Result |
|---|---|
| Terrain (08) | Deterministic death, cycle completeness, no hints and bounded work per store can't all hold at once. Decremental reachability has no bounded algorithm per deletion. |
| Dreamed Regions (11) | For cyclic graphs whose nodes are born and die independently, no static grouping avoids both leaks and unbounded waste. This explains why all 8 of round 1's region designs plateaued. |
| Tempo (15) | Without reachability, a reference can be checked against the object (generations), against a clock (extending a lifetime then means tracing), or not at all. |
| Supporting (01, 06, 20) | Tracking only the creation of edges must free late. "Free at any time" is safe only for data that has a recipe, and proving that is effect typing. |

**L3. Breaking reachability turns leaks into data loss.**
- **The split is clean.** The 5 designs that kept reachability (05, 08, 11, 16, 18) leaked. The other 15 killed things too early: silent no-ops, writes to the wrong object, lost writes.
- **Too alive is the safer default.** A leak with a detector beats data loss with a test mode, and this holds especially in UI code.
- **Recoverable dereferences are costly.** A safe use-after-free costs one compare. A recoverable one makes every line a possible exit point.
- **This bears on K1.** K1 is a "too dead" mechanism, and 17 C5 adds another case where a save is lost.

**L4. Scenario (c) is not really a memory problem.** Four framings, best first:
1. **Unregistration (02, 10).** Undoing a registration by identity is safe because it commutes with other operations. Undoing a value is unsafe.
2. **Anchors that really end (01).** The cycle is harmless if closing the window is a hard teardown.
3. **A closure is an unnamed pointer to state (04, 06, 20).** If it captures an address that is resolved at call time, there is nothing to retain. This is the ADR's Q9.
4. **Re-entrancy (09).** With non-owning handles, the cycle becomes a `busy` failure. Test this for both O1 and O4.

**L5. The lifetimes that don't nest are domain events, and there are few of them.**
- They are windows, peers, requests, sessions and timers.
- Handling them needs a library, not a language feature (13).
- Long-lived state that doesn't nest needs identity plus explicit deletion, i.e. slot maps (04).

**L6. Identity references and role references are different.**
- "This exact object" is not the same as "whatever currently fills this role" (14).
- Making the role reference the only non-owning kind causes silent retargeting when indices shift. Cases found: a missing key saving doc1 into doc2 (06 C6), deleting the wrong email (14 C1), mis-paired avatars (15 C7), and editing the wrong line (20 C6).

**L7. Complexity is conserved, and bugs cluster at its boundaries.**
- **Every premise moved complexity to a boundary:** rebirth (03), purity (20), transactions (04, 12), a hidden cost model (16), or runtime errors (17).
- **A log line can move the boundary** (12 C2).
- **Batch programs never reach a boundary:** 01, 02, 03, 04, 11, 20.
- **One long-running participant stalls reclamation for everyone:** 01, 04, 15, 18, 20.
- **This confirms K4.**

**L8. Isolation trades races for deadlocks.** 9 of 20 designs deadlocked or re-entered, and STM combined with I/O is unsound (04, 12).

**L9. Profile and training artifacts may tune performance, never meaning.**
- 05, 11 and 18 each leaked semantics through training data: finalizer timing, move vs copy, locking, OOM.
- 05 and 11 also broke the requirement that debug and release builds behave the same.

## 4. Kernels

### New kernels (not in K1–K11)

**N1. Scoped leak expectations and tests that fail on a leak.** *(13 analyses)*
- **What it is:**
  - In debug and test builds, an anchor (window, connection, request, test case) declares which objects must die with it.
  - When the anchor ends, any survivors are reported with their retaining path and the edge to make `weak`.
  - The test runner fails on new leaked cycles by default.
  - Cheaper heuristics (staleness measured by allocation, survivors across event generations) feed the same report.
- **Fit:** both, but mostly O1, because O1's simplicity cost *is* the silent `weak` mistake. No new user rule.
- **Risks:**
  - It is bound by test coverage.
  - It needs debug-only tracing, which needs a G2 ruling (widen P1).
  - Caches need an allowlist.
  - It must scope to the anchor's subtree to stay cheap.
- **What it adds to the ADR:** the ADR has an exit-time report. N1 moves detection to the moment of the cause and makes it a gate.

```text
// illustrative only — not a syntax decision
test "closing a window frees its editor" {
    w = Window(); e = Editor(w)
    expect(e).diesWith(w)          // debug/test only
    w.close()
}   // FAIL: Editor#3 still retained: App.bus → closure(editor.x:12) → Editor
```

**N2. Callbacks owned by an anchor: closing releases callbacks and registrations.** *(01, 02, 10, 13; 09 and 15 point the same way)*
- **What it is:**
  - Standard-library anchors that have an external end (Window, View subtree, Connection, Request, Timer) get a deterministic `close()`.
  - `close()` drops every callback the subtree holds and removes every registration made through the anchor, by identity and in reverse order.
  - It never reverts values.
- **Under O1:** the editor → window → button → closure → editor cycle breaks at close, and `self` captures stay strong.
- **Fit:** O1, and O4 inside `shared`. No new rule if registrations take the anchor explicitly (`bus.on(evt, owner: w) {…}`).
- **Reject 10's variant**, which infers the anchor implicitly from dynamic extent.
- **Risks:**
  - The trigger must be an explicit end event, never `deinit`, because the cycle stops `deinit` from running.
  - Anchors that are never closed still leak, and N1 is the backstop.
  - `weak` is still needed for (b).
- **Why it matters:** it is a different answer to Q11. K1 trades a silent leak for a silent skip. N2 keeps captures strong and breaks the cycle at a point the OS supplies, so there is nothing to skip.

**N3. A tool that suggests where `weak` goes, explaining with pairs of traces.** *(05, 08, 11, 16)*
- **What it is:**
  - From N1's test traces, solve for the minimal set of `weak` edits.
  - Where tests disagree, show two concrete runs that need opposite answers.
  - As a cheap static and debug check, flag back-edges from young objects to old ones (16).
- **Fit:** both. It is advisory, so the human keeps the keyword. It extends K6.
- **Risks:** solver complexity (start with the heuristic) and coverage.

**N4. A standard-library `Memo` and `TtlCache`, with a chaos test mode.** *(06, 07, 13, 15, 20)*
- **What it is:**
  - A budgeted cache whose entries carry a recompute function or a TTL.
  - `--amnesia` evicts everything after every event, and the test fails if behaviour changes.
- **Fit:** both. It handles the pure half of (d).
- **Risks:**
  - Inputs must be held by value or key, not as RC snapshots.
  - The eviction cost has to include transitive recompute.
  - Evict only at explicit points, never on a background thread, so G2 is never in question.

**N5. A phase region with a reference-free exit.** *(03)*
- **What it is:** `batch { … }` bump-allocates, and its result must be a reference-free value that is copied out.
- **Fit:** O4. +1 rule, opt-in.
- **Risks:** stores into outer objects also escape (`log.add(line)`), so it needs a store barrier or a static restriction. It overlaps K11. Later.

**N6. Logical retirement: `retire x because "…"`.** *(17)*
- **What it is:** it nils weak references immediately. Later strong dereferences trap and report the reason.
- **Fit:** O1. About +1 rule.
- **Priority:** low. It must trap, not recover.

**N7. A zeroising `SecretBytes`.** *(03 C8)*
- **Why:** an immutable `String` can't be wiped.
- **What it is:** a buffer zeroed on free and excluded from debug journals.
- **Fit:** both. Low risk, and highly relevant to IAM and banking code.

**N8. Cohort allocation guided by profiles.** *(18, 11)*
- **What it is:** pages are grouped by predicted lifetime, but ARC or ownership still decides when objects die.
- **Status:** later, and for performance only.

**Passed to other ADRs:**
- **Concurrency:** a built-in actor or monitor-guarded `shared`, but only with async calls (L8).
- **FFI:** `extern cell` process isolation for C libraries (19).
- **Syntax:** a class written as a standing function (09).
- **Debugging:** record and replay per handler (04), and a virtual test clock (13).

### Effect on round-1 kernels

| K | Effect | Evidence |
|---|---|---|
| K1 | **Risk confirmed and refined.** Silent no-ops showed up in 09, 12, 14, 17 and 20, and 17 C5 adds a new lost-save case. Options: an explicit `else` at registration instead of a silent skip, or N2 instead. | 09, 12, 14, 17, 20 |
| K2 | **Strongly extended.** 18 of 20 analyses proposed liveness tooling. N1 and N3 are the substantive additions. | all except 06, 20 |
| K3 | **Extended:** debug builds must not use a different memory model. | 05 C7, 11 C7 |
| K4 | **Confirmed again.** Freeing deferred to turns or epochs broke under nesting, `await` and long participants, and finalizers re-entered. | 9 analyses |
| K5 | **Confirmed.** Rosters indexed by weak references mis-paired. | 15 C7 |
| K6 | **Extended** by N3's age heuristic. Reject "`shared` may only hold data that is acyclic by type". | 14, 16 |
| K7 | **More evidence:** isolation deadlocks, STM with I/O, epoch stalls, and freezing graphs that contain uncounted back-edges. | 9+ |
| K8 | **Refined:** make it an optional, non-storable `owner` borrow that is updated on moves and restricted to heap-boxed owners. | 14, 16, 19 |
| K9 | **Confirmed.** | 01, 02 |
| K10 | **Strengthened to "no":** islands only for data that dies together. | 11 |
| K11 | **Confirmed.** N5 is a version users can see. | 4 analyses |
| Q9 | **Confirmed and refined:** keys must be stable and generation-checked. | 06, 14, 15, 20 |

## 5. Across all 40 ideas

**Score distribution**

| | Range | Mean | Median | Ideas at 60 or above |
|---|---|---|---|---|
| Round 1 | 47–68 | 59.9 | | 13 |
| Round 2 | 45–63 | 54.0 | | 4 |
| All 40 | max 68 | 57.0 | 56.5 | |

- The best idea is 14 points below O4.
- "Going crazy" cost about 6 points and raised no ceiling.
- 38 of 40 ideas scored 2 or less on implementation risk.
- No idea in either round scored above 4 on simplicity.

**What every failing design had in common:** each one replaced the programmer's cheap statement of lifetime with a substitute, and each substitute failed at its own boundary.

| Substitute | Ideas (round 2) | Range | Failure |
|---|---|---|---|
| Reachability maintained by the runtime, with no hints | 08, 16, 18 | 58–61 | Unbounded work per store. G2 leans fail. |
| Learned from tests or training | 05, 11 | 55–56 | Coverage becomes the safety boundary. Debug ≠ release. |
| Runtime history (first store, creator) | 17, 19 (02, 10, 13, 15) | 53–62 | Action at a distance. Objects die too early. |
| A clock, usage or a schedule | 07, 13, 15 | 48–53 | Data loss when a holder goes idle. |
| No references (keys, paths, queries, recipes) | 06, 09, 12, 14, 20 | 48–57 | Logical dangling: silent no-ops, writes to the wrong object. |
| Restart, rollback or retraction | 02, 03, 04, 10 | 45–63 | Lost state, duplicated I/O. |
| External anchors or regions as the whole model | 01 (11) | 53 | Leaks inside long-lived anchors. |

**Is there a fundamentally better model? No.** The evidence points to one conclusion: **the explicit lifetime information has to come from the programmer (`weak`, `shared`, moves) or from a type system.**

There are four places it could come from:
1. **The programmer, cheaply:** O1 or O4. This is where the leaders are.
2. **A type system:** O5, which fails G3 and P-RUST.
3. **The runtime, by tracing:** GC or O7, which fails G2.
4. **Nobody:** every idea that tried this leaked or lost data.

The support for that conclusion:
- Three independent impossibility results (L2).
- Five more analyses reached it from other directions.
- 40 ideas never got within 14 points.

Limits on the evidence:
- Each idea had only one AI analyst.
- John hasn't confirmed the weights.
- G3 kept both rounds away from type-system designs.

**What this means for the ADR:**
- Close the search for a new model.
- The remaining leverage is all on O1 and O4's side:
  - make the programmer's single statement cheap to place (N3);
  - make it loud when it's wrong (N1);
  - make frameworks need it less (N2 and the Q9 handles).
- P1 now carries more weight, because N1 needs debug-only tracing.

## 6. Does anything change the O1 vs O4 decision?

**No whole-point score changes.**

**O1 + N1, N2, N3**
- **Simplicity stays at 4.** N1 makes `weak` mistakes loud only on tested paths, and N2 narrows where `weak` is needed without removing the rule.
- **Implementation risk stays at 5.** The tooling doesn't ship in release builds.
- **Tooling stays at 4.** The reasons for 4 (coverage attribution, debugger formatters) are untouched.
- **Total:** 25·4 + 15·5 + 15·5 + 15·5 + 10·3 + 10·2 + 10·4 = 415 → **83.0**

**O4 + N1, N2 (inside `shared`), refined K8**
- **Simplicity stays at 3.** O4's costs (moves, exclusivity) are already loud compile errors.
- **Total:** 25·3 + 15·4 + 15·5 + 15·4 + 10·5 + 10·4 + 10·5 = 410 → **82.0**

**One conditional (from 09 C2 and 19 C6, re-entrancy).** If O4's "overlapping `shared` mutation traps" rule covers the whole object for the length of a mutating method, a synchronous delegate or observer callback that re-enters the owner will trap. O1 has no exclusivity rule, so it isn't affected.
- If the spike confirms this, O4's Expressiveness drops from 5 to 4: 25·3 + 15·4 + 15·4 + 15·4 + 10·5 + 10·4 + 10·5 = 395 → **79.0**.
- It isn't scored now because the ADR doesn't say how fine-grained that trap is.

**Sensitivity**

| Variant | Arithmetic | Total |
|---|---|---|
| O1, Simplicity 4.5 (N1 counted as making mistakes loud) | 427.5 / 5 | 85.5 |
| O1, Tooling 5 | 425 / 5 | 85.0 |
| O1, both | 437.5 / 5 | 87.5 |
| O4, re-entrancy confirmed | 395 / 5 | 79.0 |

**Reading:**
- The ranking holds.
- Q4 (threads in v1) still decides it.
- Round 2 tilts the judgement towards O1, not the score.
- N2 gives Q11 an alternative to K1's silent skip.

## 7. Recommended ADR-0001 amendments beyond round 1's list (not applied)

1. **Debug runtime.** Add scoped leak expectations, checked when an anchor ends or a test tears down, with retaining paths. Make the test runner fail on new leaked cycles (N1). Keep the exit report as a backstop.
2. **Widen P1.** Ask John to rule on debug- and test-only tracing when an anchor ends or a test tears down, not just on the exit-time report.
3. **Give Q11 three answers to choose from.**
   - (a) K1: a silent skip, logged in debug builds. Risk: lost work happens silently.
   - (b) K1 with an explicit `else` at registration. Cost: extra syntax.
   - (c) No K1; use N2's anchor teardown plus N1 instead. Risk: anchors that are never closed leak.
4. **Spike additions.**
   - Add a third O1 arm: N2 plus N1, without K1.
   - Seed missing-`weak` bugs and count how many N1 catches.
   - Add a re-entrancy case to both arms, which settles the conditional in §6.
5. **Q9 DSL constraint.**
   - Handles must be stable, generation-checked keys.
   - Positional identity is allowed only for ephemeral, view-local state.
   - Every `for` loop in a view keys its children.
   - Writing through a dead handle is loud by default.
6. **Two principles for Consequences.**
   - Profile and training artifacts change performance only, never semantics.
   - Debug and release builds share one memory model.
7. **"Rejected before scoring."** Add round 2 (20 ideas scoring 45–63) and the impossibility results in L2.
8. **Evidence for Q4, Q7 and the concurrency ADR.**
   - Isolation with synchronous calls deadlocked in 9 of 20 designs.
   - STM with I/O is unsound.
   - Epoch schemes stall on one long-running participant.
   - Graphs with uncounted back-edges must not be frozen or sent.
9. **Stdlib ADR.**
   - `Memo` and `TtlCache` (N4).
   - `SecretBytes` (N7).
   - No indexed weak collection.
10. **If O4 is chosen,** specify K8 as a runtime-maintained optional `owner` borrow, limited to heap-boxed owners and stripped when a graph is frozen or sent.
