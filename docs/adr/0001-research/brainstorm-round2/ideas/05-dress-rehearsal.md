# 05 — Dress Rehearsal

## 1. Name

**Dress Rehearsal.** The program performs in full before it ships. The compiler watches who holds whom, and casts each reference as an owner or a bystander.

## 2. The crazy premise

**Sacred assumption broken:** compilation is a function of the source text.

Here the release build is a function of **source + a rehearsal corpus** (tests, seeded fuzz runs, recorded sessions). The compiler does not infer ownership from the code. It runs the code under a tracing heap at build time, records which references actually kept things alive, and solves for a static ownership assignment that agrees with every recorded run. Code that no rehearsal reaches cannot be compiled for release. Memory safety becomes a property of the test suite, and the shipped binary traps safely the moment it leaves the rehearsed envelope.

Gates and assumptions bent:
- **G2:** the *build* uses a tracing collector, but the *shipped binary* never runs one. I read G2 as being about the runtime. **needs-john.**
- **Build determinism / hermeticity:** the build runs your program. Rehearsals must be deterministic (seeded, IO recorded) so the plan is reproducible.
- **"Compiles ⇒ shippable":** an untested line is now a build error in release.

## 3. Pitch

You write code as if the language were garbage collected: plain references, closures that capture `self`, parent pointers, shared caches, no `weak`, no lifetimes, no ownership keywords. Debug builds really are garbage collected. Every debug run, test and fuzz case records a trace of reference stores and deaths. A release build replays the corpus and asks one question of every reference slot in the program (each field declaration, local, parameter, closure capture and container element position): *was this slot ever the last thing keeping its target alive?* It then solves a small SAT problem. Slots become **owning** (ref-counted) or **borrowed** (no count, generation-checked), and the assignment must satisfy two conditions in every trace: nothing reachable is ever freed, and nothing unreachable survives, so no owning cycles. The result is ARC where the weak refs were placed by evidence rather than by the programmer. The assignment is written to a committed, diffable `memory.plan`. If no assignment exists, the build fails and shows you the two rehearsals that disagree about who owns whom. In production, a borrowed ref whose target was freed traps deterministically. It never corrupts memory. The trap dumps a replayable "missed scene" that you drop into the corpus.

## 4. The rules (everything a programmer must learn)

1. **Write as if garbage collected.** References are references. There is no ownership, borrow, weak or lifetime syntax.
2. **Release builds rehearse.** `build --release` runs every test, every fuzz target (seeded) and every recorded session in `rehearsals/`.
3. **No unrehearsed reference code.** Rehearsal must execute every allocation site and every statement that stores a reference (field, local, capture, container insert). Otherwise the build fails with `unrehearsed: line N`. This is the G9 coverage tool, used as a gate.
4. **Contradictions are build errors.** If rehearsal A needs slot S to keep its target alive, and rehearsal B needs S not to (because it would form an owning cycle that never dies), the build fails and names S, A and B. You fix the code or the test.
5. **Leaving the envelope traps.** In a release binary, using a reference whose target was freed under the plan is a deterministic crash with a report. It is never undefined behaviour. `rehearse add <report>` turns the report into a regression rehearsal.
6. **Cross-thread mutation goes in `lock x { }`.** Rehearsal runs threads under a deterministic scheduler that explores interleavings. A witnessed unlocked race fails the build.
7. **`memory.plan` is code.** It is committed and reviewed. A diff like `Node.parent: owning → borrowed` is a semantic change to review like any other.

In practice, day-to-day users meet only rules 1, 3 and 4.

## 5. Under the hood

**Static slots.** A static slot is one of: a field declaration, a local or parameter declaration, a closure-literal capture, or the element position of a built-in container *per allocation site* of that container. Two different `List`s can therefore get different plans. Every runtime reference lives in an instance of exactly one static slot.

**Rehearsal runtime (debug and build).** Precise tracing heap. Each event in the trace is one of `alloc(o, site)`, `store(slot-instance, o|nil)`, `slot-instance-dies` (frame exit, or its holder dies), `deref(slot-instance)` or a thread event. Conceptually, reachability is recomputed after every event. Feasibility is not a concern.

