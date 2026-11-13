# 13 — The Heap Plan: closed-world outlives-pruning with group backstop

## 1. Name

**The Heap Plan.** The compiler looks at the whole program at once and works out how each class's memory is handled ("outlives-pruning"). Whatever it can't sort out falls back to reference-counted groups.

## 2. Inspiration — how the lens maps onto memory

Whole-program compilers and static schedulers share one idea: if you can see everything, you can decide things ahead of time that would otherwise need a runtime referee. A static timetable replaces a run-time scheduler. Closed-world class-hierarchy analysis replaces dynamic dispatch. Link-time optimisation replaces cross-module guessing.

Mapped onto memory:

- **The closed world fixes the heap's shape.** Only a closed world can enumerate every class, every closure literal and every field store. So the compiler can build the complete *heap type graph*: "a field (or element, or closure capture) of type S can point to a T". Under separate compilation that graph is never complete, because a later module can always add an edge. Here it is exact.
- **Type-graph cycles are the only place memory cycles can happen.** If a class is not in any strongly connected component (SCC) of the graph, its instances can't take part in a reference cycle. Plain RC for those classes is complete, with no weak refs and no collector.
- **Abstract interpretation can delete edges.** Sometimes the target of an edge provably outlives its source in the heap: an immortal app object, or an editor that dominates every path to its button's closure. That edge needs no count and creates no cycle. Delete it from the graph, recompute the SCCs, and most "cycles" disappear.
- **The leftover SCCs get a collector-free backstop.** Objects of those classes live in *groups*, reference-counted as a unit (group RC). Groups merge on link and are freed whole.
- **The output is a timetable.** The compiler publishes a *heap plan*, a per-class table saying how each class is managed and why. CI diffs it like a static schedule.

## 3. Pitch

You write code as if the language had a garbage collector. Objects are shared references, there is no `weak`, no lifetimes, no borrow rules and no `free`. But no collector ever runs. The compiler sees the entire program, including dependencies, which are just source repos (G7). It builds the program's heap type graph and uses abstract interpretation to prove "this target always outlives this source" for as many edges as it can. Proven edges become raw, uncounted pointers, and the remaining graph is split into SCCs.

- Classes outside every SCC get exact, deterministic RC. Whole-program uniqueness and escape analysis remove most of the counts, and counts are made atomic only for types that provably cross threads.
- Classes still inside an SCC ("knots") put their instances into **groups**. Linking two knot objects merges their groups (union-find). Links inside a group are uncounted, and a group carries one external count. When that count hits zero the group's member list is freed in one deterministic sweep.

The language contract is that an object is freed after it becomes unreachable and no later than its group's death. Better analysis only moves frees earlier and never changes the meaning of a program. The plan is a build artefact you can read, query (`lang plan Editor`) and diff in CI.

## 4. The rules (everything a programmer must learn)

1. **Values and references.** Numbers, bools and (immutable) strings are copied. Everything else (class instances, `List`, `Map`, closures) is a reference: assigning or passing it shares it.
2. **Nothing is freed while it can still be reached.** There is no `free`, no `weak` and no lifetime syntax. A callback stored somewhere keeps whatever it captures alive, just like any other reference.
3. **When it is freed:**
   - If the heap plan marks a class *exact*, each instance is freed the moment its last reference goes.
   - Otherwise the class is *grouped*. Linking grouped objects merges their groups, and a group is freed as a whole no later than the moment nothing outside it refers into it. Removing a link inside a group does not by itself free anything.
   - `lang plan` tells you which case applies to a class and why.
4. **`deinit` cannot make `self` reachable again** (compile error). In grouped classes, `deinit` runs in unspecified order, somewhere between "unreachable" and the group's death. Use an explicit `close()` for prompt resource release. The compiler warns when a class with a `deinit` ends up grouped.
5. **Threads.** A value handed to another thread is copied unless it is either:
   - `frozen`: deeply read-only, and shared; or
   - `Locked`: its contents can only be touched inside `with`.

   When the sender never uses the value again, the compiler turns the copy into a move.

