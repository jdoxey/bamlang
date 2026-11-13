# Round 1 brainstorm: 20 memory-management ideas compared with O1 and O4

## Inputs and method

- **Read:** `brief.md`, `CHARTER.md`, `ideas/01–20`, `analyses/01–20`, and ADR-0001.
- **Scores:** each idea was scored by a separate analyst, and those scores are used throughout. A script re-added every total (Σ weight × score / 5), and all 20 matched the analysts' totals.
- **Rubric weights:**

  | Criterion | Weight |
  |---|---|
  | Simplicity | 25 |
  | Safety | 15 |
  | Expressiveness | 15 |
  | Implementation risk | 15 |
  | Performance | 10 |
  | Concurrency | 10 |
  | Tooling | 10 |

## 1. Bottom line

- **No idea beat O1 (83) or O4 (82).**
  - Analyst scores ran from 47 to 68, with a mean of 59.9.
  - The best, Cascade Links (03), is 15 points behind O1.
  - All 20 got the same verdict, "kernel worth stealing", so the verdict tells you nothing. The kernels are the useful output.
- **Most of the gap is Simplicity and Implementation risk.** Those two account for 15.4 of the average 23.1-point gap to O1 (67%).
  - 17 of the 20 scored 2 on implementation risk.
  - No idea beat O1 on Simplicity.
- **Most ideas were fixing a problem O1 and O4 don't score badly on.** Most exist to remove `[weak self]` from scenario (c).
  - O1 and O4 already score 5 on Expressiveness, and the ADR charges the `weak` rule to Simplicity.
  - So the most a fix for (c) can earn is one step on Simplicity.
  - Every replacement mechanism cost 1–2 Simplicity steps plus 2–3 implementation-risk steps.
- **Main takeaway: one kernel, reached independently 16 times, should go into the ADR as an open question.** The kernel is "closures never keep `self` alive", narrowed by the analysts' counterexamples to:
  - `self` only;
  - a void call is skipped when `self` is gone;
  - a call that returns a value traps;
  - debug builds log every skip.

  It changes no score. It trades a silent leak for a silent skipped call, and John has to decide whether that trade is acceptable.
- **The O1/O4 ranking doesn't change:** 83.0 vs 82.0 after kernels, scoring in whole points.

## 2. Ranked table

Every verdict is "kernel worth stealing", so the table leaves that column out. The analyst score is the one used for ranking. "Self" is the inventor's own score, where one was given.