**The assignment problem.** For each static slot `s` there is a boolean `own(s)`. Production semantics under that assignment: `oc(o)` is the number of live owning slot instances holding `o`, and `o` is freed when `oc(o)` drops to 0, cascading to the slots it holds. That is RC semantics, so an owning cycle never dies. Two constraint families come from the corpus:
- **Safety (S).** At every event, every object reachable in rehearsal must have `oc > 0` (roots count). This yields positive clauses: "at time t, object o was held only by instances of slots {s1..sk}" gives `own(s1) ∨ … ∨ own(sk)`.
- **Promptness (L).** When an event makes a set D unreachable in rehearsal, D must also die in production at that same event. That means every cycle among D's internal slot edges must contain a borrowed slot. This yields negative clauses: `¬own(a) ∨ ¬own(b) ∨ …` per elementary cycle.

S is monotone in owning and L is anti-monotone, so the problem is a hitting-set/SAT instance. **Tie-break:** among satisfying assignments, maximise owning slots, then break ties by source order. Leaks are the safer way to generalise than traps, so the solver marks a slot borrowed only when L forces it. If the instance is UNSAT, the unsat core maps back to a minimal set of trace moments. That set is the rule-4 error message.

**Production binary.**
- *Owning* slot: RC. It is non-atomic unless an object from that allocation site was ever witnessed reachable from two threads, in which case it is atomic. Swift-style static elision removes RC traffic on obvious moves.
- *Borrowed* slot: a raw pointer plus a generation check on deref. Every object carries a generation word that is bumped on free. The check is statically elided where trivial, such as a parameter dereferenced while the caller's frame holds the object.
- *Thread crossing:* `spawn` and channel send check that the sent object's site is flagged cross-thread. The flag is computed transitively over rehearsed reachability. An unflagged send traps as "unrehearsed thread crossing".
- *Leak watch:* each site has a quota of 10× the live high-water mark seen in rehearsal. Exceeding it logs a "possible missed scene". It does not trap.

**Debug builds** skip the plan entirely. They run on the rehearsal heap (a GC), and recording is optional. Debug is easy to use, release is checked.

## 6. Scenarios (illustrative only — not a syntax decision)

**(a) Lines of a file.**
```
fun readLines(path) {
  lines = List()
  for line in File(path).lines() { lines.add(line) }
  return lines
}
```
Each string is held only by `lines@site.elem`, and `lines` is held only by the local and then the caller's slot. S makes these slots owning. L never fires because there are no cycles. Static move-elision removes almost all RC traffic. Plan: `readLines.lines: owning`, `List@12.elem: owning`.

**(b) Tree with parent pointers.**
```
class Node { children = List(); parent = nil
  fun add(c) { c.parent = self; children.add(c) } }
```
The rehearsal `drop_tree` frees the root, and the dead set has a cycle `children.elem ↔ parent`. L requires `¬own(children.elem) ∨ ¬own(Node.parent)`. S requires `children.elem` to be owning, because children are often held only there. So the plan comes out as `Node.parent: borrowed`. Now suppose some test writes `n = root.children[0]; root = nil; print(n.parent.name)`. Then S demands `own(Node.parent)` and the instance is UNSAT. The build error reads: *"Node.parent kept the root alive in test `detach_keeps_parent` (line 40), but owning it leaks the tree in `drop_tree`. Decide who owns the root."*

**(c) UI callback capturing `self` (the crux).**
```
class Editor { text = ""; saveBtn = Button("Save")
  init { saveBtn.onTap = { self.save(); self.dirty = false } } }
window.content = Editor()
```
In the rehearsal `open_tap_close`, closing the window cuts `window.content`, and the set {editor, button, closure} dies together. The internal cycle `Editor.saveBtn → Button.onTap → capture(self)` needs one borrowed slot. S needs `saveBtn` and `onTap` to be owning, because each is the sole holder. So `capture(self)@Editor.init: borrowed`. The programmer never typed `weak`. Now suppose a recorded session shows a timer re-firing `onTap` after the window closed. S then needs the capture to be owning, L forbids it, and the build fails with both traces. The fix is behavioural, such as cancelling the timer in `close()`. The rehearsal confirms the fix. If that path was never rehearsed, production traps at `self.save()` with a replayable report and does not touch freed memory.

**(d) Shared cache used by two components.**
```
cache = Cache(); a = Search(cache); b = Preview(cache)
```
In one rehearsal `a` dies first, and in another `b` dies first. Each of `Search.cache` and `Preview.cache` was the last holder somewhere, so both are owning (RC). The cache's `Map@site.value` slot is owning. A caller local that holds an entry past its eviction becomes owning too, which makes entries shared, with no API change. Plan diffs show this happening.

