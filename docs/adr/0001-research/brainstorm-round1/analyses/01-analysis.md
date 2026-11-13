# Analysis 01: Tissues and Nerves

Analyst verdict: **Kernel worth stealing**. Weighted total: **60 / 100** (O1 83, O4 82).

## 1. The idea in three sentences

Heap objects are grouped into a tree of programmer-created lifecycles (`grow` makes a "tissue", e.g. a window or session). Inside a tissue, references are ordinary non-atomic RC, and the whole tissue, cycles included, is freed by a list walk when its parent drops it or `die()` is called, deferred while any local still points in. A reference that crosses tissues is decided at store time to be a "nerve" (a zeroing weak ref whose dead target ignores calls); a new object joins the tissue of whatever first stores it.

## 2. Prior art: a recombination, plus one new mechanism

Most of the parts already exist:

| Part of the idea | Prior art |
|---|---|
| Forest of regions; local memory management per region; one thread mutates a region | Project Verona ([OOPSLA'23](https://arxiv.org/abs/2309.02983), [MSR page](https://www.microsoft.com/en-us/research/publication/reference-capabilities-for-flexible-memory-management/), [summary](https://tamnd.github.io/brain/research/memory-management/ownership/07_project_verona_regions/)): "organises all the objects in a program into a forest of isolated regions… Memory is managed locally for each region". |
| `secrete` with one count for a frozen graph | Verona `imm`/freeze, with RC over SCCs (Parkinson, Clebsch, Wrigstad, ISMM'24). Also Kotlin/Native's old `freeze()`. |
| `gland` + `with` | Verona cowns + `when`, but without Verona's deadlock-free multi-acquire. |
| Tissue tree; parent death kills children; `die()` deferred; nerve; thread affinity; `send` | Qt object trees ([doc](https://doc.qt.io/qt-6/objecttrees.html), [QObject](https://doc.qt.io/qt-5/qobject.html), [QPointer](https://doc.qt.io/qt-5/qpointer.html)): parent deletes children; `deleteLater()`; `QPointer` auto-nulls; `moveToThread`; connections whose context object has died are dropped. |
| Inert dead target; receptor side table | Objective-C nil messaging; the ObjC runtime's zeroing-weak side table. |
| Owning vs non-owning references, with checks on destroy | Gel, "Ownership You Can Count On" (Dingle & Bacon; [discussion](https://lists.puremagic.com/pipermail/digitalmars-d/2021-November/321376.html)). |

**Genuinely new:**
- Strong vs weak is *inferred dynamically* at every store, from tissue membership. In Verona a cross-region reference is a static type error; here it becomes a zeroing weak ref.
- Homing ("first store wins") assigns a region by first holder, not by allocation site or scope.
- An automatic `host` back-pointer.

Verdict on novelty: a real contribution, best described as "Verona's region forest with dynamic instead of static isolation, given Qt's object-tree ergonomics".

## 3. Soundness: counterexamples under the rules as written

All code is illustrative only — not a syntax decision.

### C1. Use-after-free via a stem cell's provisional reference (spec bug)
Stem → homed-cell edges are "provisionally counted". But apoptosis frees every cell regardless of RC, and only *locals* pin a tissue.
```
let holder = List()                        // stem, held by a local
holder.add(app.windows[0].toolbar)         // stem -> W edge: counted, not a nerve, not a pin
app.windows[0].die()                       // receiver temp pins W only during the call
// W.pins == 0 -> apoptosis frees toolbar; holder's slot is not in receptors
holder[0].count                            // dangling read
```
Fix: count stem→tissue edges as pins, or register them as receptors.

### C2. Nerve created during `deinit` (ordering bug)
Apoptosis cuts incoming nerves in step 1 and runs deinits in step 4. A deinit that does `logger.last = self`, or enqueues a closure capturing `self` into another tissue, registers a new nerve after the cut. Step 5 frees the cell, so that slot dangles.

Fix: the barrier must refuse nerves into doomed tissues, and cutting must run after deinits. This is easy to patch, but it shows the runtime has many such orderings that all have to be exactly right.

### C3. Data race through a gland (spec hole)
```
let item = Item()                            // stem, local on thread A
with stats { s in s.items.add(item) }        // item homes into the gland tissue
spawn { with stats { s in s.items[0].n += 1 } }   // thread B, under the lock
item.n += 1                                  // thread A: a local is a counted ref, not a nerve
                                             // load -> no lock check; also a non-atomic RC race
```
The lock check is defined only for nerve *loads*. Locals that alias gland cells escape it, and so do locals bound inside `with` that outlive the block.

Fix: either a uniqueness check (rc == 1) when homing into a gland and an escape check on `with`-bound locals, or a lock check on *every* access to a gland cell. The first is O4-style move/borrow rules arriving through the back door.

The same question arises for `spawn { doc.edit() }` capturing a thread-local cell. Either that is a race, or the capture becomes a cut nerve and the spawned job silently does nothing. The spec doesn't say which.

The local `job` still exists after `send job to worker` (the trap fires only when pins > 1). So the compiler also needs use-after-move analysis on that local.

### C4. Transfer between lifecycles is impossible without `copy()` (inherent)
Nothing can be reparented. Any object that passes through an intermediate holder dies when it reaches its real owner:
```
app.inbox.add(Request(bytes))       // homes into App's tissue
let r = app.inbox.pop()             // App lets go; the local keeps r alive
session.current = r                 // cross-tissue store -> nerve
// end of scope: r's RC hits 0 -> freed; session.current is dead immediately, silently
```
The same thing happens with:
- work queues and channels;
- dragging a tab or node between windows or documents;
- undo stacks;
- object pools;
- a "build in a scratch list, then hand over" step whose scratch list is a field.

### C5. Heisenbug: a debug line changes ownership
```
func make() -> Thumb
  let t = Thumb(bytes)
  self.lastMade = t           // added for debugging; t now homes into self's tissue
  return t
cache.put(k, make())          // the cache now holds a nerve; the entry dies when lastMade is overwritten
```
Ownership depends on the dynamic order of incidental stores, not on anything visible at the `put`.

### C6. `host` breaks on reparenting, depending on order
`newParent.add(c); oldParent.remove(c)` leaves `c.host` dead even though `c` is live under `newParent`:
- the first add doesn't overwrite a non-null `host`;
- the remove then clears it.

The reverse order works.

### C7. Zombie observers and leaks inside a tissue (inherent)
Within one tissue there is no weak reference at all:
```
model.observers.add(view); view.model = model    // both in the window tissue: counted cycle
window.content.remove(view)                       // view stays alive AND keeps receiving
                                                  // notifications until the window dies
```
In the root/App tissue this is O1's permanent cycle leak, with no `weak` available to fix it. The only remedy is `grow`ing more tissues, so placing objects in tissues becomes the annotation, made at a different site.

### C8. A local in a long-lived frame stops death
`func run() { let doc = grow Doc(); app.docs.add(doc); loop { pump() } }`. The `doc` local pins the tissue for the whole program, so closing the document never frees it. The outcome depends on whether the compiler ends a local's liveness at its last use, so the semantics would depend on the optimizer.

## 4. Scenarios

| | Verdict |
|---|---|
| (a) | **Works.** Plain ARC; tissues aren't involved. |
| (b) | **Works for static trees.** `host` is elegant. Reparenting is order-sensitive (C6), and pasting across documents produces nerves unless you deep `copy()`, which is unspecified (shallow or deep?). |
| (c) | **Works on the happy path, and it's the best answer to (c) seen so far.** It needs no `[weak self]`, and closing a window from its own button is safe. It depends on the Button being created inline: `self.saveBtn = Button(..)` followed by `toolbar.add(saveBtn)` flips ownership. |
| (d) | **Works if every entry is built inline at `put`.** An entry first stored elsewhere silently becomes a nerve (C4, C5). Evicted entries are inert, not dangling. |
| (e) | **Works.** Python-style aliasing; nothing new. |
| (f) | **Partly hand-waved.** `secrete` is sound. `gland` has a race (C3). `send` needs move analysis, and it silently kills any input that wasn't copied in. |

## 5. Gates

- **G2: pass.** There is no tracing. Apoptosis walks the list of a tissue the program chose to kill, and homing visits only new cells. The debug-only "tumour report" needs a reachability pass at tissue death. It never reclaims, so it doesn't break the gate, but it should be labelled as debug-only tracing.
- **G3: pass, with the shared flag.** `grow`/`send`/`secrete`/`gland`/`alive` are expression keywords, not annotations. Like O1 and O4, it relies on built-in `List`/`Map` (needs-john, but no worse than O1/O4). `host as Node` needs a checked downcast, which is not a template.

## 6. Scores

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 3 | Almost no syntax, but there are 9 rules plus about 10 sub-rules. Ownership is invisible and depends on history (C4, C5), so "why is this dead?" needs a tissue-tree mental model. O1 has fewer, local rules. |
| Memory safety | 15 | 3 | As written it has a UAF (C1, C2) and a race (C3), all patchable. Even after patching, inert death turns memory errors into silent wrong data, as nil-messaging does. |
| Expressiveness (b, c, d, OO) | 15 | 4 | Excellent (c), `host` for (b), easy implicit-self OO. There is no transfer between lifecycles and no weak inside a tissue (C4, C7). |
| Implementation risk (AI-built, LLVM) | 15 | 2 | Store barriers, homing walk, receptor tables, pins, tagged field pointers, dead vtables, deferred death, gland checks, and move-after-send. Three soundness holes turned up in a single review. |
| Performance & predictability | 10 | 3 | Every pointer store goes through a barrier and a hash-table update; 5-word header; double increment on local retain; bit-masking on field loads. On the plus side: non-atomic RC, and bulk free that's predictable. |
| Concurrency fit | 10 | 3 | Thread-confined tissues and frozen sharing are the right shape, as in Verona. Glands leak through locals, `with` has no deadlock-free multi-lock, and `spawn` capture semantics are unspecified. |
| Tooling, debuggability & C FFI | 10 | 3 | The necrosis log and tissue-tree view are good. Silent no-ops in release, tagged pointers, and C code that stores pointers outside the barrier all need a pin/handle API. |

Arithmetic, Σ w × s / 5:
- Weighted products: 25·3 + 15·3 + 15·4 + 15·2 + 10·3 + 10·3 + 10·3 = 75 + 45 + 60 + 30 + 30 + 30 + 30 = 300.
- 300 / 5 = **60**.

**Comparison:** 23 below O1 (83) and 22 below O4 (82).
- **The idea wins on:** (c) ergonomics and cycle bounding.
- **The idea loses on:** simplicity (−1 vs. an assumed 4 for O1), implementation risk (−2 vs. an assumed 4), and safety (−1 or −2).

Patching C1–C3 would raise safety to about 4 and the total to about 63, still well short of O1 and O4.

## 7. Fatal flaw and the salvageable kernel

**Fatal flaw (for the primary model).** Whether a reference owns its target is a runtime property, decided by the first store that happened to occur and invisible in the source and types. It can't be revised without `copy()`, and its failure mode is a silent no-op. So the same `cache.put(k, v)` line owns in one run and doesn't in another (C4, C5), and the program won't say so. That is the opposite of G1. The runtime needed to make it sound is large and subtle, which counts against an AI-written compiler.

**The kernel.** It could be adopted into O1, and the parts are separable:
1. **Inert dead-capture closures.** When a closure is stored into a field of an object other than the captured `self`, `self` is captured weakly and the closure becomes a no-op once `self` is dead. This removes `[weak self]` and `guard let self` from the UI case, at the cost of one rule. The edge case where the closure is the only owner (fire-and-forget async) needs an explicit strong form, or the "stem joins the closure" homing trick limited to closures.
2. **Automatic `host` back-pointer.** A built-in non-owning, zeroing parent reference set on containment. It removes the most common use of `weak var parent`, provided it is defined as "the most recent holder" so that it survives reparenting (C6).
3. **Deferred destruction while pinned.** An object's deinit/free is postponed while one of its methods is on the stack (Qt's `deleteLater`, done automatically). It's cheap in ARC, because the callee frame already retains `self`.
4. **Optional, as an O1/O4 library feature: lifecycle groups.** A `grow`n group whose cycles are bulk-freed at group death, with incoming references automatically zeroed. This bounds O1's cycle leaks to a window or session without a collector. It's worth prototyping only after 1–3.
5. **Tissue-level single atomic count for frozen graphs.** Cheap sharing of immutable data across threads, for O1's or O4's thread story (credit Verona).

## 8. Verdict

**Kernel worth stealing.** As a whole model it is not a contender: it scores 60 against 82–83, has three soundness holes as specified, and its ownership is history-dependent and silent. Items 1–3 above would make O1 noticeably better at scenario (c) for about one extra rule.
