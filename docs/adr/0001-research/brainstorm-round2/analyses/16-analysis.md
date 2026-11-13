# Analysis 16: Seniority & Runoff

Analyst verdict: **Kernel worth stealing.** Total **61 / 100**.

## 1. The idea in 3 sentences

Every live object has a place in a per-thread total order called "seniority". A reference that points down the order (older to younger) is a counted *vote*. Any other reference is an uncounted *petition*, kept on a back-pointer roll at its target. Because votes always point one way, they can never form a cycle, so a plain count is exact. When an object's count reaches 0, the runtime cascades to find the dying set S. Any live object that petitions into S has its petition turned into a vote, which revives part of S and moves it to just after the new voter. Everything left in S is freed at that statement, with deinits.

## 2. Prior art

This is a recombination, not a new family. Lineage:

- **Brownbridge (1985)** is the strong/weak split with "no strong cycles" as an invariant ([DOI](https://www.doi.org/10.1007/3-540-15975-4_42)). Lecture slides list the family's known failures: cyclic structures can be wrongly discarded, the algorithm can fail to terminate, and the worst case is exponential ([Rose-Hulman slides](https://www.rose-hulman.edu/class/csse/csse490-dsr/201030/Slides/ReclaimCyclicStructures.pdf)).
- **Pepels, van Eekelen & Plasmeijer (1988)** document three problems ([IR88-10](https://www.cs.ru.nl/~marko/research/pubs/1988/IR88-10CyclicProof-incl-fig.pdf)):
  - The original algorithm ignores weak pointers it meets during traversal, so live cycles get freed.
  - Assuming a copied pointer keeps its strength creates strong cycles.
  - Salkild's fix can loop forever.
  
  The same paper introduces the strength-bit trick: a pointer is strong when its bit matches its target's bit. It also gives a proof of termination, but admits worst cases are at least exponential.
- **Brandt, Krishnan, Sharma, Busch** published "Concurrent, parallel GC in linear time" (ISMM 2014, [ref](https://bibtex.github.io/ISMM-2014-BrandtKSB.html)). Their 2018 distributed follow-up is "based on the Brownbridge system", uses four reference types, and needs transactions and termination detection ([ISMM 2018](https://conf.researchr.org/details/ismm-2018/ismm-2018-papers/8/Distributed-Garbage-Collection-for-General-Graphs)).
- **Related:** Lins' lazy cyclic RC ([JUCS](https://lib.jucs.org/article_preview.php?id=28084)), and Bacon–Rajan trial deletion (from memory, no URL). The canvass-and-revive step is trial deletion triggered on a drop to zero, rather than run in batches.

What does look new:

- Strength is decided by **incremental topological order** (an order-maintenance list plus HKMST-style budgeted search), not by parity bits.
- Petitions are indexed by **explicit back-pointer rolls**. These fix Brownbridge's "missed weak pointer" bug, at about 4 words per back-edge.
- The language-level packaging: no `weak` keyword, plus `recall` diagnostics.

## 3. Soundness: counterexamples

All code below is illustrative only, not a syntax decision.

**C1. Dangling pointer from multi-stage revival.** This is the termination/soundness argument's real hole. Promote step 3 only handles votes from R to targets that are "inside R" or "outside the *original* S". It never covers a later-revived set R2 voting into an earlier-revived set R1.
```
L = List()                 // global, rank 0
o = Obj()                  // rank 1, held only by local o
q2 = Obj(); o.a = q2       // rank 2, vote
q1 = Obj(); o.b = q1       // rank 3, vote
r = Obj(); q1.r = r; q2.r = r              // rank 4, two votes
p = Obj(); L.add(p); q1.p = p              // rank 5, votes from L and q1
p.back = q1               // closes a cycle, so S3 makes it a petition
r.back = q2               // closes a cycle, so S3 makes it a petition
o = nil                   // runoff: S = {o, q2, q1, r}
```
- First promotion: p→q1 gives R1 = {q1, r}, and r's count is restored to 1 by q1.
- The parked petition r→q2 is then promoted, giving R2 = {q2}, placed after r.
- The edge q2→r is now an upward "vote". The rule never visits it, so it is never re-counted and never demoted onto r's roll.

What happens next depends on how the implementation handles that edge:
- **Rule as written:** do `L.add(q2)` then `L.remove(p)`. Now p, q1 and r cascade to zero. r's roll is empty, because q2→r is tagged as a vote, so r is freed while live q2 still holds `q2.r`. **Use-after-free.**
- **"Fixed" by re-counting every vote from R:** this creates a strong cycle r⇄q2. After `L.remove(p)` that cycle **leaks**.

The real fix is to change "outside original S" to "outside current S". That re-establishes the argument, but it shows the proof was not checked.

**C2. A self-store makes a strong self-loop and leaks.**
```
n = Node(); n.next = n
```
This is a sentinel node or a one-element ring. The ranks are equal, so S1 fails. n has no heap votes, so S2 fires: it moves n just before itself, then casts a vote. The result is a strong self-cycle, and n never dies. S2 needs a `src ≠ dst` guard.

**C3. A deinit runs after the cascade has already released its fields.** Phase 1 decrements S's votes *before* phase 4 runs the deinits, which is the reverse of ARC.
```
deinit { self.cache = nil }   // the old vote to a live cache is decremented a second time
```
- The cache was shared with live component B, at count 2. The cascade takes it to 1, and the deinit takes it to 0. The cache is freed while B uses it. **Dangle.**
- `deinit { self.log = liveLogger }` adds a vote from a dead object that is never removed. **Leak.**

**C4. A runoff nested inside a deinit causes a leak.** The claim "no runoff nests" ignores deinits.
```
class Editor { doc: Doc   // petition: doc is older than editor
  deinit { App.activeDoc = nil } }   // drops doc's last vote
```
- The editor dies. Its deinit starts a nested runoff on doc.
- Canvass counts a petitioner as "live" if it is "not in S". The dying editor is not in the *nested* S, so editor→doc is promoted to a vote.
- The editor is then freed without that new vote being decremented. Doc keeps count 1 forever. **Leak.**
- The fix is a dying flag plus deferred runoffs. That adds more state to the invariant.

**C5. The crux scenario (c) gets the wrong orientation.** The inventor's walkthrough assumes the capture of self is a petition. In fact S2 fires first.
1. The new closure has no heap votes, so it is moved *before* the editor and votes for it.
2. `button.onTap = closure` then closes a cycle, so S3 makes it a petition.
3. When init's temporary drops, the closure's count hits 0 and a runoff fires. It revives the closure through the button and flips the edges.

The end state is correct. But **every self-capturing UI component pays a runoff at the end of construction**. "Construction order matches ownership" is defeated by the same heuristic that was meant to exploit it.

**C6. Quadratic walk and revive with nothing freed.** Take a doubly linked list of tabs or undo states, where next is a vote and prev is a petition. The app holds only `cur`.
```
app.cur = app.cur.next    // repeat
```
- Each step drops the vote to the old current node. That node and everything older than it is suspended, then revived through the new node's prev petition and re-ranked.
- Walking forward k steps costs O(Σ sizes of tabs 0..k). Walking back once re-suspends the entire tail.
- An innocent statement costs O(n) and frees nothing. The "it learns the shape" claim fails on zipper or cursor structures.

**C7. A frozen graph with parent petitions dangles across threads.** The claim that frozen objects are "acyclic by construction" is wrong.
- `freeze(loadConfig())` freezes an *existing* graph. A config tree with parent pointers carries petitions into the frozen set.
- Frozen objects use plain atomic RC with no runoff. Thread A drops the root, so the root is freed. Thread B still holds a child, and `child.parent` now **dangles**.
- Cross-thread runoffs would need a global lock.

**C8. `Shared` region transfer is unspecified.** Take `jobs.with { q in q.add(Job(editor)) }`.
- The Job lives in thread A's parliament, which makes this a cross-parliament store. Unless the Job is moved or isolated, thread B can reach `editor`, which is a **data race**.
- `jobs.with { q in q.removeFirst() }` lets a box object escape while it still points into the box.
- Making this safe needs Pony-iso or Swift-region-style isolation checking. That is a large hidden rule set, and it may need annotations (G3).

**C9. Store order.** Step "Clear the old ballot... then S1" is release-before-retain. `list.head = list.head.next` frees head.next before the store, unless temporaries are always counted. This contradicts "ARC-style elision applies unchanged". Easily fixed, but it is a third spec bug in a ~20-line mechanism.

**C10. Semantic loss: there is no way to say "don't own".** Weak refs do two jobs: breaking cycles (which this scheme automates) and *non-owning intent*, which it cannot express.
- A global notification centre or a repeating timer that holds `{ self.refresh() }` keeps every editor alive forever.
- A weak-valued cache is impossible.
- "No leaks" here means tracing-GC "no unreachable garbage", not "no logical leaks".

## 4. Scenarios

| | Verdict | Note |
|---|---|---|
| (a) | **works** | Every `add` is a senior→junior vote, so the cost equals ARC. |
| (b) | **works** | Parent pointers are petitions, and the subtree dies leaf-first. Breaks when frozen (C7). |
| (c) | **partial** | No leak and no dangle, but it orients wrong (C5) and has no non-owning callbacks (C10). |
| (d) | **works** | Two votes. Entries' back-refs are petitions. |
| (e) | **works** | Borrowed parameter, mutated in place. |
| (f) | **hand-wave / fails** | `Shared` transfer is unspecified (C8). Frozen graphs with petitions dangle (C7). Cross-box cycles leak, as the inventor admits. |

## 5. Gates and charter

- **G2: needs-john, leaning fail.** There is no root scan, and timing is synchronous. But a runoff is trial deletion, which is a cycle-collection technique, and C6 shows it repeatedly walks *live* data. That is local partial tracing on the mutator path. O7 (ORC) was gated for the same family of reason.
- **G3: pass for the core**, with no `weak`, generics or annotations. **Flag:** a sound `Shared` (C8) almost certainly needs isolation or sendability markers. `List` and `Map` are the usual pending question.
- **G8 (debugging): strained.** Strength is invisible in source and depends on history. The debugger must surface ballots, ranks and runoff costs.
- **P-C:** reference fields are tagged words, not raw pointers, so C structs cannot hold language references directly.
- **P-SWIFT:** the hidden cost model brings back "too complicated" at the performance layer, not the syntax layer.

## 6. Rubric

| Criterion | Weight | Score | Why |
|---|---|---|---|
| Simplicity | 25 | 4 | 3 to 4 user rules, the fewest seen. But the thread-isolation rules are missing and will grow, and cost cliffs need a mental model of seniority. |
| Memory safety | 15 | 3 | As specified: a dangle (C1, C3, C7) and leaks (C2, C4). Fixable, but the invariant is delicate and unproven. Raw FFI pointers are unsafe. |
| Expressiveness | 15 | 4 | (b), (c) and (d) need only plain refs and implicit self. Non-owning intent is lost (C10). |
| Implementation risk | 15 | 2 | Order-maintenance list, HKMST, multi-stage revival, deinit re-entrancy, region transfer. 4 holes in about 20 lines. Testable against a tracing oracle, which is the only reason this isn't 1. |
| Performance | 10 | 2 | Rank compare and search on every store, a branch on every load, 4-word petitions, an O(n²) zipper walk (C6), and history-dependent costs. |
| Concurrency | 10 | 2 | Per-thread parliaments, an unspecified `Shared` transfer, a frozen-graph dangle, and cross-box leaks. |
| Tooling and FFI | 10 | 3 | Veto and `recall` diagnostics are excellent. Tagged fields and the need for root handles hurt C FFI and debugger simplicity. |

Total = 25·4/5 + 15·3/5 + 15·4/5 + 15·2/5 + 10·2/5 + 10·2/5 + 10·3/5
= 20 + 9 + 12 + 6 + 4 + 4 + 6 = **61**.

This compares with O1 at 83 (−22), O4 at 82 (−21) and round 1's best at 68 (−7). The inventor's self-assessment of 79 assumed safety 5 and simplicity 5. Neither survives C1 to C8.

## 7. What the premise teaches, and the kernel

**What the premise teaches.**

1. The thing people want from a GC is *reachability semantics*, and the thing they want from ARC is *deterministic timing*. This design shows the two can coexist, but only by moving reference strength out of the source and into hidden runtime state. The complexity is not removed. It turns into an unpredictable cost model: stores become searches, and drops become walks of live data.
2. `weak` carries two meanings. Breaking cycles can be automated. Expressing "I don't own this" (observers, timers, caches) cannot, so removing the keyword removes something users need.
3. The empirical bet behind the premise holds up, and it is the useful part. **Allocation order predicts ownership direction**: back-edges (parent, self captured by a closure, entry→cache) point from younger objects to older ones. Paradoxically, S2's attempt to exploit this is what breaks C5.

**Kernel to steal into O1 or O4.** None of this needs the parliament at release time.

- **Debug-mode age-inversion detector.** Debug object headers carry a 64-bit allocation sequence number. A strong store from a younger object to an older one that is reachable from it is logged as a "likely cycle edge". `self` captured by a closure stored on self is the canonical case. It turns O1's "where do I put `weak`?" into a concrete warning with a field path.
- **Static lint, same heuristic:** "a closure created in a method of `T`, stored (transitively) in a field of `self`, captures `self` strongly. Suggest `weak self`." This directly targets the crux scenario (c).
- **`recall x`** (assert this drop frees x; otherwise list the holders by field path), plus a debug-only "who is keeping this alive?" trial-deletion query. Both are drop-in debugging tools for ARC (O1) or `shared` (O4), and satisfy G8 with no runtime cost in release.
- **Differential test harness.** Run debug builds against a shadow tracing oracle to report leaked strong cycles at exit. Because it only runs in debug, it is a GC-like check that doesn't violate G2.

## 8. Verdict

**Kernel worth stealing.** As a release memory model it is a Brownbridge-family recombination with the family's signature failures, still present in an argument written fresh. It scores 61, below every reference option. Its age-ordering insight and its `recall` / voter-roll diagnostics are cheap, valuable debug tools for O1 or O4.
