# Analysis 17: Scenes and Call Sheets

Analyst verdict: **Kernel worth stealing**. Weighted total: **52 / 100** (O1 83, O4 82). The inventor self-assessed about 70.

All code is illustrative only, not a syntax decision.

## 1. The idea in three sentences

Class instances ("actors") are bump-allocated into dynamic, overlapping regions ("scenes"). Each scene is opened around a lead object and owned by one move-only handle. A scene's objects may hold raw pointers only into the scene itself or into older scenes named on its acyclic "call sheet". Anything else must use a generation-checked weak reference (an "understudy"). Region lifetime is reference-counted per scene, never per pointer, and every free is deferred to the end of the current event dispatch or loop iteration (a "cue"). That makes all references valid within a cue with no checks, and a small inferred shadow stack protects the locals that span cues.

## 2. Prior art

It is not a rename of any single option on the covered list, but nearly every part has a direct ancestor:

- **Reference-counted regions: Gay & Aiken, RC / "Language support for regions" (PLDI 2001).** RC prevents unsafe region deletion by keeping a count of references to each region, and deleting a region frees everything in it ([Berkeley TR](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2000/5340.html), [dblp](https://dblp1.uni-trier.de/rec/conf/pldi/GayA01.html)). Scenes count at a coarser grain (call-sheet edges rather than cross-region pointers), which is cheaper but less precise.
- **Ancestor-only cross-pool references: Apache APR pools.** In APR, data may be put into a table only if it was allocated in that table's pool or one of its ancestors, and `APR_POOL_DEBUG` checks this on insert ([APR pool debug](https://apr.apache.org/docs/apr/group___pool_debug.html)). That is rule 6 for a tree, checked at runtime. Scenes generalise the tree to a DAG, and "waiting in the wings" replaces "parent destroys children".
- **Single-entry regions, freeze, and lock-guarded regions: Project Verona.** In Verona, a region has one entry point, references within a region are unrestricted, and cross-region references must be `iso` or `imm`. Cowns plus `when` blocks guard concurrent access ([Verona regions summary](https://tamnd.github.io/brain/research/memory-management/ownership/07_project_verona_regions.md), [OOPSLA 2023 paper](https://arxiv.org/pdf/2309.02983)). Lead + stage handle maps to the entry point + `iso`, `freeze` maps to `imm`, and `guarded`/`backstage` maps to cown/`when`.
- **Dynamic regions with outlives ordering: Cyclone.** Cyclone has dynamic regions with handles, plus outlives constraints and region subtyping ([Cyclone regions TR](https://www.cs.umd.edu/~mwh/papers/cyclone_regions_tr.pdf)). The call sheet amounts to an outlives relation declared at `open` time instead of in types.
- **Free only at quiescent points: QSBR / epoch reclamation and ObjC autorelease pools.** Frees are deferred until each thread passes a quiescent state ([CPython QSBR](https://chromium.googlesource.com/external/github.com/python/cpython/+/b00a14018172652226bd6efb517af021bd03aa88/InternalDocs/qsbr.md)). The cue is a single-thread quiescent state.

**What is new:** Verona lets regions refer only *down* (to iso children) or to immutable data. Scenes let them refer *up and sideways* into mutable older regions, and they keep the DAG acyclic by ordering on creation time, with scene-granular counting. Two further twists are new as far as I know: using cue quiescence as the within-cue safety argument rather than as a performance trick, and the "implicit self decides the birth region" rule. It is a genuine combination with one real new joint, not a rename.

## 3. Soundness: counterexamples

**C1. Use-after-free through the "lead of a stage handle it owns" clause (rule 6).** The check runs only when the field is stored. Ownership of the handle can change afterwards.
```
class App
  var w: stage Editor?
  var focused: Editor?
  func f()
    w = open Editor()          // Editor scene calls App's scene, not the other way round
    focused = w                // allowed: the lead of a handle App owns
    w = nil                    // handle dropped → Editor struck
  // cue end: Editor has caller count 0 (nobody calls it) and is not on the cast list → FREED
  func g() { focused.text = "x" }   // next cue: dangling write
```
The same thing happens if the handle is moved into another actor (`other.keep(w)`) or removed from `windows`. To fix it, the lead must be reachable only *through* the handle (a non-storable borrow), or plain lead pointers must count against the scene. The second fix is per-pointer counting coming back in.

**C2. Data race: `send` checks incoming callers only, not the outgoing call sheet (rule 11).**
```
let counter = open Counter()                 // main thread, mutable
let job = open Batch() calling [counter]     // the default call sheet would also be a mutable scene
job.c = counter                              // legal: counter is on the call sheet
send job to worker                           // legal: nothing calls on job
// worker: job.c.n += 1     main: counter.n += 1   → race; the caller-count decrement is also non-atomic
```
The fix is "every scene in reach(s) must be frozen or guarded". `freeze s` has the same gap: s's actors may point into a mutable scene. Neither rule states this.

**C3. Cross-thread use-after-free of a frozen scene.** Thread T2 reads an understudy to a frozen actor, and the rules say the resulting local is "safe for the rest of the cue". Meanwhile T1 drops the scene's handle. T1's cue end checks only *T1's* cast list and caller count, then frees the scene while T2 is still reading it. Freeing frozen scenes needs global epoch reclamation (QSBR across all threads), which the design does not specify.

**C4. Leak by default in declarative UI (G11).** Closures are actors (rule 8) and are born in `self`'s scene (rule 3).
```
class Editor
  func render() -> View                        // runs on every keystroke
    VStack { Text(self.text); Button("Save") { self.save() } }   // ≥3 actors + 1 closure into Editor's scene
```
A two-hour editing session leaves millions of dead view nodes and closures in the Editor scene until the window closes. The same applies to any method of a long-lived object, Production included, that creates temporary helper objects, iterators or callbacks. The only general remedy is `restage`, which is a copying collection.

**C5. Nested cues never free (rule 9, "end of the outermost cue only").** A thread entry is itself a cue, so `while true { cue { … } }` on a worker thread is a nested cue and frees nothing until the thread exits. The same goes for a modal dialog's nested run loop and for a bulk import running inside a button handler. Freeing at nested cue ends would make this safe only if may-cue inference is perfect *and* every receiver and temporary (not just named locals) is shadow-stacked.

**C6. Lost writes through `edit` aliasing (memory-safe, but surprising).**
```
normalise(edit doc.rows[3].cells)   // pointer into the rows buffer
// inside: doc.rows.add(r) via an app-global path → rows reallocates; the old buffer is deferred, not freed
// the callee keeps writing into the stale buffer; the writes silently vanish
```
Rule 2 forbids aliasing only on the *same variable*. Swift needs dynamic exclusivity checks for exactly this case.

**C7. Inconsistent strike cascade.** Rule 5 drops owned handles when the owning scene is *struck*, but section 5 cascades them when it is *freed*. Under the free-time reading, the default "child calls opener, opener holds child's handle" pattern deadlocks into a leak. W opens D, so D calls W, and W stores D's handle. W cannot be freed while D calls it, and D is struck only when W is freed. Under the strike-time reading, a struck scene that is waiting in the wings still has live actors whose handle fields now refer to struck scenes. It is also unspecified whether new actors can be born into a struck scene, and allowing that reopens the cycle.

## 4. Scenarios

- **(a)** Works. Props are plain owned values with last-use moves, as in O2/O4. Copy semantics when reading an actor's prop field (`let xs = self.items`) needs COW, which the design does not mention.
- **(b)** Works for a build-once tree, since the intra-scene cycle is free. For a mutated tree it is a hand-wave: removed subtrees stay until the scene is struck.
- **(c)** Mostly genuine, and the best part of the design. Window-scoped `self` capture has no `weak`, Signals use understudies, and mid-event close is safe. It is undermined by C1 (App → focused editor) and C4 (re-rendered closures leak).
- **(d)** Works when entries are props. Actor entries either leak in the long-lived cache scene, or need a scene per entry, at which point the panes (older than the entries) fall back to understudies, which are weak refs.
- **(e)** Works: in place, one pointer. The C6 aliasing surprise applies through actor paths.
- **(f)** Hand-waved. Besides C2 and C3, `worker.run({ backstage stats {…} })` sends a closure (an actor in a main-thread scene) to another thread, which breaks "a scene belongs to one thread". The design also never says how a move-only `stage` handle to a guarded scene is shared by two threads.

## 5. Gates

- **G2: pass (core); needs-john if `restage` is adopted.** There is no tracing. A free walks only the chunks being freed and touches no live objects, which makes it closer to APR pools than to a GC. But C4 means real programs will want `restage`, a programmer-triggered copying collection, so the gate pass is fragile in practice.
- **G3: needs-john (the shared pending question).** `List<T>`, `stage T` and `~T` are compiler-known parameterised types. `edit`, `on s`, `calling [...]` and `guarded` are keywords or expressions, not annotations. It adds nothing worse than O1's `weak`.

## 6. Scores

| Criterion | W | Score | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 2 | 11 rules, plus the user must design a scene DAG ahead of time and reason non-locally about "which scene is this born into". Leak-by-default traps (C4) and runtime "not on call sheet" errors. Not Rust-steep, but well above O1's "strong + weak". |
| Memory safety | 15 | 3 | The within-cue argument is sound. As written, the spec has a single-thread UAF (C1) and two cross-thread holes (C2, C3). All are patchable, but the invariant is intricate. |
| Expressiveness (b, c, d, OO/G11) | 15 | 3 | (c) and implicit-self birth are excellent. Older → younger pointers need understudies, churny actor data leaks, and declarative re-render (G11) is the worst case. |
| Implementation risk (AI-written, LLVM) | 15 | 2 | It needs: an aligned-chunk allocator, store checks with cached reach sets and per-list scene summaries, whole-program may-cue inference across modules and FFI, a shadow stack, cue-end machinery, type-header chunk walks, and cross-thread send/freeze/guard with epochs. The subtle invariants are easy to get silently wrong. |
| Performance & predictability | 10 | 3 | Bump allocation and no per-pointer RC traffic give excellent throughput. Memory is unpredictable (garbage until strike, deferred buffers, forgotten cues), and striking a large scene causes a pause proportional to its size. |
| Concurrency fit | 10 | 3 | Whole-region send/freeze/monitor is a good Verona-like shape with few atomics, but the rules as written allow races (C2) and leave closure or handle sharing across threads unspecified. |
| Tooling, debugging & C FFI | 10 | 3 | The scene inspector ("born in Window#12 at editor.x:40") doubles as a nice leak finder. On the cost side, C needs `pin` across cues, cue end must hook into foreign run loops (AppKit, Win32), and C callbacks are pessimised to may-cue. |

**Arithmetic:** 25×2/5 = 10; 15×3/5 = 9; 15×3/5 = 9; 15×2/5 = 6; 10×3/5 = 6; 10×3/5 = 6; 10×3/5 = 6.
Total = 10 + 9 + 9 + 6 + 6 + 6 + 6 = **52**. That is 31 below O1 (83) and 30 below O4 (82). It loses mostly on simplicity (−10 versus a 4) and implementation risk.

## 7. Fatal flaw and salvageable kernel

**Fatal flaw:** reclamation granularity. Nothing in a scene is freed before the whole scene is struck, and by default an object is born into the scene of the long-lived `self` that creates it. So ordinary OO and declarative-UI code (temporary helpers, closures, re-rendered view trees, edited trees, evicted actor cache entries) leaks for the lifetime of the window, session or program. The general escape hatch is a copying collection (`restage`), which runs into G2. On top of that, the safety story depends on a lot of runtime machinery (reach sets, cast list, may-cue inference, cross-thread epochs) that already has holes in its first specification (C1–C3).

**Salvageable kernel (adoptable into O1 or O4):**
1. **Cue-boundary deferred release (O1 optimisation).** Treat each event dispatch as an autorelease-style quiescent point. A final release that happens mid-dispatch is queued to the cue end, so the compiler can drop retain/release on locals and temporaries within a dispatch. A running closure can never be freed out from under itself, and closing a window mid-tap becomes trivially safe. Swift and ObjC already show this works. Only the "may-cue" inference for nested run loops is new.
2. **Weak-by-default listener lists (`Signal`) in the standard library.** App-wide subscriptions hold their listeners weakly, so a listener whose owner dies is skipped silently. That removes most of the `[weak self]` noise in (c) for O1 with no new language rule.
3. **Optional bump-allocated "scene" arenas with a creation-ordered reference check.** Useful as a library or optimisation tool: a request or parse arena where stores from older to younger objects are checked APR-style in debug builds. It must not be the primary model.

## 8. Verdict

**Kernel worth stealing.** The call-sheet DAG is a genuinely clever way to allow sideways and upward mutable cross-region pointers without cycles, and it handles scenario (c) elegantly. But coarse reclamation, leak-by-default birth and a heavy, still-leaky runtime safety apparatus keep it well below O1 and O4. Cue-deferred release and weak-by-default Signals should go into O1/O4.
