# Analysis 02: Estates and Liens

Analyst: independent. Inputs: brief.md, CHARTER.md, ideas/02-estates-and-liens.md.
All code below is illustrative only, not a syntax decision.

## 1. Restatement

1. Every class instance is allocated in an *estate*: a bump-allocated group of objects owned by a move-only *deed* held in an ordinary field. When the deed is dropped, the whole group is freed in one go. Pointers inside an estate are never counted.
2. A pointer stored in a field that crosses from one estate into another is a *lien*. The runtime counts liens per estate pair through a store barrier. A closed estate that still has liens stays alive in *receivership* instead of dangling.
3. Freeing happens only at *settlement* points, when the thread's language stack is empty. Locals therefore need no counting. A small trial-deletion pass over the estates closed this turn (the *court*) frees cycles between estates. `mut` uses move-out escrow, and threads share data through `send`, `freeze` and `trust`.

## 2. Prior art

This is a new combination, but no single part of it is new.

- **Counted regions, with same-region pointers uncounted.** Gay and Aiken's RC compiler for C ([PLDI'01 paper](https://www.cs.cornell.edu/courses/cs612/2000SP/papers/gay-regions.pdf), [tech report](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2000/5340.html)) keeps one count per region of the pointers coming from other regions, globals and live frames. It does not count same-region pointers, and `deleteregion` is a no-op while the count is nonzero. Liens are this design, with two changes:
  - (i) counts are kept per estate *pair*, which is what makes the court possible;
  - (ii) the stack is empty at settlement, so locals are never counted. RC instead has to scan the stack at `deleteregion` time.
- **Regions with one owning entry, nested in a tree, frozen to share, and locked through cowns.** Project Verona ([overview](https://tamnd.github.io/brain/research/memory-management/ownership/07_project_verona_regions/), [FAQ](https://microsoft.github.io/verona/faq.html)) has an `iso` entry point owned from a field, `freeze`, and cowns, which play the role of `trust`. Verona restricts cross-region references to `iso` or `imm` *statically*. This idea allows any cross-region reference and counts it *dynamically*, which is the main twist. Freezing cyclic data and refcounting it: [Parkinson, Clebsch and Wrigstad, ISMM'24](https://conf.researchr.org/details/ismm-2024/ismm-2024-papers/3/Reference-Counting-Deeply-Immutable-Data-Structures-with-Cycles).
- **Not counting locals and reclaiming later.** This is Deutsch–Bobrow deferred RC ([overview](https://en.wikipedia.org/wiki/Reference_counting)) combined with RCU/EBR quiescent states.
- **Court.** This is Bacon–Rajan-style trial deletion, run over a graph of estates instead of objects.
- **Escrow.** This is Swift `inout` plus exclusivity, implemented as a move-out.

Verdict on novelty: the per-pair liens, receivership and settlement fit together in a real and coherent way, and none of the covered options O1–O8 does it. Every part has a precedent, though. The closest single relatives are RC regions and Verona.

## 3. Soundness: counterexamples

**CE1. A value that holds object references skips the barrier, so a pointer dangles.** The barrier covers only "stores of object references into object fields and closure captures". But `List`, `Map` and structs are values that may contain object references: the idea's own (b) has `children: List of Node`.
```
own var a = new estate Holder()
own var b = new estate Holder()
var tmp = List()                 // local value: no barrier
tmp.append(Node() in b)          // element store into a fixture: no barrier
a.items = tmp                    // value store into a field: not an "object ref store"
b = nil                          // b: liens_in_total == 0 -> freed at settlement
// next turn: a.items[0] dangles
```
There are two possible fixes, and both cost something:
- Barrier every element store into a buffer and give each buffer an owning estate. Then moving or copying a value between estates is O(n): re-attribute every element. CoW sharing a buffer across two estates also breaks.
- Ban object references inside values. That breaks (b), (c) and (d) as written.

The claim that the barrier is cheap does not survive either fix.

**CE2. A local reference survives `send`, so there is a data race.** The `send` check only looks at liens, and locals never carry liens.
```
own var job = new estate Batch(rows)
let r = job.firstRow             // local, uncounted
worker.send(job)                 // passes: liens_in_total == 0
r.total += 1                     // int store: no barrier; races with worker
```
Possible fix: make `send` take effect at the next settlement, when no frames exist. That turns `send` into a deferred operation that can fail late if a lien appears in the meantime.

**CE3. Frozen estates are freed while another thread is using them.** Settlement only guarantees that nothing is freed under the *freeing thread's* own frames. Frozen estates are shared.
```
T2: let t = self.table           // local into frozen F, uncounted
T2: self.table = nil             // atomic lien_dec: F.liens_in_total -> 0
T1: (deed of F already dropped) settles; court sees F unsupported -> frees F
T2: t.find(k)                    // use-after-free
```
Possible fix: free frozen estates only after every thread has passed a settlement point, as an EBR grace period. One thread that never settles then pins all frozen garbage.

**CE4. A reference escapes a `trust` block.** The estate-block escape check is not stated for `with`.
```
var leak: Stats? = nil
with stats as s { leak = s }     // local, so not a jurisdiction breach
leak.count += 1                  // unlocked mutation, races
```
This is fixable by applying the same intraprocedural check that estate blocks get.

**CE5. Long-lived objects leak their temporaries (memory, not safety).** Rule 2 says objects are born in `self`'s estate, and `estate { }` does not redirect allocations made inside methods.
```
let server = Server()                      // global estate, never closes
loop
    estate { conn.write(server.handle(conn.read())) }
    settle
// Server.handle: let p = Parser(req)  -> born in Server's estate
// Every request's Parser and Response objects are retained forever.
```
A beginner who never writes `new estate` never frees any object at all. Under O1 the same code frees `p` immediately.

**CE6. Fine-grained estates are too expensive.** `estate_of(p) = *(p & ~0xFFFF)` means one estate costs at least one 64 KiB chunk, or at least one 4 or 16 KiB page if commit is lazy.
- The idea's own fix for landfill in (b), one estate per subtree, multiplies this.
- So does the cache in (d), with one estate per entry. A million small entries cost 4–64 GB.

The two mitigations, coarse estates and fine estates, therefore pull against each other.

**CE7. Escrow misbehaves silently in release builds.**
```
fun normalize(mut xs: List of Float)
    for i in 0..xs.count { xs[i] = xs[i] / self.mean() }   // mean() reads self.samples
self.normalize(mut self.samples)   // debug: trap. release: mean() of empty -> NaN everywhere
```
The program is memory-safe but behaves differently in release. Swift traps in both modes. The fix is to always trap, which needs a poison check on every read of a home that can be escrowed.

**CE8. A spec inconsistency.** The mapping table says an estate in receivership is "read-only for new liens". Rule 4 implies that any reachable reference can be stored. Take `let e = cache.get("x"); cache.evict("x"); other.cur = e`. One reading traps, which is surprising. The other is allowed, which is fine. The rule needs pinning down.

**CE9. Memory is held up for long periods.** Several situations stop reclamation:
- Nested modal loops (Cocoa tracking during a window resize, `runModal`) must not settle.
- Long compute loops away from a thread's entry function never settle.
- Async/await, or generator frames suspended across a turn, would hold uncounted locals across settlement. If the language ever gets coroutines, this becomes a hole and not just a delay.

**What holds up.**
- Within one thread, if CE1 is fixed, the court is correct. Support is a fixed point over the closed set, and the liens that count as support come from open estates.
- Bulk free at a moment when no frames exist rules out dangling pointers.
- Closing a window from inside its own `onTap` really is safe.
- Deadlock is no worse than with any mutex, through nested `with`. Verona's ordered acquisition avoids it, and this idea does not.

## 4. Scenarios

- **(a) Works.** A pure value, with exact frees through the fixture list. No estate machinery is involved.
- **(b) Works for cycles, but landfill on pruning.** Parent pointers are free. Pruning retains nodes until the document closes. The fix, per-subtree estates, runs into CE6.
- **(c) Genuinely works, and is the best answer of any scheme so far.** It needs no `weak self`, and self-close inside the handler is safe. Caveat: a DSL that rebuilds view objects every render piles them up in the window's estate unless the framework puts each render tree in its own estate.
- **(d) Safe.** Eviction under use is handled well by receivership. Per-entry estates have the CE6 memory cost, and one lien can retain a whole entry.
- **(e) Works.** Escrow gives zero-copy, alias-free mutation. CE7's release-mode behaviour needs fixing.
- **(f) Hand-wave as specified.** CE2, CE3 and CE4 are real races or use-after-frees. Plausible fixes exist (deferred send, EBR for frozen estates, an escape check for `with`), but none of them is in the spec.

## 5. Gates

- **G2: needs-john** (leaning pass). The court does reachability with trial deletion, but over the *estates closed this turn*. It never visits an object, never scans the heap, runs at deterministic points, and its cost is bounded by the lien-table entries of the closed estates. That is materially weaker than O7's object-level cycle collector, which was itself gated. The CE3 fix adds epoch-deferred reclamation, which John should also rule on. `refinance` would be tracing, so G2 rules it out.
- **G3: pass, with a flag.** `own` and `lease` are built-in slot or type-modifier keywords, the same kind of thing as `weak`, not user-visible generics or annotations. `List of X` / `Map of K to V` carry the same pending ruling on built-in containers as every other option.

## 6. Rubric

| Criterion | Wt | Score | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 3 | Users must learn 8 rules plus where objects are born, and estate design is mandatory. Without estates, no object is ever freed (CE5). It does remove `weak`. |
| Memory safety | 15 | 3 | Single-thread safety is strong once CE1 is fixed. As specified, CE1–CE4 are holes. Several checks exist only at runtime. |
| Expressiveness (b)(c)(d), OO/self | 15 | 4 | (c) and (b)'s cycles are best in class and implicit `self` is natural. Landfill and per-estate cost limit (b) pruning and (d) at scale. |
| Implementation risk (AI-written, LLVM) | 15 | 2 | The runtime is novel: a chunk allocator, barriers that understand values, the court, run-loop integration on Cocoa and Win32, EBR, escrow plus unwinding, escape checks. There is no production precedent. |
| Performance & predictability | 10 | 3 | Bump allocation, no RC on locals and bulk free are excellent for throughput. Memory use is unpredictable (landfill, retention of whole estates, a 64 KiB floor), and every reference store pays the barrier. |
| Concurrency fit | 10 | 3 | Zero-copy send, freeze and trust are a sensible Verona-like trio. As specified they are unsound, and send can fail at runtime. |
| Tooling, debug, C FFI | 10 | 3 | Plain pointers suit debuggers, "why is estate X alive" is answerable, and `pin` is simple. ASan and Valgrind don't understand bump chunks, and failures surface at runtime. |

Total = (25×3 + 15×3 + 15×4 + 15×2 + 10×3 + 10×3 + 10×3) / 5
      = (75 + 45 + 60 + 30 + 30 + 30 + 30) / 5 = 300 / 5 = **60**.

If CE1–CE4 are assumed fixed, memory safety rises to 4 and the total becomes (300 + 15) / 5 = **63**. Implementation risk stays at 2 because the fixes add machinery.

Against the references: about 20 points below **O1 (83)** and **O4 (82)**, roughly level with O8 (60). The gap comes from simplicity (−5 to −15 versus O1, depending on O1's score) and implementation risk. It beats O1 only on expressiveness for (c) and (b).

## 7. Fatal flaw and kernel

**Fatal flaw.** The only unit of reclamation is the estate. Coarse estates retain garbage without bound (CE5: every long-lived object's method temporaries). Fine estates cost a page each (CE6). Workloads with many small objects that each have their own lifetime fall between the two: servers, caches, editors with undo, declarative UIs that rebuild views. The language's default, never writing `new estate`, frees no objects at all. On top of that, the "cheap barrier" premise breaks as soon as values can hold references (CE1). Fixing it makes value moves O(n) or removes references from collections.

**Salvageable kernel.**

1. *Into O1: settlement-deferred release.* Run ARC with Deutsch–Bobrow deferral: don't retain or release locals, queue objects whose count reaches zero, and free the queue at event-loop or thread-loop boundaries when no language frames exist, so no stack scan is needed. This removes most ARC traffic and makes "close the window inside its own onTap" safe by construction.
   - It needs an EBR grace period for objects shared across threads (the CE3 lesson).
   - It needs a rule for long loops: a `settle` in the thread entry function, or falling back to counted locals.
2. *Into O1 or O4, optional: a built-in group allocation for UI windows.* An `estate` bundle is a single RC unit. Pointers inside the bundle are uncounted, and only cross-bundle references are counted. The button→closure→self cycle then needs no `weak`. Keep it opt-in and coarse, which is where it shines (windows, documents), and keep ordinary ARC for everything else, so CE5 and CE6 go away.
3. *Minor:* escrow as the implementation of `mut`/`inout` on fields, trapping in all build modes.

## 8. Verdict

**Kernel worth stealing.** It is not a contender: it scores 60–63 against 82–83, its default behaviour retains garbage, and its thread story is unsound as specified. Settlement-point deferred release, plus opt-in estate bundles for UI object graphs, would genuinely improve O1's weakest scenario, (c).