| # | Idea (file) | Lens | Analyst | Self | What it is | Fatal flaw |
|---|---|---|---|---|---|---|
| 1 | Cascade Links (03) | Databases | **68** | — | Each object has one owner. Every other reference is a link that empties when its target dies: `T` cascades, `T?` nulls. Freeing waits for commit points. | Safety depends on frees waiting for a commit point, so reclamation and file-close timing depend on the shape of the call stack. `T` vs `T?` quietly sets the delete policy. |
| 2 | Chronicle (05) | Version control | 67 | — | Immutable reference-counted values that only point to older values, plus a world tree of objects with identity, reached through generation-checked links. Removal happens at the end of the turn. | Object lifetime is effectively manual and leaks are the default. Biggest runtime of any idea. |
| 3= | Tick & World (09) | Game engines | 65 | — | Scratch memory is reset each tick. Anything kept is baked into an entity tree addressed by generation ids. | Memory is only reclaimed at ticks. Non-event code grows without bound, and bakes have hidden O(n) or exponential cost. |
| 3= | Precedent-Bound (11) | Spreadsheets | 65 | — | One owner. Links go blank when their target dies. A closure is disposed when anything it captured dies. | The burden of single ownership plus a large notification runtime, and ownership cycles still leak. |
| 3= | Depots (18) | Logistics | 65 | 77 | Objects live in owned depots (non-atomic RC inside, bulk free on close). References across depots are recallable `far` refs. | Where an object is placed is implicit and decided at runtime. Mistakes surface only as traps or silently skipped work. |
| 3= | Tide (20) | Tides | 65 | 77 | Nothing is freed during a turn. Between turns only a single-owner world tree survives, plus links. | Every store transfers ownership, so ordinary worklists trap. Moves race with references taken earlier in the turn. Non-event code holds everything. |
| 7 | Circulation (12) | Library lending | 63 | — | The first store into a field or collection becomes the owner. Stack loans pin their target; heap loans are nulled eagerly. | "First shelf wins": adding a log line can steal ownership. |
| 8= | Supervised Homes (10) | Distributed systems | 62 | 75–79 | Actor-like heaps freed whole when their home stops. `far` leases connect homes. | The homes that matter never stop, and cycles inside them leak. |
| 8= | Double-Entry Claims (15) | Accounting | 62 | — | Every reference is recorded in a register on its target and settled when the target closes. | The ledger has to stay exact across moves, reallocations and threads. A closure dies with its shortest-lived capture. |
| 10= | Tissues & Nerves (01) | Biology | 60 | — | A tree of lifecycles with RC inside each. References across lifecycles are inert, self-zeroing "nerves". | Whether a reference owns its target is set at runtime by the first store, and mistakes fail silently. |
| 10= | Estates & Liens (02) | Economics | 60 | — | Bump-allocated estates. References between estates are counted per pair of estates. Freeing happens at settlement. | Coarse estates leak, fine-grained ones cost a page each, and the default frees nothing. |
| 10= | Leasehold (07) | Property law | 60 | — | When a target dies, the holders of its required leases are destroyed too (forfeiture). | Forfeiture climbs the ownership chain and silently destroys windows and their state. |
| 10= | Heap Plan (13) | Whole-program compilation | 60 | — | The compiler proves which edges point at something longer-lived and leaves them uncounted. Cyclic classes go into RC groups. | Safety rests on a hard proof engine, and RC groups never shrink. |
| 14 | Biome (14) | Ecology | 58 | — | A tree of habitats. Storing an object somewhere longer-lived moves it up the tree. | Overwritten objects in long-lived habitats leak. Breaks under modal loops and `await`. |
| 15= | Charge & Decay (06) | Physics | 55 | — | The first lasting store becomes the owner. Links are cleared on decay. | The callback crux (c) creates an ownership cycle during `init`. The order of stores can delete data. |
| 15= | Ground Plane (08) | Electronics | 55 | 70 | An ownership tree with fixed and swappable fields. Plain references may only point toward the root. | Whether a reference is legal depends on the tree's runtime shape. Assumes nothing is on the stack at each tick, which isn't true. |
| 15= | Dominion (19) | Graph theory | 55 | 80 | Non-owning references are stored as positions in the ownership tree. | Identity is positional, so moving a subtree breaks references or silently points them at other objects. |
| 18 | Kinship (16) | Family structure | 54 | — | One guardian per object. References to ancestors are uncounted. An orphanage frees dropped objects at the end of the turn. | Solves only the easy, nested references. You pay O4's rules plus about a dozen more. |
| 19 | Scenes & Call Sheets (17) | Theatre | 52 | 70 | Overlapping regions arranged so references can't form a cycle. RC per scene. | Nothing is freed until its scene closes. A UI that re-renders leaks. |
| 20 | Spaces & Descriptors (04) | Operating systems | 47 | 70 | Scratch memory per turn plus moving "spaces" reached through descriptors. | Use-after-free when spaces move. `renew` is tracing. |

**Self-scores vs analyst scores.** Only 7 of 20 inventors gave a self-score. Every one of them overrated their idea, by 12 to 26 points (mean +17). Inventors priced their runtimes as "known parts"; analysts priced the interactions between them.

## 3. Recurring patterns

### Mechanisms the inventors reached independently