That's all. Rules 2–4 are the whole memory model. Rule 3's second bullet is the one new idea, and the plan tool makes it concrete for every class.

## 5. Under the hood

**Pipeline.** The compiler is whole-program only, and that includes the stdlib and dependencies. It emits one LLVM module.

1. Closed-world call graph: class-hierarchy analysis plus rapid type analysis, and closure-flow analysis (0-CFA). This finds which closure literals can reach which function-typed fields.
2. **Heap type graph** H. Nodes are concrete classes, closure-environment types (one per closure literal) and container instantiations. Edges come from fields, container elements and captures.
3. **Outlives proofs.** For each edge `S.f -> T`, try to prove that whenever `s.f == t` holds, t outlives s *in the heap*. The proof uses a small set of rules:
   - **(i) Immortal.** Every allocation site of T runs at most once and its result is held by a binding that lives until exit (a global, or a never-reassigned `main` local). Example: the `App`.
   - **(ii) Dominator.** Every heap path to s passes through t, so t dominates s. Example: a closure stored only in fields of objects that t itself confines.
   - **(iii) Pinned by a dominator.** Some d dominates s and holds t in a *write-once* field, meaning one the whole-program analysis sees assigned only in d's constructor.

   The proofs run as an abstract interpretation over allocation sites, using owner-relative contexts ("allocated while `self` = t, stored only into objects confined to t").
4. **Prune** every proven edge, then run Tarjan's SCC algorithm on what remains. Classes outside all SCCs are *exact*; classes inside an SCC are *grouped*, with one knot per SCC.
5. **Choose a representation for each store:**
   - *Pruned edge*: a raw pointer store with no count.
   - *Exact edge*: increment the new value, decrement the old. Uniqueness, borrow and last-use inference across the whole call graph removes most of these.
   - *Knot-internal edge* (source and target in the same knot): compare the two objects' groups and union them if they differ. The new external count is `P.ext + Q.ext`. No per-object counts. This is safe because a knot-internal reference can never exist *between* two different groups: making one triggers a merge.
   - *Edge into a group from outside* (another knot, an exact object, the stack, or a global): increment or decrement the group's external count.
