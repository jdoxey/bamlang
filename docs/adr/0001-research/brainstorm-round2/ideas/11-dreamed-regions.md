# 11 — Dreamed Regions ("Somnia")

## 1. Name

**Dreamed Regions.** The program watches itself while awake. While it sleeps, it decides where each kind of
object should have lived and rewrites its own allocation code for the next day.

## 2. The crazy premise: which sacred assumption it breaks

**Sacred assumption: where an object's memory lives, and when it is reclaimed, is determined by the source code**
(through the programmer's annotations, the compiler's static inference, or a fixed runtime rule).

In Somnia, lifetime placement is **not a property of the source**. It is *learned from the program's own past runs*
and stored in a generated sidecar file, `app.sleep`. The compiler reads that file and emits different allocation
code. The same source with last week's sleep file and with today's has different memory layouts, peak usage and
leak behaviour. Program semantics (values and outputs) stay identical.

The brief's core difficulty is that lifetimes are known to the programmer but not the compiler. Somnia's answer is
that they aren't known to the programmer either. They are known to **the running program**, so it should be the one
to write them down.

Assumptions also broken:
- **Reproducible builds.** Memory behaviour depends on training data.
- **"The binary is fixed."** This applies only in Variant B (on-device REM), where a long-running process recompiles
  its own allocation sites.
- **G2** is kept in the strict variant. It is *bent* only by an optional variant (see §8).
- **G3:** the sleep file may count as an annotation in disguise. **needs-john.**

## 3. Pitch

You write ordinary OO code with plain references: cycles, parent pointers, and closures that capture `self`. There
are no ownership rules, weak refs or borrows. Every object is allocated into a **region**, and a region is freed
whole when nothing outside it points in. You never name regions. Each **allocation site** has a *placement* that
says which existing region a new object joins: the region of `self`, of an argument, or of the object it is being
stored into, or a fresh region, or the current scratch region. Placements start from simple static defaults.

Then the program **sleeps**. Light sleep runs at quiet points (rest points) and frees dead regions in bulk. Deep sleep
(a "dream") runs in dev/test/CI and replays what was observed:
- which regions leaked through cross-region cycles
- which regions held mostly dead bytes
- which scratch allocations escaped

It then re-solves the placements to fix them: merge sites that form cycles into one region, split sites that waste
space into their own regions, and demote escaping temps. The result is written back to `app.sleep`, and the next
build uses it.

Safety never depends on the dream being right, because region reference counts keep it safe. Only *memory
efficiency* depends on it. A wrong dream leaks or bloats. It never dangles.

## 4. The rules (everything a programmer must learn)

1. **References are ordinary.** Assign, store, capture and form cycles freely. Every non-`shared` object belongs to
   one thread.
2. **Memory is reclaimed at rest points:** when an event handler returns to the loop, at loop back-edges, and when a
   thread idles. You don't write them; the compiler inserts them. Long-running code with no loop and no return has
   no rest point and grows until it ends.
3. **`send x` to another thread copies x.** It is O(1) when x is self-contained, and then it is a move.
4. **`shared` objects** (a built-in kind, as in O4) can be used from any thread. Their methods lock automatically.
5. **A leak means the program was trained on different shapes than it now sees.** Run your tests with
   `lang dream`, commit `app.sleep`, and read `lang dream --explain` when memory grows. Debug builds name every
   cross-region cycle ("nightmares").
6. **FFI:** a pointer handed to C pins its object's region until `release(p)`.

That is the whole list. Rules 2 and 5 are the ones a learner actually has to internalise.

## 5. Under the hood

**Placements** (per allocation site; site id = hash of qualified function, allocation ordinal and type):

| Placement | New object goes into |
|---|---|
| `Self` | region of the receiver of the enclosing method |
| `Arg(i)` | region of argument i |
| `Target` | region of the object it is immediately stored into or appended to |
| `Fresh` | a new region; this object is the region's *anchor* |
| `Scratch` | the innermost rest frame's scratch region |
| `Shared` | the process-wide shared region set (atomic counts, per-region lock) |

**Static defaults** (used when a site is not in the sleep file, which includes every new site after an edit):
- A closure literal that captures `self` gets `Self`; any other closure gets `Scratch`.
- `x.f = T(...)` and `xs.add(T(...))` get `Target`.
- A plain allocation inside a method gets `Self`.
- An allocation in a free function or `main` gets `Scratch`.

**Region header:** an incoming count (heap pointers from *other* regions and globals), an outgoing edge table
(target region → count), a finalizer list, and a size-class free-list allocator. Internal frees are allowed only for
compiler-known unique buffers, such as a List's old backing array.

