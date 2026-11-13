# Analysis 04: Spaces and Descriptors

Analyst: independent. Inputs: brief, charter, idea 04 only. All code is *illustrative only, not a syntax decision.*

## 1. Restatement (3 sentences)

Every event handler, thread body or `turn {}` block bump-allocates scratch memory, and all of it is freed when the turn ends. Data that must outlive a turn goes into a programmer-created **space**: a heap with a non-nested lifetime, arranged in a tree and freed as a whole by `exit()`. Inside a space, references are plain (self-relative) pointers and cycles cost nothing. References between spaces become generation-checked fd-like **descriptors**, which abort the current turn with `Closed` if the target space has exited.

## 2. Prior art

Not a rename of O1–O8. It is, though, a recombination of known systems, several of them not on the brief's list:

| Piece of idea 04 | Prior art |
|---|---|
| Spaces as regions with a dynamic (non-lexical) lifetime, intra-region refs unrestricted, region as the unit of ownership/transfer | **Project Verona** regions and cowns ([MSR paper](https://www.microsoft.com/en-us/research/publication/reference-capabilities-for-flexible-memory-management/), [arXiv 2309.02983](https://arxiv.org/abs/2309.02983)). Verona also lets a region be sent between threads whole and allows per-region memory strategies (arena/RC/trace). This is the closest match. |
| Space tree; freeing a parent frees its children | Samba **talloc** ([man page](https://www.samba.org/~tridge/etest/lib/talloc/talloc.3.html)), Apache APR pools. |
| Non-lexical memory areas with checked cross-area stores and deferred reclaim while threads are inside | **RTSJ ScopedMemory** ([Oracle docs](https://docs.oracle.com/javase/realtime/doc_2.2/release/rtsj-docs/javax/realtime/ScopedMemory.html)). It uses runtime assignment checks ([IllegalAssignmentError](https://www.aicas.com/jamaica/8.2/doc/rtsj_api/javax/realtime/IllegalAssignmentError.html)) and reference-counts the threads inside an area. It is notorious for being hard to use. |
| Dynamic regions behind checked handles | **Cyclone** dynamic regions ([Hicks et al.](https://www.cs.umd.edu/~mwh/papers/ismm.pdf)). Cyclone checks statically; 04 checks at run time. |
| Per-turn scratch reset | Objective-C autorelease pools, PHP per-request memory, game frame arenas. |
| Copy-on-send, per-actor heaps | Erlang per-process heaps. |
| Generation-checked handles | O6 (Vale), slot maps. |

**What is new:** (i) the *store barrier that moves a scratch graph in on store* (`write()` semantics). RTSJ throws on this case instead. (ii) Self-relative intra-space pointers so the MMU can fork, send and relocate whole spaces. (iii) `Closed`-aborts-turn combined with auto-unregistering the callback. (iv) The `ps`-style space-tree debugger. (i) and (iii) are genuine twists. (ii) is novel in a language runtime, but its key claim is technically shaky (§3, C6).

## 3. Soundness: counterexamples

**C1. Dangling pointer from a nested turn to an outer turn's scratch.** The store barrier runs only on stores *into space objects* (§5). Rule 2 copies out only *variables* assigned in the block, not field stores.
```
let acc = List()                 // outer turn's scratch
turn { acc.add(Node("x")) }      // Node is in the inner turn's scratch; it is a field store, not a variable assignment
print(acc[0].name)               // the bump pointer was reset at block end: use-after-free
```
The same problem arises with nested event loops (`runModal()` inside a handler) and with synchronous callbacks *if* they count as turns. Rule 1 says "each callback or event invocation", so it is undefined whether `xs.map { Foo(it) }` frees its results. Fixing it needs a barrier on scratch→scratch stores as well, plus remembered-set copy-out. That is RTSJ's problem, and the cost model gets worse.

**C2. Long-lived turns leak scratch without bound.** `main` and thread bodies are turns that may never end.
```
spawn { while true { let req = conn.read(); respond(parse(req)) } }   // scratch never resets -> OOM
```
The user has to know to wrap each iteration in `turn {}`. This is the Objective-C autoreleasepool-in-loops footgun, made the default.

**C3. Raw locals into a space after the space moves.** Locals hold absolute pointers (§5), but spaces move on pocket promotion (about 64 KiB), on `mremap` growth and on `renew`.
```
let e = space(); let n = Node() in e        // pocket space
for i in 0..10000 { n.kids.add(Node()) }    // passes 64 KiB -> promoted -> relocated
n.name = "x"                                // n is stale: writes into freed slab
```
Renew is deferred "to the end of the turn". But with nested turns (a handler inside main's event loop), main's locals still point into the old copy. A sound fix needs either (space, offset) fat locals with a lookup on every deref, or spaces that never move. Never moving gives up growth-by-remap and renew-in-place.

**C4. Data race after `send`.** The `NotYours` check runs only on *descriptor loads*, not on raw locals.
```
let job = space(); let b = Batch() in job; job.root = b
send job to worker
b.items.add(1)          // raw pointer, no check, races with worker
```
The compiler can't invalidate `b`, because `spaceOf` is dynamic. Scenario (f)'s own example has `spawn { fork(spaceOf(model)) }` touching a non-shared space owned by the main thread from 8 threads. Under rule 10 that should be `NotYours`. It is a race if it isn't.

**C5. Garbage that renew can't reclaim: cross-space cycles.** Exports are refcounted by holder entries, and holder entries are dropped only on holder exit or renew. Renew keeps everything exported.
```
loop { turn {
  let x = Node() in a; let y = Node() in b
  x.peer = y; y.peer = x            // export in b held by a; export in a held by b
}; a.renew(); b.renew() }           // both keep x,y forever: each is "exported"
```
This is ARC's cycle problem moved up to the space level. It is the same failure seen in RMI/CORBA distributed refcounting.

**C6. `fork` is not a snapshot on Linux.** Mapping the memfd `MAP_PRIVATE` gives copy-on-write *for the forker's writes only*. Per [mmap(2)](https://linux.die.net/man/2/mmap), "it is unspecified whether changes made to the file after the mmap() call are visible in the mapped region". In practice they are visible for pages the fork hasn't touched. So the owner's later writes leak into the "snapshot", torn. `List.copy()` page CoW has the same problem. Linux has no userland API for a true symmetric in-process anonymous-memory CoW. macOS `mach_vm_copy`/`vm_remap(copy=TRUE)` does provide one.

**C7. Surprising: auto-unregister kills a dispatcher.**
```
appMenu.add(MenuItem("Save", { app.current.save() }))   // app.current is a descriptor
// user closes editor A, the menu is tapped before app.current is updated -> Closed
// -> menu item permanently unregistered; editor B opens; Save menu is dead
```

**C8. Partial mutation on `Closed`.** Any field load can abort the turn: `self.total -= x; other.total += x`. If `other` is closed, the first write survives. This is safe in the memory sense but breaks program invariants. It is only fixed by the optional `atomic turn`, which needs page shadowing on three operating systems.

**C9. Store-order-dependent identity.** A scratch object `X` reachable from both `A` and `B`: store `A` into `s1` and `X` moves into `s1`. Then store `B` into `s2`, and `B.x` becomes a descriptor. If `s1` exits, `B.x` is `Closed`. Swap the two statements and `s2` owns `X`. Placement is invisible in the source (the idea admits this).

**C10. Deadlock:** nested `with a { with b { } }` against `with b { with a { } }`. The idea admits this. It is the same as with any mutex.

Verdict: the core (bulk free plus generation-checked cross-space handles) is sound in principle. The spec as written has two memory-unsafety holes (C1, C3) and a race (C4), and they all come from the same source: **raw pointers in locals interacting with moving spaces and nested turns.** It also has two leak classes (C2, C5) and one technically wrong mechanism (C6).

## 4. Scenarios

| | Verdict |
|---|---|
| (a) | **Works.** Scratch list plus a free return is a real win. Move-in copies once unless `in doc` is used. |
| (b) | **Works for build-once trees.** Churn needs `renew` or per-subtree spaces. There is no way to *move* a subtree between spaces: reparenting turns parent pointers into descriptors. Partial. |
| (c) | **Mostly works.** Intra-space editor/button/closure cycles with no `weak` are the idea's best result. Cross-space callbacks rely on `Closed` + unregister, which misfires (C7). Outer-turn locals (C3) and rendering each frame into a child space are plausible but untested. |
| (d) | **Partial.** Per-entry pocket spaces make eviction real. But the cache space itself churns (map buffers under 64 KiB, descriptor entries), so it needs periodic `renew`, and the multi-threaded version doesn't say who owns the child spaces of a `shared` space. |
| (e) | **Works.** Plain reference semantics. The CoW `copy()` claim is wrong on Linux (C6), but a plain copy still works. |
| (f) | **Hand-wave.** `send` is unsound with raw locals (C4). The fork example violates rule 10 and fork isn't a snapshot (C6). `shared` + `with` is a coarse mutex. |

## 5. Gates

- **G2: needs-john, leaning fail in practice.** Exit and scratch reset are not GC. But `renew` is a copying trace from the roots of one space. Long-lived churny spaces (the root space, caches, a document edited for hours) *require* it or grow without bound. The root space can never be exited, so its only remedy is `renew`, which is a full trace of everything global. "Programmer-invoked" makes it a manual GC call, not the absence of GC. The other way out, "give churny things child spaces", is manual memory management at a coarse grain.
- **G3: pass (flag).** `in s`, `space()`, `shared space()` and `with` are expressions and constructors, not annotations. It depends on built-in `List`/`Map`, which is the same pending question as O1 and O4.

## 6. Scores

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity | 25 | 2 | Ten rules plus invisible placement, turn boundaries, move-in vs. copy-out, the `turn{}`-in-loops discipline, exit/renew discipline, `Closed`, `alive`, `NotYours`, fork/send/shared. More concepts than ARC + weak, and they are new to everyone. |
| Memory safety | 15 | 2 | As specified: use-after-free (C1, C3) and a data race (C4). The repaired version, with fat or pinned locals and no moving, would be about 4. |
| Expressiveness (b,c,d, OO) | 15 | 4 | Cycles free inside a space and implicit `self` captures with no capture lists are excellent for (c). Cross-space ergonomics and churn hold it below 5. |
| Implementation risk | 15 | 1 | Three VM backends, self-relative pointers through LLVM (provenance and alias analysis fight it), a store barrier with forwarding, a radix table, pin counts, deferred exit, a renew copier, pocket promotion, and C1/C3 fixes that need read barriers. The hardest runtime on the list. |
| Perf & predictability | 10 | 3 | Bump allocation and bulk free are great. Costs: a barrier on every ref store, a tag branch on every ref load, O(n) move-in, bloat until renew, renew pauses proportional to the live space. |
| Concurrency | 10 | 3 | Zero-copy send and a fork snapshot are attractive in principle. In practice send has a race (C4), fork is broken on Linux (C6), and the shared-space lock is coarse and can deadlock. |
| Tooling & C FFI | 10 | 2 | The space-tree debugger is a real plus. But self-relative fields are unreadable in lldb/gdb/WinDbg without custom formatters, and C can't hold pointers into moving spaces, so it needs marshalling or a separate "C space". |

**Total** = (25·2 + 15·2 + 15·4 + 15·1 + 10·3 + 10·3 + 10·2) / 5
= (50 + 30 + 60 + 15 + 30 + 30 + 20) / 5 = 235 / 5 = **47**.

That is 36 below O1 (83) and 35 below O4 (82). It is also below O8 manual memory (60). Even generously repaired (safety 4, simplicity 3), it reaches about 58.

The inventor's self-assessment was about 70. The gap comes from implementation risk (2 vs 1), safety (4 vs 2) and tooling (3 vs 2), driven by C1/C3/C4/C6.

## 7. Fatal flaw and salvageable kernel

**Fatal flaw:** *moving, self-relative spaces combined with raw absolute locals and nested turns.* Making that combination safe needs read barriers or fat pointers on every local deref into a space. Making it useful needs a working cross-platform CoW snapshot (which doesn't exist on Linux) and a tracing `renew` (which pushes on G2). Take away moving and renew, and what is left is Verona-style regions plus talloc trees: good ideas, but with a leak story the user has to manage.

**Salvageable kernel, for O1 (or O4):**
1. **Event-source callbacks with implicit lifetime binding.** When a closure is registered with an event source, `self` is captured as a checked non-owning reference. When the target is gone, the callback unregisters itself instead of crashing. This addresses (c) in ARC without capture lists or user-written `weak`. It is the `Closed` + auto-unregister idea, minus C7: unregister only when the *captured* target is dead, not on any `Closed` in the body.
2. **Opt-in bulk-freed "island" for UI/document subtrees.** Objects allocated `in` an island aren't individually refcounted, internal cycles are free, and the island as a whole is ARC-counted, Verona-style. Refs into it from outside are generation-checked. Non-moving, so no self-relative pointers. This needs a G1 judgement on whether it's worth the extra concept.
3. **Per-handler scratch as a compiler optimisation, not semantics.** Escape analysis puts provably non-escaping temporaries of an event handler in a bump arena that resets at handler end. Invisible to users.
4. **Debugger view of live ownership islands and their sizes** (the "ps" idea), for G8.

## 8. Verdict

**Kernel worth stealing.**

One line: steal "callbacks registered on event sources bind `self` as a checked handle and auto-unregister when it dies", plus optional non-moving, generation-checked bulk-free islands. Drop the self-relative moving spaces and `renew`.
