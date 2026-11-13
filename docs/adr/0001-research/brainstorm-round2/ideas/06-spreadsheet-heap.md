# 06 — Spreadsheet Heap (recompute instead of store)

## 1. Name

**Spreadsheet Heap.** RAM is the calculation cache of a spreadsheet. The program's real
contents are a small set of input cells (state) plus the formulas (functions) that
derive everything else. Any derived object may vanish at any time and comes back when
someone asks for it.

## 2. The crazy premise

Sacred assumption broken: **"a value you hold a reference to exists in memory."**

In this model a reference is not an address. It is the *recipe* that produced the value:
function id + argument keys. The heap is a budgeted hash table of recipe results, and the
runtime may evict any unpinned entry at any moment. Dereferencing an evicted key
recomputes it. Nothing is ever freed by the programmer, nothing dangles, and nothing can
form a cycle, because **heap entries contain no pointers to other heap entries, only keys.**

Two more assumptions fall. Destroying an argument becomes always legal, because the
original can be recomputed. And mutable state lives as long as the recipe that declared
it is still *re-derived* from the program root: hooks (React/Compose `remember`) applied
to *all* program state.

Gates bent: **timing determinism** is given up, since eviction depends on memory
pressure. Values stay deterministic because recipes are pure. I claim **G2** passes (no
tracing, no inter-object RC, eviction is cache replacement), but flag it **needs-john**
because a background replacement policy may feel GC-like.

## 3. Pitch

You write pure functions (`fn`) and a few event handlers (`act`). A `fn` result is cached
under its recipe key and may be thrown away at any time. Mutable data lives only in
`state` slots inside *parts* (components). A part's state lives while the latest
evaluation of the root still produces the part, as when a view leaves a UI tree. The
same rule covers servers (a session lives while its connection exists) and CLIs. There is
no `free`, `weak`, `borrow`, `Rc` or lifetime. A closure is code plus captured keys, so an
`onTap` capturing `self` can't form a retain cycle: nothing retains anything. The worst
case is a slow program that recomputes too much. Derived data can't dangle or leak, and
its RAM has a hard cap set by the budget.

## 4. The rules (everything a programmer must learn)

1. **Two kinds of function.** `fn` is pure: no I/O and no state writes. It may *read*
   state. `act` may do I/O and write state. (These are keywords for function kinds, like
   `async`, not annotations.)
2. **`fn` results are cached formulas.** Any value a `fn` returns may be evicted and
   recomputed later. You never free values.
3. **A reference is a recipe.** Holding a value keeps nothing alive and never dangles.
   Within one *moment* (one act, or one settle; see rule 7) a reference always gives the
   same value.
4. **Across moments, a reference is live, like a spreadsheet cell.** If the state it was
   derived from changed, it yields the new value. To freeze a value, store it into a
   `state` slot. That copies it, and the slot owns the copy.
5. **Arguments may be scribbled on.** A callee may mutate an argument in place. Other
   holders silently get a recomputed original. Inside a function body, locals are ordinary
   mutable values, freed at scope exit or sealed into the cache on return.
6. **Mutable data lives only in `state` slots inside a `part`.** A part's state is
   identified by (parent part, position or explicit `key`, slot name).
7. **State lives while it is re-derived.** Acts on a root run one at a time. After each
   act, the root *settles*: dirty formulas re-run. Any part that is no longer produced
   is dropped together with its state.
8. **Closures capture by key.** A closure is code plus captured keys. An `act` closure
   that targets dropped state does nothing and returns `gone`.
9. **Outside data are facts.** Results of I/O can't be recomputed, so they are never
   evicted. They live where you put them: a local (freed at scope exit) or a `state` slot.
10. **Threads.** Pure `fn`s run on any thread, and keys can be sent anywhere. State
    belongs to one root. Other threads change it only by sending it an `act`.

Ten rules. Rules 1, 6 and 7 are new to most people. The others mostly *remove* concepts.

