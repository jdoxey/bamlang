# 16 — Seniority & Runoff (a parliament of references)

## 1. Name

**Seniority & Runoff.** Every reference is a ballot. A ballot is either a **vote** (counted, keeps its target alive) or a **petition** (on the roll, not counted). The runtime decides which, at runtime, and re-decides it in **runoff elections**. The programmer never chooses. The language has no `weak` keyword.

## 2. The crazy premise

Assumptions this breaks:

- **"Reference strength is a static property that the programmer (or the type) chooses."** Here it is a mutable runtime status. It is assigned by a global seniority order and overturned by elections. The same field can be strong on Monday and weak on Tuesday.
- **"A pointer store is a dumb O(1) write."** Here every heap store consults a global order of objects and may reorder part of it.
- **"Cycles need either a tracing pass or programmer-placed weak refs."** Here the strong subgraph is kept acyclic *by construction*, so plain counting stays exact. Cycles are resolved by a local vote when something would die.

Gates: G3 passes cleanly (no annotations, no `weak`, no generics needed by the model). G2 is pass-with-caveat. No root-to-heap trace ever happens, and no collector runs. But a runoff walks the set of objects that are *about to die*, plus any it revives. That is synchronous work on the dying set, not a separate GC run. I'd flag it `needs-john` only if he counts "walk what is dying" as collection; plain ARC cascades already do that.

## 3. Pitch

Objects live in a parliament where **seniority** is a total order over all live objects. Stack frames and globals are senior to everything; a new object is born junior-most. A reference from a senior object to a junior one is a **vote**: it is counted, like an ARC strong ref. A reference from a junior to a senior is a **petition**: it is recorded on the target's petition roll but not counted. Votes always point down the seniority order, so votes can never form a cycle, and counting votes is exact. When an object's vote count hits zero, it is not freed at once. It is **suspended** and a **runoff** is held. Every object that would fall with it is tentatively removed. Then any *surviving* object that petitions a fallen one has its petition promoted to a vote, which revives that object and moves it to just below its new voter in the order. Whatever is left has no references from anything alive, so it is freed on the spot, deterministically, with destructors. The results: no leaks, including cycles; no dangling; no weak refs; no ownership; no annotations. The cost is that every heap store and every last-drop does political bookkeeping.

## 4. The rules (what a programmer learns)

1. Objects are referenced freely. While anything alive can reach an object, it stays alive. This includes cycles: parent/child, self-capturing closures and observer loops are all fine.
2. When the last path to an object (or to a group of objects) is cut, the group dies **at that statement**. Its `deinit`s run juniors-first. Every member's memory stays valid until all the group's `deinit`s have finished.
3. A `deinit` must not store `self`, or any member of its dying group, into a live object. That is resurrection, and it traps.
4. Threads: an object crossing a thread boundary must be `frozen` (deeply immutable) or live inside a `Shared` box (locked access). Only references within one thread's parliament, or to frozen objects, are free.
5. (Optional, diagnostic) `recall x` drops your reference and asserts that `x` died. In debug builds, a failed recall lists the **voters that vetoed**: who still reaches `x`, and through which field.

That is everything. Rules 1–3 are what a Python or Java programmer already believes, minus the GC. Ballot kinds and seniority never appear in source. The debugger shows them.

## 5. Under the hood

**Object header:** a vote count (32 bits), a seniority label (a node in an order-maintenance list, Dietz–Sleator/Bender style, giving O(1) compare and amortised O(1) insert), and the head of its petition roll.

**Reference field:** one word, tagged. Tag 0 means a vote: a direct pointer. Tag 1 means a petition: a pointer to a roll node `{target, prev, next, source}` linked into the target's roll. A load is a branch, plus an indirection if it's a petition.

**Store `src.f = dst`.** Clear the old ballot: a vote is decremented (possibly triggering a runoff); a petition is unlinked. Then:

- S1. If `rank(src) < rank(dst)`, it's a **vote**: increment.
- S2. Else, if `src` has no heap votes (it is held only by frames, e.g. inside its own constructor), move `src` to just before `dst` in the order, then vote. This is always legal, because lowering a node's rank can only break *incoming* edges, and it has none.
- S3. Else, run a two-way alternating search (Haeupler–Kavitha–Mathew–Sen–Tarjan style) with a small budget, say 64 steps. If one side completes without meeting the other, reorder that side and **vote**. If a cycle is found, or the budget runs out, it's a **petition**. Being wrong is safe: runoffs fix orientation later.

Locals and globals are votes from rank −∞. ARC-style elision of retain/release for borrowed parameters applies unchanged.

**Runoff, when `count(O)` becomes 0:**

1. *Suspend.* Cascade-decrement votes from O. S = every object whose count reaches 0. This is the same walk ARC does when it frees.
2. *Canvass.* For each member of S, scan its petition roll. Petitioners not in S are **live** and go on the worklist. Petitioners inside S are parked, keyed by source.
3. *Promote.* Pop a live petition P→Q. Turn it into a vote. Q, plus everything in S reachable from Q by votes, becomes R, the revived set. Remove R from S. Insert R into the order just after P, keeping R's relative order. For each vote from R to a target T outside the original S: if `rank(T) > rank(P)`, re-increment; otherwise **demote it to a petition**. T survived suspension without it, so no new zero can arise and no runoff nests. Parked petitions whose source is in R now go on the worklist.
4. *Free.* What remains of S gets no ballot from anything alive. Run `deinit`s juniors-first, unlink S's outgoing petitions, and free the memory.

**Invariants.** Votes respect seniority, so they form a DAG. Alive ⇔ count ≥ 1 ⇔ there is a vote path from a root. No petition ever targets a dead object, because petitions into S are either from S or get promoted. Each runoff processes S once, revivals only shrink S, and demotions never zero anything, so runoffs terminate. Cost per runoff is O(|S| + petitions into S + |R|).

**Frozen objects** can only reference objects that existed before they froze, so they are acyclic by construction. They skip the parliament and use plain atomic RC. **`Shared` boxes** each hold a separate parliament with its own order, and runoffs inside run under the box's lock. The box handle itself is atomic-RC.

**Debug builds** keep full vote rolls too, so "why is this alive?" is a one-click answer.

## 6. Scenarios (illustrative only — not a syntax decision)

**(a) File into a growing list.** The list is created first (senior), and each line is created later (junior), so every `add` is an S1 vote. There are no petitions, and the cost is ARC's.
```
lines = List()
for line in File.open(path).lines { lines.add(line) }
```

**(b) Tree with parent pointers.** `p.children.add(c)` is senior→junior, a vote. `c.parent = p` is junior→senior, a petition. If the code builds them in the "wrong" order (child first), the first runoff swaps the ballots in O(1), and the shape is learned after that.
```
class Node { parent: Node?  children = List() }
p = Node()
c = Node()
c.parent = p
p.children.add(c)
root.children.remove(p)   // whole subtree dies here, deinits run leaf-first
```

**(c) UI callback capturing self (the crux).** `self.save` is captured into the closure, a junior→senior store, so it becomes a petition. Storing the closure into `button.onTap` (button senior) is a vote. Closing the window drops editor's last vote. The runoff suspends editor, button and closure. The only petition into that set comes from the closure, which is inside it, so all three are freed. Nothing is weak and nothing leaks. And if the closure is ever kept alive elsewhere (say a timer stores it), the runoff revives the editor through the closure's petition, so it never dangles.
```
class Editor {
  button = Button("Save")
  init() { button.onTap = { self.save(); self.dirty = false } }
}
window.content = Editor()
window.content = nil      // editor + button + closure die here, deterministically
```

**(d) Shared cache used by two components.** Both components vote for it (S1 or S2 at construction). Entries pointing back at the cache are petitions. The cache dies when the second component drops it.
```
cache = Cache()
a = Search(cache)
b = Preview(cache)    // S2: new component re-ranked above cache, vote
```