**(e) Mutating a large list in a function.**
```
fun normalise(xs) { for i in 0..xs.count { xs[i] = xs[i] / max } }
normalise(samples)
```
`normalise.xs` is never the last holder because the caller always holds `samples`, so it is borrowed. The parameter-outlives-call rule elides the generation check. Nothing is copied and nothing is counted. Mutation is visible to the caller, because references are just references.

**(f) Threads.**
```
stats = Stats()
spawn { lock stats { stats.hits += 1 } }
lock stats { stats.hits += 1 }
```
`Stats@site` is witnessed reachable from two threads, so its owning slots use atomic RC and the site is flagged cross-thread. The capture is owning because the spawned thread can outlive the frame. That was witnessed under the explored schedules. If you drop the `lock`, the rehearsal race detector fails the build under the interleaving that shows the race.

## 7. What is new

- **Ownership as an empirical fact.** Strong versus weak is solved from recorded executions, with a SAT formulation (S clauses vs L clauses). It is not declared by the programmer (O1, O4, O5) and not inferred statically (regions, Heap Plan).
- **Ownership conflicts become test disagreements.** The error is never "lifetime 'a does not outlive 'b". It is "these two runs of your program disagree about who owns the root".
- **Coverage is the safety gate.** G9/G10 tooling stops being hygiene and becomes the type system.
- **A committed `memory.plan`.** The memory model of the whole program can be reviewed in a PR. Performance changes (owning → borrowed, non-atomic → atomic) show up as diffs.
- **Closed-loop production.** Traps are safe, replayable, and feed straight back into the corpus.

## 8. Less crazy than it sounds, or more

**Less crazy:**
- The shipped artefact is just ARC plus generation-checked non-owning refs, which is O1 with O6-style checks. The only novel part is *who places the weak refs*, and that is the part humans get wrong in O1.
- Profile-guided optimisation already makes binaries depend on recorded runs.
- Daikon-style invariant inference already mines facts from executions.
- Many shops already gate merges on coverage and sanitizer runs.
- Worst-case generalisation is biased toward leaks (owning by default), not crashes.

**More crazy:**
- An under-tested program is not merely buggy here. It does not compile.
- Adding a test can change performance (a slot flips to RC) or break the build (a new contradiction). Your test suite becomes part of your type system, and so does a careless test.
- Libraries ship rehearsals, but the plan is whole-program, so an app's traces can flip a library's slots.

## 9. Known weaknesses

- **Line coverage ≠ behaviour coverage.** Rule 3 is necessary, not sufficient. Production *will* hit unrehearsed orderings (late callbacks, rare eviction races). The result is a safe crash, but crash-on-the-unseen is an availability risk for UI and banking apps. Leaks from over-owning are only *watched*, never prevented.
- **Data races in unrehearsed interleavings are not caught in production.** Rule 6 is only as strong as the schedule exploration. This is weaker than O4 for (f).
- **Build cost and determinism.** Every release build replays the whole corpus under a tracing heap and runs schedule exploration. Recorded IO, seeded fuzzing and incremental re-solving are mandatory, and the build is no longer hermetic over source alone.
- **Plan instability.** Performance cliffs can arrive from test changes. Locking the plan and requiring explicit `plan accept` mitigates this but adds a workflow rule.
- **Solver blow-up.** Elementary-cycle enumeration in L is exponential in the worst case, and unsat cores over long traces need good minimisation to make readable errors.
- **FFI.** C cannot be rehearsed. References passed to C are pinned as owning until the binding's release function is called, which is a de facto annotation on bindings.
- **Implementation risk is high** for an AI-written compiler. It needs three runtimes (rehearsal GC, RC, generation checks), a deterministic scheduler, a SAT/hitting-set solver with explanation, and a trace format. Each piece is known, but the integration is not.

**Self-assessment:** G2 needs-john (build-time GC only); G3 pass. Simplicity 4, safety 3, expressiveness 5, implementation risk 2, performance 3, concurrency 3, tooling 4. That gives **≈70**: below O1/O4, above every round-1 idea except possibly the best. Its real value may be as a *tool on top of O1*: a rehearsal pass that proposes where the `weak` refs go and fails CI on owning cycles.