## 5. Under the hood

**Value cache.** A concurrent table maps a 128-bit recipe hash (fn id + argument keys) to
an entry. Each entry holds the result bytes, its size, its measured recompute cost, and
its dependency set. Interior references in an entry are keys, never addresses, so an
entry can be dropped in O(1) without touching any other entry. Eviction is cost-aware
(GreedyDual-Size style): it evicts the entry with the lowest `recompute_cost / bytes`
first. Eviction is triggered by the byte budget, is incremental, and needs no liveness
information.

**Pinning and fast path.** A frame reading an entry pins it until frame exit
(stack-scoped and deterministic), and eviction skips pinned entries. That makes raw
pointers safe within the frame, including for non-retaining C calls. A key carries a hint
pointer plus a generation: a match is a direct load, otherwise a hash lookup, and on a
miss, a recompute.

**Validity.** This is Salsa/Adapton-style incremental computation. Each entry records the
(state slot, version) pairs it read. On read, a red-green check re-validates the entry
against current versions. That check is what gives rule 4 its spreadsheet semantics. An
act runs against a pinned snapshot of state versions (MVCC). An old version is freed
when the last act or settle using it ends, so there are at most a handful of versions.

**Settle and claim sets.** Each part instance records the state identities it *claimed*
during evaluation. A memo hit re-claims its recorded set without running. After an act,
only dirty subtrees re-evaluate. The runtime diffs their old and new claim sets, then
destroys the slots that weren't re-claimed, together with their owned values. Work is
proportional to what changed, not to heap size. This is no heap trace. It is a diff over
the creation sites of a small number of state slots.

**State storage.** A slot exclusively owns a plain value tree (copied in; the copy is
elided for unique temporaries). The tree may contain keys (formulas) and identities of
other parts (epoch-checked). It never contains addresses.

**Destructive update (rule 5).** If a callee mutates argument `xs` in place, the runtime
marks `xs`'s entry invalid. The next reader recomputes it. Facts (rule 9) can't be
recomputed: they're mutated in place only on their last use, and copied otherwise.

## 6. Scenarios (illustrative only — not a syntax decision)

**(a) File into a growing list of lines**
```
act main() {
  text = read("in.txt")            // fact: a local, freed at scope exit
  lines = []                       // workbench local: mutable, in place
  for l in text.split("\n") { lines.add(l) }
  print(longest(lines))            // fn longest: result cached, evictable
}
```

**(b) Tree with parent pointers.** A derived tree has no stored parent pointers, because
a parent is just another recipe:
```
fn outline(doc) = parse(doc.text)                 // cached formula
fn node(t, path) = t.at(path)                     // key = (t, path)
fn parent(t, path) = node(t, path.dropLast())     // no cycle: keys, not pointers
```
An editable tree lives in state as a value tree with ids: `state nodes = Map()` holding
`{id, parentId, children}`. A parent is an id lookup inside the slot's own value.

**(c) UI callback capturing self (the crux)**
```
part Editor(docId) {
  state text = ""
  state dirty = false
  view = Column {
    TextField(text, onChange: act(t) { text = t; dirty = true })
    Button("Save", onTap: act { self.save() })   // closure = code + key(self)
  }
  act save() { write(docId, text); dirty = false }
}
part App {
  state open = []
  view = Tabs(for id in open { Editor(id) key id })
}
```
Closing a tab removes `id` from `open`. At settle, `Editor(id)` is no longer produced, so
its `text` and `dirty` are dropped. A tap still queued against it returns `gone`. No
cycle is possible, because the Button entry holds a key and the Editor's view holds keys.

**(d) Shared mutable cache used by two components.** A pure shared cache is free: the
memo table *is* the cache.
```
fn thumb(img) = resize(decode(img), 128)   // both components call it; one entry
```
A mutable cache is state in a common ancestor, and both components receive its identity:
```
part Session { state users = Map()
  act remember(u) { users[u.id] = u } }
part Main { s = Session() key "s"
  view = Row { Roster(s)  Chat(s) } }       // both read s.users, write via s.remember
```

