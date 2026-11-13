# Analysis 11 — Dreamed Regions ("Somnia")

Analyst: independent. Pseudo-code is illustrative only — not a syntax decision.

## 1. Restatement

1. Every object goes into a region chosen per allocation site (`Self`, `Arg(i)`, `Target`, `Fresh`, `Scratch`, `Shared`).
   A region is freed whole at a compiler-inserted "rest point" once no other region points into it and no live
   local points into it.
2. Only cross-region heap stores are counted (write barrier). Locals are never counted; they are found from stack
   maps at rest points.
3. An offline "dream" reads telemetry from test runs and rewrites the per-site placements into a committed
   `app.sleep` file, merging sites to absorb cycles and splitting them to cut waste. A bad dream should only ever
   cost memory, never safety.

## 2. Prior art

The run-time mechanism is known. The learned-placement loop on top of it is a new combination.

- **Region-level RC counting only cross-region pointers, with locals scanned at delete time.** This is Gay & Aiken's
  RC regions (C@ / RC, PLDI 1998/2001): [gay-regions.pdf](https://www.cs.cornell.edu/courses/cs612/2000SP/papers/gay-regions.pdf),
  [Berkeley TR](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2000/5340.html). Somnia's region header, its barrier
  and its "pinned by stack" rule are essentially that design with regions made implicit.
- **Not counting locals, then reconciling against the stack at intervals.** This is Deutsch–Bobrow deferred RC (1976):
  [p522-deutsch.pdf](https://people.cs.umass.edu/~emery/classes/cmpsci691s-fall2004/papers/p522-deutsch.pdf). Light
  sleep is a deferred-RC reconciliation done at region granularity.
- **Predicting lifetimes from allocation sites and placing objects by the prediction.** Barrett & Zorn
  ([PLDI 1993](https://bibtex.github.io/PLDI-1993-BarrettZ.html)), profile-based pretenuring, and Google's LLAMA
  ([ASPLOS 2020](https://research.google/pubs/learning-based-memory-allocation-for-c-server-workloads/)), which
  learns lifetime classes and places objects into lifetime-matched huge pages. All of these use profiles for
  *performance only*, with a correct allocator or GC underneath.
- **Regions with per-region strategies and isolation for threads.** Project Verona's region capabilities
  ([OOPSLA 2023](https://www.microsoft.com/en-us/research/publication/reference-capabilities-for-flexible-memory-management/)).
  Verona makes regions explicit and checked by the type system, not learned.

**What is new:** making profile data decide whether memory is *reclaimed at all* (leak or no leak), not only how
fast it is reclaimed, and delivering that plan as a diffable artifact. That novelty is also the source of the
failure.

## 3. Soundness: counterexamples

**C1. Leak-or-bloat is forced for dynamic cyclic graphs (fundamental).**
```
class User { var friends = List() }
fun onSignup(dir, name) { u = User(name); dir.users.add(u) }   // each signup: different handler call
fun befriend(a, b) { a.friends.add(b); b.friends.add(a) }
fun onDelete(dir, u) { dir.users.remove(u) }
```
- **Placement `Fresh`, or promoted Scratch:** each user is its own region. Friends form cross-region cycles. A
  deleted pair leaks forever, because release has no detector.
- **Placement `Target`:** every user lands in the directory's region. Deleted users are never freed while the
  directory lives, which is forever.
- No per-site placement fixes this, because the right grouping is a property of *run-time* edges, not of sites.
- The same holds for observer graphs, scene graphs with back-links, and actor peers.
- The only cure is the lenient variant's trial deletion, which is a cycle collector, i.e. O7.

**C2. The day-one defaults retain an entire streamed file.**
```
for line in File("10GB.log").lines() { if line.has("ERR") { n += 1 } }
```
- `lines()` is a method, so its iterator gets `Self` and lands in the File's region.
- `next()` is a method, so each line string gets `Self` and lands in the iterator's region, which is the File's
  region.
- Nothing escapes, but nothing is freed until the File region dies after the loop. Peak memory is about 10 GB.
- The pitch's claim that the defaults handle (a) on day one does not hold for stdlib iterator code.
- There is also a deeper problem: one stdlib site needs `Scratch` for streaming callers and a region placement for
  collecting callers. Placement is per site, not per calling context, so a library cannot be dreamed for all users
  at once.

**C3. "Allocate, then store later" has no good placement.**
```
for raw in src { t = raw.trim(); if t != "" { lines.add(t) } }
```
- `trim()`'s result is not stored immediately, so `Target` cannot apply, and it has no argument for `Arg` to name.
- The available placements are:
  - `Self`: the result lands in raw's region, which drags the source along.
  - `Scratch`: t escapes, so the whole iteration's scratch (garbage included) is promoted. That gives 1M lines →
    1M regions.
- `region(ptr)` is "mask to the chunk header". Each region therefore owns at least one chunk, so 1M one-string
  regions cost 1M chunks (≈4 GB at 4 KB chunks).
- The dream's "split to `Fresh`" fix for (d) hits the same per-region chunk floor.

**C4. Holding a small value keeps a large region alive (surprising drag).**
`recent.add(doc.title)` keeps the whole 100 MB document region alive for a 20-byte string. With ARC only the
string would survive. The user cannot fix this at run time; only a re-dream can.

**C5. Use-after-move on `send` through an uncounted local alias (dangle/race).**
```
job = Batch(rows); keep = job
spawn worker(send job)        // region count 0, job is anchor → O(1) move
keep.rows.add(1)              // touches a region now owned by another thread
```
The count ignores locals, so `send` must also scan the sender's stack. The spec doesn't say so. The spec gives no
rule either way for using `keep` afterwards.

**C6. Freeing `Shared` objects needs every thread's stack (dangle, or a global handshake).**
- Thread A holds a local `s` that points to a shared object.
- Thread B drops the last heap reference to it, and at B's rest point the region is unpinned on B's stack.
- B frees it, and A dangles.
- Making this safe requires all threads to reach a rest point (an epoch or safepoint handshake), which is a
  cross-thread root scan, uncomfortably close to G2's line.
- Similarly, `stats.last = myLocalNode` makes a `Shared` region point into a thread-local region. That is a
  non-atomic increment from another thread, and a data race on read. The spec needs a "shared holds only shared or
  values" rule, which it doesn't state.

**C7. "Semantics are identical across sleep files" is false.**
- **Finalizer timing.** In `for p in paths { f = File(p); use(f) }` with no `close()`:
  - with one sleep file each File is freed per rest, so it works
  - with another the File sites are merged into a long-lived region, so the program hits EMFILE and crashes
- **Move vs. copy.** Whether `send` moves or copies depends on whether the region has outgoing edges, which depends
  on placement. Aliasing behaviour after a send therefore depends on training (see C5).
- **Deadlocks.** The lock is per region, and region membership is learned:
  - Two `shared` objects in one region share a lock, so A→B / B→A calls serialize safely.
  - If the dream splits them, the same code deadlocks.
  - Merging them introduces re-entrancy on one lock.

**C8. Stuck or slow: rest points at every back-edge.**
- If every rest enumerates all frames, `for i in 0..1e9 { p = Point(i,i) }` scans the full stack 10⁹ times. If
  rests are amortised instead, scratch grows between them. Either way the rule "back-edge = rest point" needs a
  budget the spec doesn't give.
- Deep recursion with no loops never rests (acknowledged in the idea).

**C9. Callbacks registered in long-lived registries leak, with no escape hatch.**
`Notifications.observe("tick") { self.refresh() }` gives a global edge into the Editor region, which then lives
forever. O1 answers this with `weak self`. Somnia removed weak refs and offers no replacement except manual
unsubscribe.

**Net assessment:**
- The single-threaded safety core (RC regions plus stack pinning) is sound and well-precedented.
- The thread story has real gaps (C5, C6).
- The "only efficiency depends on training" invariant is broken (C7).
- Leaks are not a training-coverage problem. They are structurally unfixable for churned cyclic graphs (C1).

## 4. Scenarios

| | Verdict |
|---|---|
| (a) | **Partial.** Correct, but defaults retain the whole stream (C2), and allocate-then-store fragments into chunk-per-line regions (C3). |
| (b) | **Works** for a static tree, which becomes one region with internal cycles. **Partial** under detach and graft: drag (C4), or a leak if subtrees are `Fresh`. |
| (c) | **Works** for window-owned views. The `Self` default co-locates the editor, views and closure, so no `weak self` is needed, which is genuinely nice. **Fails** for registry or timer callbacks (C9). |
| (d) | **Partial.** The default grows waste until the cache dies. Splitting to `Fresh` costs a chunk per entry, and cross-entry links leak (C1). |
| (e) | **Works.** No copy, no RC, and no barrier on scalars. |
| (f) | **Hand-wave.** Move needs an unstated stack-alias scan (C5). Shared freeing needs a cross-thread handshake (C6). Move vs. copy and lock granularity depend on training (C7). |

## 5. Gates

- **G2: pass (strict variant), with a flag.**
  - Release builds never trace the heap. Rest points do root enumeration only, as in deferred RC.
  - The lenient variant (trial deletion over the region graph) **fails**.
  - The flag: making `Shared` safe (C6) needs a cross-thread safepoint root scan. John should decide whether that
    counts as a "collection run".
- **G3: needs-john, leaning pass.**
  - The model needs no generics or annotations in source.
  - `app.sleep` is a per-site directive file that is reviewed in PRs and changes observable behaviour (C7). That is
    an annotation moved out of the source, not removed.
  - Like every option here, it relies on built-in `List`/`Map`.
- **Other charter strain:**
  - G8 (debugging): debug and release builds have different memory behaviour.
  - G10 (testing): the test suite silently becomes the production memory plan, so coverage gaps turn into leaks.
  - G7 (builds): output depends on a training artifact. Variant B breaks reproducibility and code signing outright.
  - P-GO and P-JAVA in spirit: memory is non-local and hard to predict, the complaint those languages draw.

## 6. Score

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 3 | Writing code is GC-easy. But the hidden rules (drag, rest points, sites, train-and-commit, move-vs-copy, manual unsubscribe) make leak-debugging hard. |
| Memory safety | 15 | 4 | The single-thread core is sound. The `send` aliasing and `Shared` freeing gaps are fixable but unspecified. |
| Expressiveness (b,c,d, OO) | 15 | 4 | Plain refs, cycles and implicit self, and (c) with no capture list. But there is no way to say "this dies independently" (C1, C9). |
| Implementation risk (AI on LLVM) | 15 | 1 | Stack maps (LLVM statepoints), a barrier, a region allocator, edge tables, telemetry, a tracer, a solver, site hashing and a deep copier. The most moving parts of any option. |
| Performance & predictability | 10 | 2 | The fast path is cheap. Predictability is the worst of any option: memory depends on training, plus the chunk floor and drag. |
| Concurrency fit | 10 | 2 | Thread-local regions are good, but move vs. copy, lock granularity and deadlocks are all learned (C7), and C6 is open. |
| Tooling, debug & FFI | 10 | 3 | `--explain` and nightmare reports are excellent. Debug ≠ release, nondeterministic profiles, and manual `release(p)`. |

Total = 25·3/5 + 15·4/5 + 15·4/5 + 15·1/5 + 10·2/5 + 10·2/5 + 10·3/5
      = 15 + 12 + 12 + 3 + 4 + 4 + 6 = **56**

That is 27 below O1 (83), 26 below O4 (82), and 12 below round 1's best (68). The inventor's 75 assumes the defaults
are mostly right; C1–C3 show they aren't for streaming, churn or library code.

## 7. What the premise teaches

- **"Lifetimes are known to the running program" is true and useful, but only as *evidence*, never as *authority*.**
  Everything good in this idea comes from treating observation as diagnosis. Everything bad comes from letting it
  decide reclamation.
- **There is an impossibility hiding in it.** For cyclic graphs whose nodes are born and die independently, no static
  grouping (per site, per type, per scope) can avoid both leaks and unbounded waste. Something dynamic (a tracer) or
  something the programmer states (`weak`, explicit removal) must break the cycle. This is why round 1's grouping
  ideas and this one all plateau. It strengthens the case for O1/O4: put the cycle knowledge in the programmer's one
  small rule (`weak`) and spend tooling on helping them place it.
- **Co-locating a closure with its captured `self` is the right default for UI.** Part of (c)'s pain in ARC is an
  artifact of per-object counting.

**Salvageable kernel (adoptable into O1, and O4's `shared`):**
1. **Cycle-site report in test and debug runs.**
   - At the end of each test (or on demand), trace the ARC heap in debug only, as ASan does.
   - Name the allocation-site pairs that form unreachable cycles (`Editor(editor.x:3) ⇄ closure(editor.x:7)`).
   - Suggest the field or capture to make `weak`.
   - Fail CI when new cycles appear. This is a debugging tool, not a collector, so G2 is unaffected.
2. **A committed, diffable memory report.** Per-site peak and lifetime from tests, kept as a CI artifact, so memory
   regressions show up in review.
3. **(Optional, later) profile-guided co-allocation for O1.**
   - Use the same telemetry to slab-allocate objects from correlated sites together. This is LLAMA-style and
     performance only.
   - Per-object RC stays authoritative, so a wrong profile costs only locality.

## 8. Verdict

**Kernel worth stealing.** The mechanism fails as a memory model:
- leaks in churned cyclic graphs are structural (C1)
- defaults break streaming (C2)
- training leaks into semantics (C7)
- the implementation surface is the largest of any option

Its diagnostic half becomes a first-class O1 tool: a test-time cycle-site detector that names the leak and tells you
where `weak` goes.