**(e) Large list passed to a mutating function.** It is passed by reference with a borrowed parameter, so there is no count traffic. The function mutates in place. New elements are junior, so they are votes.
```
func normalise(xs: List) { for i in 0..xs.count { xs[i] = xs[i].trim() } }
normalise(lines)
```

**(f) Threads.**
```
cfg = freeze(loadConfig())          // acyclic, atomic RC, read by any thread
jobs = Shared(List())               // its own parliament under a lock
spawn { jobs.with { q in q.add(Job(cfg)) } }
```

## 7. What is new

- **Strength as a runtime political status.** The lineage is Brownbridge (1985) strong/weak pointer flipping and its corrected successors. That family is a real prior-art thread, notorious for subtle bugs. What's new here:
  - Orientation comes from a **global seniority order** maintained with an order-maintenance list and incremental topological ordering, instead of per-object parity bits.
  - The store path is **lazy and budgeted**: a wrong guess is a petition, never an error.
  - A runoff **re-ranks the revived set just after its new voter**. The rank test then decides which re-added votes must be demoted. Because demotions can't zero anything, nested runoffs can't happen. That is the termination argument the classic algorithms lacked.
- **No `weak` in the language at all,** and no ownership either. The rule set is shorter than O1's, since O1 still teaches "use weak to break cycles".
- **Veto diagnostics as a first-class tool.** `recall` and the voter-roll debugger turn "why is this leaking?" into "who voted for it?"

## 8. Less crazy than it sounds, or more

**Less crazy:**
- In common OO code, construction order already matches the ownership direction: parents make children, editors make buttons, closures are made after `self`. So most stores take S1 or S2, and most cycles are born with their back-edge already a petition. Runoffs in steady state are as cheap as ARC frees.
- Determinism and destructor timing match ARC, which is the property people actually like about ARC.
- The algorithms involved (order maintenance, incremental topological order, trial-style revival) are published and well understood individually.

**More crazy:**
- Correctness rests on a global invariant that every store, every runoff and every FFI boundary must preserve. The Brownbridge family's history shows how easy it is to get wrong. That is risky for a compiler written ~95% by an AI agent unless the invariant is model-checked (TLA+ or a randomized differential tester against a tracing oracle).
- Seniority is a single global structure per thread, which is hostile to concurrency. Hence rule 4.

## 9. Known weaknesses

1. **Runoff spikes.** The pattern "a big structure is held only by a local, and a newer object petitions its root" makes a runoff suspend and then revive the *whole* structure. Example: `doc` is older than `app`, then `w = Window(doc)`, then the local `doc` goes out of scope. S2/S3 usually prevent this, but not always. The cost is O(structure) at an innocent-looking statement. ARC has free-spikes; this has free-*or-revive* spikes, which is worse because nothing was freed.
2. **Store overhead.** Every heap reference store does a rank compare and possibly a budgeted search. Every load branches on the tag. My guess is 1.2–2× ARC's cost on pointer-heavy code; it is unmeasured.
3. **Memory overhead.** Each header carries an order-maintenance node. Each petition needs a 4-word roll node.
4. **Threads.** `Shared` handles are atomic-RC across parliaments. A `Shared` box that ends up (transitively) containing its own handle is a cross-parliament cycle and **leaks**. A debug detector can flag it, but that is a rule users must know about.
5. **Predictability.** Whether a given field is a vote or a petition depends on history. That's invisible in source and visible only in the debugger. Performance can shift when construction order changes.
6. **FFI.** C code holding object pointers must hold a root vote, via an explicit retain handle. Raw C pointers *into* the heap can't participate in runoffs, so they're unsafe in the usual C way.
7. **G2 interpretation.** A runoff is a walk over dying-plus-revived objects. If John reads that as "a GC run", the design fails the gate. I argue it doesn't, since there is no root scan, no pause on the live heap, and no background work.

**Self-assessment:** simplicity 5, safety 5, expressiveness 5, implementation risk 2, performance 2.5, concurrency 2.5, tooling 4, for **≈79**. It doesn't beat O1 on paper. It is the one design here where the user never learns `weak`, ownership or lifetimes, and still never leaks.