**Write barrier** on pointer-field stores only (`obj.f = p`):
```
old = obj.f
if old and region(old) != region(obj): dec(region(old)); edges(obj).dec(region(old))
if p   and region(p)   != region(obj): inc(region(p));   edges(obj).inc(region(p))
```
`region(ptr)` is a mask to the chunk header and one load. Stores within a region cost nothing extra. Locals are
**never counted**.

**Light sleep (at a rest point):**
1. The compiler's stack map lists the live pointer locals in all frames. Each points into a region, and that region
   is *pinned* for this rest. This is root enumeration, not heap tracing.
2. The current rest frame's scratch region: if its count is 0 and it is unpinned, reset the bump pointer, freeing
   everything in it. Otherwise **promote** it to an ordinary region, open a new scratch, and log the escaping site.
3. Pending list: regions whose count reached 0 since the last rest, plus regions created since then. Free every one
   that is unpinned with count 0: run finalizers, then decrement every region in its outgoing table, which may add
   them to the pending list.
4. Cascades are budgeted per rest point. Any overflow carries to the next rest.

Nothing ever scans the heap at run time.

**Telemetry (always on, sampled, cheap):**
- cross-region store counts per (site → site)
- region lifetime and peak size per anchor site
- scratch escapes per site
- regions that stay pinned or counted for very long

**Debug-only checks** (like ASan; not in release builds):
- At sleep, a full trace measures *waste* (dead bytes inside live regions) and finds *nightmares* (cycles of regions
  that are unreachable from roots).

**The dream** (`lang dream`, run after tests or a recorded session):
- Inputs: the telemetry and debug traces.
- It solves a placement assignment by greedy local search, minimising:
  `leaked_bytes × L + wasted_bytes × W + cross_region_stores × C`.
- Moves it can make:
  - **merge** a site into a neighbour's region (`Self`/`Target`/`Arg`): this kills cycles and removes barrier
    traffic
  - **split** a site out (`Fresh`): this kills waste
  - **demote/promote** between `Scratch` and a region
- Output: `app.sleep`, a plain-text table with one line per site and a one-line reason.

**Threads:** regions are thread-local with non-atomic counts. `send x` moves x's region if x is its anchor, the
region's count is 0, and it has no outgoing edges except into `Shared`. Otherwise it deep-copies into a fresh
region on the receiving side. `shared` objects live in `Shared` regions with atomic counts and a lock per region.

**Variant B, on-device REM (optional, crazier):** long-running servers carry the backend. They dream on live
telemetry, recompile the affected allocation sites, and hot-swap them at a rest point. Old objects stay where they
are; only new allocations follow the new placements.

## 6. Scenarios

*Pseudo-code is illustrative only — not a syntax decision.*

**(a) Read lines into a growing list**
```
fun main() {
  lines = List()                         // Scratch (main) → promoted at first rest: it's referenced
  for line in File("in.txt").lines() {   // back-edge = rest point
    lines.add(line.trim())               // trim's temp: Scratch, freed each rest; trimmed string: Target → lines' region
  }
}
```
Growing the list frees the old backing buffer internally, because it is a compiler-known unique buffer. Once
trained, `line`'s raw buffer stays `Scratch` and the trimmed copy is `Target`, so per-line garbage is zero.

**(b) Tree with parent pointers**
```
class Node { var parent: Node?  var kids = List()
  fun add(v) { n = Node(v); n.parent = self; kids.add(n) }   // Node(v): Self → same region as parent
}
```
The whole tree is one region, so parent↔child cycles are internal and free. When the root's last outside
reference goes, the tree is freed in one operation. Weakness: a subtree detached and grafted onto another tree
keeps the old tree's region alive (see §9).

**(c) UI callback capturing self (the crux)**
```
class Editor { var text = ""
  fun build() -> View {
    Column {
      TextField(bind: text)
      Button("Save", onTap: { self.text += "!"; self.save() })   // closure: Self → Editor's region
    }                                                            // Column/Button: Self (trained: Target)
  }
}
window.root = editor.build()        // Window region → Editor region: count 1
```
Editor → button → closure → Editor is a cycle *inside* one region, so it costs nothing. When the window closes, the
Window region is freed. Its edge table decrements the Editor region to 0, and at the next rest the editor, its views
and the closure all go together. No `weak self`. Untrained, the default `Self` already gets this right. If someone
builds the views in a free function, the closure lands in a different region and the debug build reports a
nightmare: `Editor(editor.x:3) ⇄ closure(editor.x:7)`. The dream merges the two sites.

**(d) Shared cache used by two components**
```
class Cache { var map = Map()
  fun get(k) { if !map.has(k) { map[k] = load(k) }  map[k] }   // load(k)'s result: default Target → Cache region
  fun evict(k) { map.remove(k) }
}
a.cache = cache;  b.cache = cache   // two incoming edges
```
The default puts every entry in the cache's region, so evicted entries are waste until the cache dies. The debug
trace sees the waste is growing, and the dream **splits** the site to `Fresh`. Each entry becomes its own region, so
it effectively has its own reference count and is freed at the rest after eviction. The cache itself dies when both
`a` and `b` drop it.

