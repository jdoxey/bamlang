# Analysis 04: Reincarnation

Analyst: independent. Inputs: brief.md, round2.md, CHARTER.md, ideas/04-reincarnation.md.
All code is pseudo-code, illustrative only, not a syntax decision.

## 1. The idea in three sentences

Every event, frame, `main` and `beat` iteration runs as a disposable "life" with its own bump arena: inside it you have plain aliasing references and cycles, nothing is freed, and the whole arena is reset when the life ends. The only state that survives is a pointer-free, ID-linked, MVCC "durable store", written by deep copy and committed atomically at life end, with a crash rolling back the life's writes. Escaping closures become copied messages that capture only values and IDs, output is deferred until commit, and conflicting lives on different threads rerun automatically (optimistic STM).

## 2. Prior art

No single system does all of this, but every part has a precedent, and the arrangement is close to things that already exist:

- **Crash-only software / microreboot** (Candea & Fox): recovery by cheap reboot of components. https://www.usenix.org/legacy/events/osdi04/tech/full_papers/candea/candea_html/ , https://en.wikipedia.org/wiki/Microreboot
- **PHP share-nothing**: a fresh heap per request, all memory dropped at request end, state lives in an external store (DB/APCu). This is the life arena plus durable store, with RAM as the store. https://www.phpinternalsbook.com/php7/memory_management/zend_memory_manager.html , https://tideways.com/profiler/blog/php-shared-nothing-architecture-the-benefits-and-downsides
- **Clojure refs**: an STM over persistent data structures, where transactions retry and side effects inside them are forbidden (`io!`). This is the store half almost exactly. https://clojure.org/reference/refs
- **Erlang**: per-process heaps, "let it crash", terms copied into ETS/persistent_term on insert (rule 4's copy-in). https://www.erlang.org/doc/apps/erts/garbagecollection , https://www.erlang.org/docs/22/man/persistent_term.html
- **Epoch-based reclamation** and its known weakness: one long-running participant stalls all reclamation. https://mc.uwaterloo.ca/cs798/lec17.v3.pdf , https://arxiv.org/pdf/1905.07903
- Also (no search spent): Elm `update(model,msg)`, immediate-mode UI, game frame arenas, Apache APR pools, Mnesia transactions that retry, durable-execution replay (Temporal).

**Overlap with excluded material.** The arena reset is "freeing deferred to end of a tick" (Tick & World, Tide) and "groupings freed whole". A deep copy into the store is "promote to global" from scope-bound regions. Dropped messages whose IDs no longer resolve are round-1's "callbacks that become no-ops". The genuinely new contribution is narrower: **making a pointer-free transactional store the only cross-event link the language has**, so the problem of non-nesting lifetimes becomes a database problem (IDs plus explicit delete). It is a novel fusion, not a novel mechanism.

## 3. Soundness: counterexamples

**C1. Memory equals cumulative allocation, not live data (budget crash or O(n²) blow-up).**
```
fn main() {                                 // one life, budget 64 MB
    acc = ""
    for w in File.open(p).words() { acc = acc + w + " " }   // each concat allocates a new string
}
```
Nothing is freed in a life, so 100k words × an average 500 KB prefix is about 50 GB of garbage, and the program crashes on the budget. ARC would peak at about 2× the final size. Any compute-heavy `main` (a compiler, a simulation, a log analyser) faces the same problem. The fix is `beat`, but that moves loop-carried state into the store, paying MVCC on every iteration. Nothing forces lives to be short, so "lives are short by construction" (§5 of the idea) is a hope, not a rule.

**C2. Stale buffer aliases silently lose writes.** The idea says this is "memory-safe".
```
xs = List of Point; xs.add(Point(0,0))
p = xs.at(0)            // reference into the buffer (rule 2: everything is a reference)
xs.add(Point(1,1))      // grows, so xs moves to a new buffer and the old one stays alive
p.x = 99                // writes to the dead buffer
print(xs[0].x)          // 0, and the write is silently lost
```
Slices and iterators behave the same way: `for x in xs { if c { xs.add(f(x)) } }` iterates the old buffer. There is no crash, just wrong answers. That is worse than a bounds trap.

**C3. Request/response I/O versus rerun: duplicated or orphaned external effects.**
```
fn on_pay(order: Order.id) {
    o = store.lookup(order) ?? return
    r = Http.post(bank, o.amount)     // output (deferred)? or input (performed now, logged)?
    o.status = r.ok ? .paid : .failed
}
```
If POST is deferred under rule 8, the life cannot read `r`, so it has to become a two-life state machine. If it runs immediately as a "logged input", a conflict-rerun (rule 9) runs against a *different* snapshot. That is the whole point of a rerun. The rerun may then take another path or another amount, and the log entry no longer matches: the bank was charged once and the store records something else. A crash (rule 7) rolls back the store but not the bank. Scenario (d)'s own `Http.get` inside a life has the same ambiguity. Clojure and Haskell forbid I/O in transactions for exactly this reason, and rule 8 papers over it.

**C4. Commit-then-effect means the user is told data was saved when it wasn't (scenario c).**
```
fn save() { File.write(path, text); dirty = false }   // write is queued, dirty=false commits
```
The commit publishes `dirty = false`, then the queued write fails (disk full, permission denied). The store says "saved", so the Save button disables and the user quits and loses work. Effects can't roll back a commit. The error has to come back as a new message, which the idea doesn't specify. A related surprise: `File.write(p, x); y = File.read(p)` in the same life reads the old contents.

**C5. Starvation and unbounded limbo with one long life.**
```
fn work(id) { j = store.lookup(id); j.result = crunch(j.spec) }   // a 30 s life
// UI thread: on every keystroke, store.jobs[other].progress_text = ...
```
If the read-set granularity covers `jobs` (unspecified), every UI commit invalidates `work` and it reruns forever (livelock). Even with per-record granularity, the 30 s life pins every limbo block from every commit in that window, so limbo grows as write rate × longest life. This is the EBR stall the design claims to avoid. A job also can't report progress, because nothing commits until the life ends.

**C6. Captured locals are copied, so mutations vanish.**
```
fn view() { count = 0; Button("+", onTap: { count += 1; print(count) }) }  // prints 1 forever
```
This needs a compile error ("captures are read-only"), which the idea does not list. In practice every piece of state a callback touches must be `durable`. That forces the whole UI model through MVCC and makes the two-world split universal, not occasional.

**C7. Two type worlds plus hand-written conversion.** Scenario (b) needs `class Node` *and* `durable class DNode`. Moving a life graph into the store means hand-written ID allocation for every node, and moving it back means rebuilding the references. Deep copy (rule 4) of a life value that contains a view: does it copy by value or turn into an ID? Unspecified. Writing through a view (scenario b does `p.name = ...`) and then reassigning `store.x` leaves it unclear which version the old view shows.

**C8. Self deleted mid-method.** In `fn close() { store.editors.delete(self); text = "" }`, `self` no longer resolves. The life crashes and rolls back, so a close can never succeed, or the write is silently dropped. Neither outcome is stated.

**C9. Performance cliff in (e) durable.** `normalize(store.samples)` touches every chunk, so it copies the whole list and puts the old version in limbo each tick: 2 × 800 MB for 100M floats. A durable editor buffer `text = t` deep-copies the full string on every keystroke unless the stdlib provides ropes.

No deadlocks are possible (optimistic concurrency). There are no use-after-free bugs and no data races.

## 4. Scenarios

- **(a) works / partial.** Trivial within the budget, but memory is cumulative (C1), and big inputs need `beat` plus store state.
- **(b) works.** Free in a life. Durable versions are generation-checked IDs (a slot map), at the cost of two declarations (C7).
- **(c) partial.** Immediate-mode plus ID-capturing messages is a clean fit for G11, but all state must be durable (C6), effect failures after commit lose data (C4), and dead IDs drop messages (round-1 territory).
- **(d) works.** The shared store map is the idea's best case, with conflict reruns as the cost.
- **(e) partial.** In a life it mutates in place for free. Durable data pays O(touched chunks) plus limbo (C9).
- **(f) partial.** No races and composable transactions, but long lives starve (C5), I/O inside lives is unsound (C3), and there is no progress visibility.

## 5. Gates and charter

- **G2: pass (flag).** Nothing is traced. The arena is reset in O(1), and epoch limbo is deferred freeing, not collection. The flag: with long lives, limbo behaves like a heap that grows until a "collection moment" (C5), which John might see as GC in spirit.
- **G3: needs-john.** It needs built-in parameterised `List of T` / `Map of K to V` (same as O1/O4) plus a compiler-known `T.id` type per record. `durable` and `beat` are keywords, not annotations, but `durable` acts like a storage-class qualifier on types. Mention it to John.
- **G1: strained.** Ten stated rules, plus at least five unstated ones (C2, C3, C4, C6, C8): view semantics, input/output classification of every API, budgets, read-after-write, and forced state-machine structure.
- **G6: strained.** Every stdlib I/O call must be classified as input (logged), output (deferred) or durable resource. That is a major stdlib design burden.
- **G8: mixed.** Replay, hot reload and a store inspector are strong. Deferred `print` hurts and needs an escape hatch.
- **P-SWIFT:** the life/durable split repeats the struct/class problem.

## 6. Score

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity | 25 | 2 | Lives are C-simple, but users must learn a transactional database model, two type worlds and state-machine program shape (C3, C6, C7). |
| Memory safety | 15 | 4 | No use-after-free (arena plus generation IDs), no races. Stale-buffer aliases give silent wrong data (C2). |
| Expressiveness (b,c,d,self) | 15 | 3 | (b) and (d) are good. (c) works only if all callback state is durable. Every I/O round trip is a life boundary. |
| Implementation risk | 15 | 2 | The arena half is trivial. The other half is an embedded MVCC STM: read/write-set tracking in codegen, persistent containers, effect queue, input log, defunctionalisation, epochs. |
| Performance & predictability | 10 | 2 | Bump allocation is the fastest possible, but memory tracks cumulative allocation, there are budget crashes, commit/copy tax on hot state, and retry storms. |
| Concurrency fit | 10 | 3 | Race-free composable STM, minus starvation of long lives and unsound I/O inside transactions. |
| Tooling, debug, FFI | 10 | 3 | Replay and hot reload are excellent. FFI needs pinned durable buffers, C callbacks must start lives, mmap breaks reruns. |

Total = 25·2/5 + 15·4/5 + 15·3/5 + 15·2/5 + 10·2/5 + 10·3/5 + 10·3/5
= 10 + 12 + 9 + 6 + 4 + 6 + 6 = **53 / 100**

That is 30 below O1 (83), 29 below O4 (82) and 15 below round 1's best (68). The inventor self-assessed 64. The gap is C1 (cumulative memory), C3/C4 (effects versus rerun) and the simplicity cost of the two worlds.

## 7. What the premise teaches, and the kernel

**What the premise teaches.** The brief's hard case ("lifetimes that don't nest: sessions, windows, cache entries, callbacks") largely goes away once you stop asking the heap to hold it. Non-nesting long-lived things are *state* and want identity plus explicit deletion (IDs). Everything else is *scratch* and dies at an event boundary. The idea shows that this split is enough to make (b), (c) and (d) safe without RC or borrows. It also shows the price of making the split mandatory: transactions, deferred effects and two type systems. The premise also locates the real crux of (c): the problem isn't memory, it's that a closure is an unnamed pointer to state. Making callbacks *data that names state by ID* (defunctionalisation) removes the cycle entirely, which is the Elm and immediate-mode lesson.

**Salvageable kernel for O1/O4:**
1. **Event-generation leak audit (debug mode, no GC).** The stdlib event loop marks a generation at each handler entry. In debug builds, objects allocated in a handler that are still alive N events later are reported by allocation site, with growth across events (like Instruments' "mark generation"). This catches the classic ARC `onTap { self.save() }` retain cycle in tests. Counting only, no tracing.
2. **Per-handler record/replay (G8).** Log the inputs each event handler receives so a failing event can be replayed deterministically. This works with any memory model if the event loop is in the stdlib.
3. **Optional per-handler scratch arena (optimisation).** Allocations that escape analysis proves don't outlive the handler go to a per-event bump arena that is reset at handler exit. This skips RC traffic for UI and request temporaries without changing semantics.
4. **A library `Table of T` with generation-checked IDs** as the recommended home for sessions and windows in O1/O4. It is already covered (slot maps), but the idea makes a good argument for teaching it as *the* pattern for non-nesting lifetimes.

Not worth taking: the mandatory store, deferred output and automatic rerun.

## 8. Verdict

**Kernel worth stealing.** As a memory model it is a dead end: 53, with unsound I/O-versus-rerun semantics and cumulative-allocation memory. Its premise does yield a debug-mode event-generation leak audit, handler replay and an optional per-event arena that O1/O4 could adopt directly.
