# Analysis 05: Dress Rehearsal

Analyst: independent. Inputs read: the brief, round2.md, CHARTER.md and ideas/05-dress-rehearsal.md. All pseudo-code is illustrative only, not a syntax decision.

## 1. The idea in three sentences

You write code as if the language had a GC. Debug builds really do run under a tracing GC, and they record every reference store and every death. A release build replays a deterministic corpus of tests, fuzz runs and recorded sessions, then solves a SAT/hitting-set problem that marks each static reference slot as **owning** (RC) or **borrowed** (generation-checked, traps if the target is dead). The solution must satisfy two conditions in every trace: nothing reachable is freed (S clauses), and nothing unreachable survives (L clauses, which break cycles). Unrehearsed reference code fails the build, contradictions between traces are build errors, and in production a trace that was never rehearsed shows up as a safe trap or a leak.

## 2. Prior art

The pieces are known. Nobody seems to have put them together as the language's semantics.
- **Dynamic ownership inference from traces.** Dietl & Müller's *Runtime Universe Type Inference* (IWACO 2007) traces JVM execution, infers ownership modifiers, and puts them back into the source: https://ece.uwaterloo.ca/~wdietl/publications/pubs/DietlMueller07d-abstract.html (PDF: https://ece.uwaterloo.ca/~wdietl/publications/pubs/DietlMueller07d.pdf). There is also follow-up work on practical runtime inference: https://ece.uwaterloo.ca/~wdietl/students/pubs/MBaer06.pdf. In that line of work ownership is an inferred *annotation for documentation and checking*. It is not the runtime's strong/weak decision.
- **Dynamic ownership/sharing analysis of the object graph** (MIT 6.883 project lineage, ANU confinement tool): https://ocw.mit.edu/courses/6-883-program-analysis-fall-2005/58b747da7ffc69edfa1228b02b0f0a8c_object_control_i.pdf, https://researchportalplus.anu.edu.au/en/publications/a-tool-for-ownership-and-confinement-analysis-of-the-java-object-/
- **Profile-driven lifetime decisions in production allocators.** LLAMA (ASPLOS 2020) predicts object lifetimes from profiles and uses them to place objects: https://cs.utexas.edu/~mckinley/papers/llama-asplos-2020.pdf. It is only an optimisation. A wrong prediction costs performance, never safety.
- **Generation-checked non-owning refs** (Vale) and **ARC with weak refs** (Swift) are O6 and O1 in the brief.
- I found no system that places weak/strong references automatically from traces. Searches on "automatic weak reference placement" turned up only ARC patents and Swift forum threads where humans place `weak` by hand: https://forums.swift.org/t/how-arc-does-resolve-strong-reference-cycles-for-closures-that-dont-reference-class-self/64171

**Verdict on novelty.** Two things are genuinely new: ownership as an *empirically solved* strong/weak assignment, using S and L clauses with unsat cores as error messages, and test coverage as the soundness gate. The shipped runtime is O1 + O6. The inference method is a stronger version of Dietl & Müller's.

## 3. Soundness: counterexamples

**C1. Cross-thread RC corruption: an unsound path to memory corruption, not just a race.** The send check looks at the *root* object's site only. Atomicity is decided per site from rehearsed reachability.
```
cfg = Config()                    // site S1, witnessed cross-thread: flagged
tmp = Scratch()                   // site S2, never seen cross-thread: non-atomic RC
if rareFlag { cfg.extra = tmp }   // the store line IS rehearsed, but with rareFlag=false in every run
spawn { use(cfg.extra) }          // send passes: cfg's site is flagged
tmp = nil; cfg.extra = nil        // both threads retain/release Scratch non-atomically
```
A lost decrement leaks. A lost increment frees early. The freed object is then reached through an *owning* slot, and owning slots carry no generation check, so this is a real use-after-free. Racing unlocked writes such as `x.f = a` on different threads cause the same double-release. That is Swift's classic class-property race. Rule 6 only catches it under explored schedules. **Single-threaded code is sound (it leaks or traps). Multi-threaded memory safety depends on coverage.** The only sound fixes are a deep check on every send, which costs O(graph), or always-atomic or biased RC, which gives up the optimisation.

**C2. Unrehearsed teardown means a silent leak, which is the default outcome.** L clauses come only from cycles that rehearsal actually saw die, and the tie-break maximises owning.
```
class Editor { findBar = nil
  fun openFind() { findBar = FindBar(); findBar.onClose = { self.findBar = nil } } }
test "find works" { e = Editor(); e.openFind(); assert(...) }   // line coverage OK
```
No rehearsal ever drops an Editor with an open find bar, so `capture(self)@openFind` stays owning. In production every window that ever opened Find leaks, along with its whole document. Leak watch only fires at 10× the rehearsed high-water mark. One rule is missing from the list: **tests must tear down everything they build, in every configuration.** "Test end drops locals" helps. It does nothing for globals, singletons or registries.

