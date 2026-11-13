# Analysis 07: Scent Trails

## 1. The idea in three sentences

An object reached by only one stored reference at a time is freed as soon as that reference is cut and no local variable holds it. An object that has ever had two stored references gets a sticky `shared` bit, and from then on any cut makes it "fade": it is freed after W bytes of allocation unless somebody reads it from a field or stores it again, even if it is still reachable. Stale references are caught by generation checks and give `lost`. `faint` fields and the `Scent` map are non-holding references that keep an object alive only while it is being read. Threads are separate heaps ("colonies") that move graphs to each other with `send`.

## 2. Prior art: a new combination, but every part already exists

| Part | Prior art |
|---|---|
| Free objects that are reachable but stale, and poison references so a later access gives a checked error | **Leak pruning**, Bond & McKinley, ASPLOS 2009. Same premise, used there as a leak-tolerance fallback, not as the main model. https://www.cs.utexas.edu/~mckinley/papers/leak-pruning-asplos-2009.pdf . Related: Melt, OOPSLA 2008, which moves stale objects to disk: https://mdbond.github.io/melt-oopsla-2008.pdf |
| Sticky "has been shared" bit instead of a count | **One-bit reference counting / MRB** (Wise & Friedman 1977; Chikayama & Kimura 1987). https://mmref.readthedocs.io/en/latest/glossary/o.html |
| List of candidates checked against a stack scan at checkpoints | **Deutsch–Bobrow deferred RC**, which keeps a zero-count table and reconciles it against the stack (1976). https://people.cs.umass.edu/~emery/classes/cmpsci691s-fall2004/papers/p522-deutsch.pdf |
| Liveness that lapses unless renewed by use | **Leases** (Java RMI distributed GC: dirty/clean calls with lease renewal): https://www.cs.princeton.edu/courses/archive/fall97/cs461/jdkdocs/guide/rmi/spec/rmi-dgc.doc.html . **SoftReference LRU policy** (cleared when not accessed for a time that scales with free heap): https://jeremymanson.blogspot.de/2009/07/how-hotspot-decides-to-clear_07.html |
| Generation-checked references; heap per thread with move-only `send` | O6/Vale (already covered); Erlang and Pony per-actor heaps. |

What is new: making the lapse-on-disuse rule the language's main semantics for shared data, measuring W in allocation, and **drought mode** (W = 0 in tests). Drought mode is the part with no obvious precedent.

## 3. Soundness counterexamples (illustrative only — not a syntax decision)

**C1. Deselection deletes a list item (data loss, common pattern).**
```
todos.items.add(Item("pay rent"))         // held once: unshared
self.selected = todos.items[0]            // second trail -> shared (sticky)
self.selected = nil                       // cut -> item FADES, still in the list
importPhotos()                            // allocates > W; nobody reads todos.items
render(todos.items)                       // items[0] is lost: trap, or silently skipped
```
Any "current", "selected" or "last-used" field that points into a collection does this. The scheme cannot tell "the last holder let go" from "one of several holders let go", so every cut puts an obligation on every other holder. The idiom (`self.doc = self.doc`) has to run *after* someone else's cut, and the survivor cannot know when that cut happened. In practice the idiom turns into a heartbeat. The idea's "narrow case" (weakness 1) is actually the general case for any object with more than one non-owning observer that is not marked `faint`.

**C2. Library iterators mark every element as shared (breaks scenario (a)).**
```
class LineIter { current                   // non-faint field
  fun next() { current = readLine(); return current } }
for l in it { lines.add(l) }               // l has 2 trails -> shared
                                           // next() overwrites current -> previous line fades
// lines are not read for W -> lines evaporate out of the list
```
Scenario (a) is safe only if every iterator, builder and generator in the library uses `take` or `faint`. Code written by users will get this wrong.

**C3. Removing a conditional DSL node makes the editor fade (G11, scenario (c)).**
```
body { if editing { Button("Save", onTap: { self.save() }) } }
editing = false     // closure freed -> its capture of self is cut -> editor fades
                    // window.editor still holds it; a background tab is idle for W
                    // -> editor evaporates, unsaved text is lost
```
Reassigning `button.onTap` has the same effect. The editor stays alive only while the render loop happens to read `window.editor` from a field.

