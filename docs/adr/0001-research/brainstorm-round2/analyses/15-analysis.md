# Analysis 15: Tempo (memory on a calendar, references as tickets)

Analyst: independent. Inputs: brief.md, round2.md, CHARTER.md, ideas/15-tempo-tickets.md. All code here is illustrative only, not a syntax decision.

## 1. The idea in three sentences

Every heap object is born with a lifetime measured on a domain clock (frames, requests, a window instance). It is freed when that time runs out, whether or not anything still points at it. If no lifetime is written, the object takes the lifetime of the first place it is stored. Every stored pointer is a "ticket" stamped with its expiry beat, so a dereference compares that stamp with the clock. A stale ticket traps, and collections ("rosters") silently hide members that have expired.

## 2. Prior art

Tempo is mostly a safe recombination of known parts. The new parts are the glue.

- **Short-term memory / self-collecting mutators** (Aigner, Haas, Kirsch, Sokolova, ISMM 2011). This is the core premise almost exactly. Objects are allocated with an expiration date on programmer-controlled time and are never freed explicitly or implicitly. They can be *refreshed* to extend the date, which is Tempo's `renew`. The authors say it trades safety for throughput. https://tiptoe.cs.uni-salzburg.at/short-term-memory/ , https://research.google/pubs/short-term-memory-for-self-collecting-mutators , slides: https://ckirsch.github.io/talks/UCB10-STM.pdf
- **Oracle duration-based memory management** (US6253226, filed 1998). Named durations such as session, transaction, call, plus user-defined ones. The allocator takes a duration id, and ending a duration frees its pool. These are Tempo's clocks, minus the per-object beats. https://patents.google.com/patent/US6253226
- **CETS lock-and-key temporal safety** (Nagarakatte et al., ISMM 2010). Pointers carry a key that is checked against a lock held outside the object, so reuse is safe. A Tempo ticket is CETS with one lock per *clock* rather than per allocation. https://llvm.org/pubs/2010-06-ISMM-CETS.html
- Also known, not searched, and named by the inventor: timing wheels (Varghese & Lauck), QSBR/epoch reclamation, game frame allocators, APR request pools, and TTL caches (Guava `expireAfterAccess`).

**What is genuinely new:**
- "First home decides tempo" as the default, which replaces ownership.
- Rosters as collection semantics.
- Closures taking the shortest note among their captures.
- Making STM safe with clock-checked tickets across many independent clocks.
- The "score" debugging view.

## 3. Soundness: counterexamples

**C1. `renew` cannot reach existing tickets, so scenario (d) as written is broken.** A ticket carries its own `due`, and the check deliberately never touches the object. So `renew` cannot update tickets that already exist. In §6(d), `img = cache[url]` copies the ticket into a local, and `renew img` changes the object and, at best, that local. `cache[url]` still holds the old stamp, so at the original beat the roster hides the entry.
```
images.get(u)            // t=0: load, due 200
images.get(u)            // t=150: hit; renew -> object due 350; cache[u] ticket still due 200
images.get(u)            // t=201: cache[u] hidden -> miss -> second load; old image lives until 350
```
This yields an absolute TTL rather than "200 after last hit", up to 2x memory, and gallery/thumbs tickets that trap at 200. This is fundamental, not a typo. A check that does not consult the object cannot see a lifetime extension unless every ticket is found and rewritten. Finding them all means tracing (a G2 problem). Consulting the object means generation checks (O6) and loses the safe-reuse property. The only cheap patch is "renew writes back through the lvalue" (`renew cache[url]`). That fixes one home and still strands every other copy.

**C2. `renew` is shallow, so the data vanishes from inside.** `renew` relinks one object (§5). Its children were first-homed into it with the *old* note.
```
img = load(url) for 200 requests     // img.pixels (List) homed in img -> due 200
renew img for 200 requests           // img due 400; img.pixels still due 200
img.pixels[0]                        // t=250: wrong-note trap on a "live" image
```
A deep renew would need a walk over same-note objects, which is a second hidden walk like `freeze`.

**C3. First-home order changes meaning silently.**
```
fun login(req: Request, id: text)
  u = User(id)
  req.user = u           // first home: request note
  sessions[id] = u       // forever map, but u keeps the request note
// next request: sessions[id] hidden -> user "logged out", no error
```
Swapping the two store lines makes `u` live forever. The dissonance warning (rule 12) catches only cases the compiler can see. Once `u` arrives as a parameter, its note is a runtime fact.