**C3. One slot with two roles means UNSAT, and the fix is to restructure code, not to add a keyword.**
```
class Doc { fun bindSave(btn) { btn.onTap = { self.save() } } }  // one capture slot
editor.bindSave(editor.saveBtn)       // Doc owns btn: cycle, so L forces borrowed
toolbar.bindSave(Doc.scratch())       // the scratch doc is held only by the closure: S forces owning
```
This is UNSAT. In O1 the fix is one word (`[weak self]` at one site). Here you must duplicate the method or move ownership elsewhere. The same thing happens with user containers: `class Stack { items = List() }` has one allocation site, so *every* Stack in the program shares one element plan. Any wrapper or factory (`fun makeList() = List()`) merges unrelated components into one constraint system. G3 forbids generics, so the most natural fix is unavailable.

**C4. General graphs are UNSAT.** `class Vertex { edges = List() }`, where some vertices are reachable only through edges (S) and dropping the graph kills cycles (L). Same slot, so UNSAT. You are forced into "keep an `all` list plus index handles", which is the arena pattern the brief already covers.

**C5. Borrowed means trap, never nil. There is no `weak` semantics at all.**
```
toolbar.add(editor.saveBtn); window.close()   // editor freed; button survives in the toolbar
tap(saveBtn)                                  // capture(self) is borrowed: production TRAP
```
O1 with `weak self` turns this into a no-op. DR offers only Swift `unowned` behaviour, and DR picked that behaviour for you. A UI that crashes on a stale tap is an availability bug. For a banking app that is a release blocker. There is no way to write "do X if still alive" or a weak-valued cache.

**C6. The elided generation check can be unsound as worded.** "Elided when the caller's frame holds the object" is only safe if the caller holds the object in an *owning local*. If it holds it in a field, the callee can free it mid-call:
```
fun process(xs) { self.reset(); xs[0] = 1 }   // reset() does self.samples = List()
process(self.samples)                         // xs is borrowed, check elided: UAF
```
The elision must be a conservative static proof, as Swift's +0 guaranteed-parameter rules are, and must never rely on traces.

**C7. Debug and release diverge.** Debug builds run a GC with lazy collection. Release runs RC with prompt death. If types have deinit or close resources, file-close order, socket shutdown and observer callbacks happen at different times. A bug in release (a trap from C5) cannot be reproduced in debug, because debug never traps. The replay report feeds the corpus, but you cannot step through the failure under the debugger in the semantics that failed.

**C8. Determinism and build cost.** The build is a function of source + corpus + schedule-exploration budget. A larger budget explores more interleavings and can flip a site to atomic or find a new contradiction, so CI and a laptop can get different plans unless the plan is locked. Adding an innocuous test can break the build (rule 4) or add atomic RC traffic. A library's slots can flip because of an app's traces, and then that library's *own* untested internal paths can trap.

**C9. Rule 3 at ecosystem scale.** Every statically reachable reference store, including error handlers, disk-full paths and *third-party dependency code*, needs rehearsal. Most real codebases sit at 60–80% coverage. Under this rule they do not compile for release. Fault injection becomes mandatory infrastructure.

Deadlock is not made worse than in lock-based languages, and not better either.

## 4. Scenarios

- **(a) Lines of a file: works.** No cycles, so every slot is owning. Move elision makes it cheap.
- **(b) Parent pointers: works** if the tests express one consistent intent. A single dual-intent test makes it UNSAT (C3/C4), but that error is honest and well explained.
- **(c) UI callback: partial.** The common cycle is broken without `weak`, which is the idea's best demo. A late or detached callback traps instead of no-oping (C5), and unrehearsed teardown leaks (C2).
- **(d) Shared cache: works.** Plain RC sharing. A weak-valued cache cannot be expressed.
- **(e) Mutating a large list: works.** Reference semantics, borrowed parameter. Mind C6.
- **(f) Threads: partial, bordering on hand-wave.** Atomic RC per site and race detection hold only under explored schedules. Outside them, memory safety itself is lost (C1).

## 5. Gates and charter

- **G2: needs-john.** No GC runs in the shipped binary. But *debug builds are garbage collected*, so developers live with a GC every day, and the build runs one. The charter says "doesn't require a garbage collection run". John has to rule on whether that covers dev/debug.
- **G3: pass, with notes.** No source annotations. Two things need flagging. First, `memory.plan` is in effect a machine-written annotation file kept out of band. It is not human-authored, so I treat it as a pass. Second, per-allocation-site plans for built-in `List`/`Map` hit the pending question on built-in parameterised containers.
- **Other goals strained:**
  - **G7:** the build is no longer hermetic over the source.
  - **G1:** release requires near-total coverage plus teardown discipline.
  - **G8:** a debug/release semantic gap (C7).
