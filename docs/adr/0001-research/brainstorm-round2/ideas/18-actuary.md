# 18 — Actuary

## 1. Name

**Actuary**: a life table predicts when each object will die, and the runtime frees it then. A cheap invariant makes the predictions safe to trust. When a prediction is wrong, the program gets slower or uses more memory. It never gets wrong answers.

## 2. The crazy premise

Every sensible design decides an object's death from facts: scope exit, a count reaching zero, unreachability, or an owner dropping it. Actuary decides death **by forecast**. A trained model, shipped next to the binary like a PGO profile, assigns each allocation a predicted death time. The runtime frees memory when that time arrives, without asking whether anything still uses it.

The safety net is not a check at use time. It is an ordering invariant enforced when a pointer is stored: **nothing may point at an object that is predicted to die before the slot holding the pointer expires.** A violating store does not fail. It revises the prediction upward. So the forecast can be wrong in either direction, and the program still never sees freed memory.

Assumptions broken:
- Death is a fact, not an estimate.
- The memory manager's behaviour is fully fixed by the source code. Here it also depends on a data file.
- G2 is strained and needs John's ruling. With a perfect oracle there is no collection work at all. With a bad oracle the safety net does work equivalent to an incremental collector, spread across ticks. See §8.

## 3. Pitch

You write code as you would in a garbage-collected language: no owners, no `weak`, no borrows, no annotations. Cycles are fine and closures can capture `self`. The build runs your tests and workloads and records how long objects from each allocation site actually lived. It writes the result to `app.life`, a life table you commit like a lockfile. At runtime each `new` goes into a page grouped with objects expected to die at the same tick. When the tick arrives the whole page is released, with no per-object work and no tracing.

A one-compare write barrier keeps the forecast honest. If you store a pointer into something that will outlive the forecast, the target's death is pushed back. If a slot still holds an object when its lease runs out, the lease is renewed. Wrong forecasts cost renewal work in proportion to how wrong they are. Program semantics never change.

Memory management becomes branch prediction: the common case is free, and a mispredict costs a small, bounded amount of work.

## 4. The rules (everything a programmer must learn)

1. Allocate freely. Objects, lists, maps and closures can point at anything, cycles included. There is no `weak`, no owner and no `[weak self]`.
2. You can never observe freed memory. There is no use-after-free, no dangling pointer and no auto-null. A wrong forecast never changes what your program computes.
3. Death is silent. There are no destructors or finalizers. Files, sockets and locks are released explicitly or with a scoped `using`, because the time of death is a forecast, not an event.
4. Memory footprint depends on the life table. `build --train` runs your tests and declared workloads and regenerates `app.life`. A stale or missing table never breaks correctness. It only costs speed or memory.
5. `actuary report` lists the sites the oracle gets wrong, for example "`editor.swift:40` predicted 3 ticks, median actual 900". This is the memory-tuning tool. It replaces a heap profiler.
6. Threads share objects freely as far as memory is concerned. Data-race rules belong to the separate concurrency model.

That is two memory rules (1, 2), one resource rule (3) and two tooling facts (4, 5).

## 5. Under the hood

**Ticks.** A global epoch counter `now` advances by allocation volume (for example every 256 KB) or every 1 ms, whichever comes first. Advancing uses an epoch-based-reclamation handshake. Each thread acknowledges tick `e` at its next safepoint (a loop back-edge or call). There is no stop-the-world pause.

**Per-object state.** Each object has a 32-bit header field `E`, its predicted death tick. Each page records `maxE`.

**Slots and leases.** Each pointer slot (field, list element or map value) has a lease: the tick until which it promises to keep its target.
- The default is an *inherited* lease, equal to the holder's `E`. It is stored nowhere and costs nothing.
- The life table can give a store site an *explicit* shorter lease, meaning "values stored here are usually replaced within about T ticks". Examples are `editor.currentDoc = d`, `map[k] = v` and `windows.add(w)`. An explicit lease sets one tag bit on the stored pointer and adds an entry to `expiry[lease]`.

**Invariant I:** for every slot `s` holding `b`, `b.E ≥ lease(s)`, and `lease(s) > now` while the holder is alive.