**C4. Transitive captures are not protected (UI crux).** Rule 9 looks only at direct captures. Suppose `onTap: { self.doc.save() }`, where `doc` is on a document clock that ended while the window stays open. That is a wrong-note trap inside a UI callback, and under ARC it would simply work. The common "Save and Close" pattern also traps:
```
onTap: { save(); w.end(); log("closed " + text) }   // text is self.text; self ended -> trap
```
Rule 5 protects only call-born objects, and the editor was born long ago. Its memory, including this closure's environment, is freed mid-execution. It is safe, because the ticket check catches it, but it surprises the programmer.

**C5. `freeze` by note freezes the world.** "Freezes everything sharing the note" (rule 11). In §6(f), `table = buildTable() forever; freeze table` shares the note `forever` with `images`, `App` state and every other global. After that, every global is immutable for every voice, the owning voice included. Narrowing `freeze` to "the reachable graph" turns it into a trace.

**C6. Ticket field widths: use-after-free or a trace.**
- `gen:12` gives 4096 recycles per clock slot. A server that runs one `session.start()` per login, with a LIFO slot free-list, wraps a slot after 4096 sessions. A stale session ticket then passes the gen check. It also passes `now < due` against the young clock, and that is a real use-after-free.
- `due:32` relative to the epoch wraps after about 12 hours on a `request` clock at 100k requests/s. Rebasing epochs means rewriting every stored ticket, which is a heap trace.

The fix is wider tickets (24 bytes), which makes the cost problem in §9 worse.

**C7. Rosters corrupt parallel structures.**
```
names = List() forever ; avatars = List() forever
names.add(n.name) ; avatars.add(img)      // img for 200 requests
avatars[i]   // after img expires, indices shift: avatars[i] is now user i+1's picture
```
This is silent mis-pairing. Code that captures `n = xs.count` and then calls something that ticks traps out of bounds or skips members.

**C8. The tie walk and frame membership are under-specified.**
```
fun leaf() -> Node { return Node() }
fun branch() -> Node { b = Node(); b.kids.add(leaf()); return b }
doc.root = branch()
```
`leaf`'s node is born in `leaf`'s frame and homed into a call-born `b`. If the "same-frame" re-note walk does not also move frame membership through each return, `doc.root.kids` silently empties when `branch`'s caller returns. A correct fix is union-find-style "pending note" resolution, which is an unspecified mechanism. The walk is also proportional to the graph built in one call: parsing 1M JSON nodes and then homing them means a 1M-object walk.

**C9. Leaks by default.**
- `self.view = buildView()` on every keystroke in a window-long editor keeps every old view until the window closes.
- A game's `world.entities` defaults to forever, so despawned entities are never freed.

The suggested fix is "a sub-clock per entity". That puts pressure on C6 and makes every object a design decision about clocks.

**C10. QSBR stall and a deadlock risk.**
- A worker in a long compute loop never reaches a barline (its event loop, `send` or `bar`), so nothing it has pinned is reclaimed. Memory grows without bound.
- If `end()` blocks until the worker reaches a barline, and the worker is blocked receiving from the ending voice (`recv` is not a barline), the two deadlock. `end()` must be asynchronous, and the idea doesn't say which it is.
- No mutable ownership transfer between voices exists. You get only `freeze` or `Guarded`, which is a regression from O4's move.

## 4. Scenarios

| | Verdict |
|---|---|
| (a) lines into a list | **Works.** Destination-passed note, private buffer, file closed on silence. |
| (b) tree with parent ptrs | **Partial.** Cycles are free. Removed subtrees leak until the document ends. Re-parenting into another document keeps the old note (C3). |
| (c) UI callback | **Partial.** The headline case is elegant (no weak refs, subscriptions self-clean). Transitive captures and close-then-continue trap (C4). |
| (d) shared cache | **Fails as written** (C1). With lvalue-renew it becomes partial: other components' tickets still trap, and renew is shallow (C2). |
| (e) mutate large list | **Works.** It is a ticket alias, with no copy. |
| (f) threads | **Partial.** Freeze-by-note freezes all globals (C5). No transfer. QSBR stalls (C10). |

## 5. Gates and charter

