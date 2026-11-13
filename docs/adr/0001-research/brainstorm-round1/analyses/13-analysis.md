# Analysis 13: The Heap Plan (closed-world outlives-pruning with a group backstop)

Analyst: independent. Inputs: brief.md, CHARTER.md, ideas/13-closed-world-heap-plan.md.

## 1. The idea in three sentences

The compiler sees the whole program and builds a graph of which class can point to which. Wherever it can prove that a target always outlives its source (an immortal object, a dominator, a write-once owner), it turns that edge into an uncounted pointer. Classes that end up outside every cycle get plain RC. Classes still inside a cycle are put into dynamically merged "groups", each counted as one unit and freed whole when nothing outside refers into it.
The programmer writes GC-style code with no `weak`, and gets a readable per-class "heap plan" as a build artefact.

## 2. Prior art: novel combination, not novel parts

| Component | Known as | Source |
|---|---|---|
| Group RC, where an SCC or group is counted as one unit and freed whole | Bobrow 1980, "Managing Reentrant Structures Using Reference Counts" (TOPLAS) | https://www.scilit.net/publications/c54cd62b50f9da01c128c03b4119f044 , https://en.wikipedia.org/wiki/Reference_counting |
| Union-find merging of SCCs into one RC'd unit | Parkinson, Clebsch, Wrigstad, ISMM 2024 (Verona). Restricted to *frozen* data because mutable groups can't split | https://www.microsoft.com/en-us/research/publication/reference-counting-deeply-immutable-data-structures-with-cycles-an-intellectual-abstract/ |
| "Type-graph acyclic classes can't cycle, so skip cycle handling" | Bacon & Rajan 2001 "green" (acyclic) classes. Nim's acyclic-type inference is the same idea | https://pages.cs.wisc.edu/%7Ecymen/misc/interests/Bacon01Concurrent.pdf |
| Whole-program analysis that removes most RC ops | Lobster compile-time RC | https://aardappel.github.io/lobster/memory_management.html |
| Region RC, freed as a whole, with an outer count | Project Verona regions | https://arxiv.org/pdf/2309.02983 |
| Outlives proofs via dominance/confinement | Ownership-inference literature (object-sensitive confinement analysis) | (general knowledge, no search spent) |

What is new:
- Using outlives proofs to delete type-graph edges *before* the SCC computation, so the compiler effectively infers `unowned`.
- The spec contract "unreachable ≤ free ≤ group death".
- Shipping the plan as a CI-diffable artefact.
- Proof-audit mode, where pruned edges become generation-checked refs in tests.

This combination is genuinely not in O1–O8. Note, though, that Parkinson et al. limit union-find groups to immutable data, and that limit is exactly this idea's main problem (see §3, CE1).

## 3. Soundness: counterexamples

Illustrative only, not a syntax decision.

**CE1: Unbounded retention (an operational leak) in a long-lived knot.** This is the strongest counterexample.
```
class Doc   { bus = Bus(); panels = List<Panel>() }
class Panel { doc: Doc; init(d) { doc = d; d.bus.on("change", { self.refresh() }) }
              func close() { doc.bus.off(...); doc.panels.remove(self) } }
// Doc open for hours; user opens/closes 1,000 panels, each holding a 5 MB image.
```
- The cycle is `Doc -> Bus -> closure -> Panel -> Doc`. `Panel.doc` can't be pruned, because the Doc does not dominate the Panel (the Window holds it too). The Doc is not immortal.
- So {Doc, Bus, closure env, Panel} form a knot, and every panel ever opened merges into the Doc's group.
- `close()` removes the links, but groups never shrink. All 1,000 panels and their counted outgoing references (the 5 MB images) stay alive until the Doc closes.
- Under a GC, or under O1 with one `weak`, they would be freed.
- The same pattern gives unbounded growth for:
  - an LRU cache built on a doubly-linked list (`prev`/`next` plus a `Map` into the nodes: never dominated, so grouped);
  - a server-lifetime connection graph;
  - a scene graph with a `Selection` pointer.
- The spec allows a conforming implementation to retain memory up to "everything ever allocated into the group". For long-running UI apps (G11) that is a leak in practice. The only fix is restructuring to IDs or slot maps, which is the manual-handle model the idea set out to avoid.