**Write barrier** for `h.f = b`, which applies to pointer stores only. Integers and other scalars skip it.
```
L = min(h.E, now + lifeTable.lease(site))   // inherited if no entry
if b.E < L: promote(b, L)
if L < h.E: tag pointer as leased; expiry[L].push(h, f)
h.f = b
```
`promote(b, L)` sets `b.E = L` (an atomic monotone max), raises `page(b).maxE`, and recurses into the targets of `b`'s inherited-lease slots whose `E < L`. Promotion only raises predictions. It never lowers them.

**At tick `e`, in order:**
1. *Root step.* Each thread scans its own stack frames with precise LLVM stack maps. For every root target with `E ≤ e`, it calls `promote(target, e + survive(site, age))`, where the survival estimate defaults to doubling the object's age.
2. *Lease step.* For each `(h, f)` in `expiry[e]`: if `h.E > e` and `h.f` is non-null, renew with `L' = min(h.E, e + renew(site, age))`, call `promote(h.f, L')`, and requeue the entry or untag it if `L' == h.E`. Repeat steps 1–2 on the worklist until nothing changes. Promotions can only come from roots or from live holders.
3. *Death step.* Release pages with `maxE ≤ e` (`madvise`/unmap). On partly live pages, an object slot is free for reuse when its header `E ≤ e`. The allocator checks that when it reuses the slot, so nothing is swept.

**Soundness sketch.**
- Every slot pointing at an object that dies at `e` has `lease ≤ e` by I, so it is in `expiry[≤e]` or belongs to a dead holder.
- Every root is covered by step 1.
- By induction along any path from a root, everything reachable has `E > e`.
- Therefore every object freed at `e` is unreachable.

**Garbage cannot live forever, cycles included.** Renewals and promotions are capped by a holder's `E`. Inside an unreachable subgraph nothing ever raises the maximum `E`, because no roots point in and nobody stores into it. Once `now` passes that maximum, the whole subgraph dies. A cycle whose members got the same forecast is never even visited. With doubling, an object that becomes garbage at age A is freed by roughly age 2A at the latest.

**Allocation.** Allocation is a bump pointer into a *cohort page* for the predicted lifetime class. Classes are log-scale (1, 2, 4, 8 … ticks), so each thread has about 32 open pages. Objects with the same forecast share pages, so pages die whole.

**The oracle.**
- Key: allocation site plus a 2-frame calling-context hash, giving a lifetime histogram in ticks. The forecast is a chosen quantile. The costs are asymmetric: a low guess costs renewal work, a high guess costs memory.
- Store sites get lease histograms in the same way.
- The runtime adapts online: a per-site multiplier doubles after repeated promotions and decays slowly.
- The compiler ships a pretrained "all programs ever written" table for stdlib sites. For example, a List growth buffer dies at the next resize and an iterator dies within one tick. This keeps cold starts reasonable.
- **Training mode** gets ground truth by running the program under an exact tracing collector, which is never shipped. The collector teaches. The binary obeys the table.

## 6. Scenarios (illustrative only — not a syntax decision)

**(a) File to list of lines**
```
fn readLines(path) {
    lines = List()
    using f = File.open(path) { for l in f.lines() { lines.add(l) } }
    return lines
}
```
The stdlib table predicts that the backing buffer dies at the next growth. `list.buffer` has an explicit short lease, so each replaced buffer dies whole within a tick or two. The final buffer is promoted when its lease is renewed. Line strings inherit the buffer's lease and get the same forecast as the list. The caller's root step keeps `lines` alive.

**(b) Tree with parent pointers**
```
class Node { parent; children = List()
  fn add(c) { c.parent = self; children.add(c) } }
```
There are plain pointers in both directions. The barrier gives parent and child the same `E`, so the tree is one cohort and dies together, with no `weak`. For a detached subtree, `node.parent = nil; children.remove(node)`, the subtree lingers until the lease on `children.add` lapses. With a trained table that is about as long as children usually stay. Untrained, it is up to the tree's own `E`.

**(c) UI callback capturing `self`, the crux**
```
class Editor {
  fn build() { Button("Save", onTap: { self.save(); self.dirty = false }) }
}
app.windows.add(Window(Editor()))      // explicit lease from the table
app.windows.remove(w)                  // user closes the window
```
The closure, button, editor and window form a cycle with equal `E`. No weak capture is needed. While the window is in `app.windows`, its leased slot is renewed each time it expires. After `remove`, the next expiry finds the slot no longer holds `w`, nothing renews it, and the whole cycle dies at its shared `E`. A callback queued on the event loop stays alive because the queue's slot keeps renewing it. No callback ever fires into freed state.