- **G2: pass, conditionally.** Tick frees are O(due) cascades, like RC frees. The tie and `freeze` walks are bounded, synchronous and non-periodic. This flips to **fail** if ticket epochs or generations are fixed by rebasing instead of widening (C6), or if deep `renew` or reachable-graph `freeze` is adopted (C2, C5). Each of those is a trace.
- **G3: needs-john, leaning pass.** `for 3 frames` is a value expression at the allocation site and not in any type. However, `clock X within Y` is a declaration whose only purpose is lifetime reasoning, which is the spirit G3 objects to. Untyped `List()`/`Map()` leaves the pending question of built-in parameterised containers open.
- **Other charter strain:**
  - **G1:** 12 rules, plus nonlocal semantics (rosters, stale-after-renew, order-dependent homes).
  - **G6:** every standard-library collection's `count` and indices become time-varying.
  - **G10:** tests must drive clocks to cover expiry paths.
  - **G8 is a genuine plus:** the score view and wrong-note diagnostics.

## 6. Score

| Criterion | W | S | Why |
|---|---|---|---|
| Simplicity & learnability | 25 | 2 | 12 rules. The beginner subset is small, but its failures (C1, C3, C7) need all 12 to diagnose. |
| Memory safety | 15 | 3 | Clock-checked tickets are sound in principle. Field wrap gives a real use-after-free (C6). Silent data loss and production traps. |
| Expressiveness (b, c, d, OO) | 15 | 3 | (c) is nicer than ARC in the base case, (d) breaks, (b) leaks. Implicit self is fine. |
| Implementation risk (AI, LLVM) | 15 | 2 | Fat tickets everywhere, timing wheels, destination-passed notes, pending-note resolution, tick-effect inference, rosters, QSBR, pin. All novel, with no reference implementation. |
| Performance & predictability | 10 | 3 | No RC traffic and batch frees. Against that: 16–24 B tickets, 24 B headers, a check per deref plus re-checks after calls, and peak memory inflated by lingering garbage. |
| Concurrency fit | 10 | 3 | No atomic RC, and QSBR is proven. Freeze-by-note, no transfer, and stalls. |
| Tooling, debug, FFI | 10 | 3 | Superb diagnostics and timeline (4). FFI is awkward: fat tickets in C structs, pin lifetimes, C callbacks (2). |

Total = (25×2 + 15×3 + 15×3 + 15×2 + 10×3 + 10×3 + 10×3) / 5
     = (50 + 45 + 45 + 30 + 30 + 30 + 30) / 5 = 260 / 5 = **52**.

Comparison:
- 31 below O1 (83) and 30 below O4 (82).
- 16 below round 1's best (68), and below the inventor's self-assessed 68. The gap comes mostly from C1/C2 (the headline cache scenario) and from implementation risk.

## 7. What the premise teaches, and the kernel

**What the premise teaches:**
1. Programmers really do state non-nesting lifetimes most naturally as *domain events* ("until window 7 closes"), not as owners or scopes. That is the strongest framing of scenario (c) in either round.
2. There is a hard trilemma for any reachability-free scheme. Reference validity can be checked (i) against the object (generations: reuse needs type-stable memory), (ii) against an external lock or clock (CETS/Tempo: then *extending* a lifetime means finding every reference, which is tracing), or (iii) not at all (STM: unsafe). Calendar lifetimes plus extension plus safety plus no trace cannot all hold.
3. Decoupling the free from reachability turns cycles from a leak into a non-issue, but it moves the leak into "the duration was too long". It is the regional-leak problem again, in domain terms, as the inventor concedes.

**Salvageable kernel (adoptable into O1 or O4 without new syntax):**
- **Domain-clock lifetime expectations as an ARC debug mode.** This is the main steal. A library call such as `w.expect(editor)` (or an allocation inside `w.scope { }`) records that this object should die when `w` ends. In debug builds, `w.end()` reports every expected object that is still retained, with the retaining path, for example: "Editor from window#7 still alive 3 beats after close: Button.onTap -> closure -> self". This is O1's retain-cycle detector, phrased in the programmer's own terms, with no GC. In release builds it is a no-op.
- **The score / piano-roll heap timeline** as a G8 profiler for O1/O4: allocation sites bucketed by the domain events they were born and freed between.
- **Rosters as an explicit standard-library type,** not as the semantics of every collection: a weak-member `Roster` whose `count` excludes dead members. In O1 that is a self-pruning subscriber list, which removes most manual `unsubscribe` code in (c). Pair it with a timing-wheel `TtlMap` for (d).
- **Clock-table checked handles** as an option for O4 slot maps. A per-arena epoch makes "the arena ended" checkable without touching freed memory.

## 8. Verdict

**Kernel worth stealing.** The mechanism is safe Short-Term Memory with a nice default. However, the renew/ticket contradiction (C1) breaks the headline cache scenario, and the fixes all lead back to tracing or to generation checks. The domain-clock framing is valuable as a *diagnostic* layered on ARC, not as the allocator.