**CE2: Merge contagion.**
```
nodeA = docA.root.children[0]
docB.root.add(nodeA)     // knot-internal store: groups(A) ∪ groups(B), forever
docA = nil               // docA's whole tree is retained until docB dies
```
One cut-and-paste permanently ties two documents' lifetimes together. The cause is invisible in source and depends on runtime history, not on code shape. `lang plan` can't explain it because it is per-class, not per-instance.

**CE3: Rule (ii) with allocation-site abstraction is unsound, or useless, for recursive structures.**
```
p.add(c)            // p.children has c, c.parent = p
q.add(c)            // legal (GC-semantics) program bug: c in both lists, c.parent = q
q.parent.remove(q)  // q freed (c.parent is uncounted); q's children released, c survives via p
c.parent.name       // use-after-free in release build
```
- Allocation-site contexts conflate all `Node`s. "Every heap path to a Node goes through a Node" is trivially true, but it does not show that the path goes through *`c.parent` specifically*.
- Proving that would need a shape invariant: c is in exactly one list, and that list belongs to c.parent. That is heap-shape analysis, which is notoriously hard.
- So either the engine is too weak and (b) almost always ends up grouped (the idea's own (b) story then becomes the fallback), or it is too clever and wrong, which means a release-build UAF.
- Proof-audit mode catches this only if a test exercises the aliasing.
- The same precision demand appears in (c) once two Windows exist and a factory places `w1.editor.saveButton` into `w2.view`.

**CE4: The data-race hole around `Locked`.**
```
n = Node()
results = Locked(List<Node>())
with results as r { r.append(n) }               // n now reachable under the lock AND from the main thread
spawn { with results as r { r[0].name = "x" } }
n.name = "y"                                    // unsynchronised write: data race
with results as r { leaked = r }                // guard escapes the with-block
```
The claim that "data races can't be written" needs two unstated rules:
1. Values stored into a `Locked` are moved, deep-copied or isolated.
2. The `with` binding can't escape its block.

Rule 1 is an isolation discipline (Pony `iso` or Verona regions). Rule 2 is a scoped-borrow rule. Neither is among the five rules. "Copy on send" is also undefined for closures, for `File`s, and for cyclic graphs (deep-copying a group).

**CE5: Surprising group `deinit`.** Member A's `deinit` calls `b.flush()` on member B, whose `deinit` (unspecified order) has already closed B's file. This is not a UAF, because memory goes only after all deinits run, but it is a logical use-after-close. In grouped classes, `deinit` is effectively unusable for anything that touches peers.

**CE6: The spec bound is near-vacuous.** §5.11 defines "grouped" over the *unpruned declared* type graph. In that graph a function-typed field such as `onTap: () -> Void` can point to any closure env, and a closure can capture anything. So every class with a callback field, plus everything that is ever captured, sits in one giant spec SCC. The *portable* guarantee for most UI classes is then "freed no later than the giant group's death", which is roughly program exit. Real behaviour depends on how precise a given compiler version is.

**CE7: FFI breaks the closed world.** On real targets, scenario (c)'s closure is handed to AppKit, Win32 or GTK, so C stores it. The edge leaves the closed world. Either the closure is pinned until C calls an unregister (manual memory again), or it is treated as a global root, which groups the editor with everything it touches.

Not found: deadlocks beyond the ordinary nested-`with` lock-ordering one, and stuck states. Pin chains are sound as described, just slow.

## 4. Scenarios

| | Verdict |
|---|---|
| (a) | **Works.** List and File are acyclic and exact. Uniqueness analysis gives zero-count moves. |
| (b) | **Hand-waves.** The exact-tier story depends on a shape proof rule (ii) can't deliver soundly (CE3). Realistically it is grouped, so removed subtrees are retained until the tree dies. |
| (c) | **Works semantically, hand-waves on precision.** It is correct either way: pruned, or grouped and freed when the window dies. Bus- or document-registered handlers degrade into CE1 retention, and native toolkits hit CE7. |
| (d) | **Partially works.** The plain shared cache is fine (exact). An `onEvict` closure or an LRU list gives permanent, ever-growing retention (CE1), which the idea itself admits. |
| (e) | **Works.** Plain reference passing. The whole program shows that `xs` doesn't escape, so there is no inc/dec. |
| (f) | **Hand-waves.** Copy/move/frozen/Locked is fine in outline, but CE4 shows the missing isolation and escape rules. Deep copy of graphs and closures is undefined. |

## 5. Gates

- **G2: pass.**
  - Group free is a sweep over a member list, and a merge is union-find. Neither is a reachability trace.
  - Pins are RC operations.
  - "Split on remove" (§8) would be a partial trace and would push this to needs-john, but it is explicitly excluded.
  - The cost of passing G2 is CE1: without a trace, groups can't shrink.
- **G3: needs-john.**
  - No annotations or macros are needed for memory. `frozen` and `Locked` are language keywords or built-ins, not user annotations.
  - The model does depend on built-in parameterised `List<T>`, `Map<K,V>` and `Locked(T)`, and the heap type graph is computed per container instantiation. This is the brief's pending flag, no worse than O1 or O4.

## 6. Scores

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 4 | Fewest surface rules of any option (no `weak`, no borrows). Docked one point because "when does this die?" is non-local, history-dependent (CE2) and tied to the compiler's proof engine. |
| Memory safety | 15 | 3 | Safe in principle, but release-build safety rests on an unproven, hard abstract interpreter (CE3), and there is a data-race hole (CE4). |
| Expressiveness (b, c, d, OO / self) | 15 | 4 | You write (b), (c) and (d) GC-style with implicit `self` and free capture. Docked one point because the retention fix for (b) and (d) is restructuring into handles. |
| Implementation risk (AI-written, LLVM) | 15 | 1 | Whole-program 0-CFA, object-sensitive confinement and write-once inference, may-release effects for pins, union-find runtime, proof-audit codegen, thread-escape analysis and PGO. An unsound proof is a silent UAF. This is the hardest compiler on the list. |
| Performance & predictability | 10 | 2 | RC elision and arena-like groups are fast. But peak memory and `deinit` timing change with distant edits and runtime history, pin chains are a performance cliff, and every knot-internal store does a union-find lookup. |
| Concurrency fit | 10 | 3 | Atomic counts only where needed is good, and frozen/Locked is reasonable. Isolation and escape rules are missing (CE4), and deep copy on send is costly and ill-defined. |
| Tooling, debuggability & C FFI | 10 | 3 | The plan artefact, `--diff` and proof-audit mode are genuinely good. Against that: whole-program-only builds (no binary libs, slow incremental builds, hard IDE/LSP), FFI that breaks the closed world (CE7), and release UAFs from bad proofs that are very hard to debug. |

Weighted total = Σ W×S/5:
- 25×4/5 = 20.0
- 15×3/5 = 9.0
- 15×4/5 = 12.0
- 15×1/5 = 3.0
- 10×2/5 = 4.0
- 10×3/5 = 6.0
- 10×3/5 = 6.0

**Total = 20 + 9 + 12 + 3 + 4 + 6 + 6 = 60 / 100.**

Comparison:
- **vs O1 (83):** 23 points behind. O1 is equally simple in practice (one `weak` rule), safe by construction and cheap to build.
- **vs O4 (82):** 22 points behind.

The idea beats both only on surface simplicity for beginners and on (c) ergonomics. It loses heavily on implementation risk and predictability. Even with implementation risk raised to 3, the total is 66, still well below both.

## 7. Fatal flaw and salvageable kernel

**Fatal flaw.** Two problems combine:
1. The safety-critical proof engine is beyond what an AI-written compiler can be trusted to get sound.
2. The collector-free backstop can't shrink, so the cycles it exists to handle (long-lived mutable graphs, document-scoped observers, LRU lists) leak in practice.

The idea removes `weak` by moving the hard lifetime question into a heavyweight, fallible analysis, and the fallback is region-style retention, which the brief already lists as a known failure. Parkinson et al. restrict union-find groups to *immutable* data for exactly this reason.

**Kernel worth stealing, into O1 especially and also O4's `shared` kind.**
- **Type-graph cycle lint plus a heap-plan report.** In O1, compute the closed-world (or per-package) type-graph SCCs and *tell the user* which edges can close a cycle: "Editor -> Button.onTap -> closure captures self -> Editor: one of these must be `weak`". That turns O1's main pitfall (silent leaks from cycles) into a compile-time diagnostic. It needs no new semantics.
- **Outlives-pruning and immortality inference as pure optimizations.** Where the compiler proves an edge's target outlives its source, or that an object is an app-lifetime singleton, it elides the RC ops. Proof-audit mode (generation-checked in debug/test) guards soundness. If a proof is wrong, only the optimization is lost, and nothing changes in the semantics.
- **Proof-audit mode** as a general pattern: every unchecked optimization ships with a checked twin in test builds.
- Leave group RC out, or limit it to `frozen` data, as Parkinson et al. do.

## 8. Verdict

**Kernel worth stealing.**