**(d) Shared mutable cache**
```
cache = Cache()                        // Map inside
a = Search(cache); b = Preview(cache)
cache.put(key, value)                  // map value slot: explicit lease
```
The cache's `E` is at least the `E` of both components. Entries get leases from the `put` site. Evicted entries die when their lease lapses. Hot entries are renewed with doubling.

**(e) Large list passed to a mutating function**
```
fn normalise(xs) { for i in 0..xs.count { xs[i] = xs[i] / max } }
normalise(samples)                     // by reference, in place, no copy
```
There are scalar stores, so no barrier runs. Storing an object element costs one compare.

**(f) Sharing between threads**
```
results = List()
spawn { results.locked { r in r.add(compute()) } }
```
Memory needs nothing special. The worker's stack is its root set and is scanned at its own safepoints. Barrier promotions are atomic monotone maxima. Locking belongs to the concurrency model, not to memory.

## 7. What is new

- **Death by forecast, made safe by an ordering invariant on stores.** The rule is "never point at something predicted to die sooner than your lease". Leases renew, and promotion only ever raises a prediction.
- **Work is proportional to the forecast error, not to heap size.** A perfect table does zero memory-management work beyond page releases. A table that always guesses "dies now" turns the runtime into an incremental tracer. A table that always guesses "never" turns it into a never-free allocator. The table is a dial between Java and leaking, and training moves it toward zero cost.
- **Cycles are free when they are predicted together.** Equal forecasts mean one cohort and one page release, with no weak references and no cycle detector.
- **The life table is a build artifact**, like a lockfile or a PGO profile, with a mispredict report as the memory-tuning user interface. It is not an annotation, because nothing appears in the source (G3).
- **A tracing collector used only as a teacher during training**, never in the shipped binary.

## 8. Less crazy than it sounds, or more

**Less crazy.**
- Allocators that predict object lifetimes from calling context already exist. As far as I recall, Google's LLAMA (ASPLOS 2020) placed C++ objects into huge pages by predicted lifetime.
- Generational collectors already pretenure by allocation site.
- Epoch-based reclamation already frees memory in batches by epoch without a pause.
- The barrier costs about as much as card marking.
- The soundness argument is short and does not depend on how good the model is.

**More crazy.**
- The root step plus renewal propagation *is* a collector. It is incremental and pauseless, but when forecasts are wrong it does work equivalent to tracing. Whether that passes G2 ("doesn't require a garbage collection run") is a real `needs-john` question. With a trained table I estimate the work at under 1% of objects, but it is never guaranteed to be zero.
- Memory footprint depends on a data file. Two builds of the same source can differ in RSS by a factor of two.

## 9. Known weaknesses

- **G2 is arguable** (see §8). A cold or stale table means a cold runtime that does GC-like work.
- **Implementation risk is high:**
  - precise stack maps (LLVM statepoints, the same machinery as a real GC)
  - safepoint polling
  - an atomic barrier
  - a cohort allocator
  - promotion worklists
  - training infrastructure with a tracing teacher

  That is a lot for a compiler written about 95% by an AI.
- **Promotion can be O(n).** Renewing the lease on a large list's buffer recurses into every element whose inherited lease is short. Containers need a special case, such as recording one container-level `minE` instead of recursing.
- **Footprint is unpredictable.** Garbage can linger for about as long as it has already lived, plus forecast slack. Memory-tight programs (embedded, mobile under pressure) cannot bound RSS from the source alone.
- **No destructors** is a real loss for RAII-style resource handling. `using` partly covers it.
- **FFI:** a C callee may hold a pointer only for the duration of the call, because the stack scan covers its arguments. To keep a pointer longer, C must hold an explicit handle, which is held by a root.
- **Training workload bias:** if production lifetimes differ from the tests, the result is slower and fatter, but still correct.
- **Header and tag overhead** is 4 bytes per object, plus one pointer tag bit and expiry-queue entries for leased slots.

**Self-assessment** (assuming G2 passes; G3 passes):

| Criterion | Score |
|---|---|
| Simplicity | 5 |
| Safety | 5 |
| Expressiveness | 5 |
| Implementation risk | 1.5 |
| Performance and predictability | 2.5 |
| Concurrency | 3 |
| Tooling and FFI | 3 |
| **Total** | **≈ 76** |

If G2 is ruled a fail, the idea is dead as specified. Then the only shippable variant is "the table plus a never-free fallback", which leaks.