- **Goals served:** **G9/G10** are elevated from hygiene to the type system, and the design is a strong fit for **G11/P-PY**, because you write closures capturing implicit self freely.

## 6. Scores

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 3 | Writing code is GC-simple. But fixing a rule-4 error takes full ARC-cycle reasoning *with no vocabulary to express the fix*, and the hidden rules (teardown, determinism, coverage, wrapper slot merging) are real. |
| Memory safety | 15 | 3 | Single-threaded code is sound (it leaks or traps). Cross-thread RC corruption is reachable outside rehearsal (C1). C6 needs care. Production traps are a designed outcome. |
| Expressiveness (b, c, d, G11) | 15 | 4 | Closures, parent pointers and sharing work with zero ceremony. Dual-role slots go UNSAT, and there are no weak/nil semantics. |
| Implementation risk (AI on LLVM) | 15 | 1 | Precise tracing GC (LLVM stack maps), a trace recorder with IO recording, a deterministic interleaving explorer, a SAT solver with readable unsat cores, elementary-cycle enumeration, incremental re-solve, and an RC + generation runtime. That is four or five research-grade subsystems, all of which must agree. |
| Performance & predictability | 10 | 3 | Runtime is roughly O1 plus generation checks, and per-site atomics are a real win. Plans shift when tests change, and release builds are very expensive. |
| Concurrency fit | 10 | 2 | Correct only within the explored schedules, and failures outside them are memory-unsafe. |
| Tooling, debuggability, C FFI | 10 | 3 | The diffable plan, replayable traps and trace-pair errors are excellent. Debug and release semantics split, and FFI needs pin bindings (de facto annotations). |

**Total** = (25×3 + 15×3 + 15×4 + 15×1 + 10×3 + 10×2 + 10×3) / 5 = (75 + 45 + 60 + 15 + 30 + 20 + 30) / 5 = 275 / 5 = **55**.

For comparison: O1 scores 83, O4 82 and the best round-1 idea 68. Dress Rehearsal is 28 points below O1 and 13 below round 1's best. The inventor's self-assessment of about 70 assumed implementation risk 2 and concurrency 3. C1 justifies the lower concurrency score.

## 7. What the premise teaches, and the kernel

**Lessons from the crazy premise.**
1. *The strong/weak decision is a fact about intended behaviour, not about types.* C3 and the (b) contradiction show this. No static or dynamic inference can choose who owns the root, because the program supports two intents. So the brief's "lifetimes known to the programmer, not the compiler" is literally true. The only question is the *medium* for stating that intent: annotations (O1 `weak`, O4 `shared`) or tests (DR). Tests turn out to be a worse medium. They are incomplete by construction, and the default for unseen cases (leak, or trap with no nil) is worse than an explicit keyword.
2. *Ownership errors explained as two concrete runs* ("test A needs this to keep the root alive; test B leaks if it does") are a far better error UX than any lifetime message. That carries over to any model.
3. *Teardown tests are the missing ARC test.* O1 fails silently on cycles because nobody tests that things die.

**Salvageable kernel (adoptable into O1, and largely into O4):**
- **K1, "rehearsal" leak mode for the G10 test runner (O1).** In debug and test builds, add an optional cycle-detecting heap check at test end. Every object allocated by the test must be dead after teardown, or the test fails and prints the cycle. This is not a collector run in production, so G2 is unaffected.
- **K2, a weak-placement advisor.** Run DR's S/L hitting-set solve over the K1 traces and *suggest* the minimal `weak` edits ("make `capture(self)` at editor.lang:12 weak; `Node.parent` weak"), with an unsat-core explanation when the tests disagree. The human keeps the keyword and the solver gives advice. For O4 the same machinery can suggest where `shared` is needed.
- **K3, trace-pair error messages** for any ownership or cycle diagnostic.
- **K4, per-allocation-site atomic-RC elision**, but only via a *sound* mechanism such as biased RC or static thread-escape analysis, never via traces alone (C1).
- **K5, a committed memory report** (`memory.plan` as an *output*). It is a generated, diffable summary of each slot's strength and atomicity for review, and nothing depends on it for correctness.

## 8. Verdict

**Kernel worth stealing.** As a language semantics it fails. Coverage becomes the safety boundary, and multi-threaded memory safety leaks out through it (C1). Production behaviour is trap-or-leak on unrehearsed paths. Implementation risk is the highest of any option seen. As a *tool on top of O1*, the K1 teardown-leak tests and the K2 S/L weak-placement advisor are cheap, G2- and G3-clean, and aim directly at O1's main weakness: humans misplacing `weak`.