| Mechanism | Count |
|---|---|
| Closures that die, do nothing or unregister when something they captured dies | **18** |
| — the whole closure dies if *any* capture dies | 12 |
| — tied to one context object (self, owner, home) | 6 |
| Deferred destruction while user code might still hold a reference | **19** |
| — at a turn, tick, commit or quiescent point | 11 |
| — while a stack pin or a running method exists | 8 |
| Single owner plus non-owning references that are cleared or checked, as *the* model | **12** |
| Regions or groups freed whole | **8** |
| Ownership or placement decided by runtime history (first store, the creator's `self`) | **10** |
| Uncounted upward reference (to an ancestor) | 4 |
| Concurrency built from moving a graph, freezing it, or putting it behind a lock | 20 |

Most ideas turn out to be Qt's object model (13 analyses cite it) or Project Verona's regions (10), made into language rules and checked at runtime instead of statically.

The ideas answered scenario (c) in three ways:
1. **Put the cycle inside a group that dies together** (9 ideas). These always leaked inside long-lived groups.
2. **Make the capture non-owning** (12 ideas). These always produced callbacks that silently did nothing.
3. **Make the capture an uncounted upward pointer** (4 ideas). These only handled callbacks nested inside their owner.

### Failure modes the analysts found independently

| Failure mode | Count |
|---|---|
| Data race through a surviving alias on send or lock | **18 / 20** |
| Use-after-free in the spec as written | **15** |
| Callbacks that silently do nothing, losing work | **14** |
| — a dead *secondary* capture skips the *primary* effect (the lost save) | 5 |
| Nested event loops, modal dialogs, `await` or re-entry breaking the quiescent-point premise | **11 of the 11 turn-based ideas** |
| Leaks inside long-lived regions | **8 of the 8 region-based ideas** |
| Reclamation tied to turn shape (a CLI, server or long loop never reaches a boundary) | 8 |
| Ownership by first store causing action at a distance ("add a log line" was the trigger in 4) | **10** |
| Destructor ordering, resurrection, zombie objects | 10 |
| Single ownership still leaks, in ideas that claimed "no cycles possible" | 3 |

What these patterns say:
- **Each class of mechanism failed at its own boundary, every time.** These are structural results, not bad luck in one spec.
- **Runtime checks can't replace static control of aliasing between threads.** 18 of 20 raced through a surviving local reference. Four analysts independently concluded the fix is O4-style move rules. That supports the ADR's "pick O4 if v1 needs threads".
- **A silent skipped call is the new silent leak.** Fourteen designs traded ARC's silent leak for a silently skipped call. For an editor or a banking app, a skipped save is worse than a crash.

## 4. Kernels worth stealing

Ranked by value against risk.

**K1. Closures never keep `self` alive.** *(16 of 20 analyses)*
- **How it works:**
  - A closure captures `self` weakly, upgrades it once on entry, and holds it strongly for the rest of the call.
  - If `self` is gone, a void call is skipped (and logged in debug builds), while a call that returns a value traps.
  - Other captures stay strong.
  - There is an explicit strong-`self` capture for fire-and-forget objects.
- **Why it is narrowed this way:**
  - Variants that skipped when *any* capture died lost saves in 5 analyses.
  - Capturing locals weakly killed DSL-local state in 9.
  - Value-returning closures that returned none broke comparators in 2.
- **Fit:** O1 directly. In O4 it applies only inside `shared`.
- **New rules:** O1 goes from 5 rules to 6, plus one opt-out form. No escape analysis is needed, because only a closure that runs after its method returns can find `self` dead, and that is exactly the escaping case.
- **Remaining risks:**
  - Fire-and-forget objects silently do nothing unless they opt out.
  - Cycles through captures other than `self` remain, so the lint must cover them.
  - Each escaping closure costs one weak-table registration.
  - It trades silent leaks for silent skips.

```text
// illustrative only — not a syntax decision
button.onTap = { save() }            // self weak; after editor dies -> skipped, logged in debug
timer.after(5s) { strong finish() }  // opt-out for objects kept alive only by their own callback
```

**K2. Tooling that explains liveness.** *(15 analyses)*
- **What it is:** answers "why is this nil?" (where the target was freed, and from which call path), "why is this alive?" (the retain path), the K1 skip log, and a tree view of the heap's strong edges.
- **Fit:** both options. No new user rule.
- **Requirement:** needed if K1 is adopted.

**K3. Audited proofs, and the same traps in every build.**
- **What it is:** every unchecked optimisation gets a checked twin that runs in test builds, and runtime traps fire the same way in debug and release.
- **Fit:** both options.

**K4. A running method keeps `self` and its own closure context alive.**
- **What it is:** the object can't be destroyed while one of its methods, or its own closure, is running. This makes "close the window from its own `onTap`" safe. It is a code-generation invariant, not a user rule.
- **What to reject:** don't adopt turn-deferred freeing as a safety mechanism; it broke in 11 of 11 designs. Batching RC decrements per event is acceptable as an optimisation only: track nesting depth, never defer `deinit`, and never rely on it for safety.

**K5. A built-in `Event`/callback registry that prunes dead entries.**
- **Fit:** both options.
- **Constraint:** iteration only. A general indexed `List of weak T` shifted indices under readers in 4 analyses.

**K6. A lint that finds cycles in the type graph.**
- **What it is:** a per-package report of the field and capture edges that can close a cycle.
- **Caveat:** fields of function type make the declared graph one giant cycle, so the lint needs closure-flow information. K1 removes the self-capture edges, which helps.

**K7. Concurrency constraints.**
- **What they are:** `freeze` with one atomic count per frozen graph; sender-side recursive share-marking (reader-side "publish on first read" races); no dynamic checks on send.
- **Fit:** O4 handles these best.
- **Implication:** this confirms that ADR question Q7(C) is hard.

**K8. For O4 only: an `outer T` back-pointer to the owner, plus upward self-capture.**
- **What it is:** a closure stored inside `self`'s own `let`-owned parts captures `self` uncounted.
- **Cost:** about 2 new rules. It is unsound in O1.
- **Risks:** moving such a closure out of its subtree is a use-after-free. Preventing that needs either a proof or an ancestor check on every store.

**K9. `await` looks up a weakly captured `self` again.**
- **What it is:** if `self` is gone the task is cancelled, and `defer` blocks still run.
- **Where it belongs:** the concurrency ADR.

**K10. Opt-in groups ("islands") freed in bulk.**
- **Status:** not for v1. All 8 region-based designs leaked inside long-lived groups.

**K11. A per-event bump arena chosen by escape analysis.**
- **Status:** an optimisation for later.

## 5. Does any kernel change the O1 vs O4 decision?

**No.**

**O1 + K1–K6:** no individual score changes.
- **Simplicity stays at 4.** The rule count goes from 5 to 6 plus an opt-out. The `weak` rule remains for back-references and delegates, and a new way to fail silently (skipped calls) arrives.
- **Total:** 25·4 + 15·5 + 15·5 + 15·5 + 10·3 + 10·2 + 10·4 = 415 → **83.0**.

**O4 + K1, K2–K5, K7, K8 (checked when a reference is stored):** no individual score changes.
- **Simplicity stays at 3:** the rule count goes from 9 to 11.
- **Implementation risk stays at 4**, or drops to 3 if K8 has to be proved rather than checked.
- **Total:** 25·3 + 15·4 + 15·5 + 15·4 + 10·5 + 10·4 + 10·5 = 410 → **82.0**.

**Sensitivity** (the Conc 0 and Conc 20 columns renormalise the other weights):

| Variant | Total | Conc 0 | Conc 20 |
|---|---|---|---|
| O1 + kernels | 83.0 | 87.8 | 79.1 |
| O1 + kernels, Simplicity 4.5 | 85.5 | 90.6 | 81.4 |
| O1 + kernels, Simplicity 5 (generous) | 88.0 | 93.3 | 83.6 |
| O1 + kernels, Implementation risk 4 | 80.0 | 84.4 | 76.4 |
| O4 + kernels | 82.0 | 82.2 | 81.8 |
| O4 + kernels, Simplicity 3.5 | 84.5 | 85.0 | 84.1 |
| O4 + kernels, Implementation risk 3 (K8 proved) | 79.0 | 78.9 | 79.1 |

**Reading:**
- The gap stays at 1 point under whole-point scoring, and still at 1 when each option gets its most generous half-step.
- Q4 (concurrency in v1) still decides it.
- The kernels' real effect is on G11 rather than on the score. With K1, O1's standard callback needs no `weak`. O4's still needs `shared` unless K8 is adopted, and K8 is risky.
- The counterweight: K1 is the brainstorm's own failure mode in a narrower form, and it hasn't been measured yet.

## 6. Recommended changes to ADR-0001 (not yet applied)

1. **New question Q11:** "Should a closure ever keep `self` alive?" Ask it with K1 as specified above, the trade it makes, the fire-and-forget opt-out, and void calls skipping vs value-returning calls trapping. Recommend yes, conditional on the spike.
2. **The spike:** port the ~1k-line UI sample under O1 twice, once with K1 and once without. Count fixes per 1k lines, skipped calls and leaks. Deliberately include one fire-and-forget pattern.
3. **Debug runtime:** add the record of why a weak reference became nil, the retain-path query, and the K1 skip log, on all three operating systems.
4. **Release builds:** a running method or closure keeps `self` and its own context alive. Deferred frees are an optimisation only, under the K4 constraints. Cite the 11-of-11 result.
5. **Stage-1 entry criteria:** proof-audit mode, and identical trap behaviour in debug and release.
6. **Lint:** make a per-package cycle report in the type graph a stage-2 goal, with the caveat about fields of function type.
7. **Q4 and Q7 evidence:** 18 of 20 runtime-checked designs raced through surviving aliases, and reader-side publish is unsafe.
8. **P2 list and the stdlib ADR:** add an iteration-only `Event` type, and no indexed `List of weak T`.
9. **If O4 is chosen:** add K8 as an open question, checked when a reference is stored vs proved.
10. **"Rejected before scoring":** add the 20-idea brainstorm and its range of 47–68.

## 7. Ideas worth a second look

**None as models.** These two come closest:

- **Tide (20):** the only idea scored 3 on implementation risk.
  - Fixes needed: a first-class non-owning collection, sends delayed to the end of the turn, and a rule for how nesting depth works.
  - With those fixes it reaches about 70, or 78 at best.
- **Cascade Links (03):** the highest score, and the only idea scored 5 on Expressiveness.
  - Fixes needed: replace commit-point frees with K4, and separate the cascade policy from `T` vs `T?`.
  - With those fixes it reaches 76 at best, and at that point it is O1 + K1 plus derived inverse collections.

Neither reaches 82. Spend the time on the O1/O4 spike.