**C4. Memory-unsafe as specified: the 16-bit generation wraps.**
```
f = faint cache.entries[k]              // ref = (slot S, gen g)
repeat 65536 { tmp = Small() }          // a LIFO slab reuses slot S 65536 times
f.field                                 // gen matches again -> reads an unrelated object, possibly of another type
```
Packed 48+16 references are not memory-safe. They need 64-bit generations (16-byte references), or slots must be retired when their generation saturates. Weakness 6 lists the cost but not this hole.

**C5. Under-specified state machine: re-laying a candidate gets it freed.**
```
tmp = a.f; a.f = nil          // x unshared -> candidate list
b.f = tmp; tmp = nil          // lay. The header has no "held" bit, so either x becomes
                              // shared (weakness 2), or nothing removes it from the candidates.
// checkpoint: x is a candidate and not in a hand -> freed, though b.f holds it -> b.f is lost
```
Making this correct needs a "held" bit that is cleared on cut and checked at the checkpoint. That bit, together with `shared`, is a saturating 2-bit count, and it still cannot recover the step from "shared" back to "held once", which is the source of C1.

**C6. Finalizers re-entering mutating code (surprising behaviour, possible self-deadlock).**
```
list.add(x)    // allocates -> checkpoint -> Conn evaporates -> Conn.deinit runs
               // Conn.deinit calls registry.remove(self), and registry IS `list`, mid-resize
```
Evaporation runs `deinit` inside an arbitrary allocation. That is the classic finalizer re-entrancy problem: invariants are broken, and any lock held by the allocating code is taken a second time. Freeing unshared objects has the same issue when cascades run at checkpoints.

**C7. `send` cannot check its own precondition.**
```
job.config = self.config            // config is now shared
worker.send(take job)               // config is still held by self.config
```
With no counts, the runtime has to walk the whole graph to find shared-bit objects. Then it can deep-copy them (cost and semantics change), refuse the send (surprising), or invalidate them in the sender (`self.config` becomes lost). The idea does not say which.

**C8. Behaviour depends on data size.** W is measured in allocation, so an image editor that decodes 30 MB frames burns through a 64 MB W in two frames. Code that worked with small test images loses state with production-sized images. Drought mode catches this only on paths the tests run, and only if the test checks the object after a checkpoint.

**C9. Leaks.** A dropped cycle can close itself again (weakness 3). A conservative scan can produce false hands. A non-faint "last seen" field read by a heartbeat keeps its target alive forever. These are mild compared with C1–C3: in this scheme the main failure is losing data, not leaking it.

## 4. Scenarios

- **(a) Growing list:** partial. It works only if no library iterator keeps a held reference to the yielded item (C2).
- **(b) Parent pointers:** works with `faint parent`. Without it, the tree is correct but takes depth × W to free. Re-parenting without `take` makes the node fade.
- **(c) UI callback:** partial. No weak capture is needed, but the editor is shared, so any later cut (DSL rebuild, `onTap` reassignment) makes it fade while it is still held (C3).
- **(d) Shared cache:** partial. It is trivial when the cache is a global (a hand). In the case the brief means (held by two components), the survivor must walk the cache or re-store it after the other dies. `Scent` entries are sensible.
- **(e) Mutating a large list:** works. Parameters are hands, so there is no cost.
- **(f) Threads:** hand-wave. Rehoming a graph that contains objects with the shared bit set is unspecified (C7), and there is no shared immutable data.

## 5. Gates and the charter

- **G2: needs-john.** There is no heap trace, so the letter of G2 is met. But each checkpoint is still a collector step started by the runtime: a conservative root scan, a timing-wheel sweep, cascades on a budget, and `deinit` at unspecified times. The Deutsch–Bobrow lineage counts this as a form of GC. That is the unpredictability P-GO and P-JAVA complain about, at a smaller scale. John should decide whether "bounded root scan + deferred frees" counts as a GC run.
- **G3: pass, with a flag.** `faint` is a field modifier with the same status as O1's `weak`. `Scent` is a compiler-known parameterised container, which raises the same pending question as `List`/`Map`.
- **Other goals:**
  - G1 is strained: 11 rules plus a new mental model, and the hold-or-`faint` choice is still needed.
  - G8 cuts both ways. The cut-site report on `lost` is good, but bugs that act at a distance in time are hard to debug.
  - G10 benefits from drought mode.
  - RAII is lost for shared resources (files and sockets must be closed explicitly), which strains the P-C/P-CPP ergonomics O1 keeps.