6. **Group freeing.** Each group owns a list of allocation chunks and keeps its union-find representative (the group's canonical id). When `ext` reaches 0 the runtime runs every member's `deinit`, releases the members' outgoing *counted* references and then frees the chunks. This is a sweep over a member list, not a reachability trace: the same work as dropping a big RC tree.
7. **Pinning, so stack references stay safe.** A pruned edge is proven only for the heap. When a local (or argument) holds s and the analysis can't show that s's outlives-chain stays alive for the local's live range, the compiler inserts `pin`/`unpin`. These increment and decrement the chain of pruned targets; a generated function walks the chain.
   - Pins are almost always removed. A method's receiver chain is pinned already, a loop over `self.children` needs none, and a whole-program "may-release" effect analysis covers the rest.
   - Calling a closure pins its pruned captures for the duration of the call.
8. **Profile-guided extras.**
   - Profile runs and the built-in test runs (G10) record which allocation sites end up merged into which groups, so the next build allocates them directly into the right group's chunk. This makes groups behave like arenas.
   - The same runs record retention: members that are dead but still held by a live group. These are reported as "group churn".
   - Optional *tick arenas*: temporaries that the analysis proves never escape one pass of the event loop (one "tick") are bump-allocated and reset each tick.
9. **Atomicity.** A thread-escape analysis marks only types reachable from `spawn` captures, `frozen` or `Locked` as needing atomic counts.
   - Groups inside a `Locked` are merged only under its lock.
   - `frozen` groups never merge again, so for them only the external count needs to be atomic.
10. **Artefacts and tooling.**
    - `plan.txt`: the class, its tier, the edges that were pruned and which proof rule pruned each, and the reason the class is grouped if it is.
    - `lang plan --diff`, for CI.
    - **Proof-audit mode** for debug and test builds: every pruned edge is compiled as a generation-checked reference (a reference that records the generation of the object it points to and checks it on use). If a proof was unsound, a test traps instead of causing a use-after-free.
11. **Spec-level bound.** The spec defines "grouped" using the *unpruned* declared type graph, which is a worst case. A real compiler prunes more, so its groups are subsets of the spec's groups. Counted references between groups still form a DAG, so anything the spec would free is freed no later. Compiler improvements stay compatible with the spec.

## 6. Scenarios

**(a) Reading lines into a growing list**
```
// illustrative only — not a syntax decision
func readLines(path: String) -> List<String> {
    lines = List<String>()
    f = open(path)
    while line = f.readLine() { lines.append(line) }
    return lines            // f freed here: exact tier, deterministic close
}
```
`List<String>` and `File` aren't in any SCC, so both are exact. Uniqueness analysis sees that `lines` is never aliased, so it runs with zero counting and is returned by move. Growth is an ordinary reallocation.

**(b) Tree with parent pointers**
```
// illustrative only — not a syntax decision
class Node {
    name: String
    parent: Node?
    children = List<Node>()
    func add(c: Node) { children.append(c); c.parent = self }
    func remove(c: Node) { children.remove(c); c.parent = nil }
}
```
The type graph has the loop `Node.children -> Node.parent -> Node`. If every heap store of a `Node` goes into some `children` list (or into `Tree.root`), rule (ii) holds: the parent dominates the child. `Node.parent` is pruned, and `Node` becomes **exact**. Removing a subtree frees it immediately, and `n = tree.root.children[0]` held across `tree = nil` gets a pin.

If some other object stores a node too, say `Selection.current = n`, the proof fails and `plan.txt` says so: "Node.parent not pruned: Selection.current (sel.lang:12) stores a Node outside any children list". `Node` then becomes **grouped**, and the whole tree is one group, kept alive while the tree or the selection refers to it. That is correct and leak-free, but removed nodes are retained until the whole tree dies.

**(c) UI callback capturing `self` (the crux)**
```
// illustrative only — not a syntax decision
class Editor {
    doc: Document
    saveButton = Button("Save", onTap: { self.save(); self.dirty = false })
    func save() { ... }
}
class Window {
    editor = Editor()                  // write-once field
    view = Column(editor.saveButton, ...)
}
```
- **The loop:** `Editor -> Button -> closure env -> Editor`.
- **Why the edge can be pruned:** the closure is stored only in `Button.onTap`. Every heap path to the button comes from the `Window`, through both `editor.saveButton` and `view`, and the window holds the editor in a write-once field. So rule (iii) proves that the editor outlives the closure, and `capture self` is pruned.
- **Result:** every class here is **exact**. Closing the window frees window, editor, buttons and closures at once, deterministically.
- **The tap itself:** a tap pins `self` for the duration of the call, so `self.save()` is safe even if the handler closes the window halfway through.
- **The app:** a capture of `app` in any handler is pruned by rule (i), since the app is immortal.
- **Registering elsewhere:** if the editor also registers `{ self.save() }` with a long-lived `bus`, that closure isn't confined, so Editor + closure become a group. The bus keeps that group alive until the handler is unsubscribed. These are the semantics of a GC language, with no `[weak self]` anywhere.

**(d) Shared mutable cache**
```
// illustrative only — not a syntax decision
class Cache { entries = Map<String, Image>(); func put(k, v) {...}; func get(k) -> Image? {...} }
cache = Cache()
gallery = Gallery(cache)
thumbs  = Thumbnailer(cache)
```
`Cache` and `Image` are exact, so the cache is freed when both components drop it. Here it is created once in `main`, so it is immortal and has zero counts.

Now give entries an `onEvict` closure that captures the `Gallery`. That gives the loop `Gallery -> Cache -> closure -> Gallery`. The proof fails because the cache is shared and not dominated, so `{Gallery, Cache}` become one group. Evicted `Image`s, which are exact, are still freed immediately. Evicted closure environments stay until the group dies, and the plan's churn report flags this.

**(e) Mutating a large list in a function**
```
// illustrative only — not a syntax decision
func normalize(xs: List<Float>) { m = xs.max(); for i in 0..xs.count { xs[i] = xs[i] / m } }
scores = loadScores()     // 10M floats
normalize(scores)         // in place, caller sees the change
```
This is plain reference semantics with no copy, and no exclusivity or inout rule to learn. Whole-program analysis sees that `normalize` never stores `xs`, so the call does no inc/dec.

**(f) Sharing between threads**
```
// illustrative only — not a syntax decision
results = Locked(List<String>())
config  = frozen loadConfig()
for p in paths {
    spawn { lines = readLines(p); with results as r { r.appendAll(lines) } }
}
big = makeBigList()
spawn { crunch(big) }     // a move: big is never used again in this thread
```
`p` is copied (it's a string). `results` and `config` are shared, and their counts are atomic only because the escape analysis put them there. If `big` were used again after the `spawn`, it would be copied, which is a visible, predictable cost. Data races can't be written: mutable data only crosses threads by copy, move or `Locked`.

## 7. What's genuinely new vs. the covered options

- **Weak references are decided by the compiler, with proofs.** O1 makes the programmer choose `weak`. Here, an edge whose target provably outlives its source *in the closed-world heap* is turned into a raw pointer, made safe for stack references by pins. If the proof fails the code gets safe but slower handling, never a UAF and never a leak. This differs from the brief's "fragile inference": failure only moves an object to the group tier, and the plan explains why.
- **Groups are a cycle backstop with no collector.** They merge on link and are counted as a unit. O7 needs a cycle collector. Region inference and scope-bound regions are tied to lexical scope and need `promote`. Arenas are manual. Groups are dynamic, implicit and keyed to type-graph SCCs, and freeing one is a sweep, not a trace.
- **The contract is "unreachable ≤ free ≤ group death".** The language promises a bound that is fixed by the spec (§5.11), and optimisation can only move frees earlier. So the compiler can get smarter without breaking programs.
- **The memory plan is a build artefact.** It's a per-class timetable of how memory is managed, with `--diff` for CI, the static-schedule idea applied to memory. **Proof-audit mode** turns the test suite (G10) into evidence that the pruning proofs are sound.
- **Immortality inference and PGO-placed group chunks** are whole-program-only tricks: the profile tells the compiler which group an object will join, so it allocates it there from the start.

## 8. Known weaknesses

- **Distant edits change behaviour.** A store added in module X can stop a proof about module Y's class, moving it from exact to grouped and changing peak memory and `deinit` timing. `plan --diff` in CI catches this, but it is still action at a distance.
- **Groups never shrink.** A long-lived group with churn (a document model, an editor's panels, the (d) eviction case) keeps dead members until it dies. The programmer's only lever is restructuring (IDs, slot maps, confining stores), guided by the churn report. A future "split on remove" for knots proven to be tree-shaped would need a walk of the detached subtree. That is bounded and synchronous, but closer to tracing, so treat it as a G2 risk.
- **The proof engine is the risk.** The confinement and write-once abstract interpretation is the hardest component for an AI-written compiler. An unsound proof is a use-after-free in release builds, so proof-audit mode is mandatory in tests, and the fallback being safe only helps a *sound* weak analyzer.
- **Pin chains.** A local that the analysis can't clear needs an O(chain-depth) pin, for example a deep tree node held across code that might release the tree. That's a performance cliff, and it shows up only in profiles.
- **Only whole-program builds.** There are no precompiled libraries of this language, no plugins and no `dlopen` of code written in it. Builds get slower as programs grow; summaries cached per module and SCCs recomputed at link time help. Objects handed to C must be pinned, and C holds them as opaque handles.
- **Runtime costs.** Each grouped object carries a group pointer, and each knot-internal store does a union-find lookup.
- **Gates.**
  - G2: arguably passes, since freeing a group is a sweep of its member list, not a reachability trace.
  - G3: depends on built-in `List`, `Map`, `Locked` and `frozen` (flag).
  - Rule 3's two tiers are the conceptual price, and learners will lean on `lang plan` to answer "when does this die?".