**(e) Pass a large list to a mutating function**
```
fun normalise(xs: List) { for i in 0..xs.len { xs[i] = xs[i] / 2 } ; xs.add(0) }
normalise(big)     // plain reference, no copy; new elements: Arg(0) after training
```
This costs nothing: no copy and no RC on the parameter. Scalar stores have no barrier.

**(f) Threads**
```
job = Batch(rows)                      // anchor of a Fresh region, nothing points in
spawn worker(send job)                 // isolated → O(1) region move
stats = shared Stats()                 // Shared region, locked methods, atomic count
spawn { stats.record(42) }  ;  spawn { stats.record(7) }
results = channel.receive()            // receiver gets a moved or copied region
```

## 7. What is new

- **Lifetime placement comes from observation, not static inference or annotation.** It is profile-guided region
  assignment applied to memory *semantics*, not just optimisation, with a safe fallback.
- **The cycle problem moves from the language to the training loop.** Cycles are allowed everywhere. The dream
  rearranges allocation so that observed cycles become intra-region, where they cost nothing.
- **Counting only cross-region heap edges, never locals, and freeing only at rest points.** The common case, a store
  within a region, has no RC traffic. The stack is checked by stack maps at rest, never traced.
- **A readable, diffable memory plan.** `app.sleep` is generated, reviewed in PRs and explained per site. Memory
  regressions show up as diffs in a text file.

## 8. Why it might be less crazy than it sounds, or more

**Less crazy:**
- The safety core is plain region-level RC with deferred freeing, which is a well-understood mechanism.
- The learned part only ever trades space for time. A broken or missing sleep file degrades to "every site at its
  static default", which handles (a), (b), (c) and (e) correctly on day one.
- PGO and JIT tiering already make performance training-dependent, and nobody calls those unsafe.
- The programmer-facing rule count is about 6, below O1, because there are no weak refs and no capture lists.

**More crazy:**
- The leak behaviour of release builds depends on how representative the tests were. Inputs never seen in training
  can leak through cross-region cycles, and in release nothing detects that.
- The strict variant accepts the leaks. A **lenient variant bends G2**: it runs a trial-deletion pass over the
  *region graph* (regions, not objects) during light sleep, restricted to regions decremented since the last rest.
  That is a small, bounded cycle collector at a point the program chose, but it is still a collection run.
- Variant B makes a running binary rewrite itself, which is hostile to code signing, auditing and debugging.
- Nondeterministic memory profiles across builds may annoy anyone doing capacity planning.

**Self-assessment** (rough):
| Criterion | Score |
|---|---|
| Simplicity | 4 |
| Safety | 5 |
| Expressiveness | 5 |
| Implementation risk | 2 |
| Performance | 4 |
| Concurrency | 3 |
| Tooling | 3 |

That comes to about **75**. It is competitive only if the static defaults turn out to be right most of the time.

## 9. Known weaknesses

- **Release leaks on untrained shapes.** These are cross-region cycles nobody exercised in tests. This is the
  central risk, and it is invisible until memory grows.
- **Region drag.** A long-lived object allocated into a big region keeps the whole region alive. Examples are a
  detached subtree grafted elsewhere, or a value read from a cache entry and kept forever. Per-object frees inside a
  region are impossible without tracing, so drag can only be fixed by re-dreaming, never at run time.
- **Late finalisation.** A `File` inside a large region closes when the region dies, which may be much later than
  expected. Explicit `close()` is still needed for prompt release.
- **Rest-point starvation.** A deep recursive computation or a non-looping long function never rests, so its scratch
  and pending lists grow until it returns.
- **Site-id churn.** Refactors rename sites and silently revert them to defaults until the next dream. CI should fail
  when significant sites become untrained.
- **Debug and release differ in memory behaviour.** Debug builds trace and release builds do not, so "it doesn't
  leak in debug" proves less than it should.
- **Send copies.** Non-isolated data copied to threads can be surprisingly expensive.
- **Implementation surface.** The compiler needs:
  - stack maps at every rest point
  - a write barrier on every pointer store
  - per-region edge tables
  - a telemetry runtime, a debug tracer and a placement solver
  - stable site hashing

  That is substantial for an AI-written compiler, and the solver is a research project of its own.
- **Rejected sub-idea.** Letting the dream turn optional fields into weak back-edges would fix detach-heavy trees,
  but then *program semantics* would depend on training. It was cut because it breaks the "dreams only change
  memory, never meaning" invariant.