## 6. Score

| Criterion | W | S | Why |
|---|---|---|---|
| Simplicity & learnability | 25 | 2 | 11 rules plus the fading model. The hold-or-`faint` choice is O1's strong/weak choice, but a wrong choice loses data instead of leaking. The re-store idiom is a non-local obligation. |
| Memory safety | 15 | 3 | Safe only with 64-bit generations: the 16-bit packing is unsound (C4). Reachable data can become `lost`, which is a new class of runtime failure. |
| Expressiveness (b, c, d, implicit self) | 15 | 3 | Cycles and `self` captures are free, but (c) and (d) carry the fade hazard (C1, C3), and `faint` is needed anyway. |
| Implementation risk (AI-written, LLVM) | 15 | 2 | Conservative scan of packed references, generational slabs, timing wheel, budgeted cascades, escape analysis, graph rehoming. The state machine is already under-specified (C5). |
| Performance & predictability | 10 | 2 | A generation check on every heap read, a header write on the old target for every store, 16-byte references, floating garbage up to W, and frees and `deinit` that run at unpredictable times. |
| Concurrency fit | 10 | 2 | Isolated heaps only. `send` is unspecified for shared subgraphs (C7). No shared immutable data. |
| Tooling, debugging & C FFI | 10 | 3 | Drought mode and cut-site traps are real strengths. Manual `pin`/`unpin`, a conservative scan, and failures that show up long after their cause count against it. |

Total = 25×2/5 + 15×3/5 + 15×3/5 + 15×2/5 + 10×2/5 + 10×2/5 + 10×3/5
      = 10 + 9 + 9 + 6 + 4 + 4 + 6 = **48 / 100**

(With 64-bit generations assumed, memory safety rises to 4 and the total to 51.)

Comparison: O1 scores 83 and O4 82, so this is 35 and 34 points behind them. It is 20 below round 1's best (68), in line with round 1's lowest scores. The inventor's self-assessment of 62 credits 4/5 for safety and expressiveness, which C1–C4 do not support.

## 7. What the premise teaches, and the kernel

**What the premise teaches.** The idea swaps "reachable means alive" for "recently used means alive", and the failure mirrors ARC's exactly:
- Reachability gives false positives (cycles stay alive), so the result is leaks.
- Use gives false negatives (an idle holder's object gets freed), so the result is data loss.

Both are guesses at "who still cares". For lifetimes that don't nest, that information is not in the program's access pattern any more than it is in its pointer graph. It has to be *stated*. This is strong evidence for designs where the programmer states it once, cheaply: O1's `weak`, or O4's explicit `shared` kind. It is evidence against further inference schemes.

A second lesson: leaks are much better than data loss as a failure mode. A model that fails by leaking, plus a detector, beats a model that fails by losing data, plus a test mode.

A third lesson: measuring time in allocation, plus a W = 0 mode, is a clean way to make memory behaviour that depends on timing deterministic and testable.

**Kernel worth stealing, for O1 (also fits O4):**
1. **Staleness report (debug mode).** Each object header records the allocation epoch of its last field read. A debug or `test` run lists objects that are reachable but have not been read for N MB of allocation, together with the store site that holds them. Under ARC those objects are exactly the cycle leaks and forgotten observers or callbacks. This is O1's main weakness, found without a cycle collector and with no effect on G2 in release builds. It is SWAT/Cork-style leak detection, with an allocation clock so the results are deterministic.
2. **`Cache` / `Scent` as a built-in container.** Values are evicted when they have not been read within W bytes of allocation, and drought mode (W = 0) runs in tests. This fixes scenario (d)'s "hot stays, cold goes" without weak-valued maps.
3. **Report the cause on nil.** In debug builds, when an O1 `weak` reference reads nil, report the site of the final strong release. That is the "trap shows where the trail was cut" idea, which costs nothing in release builds.
4. (Minor, known.) A uniqueness or shared bit lets ARC skip count traffic for objects that were never shared. This is the one-bit RC / Perceus territory, and worth an O1 optimisation ADR.

## 8. Verdict

**Kernel worth stealing.** As a memory model it is a dead end: freeing reachable data turns ARC's leaks into data loss, and the obligation on surviving holders is non-local and has no fixed time. The allocation-clocked staleness tooling and the drought-tested cache transfer cleanly to O1.