**(e) Large list passed to a mutating function**
```
fn cleaned(rows) { rows.sortInPlace(); rows.dedupeInPlace(); return rows }
c = cleaned(table(csv))   // scribbles on table(csv)'s buffer: zero copy
n = count(table(csv))     // table(csv)'s entry was invalidated, so it is recomputed
```
If `rows` is a fact, it's done in place on its last use and copied otherwise.

**(f) Sharing between threads**
```
act refresh() {
  stats = parallel(files, fn(f) = summarize(lines(f)))  // pure, any thread, shared cache
  totals = merge(totals, stats)                          // state write in the root's act
}
worker.send(app, act { app.refresh() })                  // other threads send acts
```
Data races are impossible: only acts write, and acts on a root are serialized.

## 7. What is new

- **Pointer-free heap entries.** References are recipe keys, so freeing any object is
  always safe and O(1), and cycles can't exist in memory.
- **Eviction is the memory model**, not an optimization. Derived data has a hard RAM
  budget and can't leak.
- **Destroying an input is always legal.** In-place mutation needs no uniqueness proof,
  borrow checker or `inout`. The price is possible recompute.
- **State lifetime = "still re-derived from the root"**, for all programs, implemented as
  a claim-set diff over dirty subtrees rather than a heap trace.
- **Spreadsheet reference semantics:** stable within a moment, live across moments.

## 8. Less crazy than it sounds, or more?

**Less.** Every piece already ships somewhere: Salsa/Adapton (memoized dependency-tracked
recompute), Spark RDD lineage, Bazel's action cache, and React/Compose/SwiftUI (state
lifetime tied to tree position). Spreadsheets have run on this model for 40 years and are
used by non-programmers. For declarative UI (G11) it is close to the *native* model: the
view tree already is a formula over state.

**More.** The `fn`/`act` split is an effect system. It is light (two keywords), but a
Python user will hit "can't print from a fn" on day one. A cache policy trades GC pauses
for *recompute storms* under memory pressure. Every access through a key costs a
generation check, so pointer-heavy code is slower than ARC. And rule 4 means reading `x`
in two different acts can give two different values.

## 9. Known weaknesses

1. **Unpredictable performance.** Recompute cost is unbounded: evicted or scribbled
   inputs can cascade back to a slow formula. A "keep" hint would help, but it risks
   becoming an annotation (G3).
2. **The claim-set rule is reachability in disguise**, restricted to state. A part that
   is always rendered is a state leak. Only the *derived* leak class is gone.
3. **Everything needs a root.** CLIs run as one long act. Libraries must think in parts
   plus formulas.
4. **FFI.** C pointers into entries are valid only while the frame pins them. A C library
   that retains a pointer forces a copy into a fact. C handles are facts in state.
5. **Mutable graphs in state fall back to ids/handles**, as in O2. Only *derived* graphs
   become trivial.
6. **State concurrency is actor-style.** A long act blocks its root. Shared-memory
   parallelism is for pure work only.
7. **High implementation risk.** It needs a concurrent memo table, red-green validation,
   MVCC snapshots, claim-set reconciliation and a cost-aware evictor. That is a large
   runtime for an AI-written compiler. One impure call slipping into a `fn` breaks
   everything, so purity must be strictly enforced.
8. **Debugging.** "Why did this recompute?" needs a lineage viewer and recompute tracing.
   In exchange, lineage makes time-travel debugging nearly free.

**Self-assessment:** Simplicity 3, Safety 5, Expressiveness 4, Impl risk 2, Perf 2,
Concurrency 4, Tooling/FFI 2. That gives **≈64/100**. It is strongest on (c) and (d) and
on hard memory safety. It is weakest on predictability and runtime size.
