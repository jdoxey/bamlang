# 20 — Amnesia

## 1. Name

**Amnesia**: a heap that is allowed to forget, at any moment, almost everything it holds.

## 2. The crazy premise: which sacred assumption it breaks

Malloc/free, tracing GC, RC, ownership, regions, arenas, generational refs: every scheme in history assumes the same thing.

> **Memory is storage. If you free something, it is gone, so you may free it only once nobody will read it again.**

That assumption is the whole reason memory management exists. Every scheme is just a way of approximating "nobody will read it again": reachability, counts, owners, scopes, generations. Cycles, weak refs, lifetimes and non-nesting sessions are all side effects of that approximation.

Amnesia drops it. **Most of the heap is a cache, not storage.** Any cached object can be freed at any time, while it is still referenced, because a reference to it is a *recipe*. Reading a forgotten object rebuilds it. Freeing that memory never needs a liveness question. There is no reachability, no counting, no ownership and no lifetime for it. Only a small, tree-shaped, reference-free core of the program, the **State**, is real storage. Because State is a tree of values, it is managed trivially.

Assumptions broken on purpose:
- Objects have a stable identity and address. Derived objects have neither; they are equal by recipe.
- Freeing is invisible to timing. It is not: a forgotten object costs a recompute.
- Closures capture objects. They capture *paths* instead.

## 3. Pitch

A program has two kinds of data. **State** is the irreducible stuff that cannot be recomputed: what the user typed, what came off the network, which windows are open. It is a tree of plain values, mutated only by event handlers, and it contains no references. **Derived** data is everything computed from State: view trees, indexes, parent links, graphs, caches, layout. You write derived data as ordinary pure functions marked `derive`. Their results may alias, share and form cycles freely, because the runtime treats them as a memo cache and evicts entries under a memory budget. Your code never notices except in timing. UI callbacks don't capture `self`; they capture the *path* to `self` in State, which is re-resolved when the tap fires. A shared cache is no longer a lifetime puzzle: it *is* a cache, and the language already has one. Determining liveness is unnecessary for the derived layer and trivial for the State layer.

## 4. The rules

1. **Everything is a value.** Locals, parameters, fields and list elements hold values. Assignment copies (the compiler moves on last use, so copies are rare). There is no reference type you can write.
2. **Each `world` has one `state`**, a tree of values. Only `on` handlers may change it. A world runs one handler at a time.
3. **Identity in State is a key.** A `Keyed` collection gives each element a stable key. Paths like `/editors[k7]` name things. Removing a key is how something "dies", which is how you express a lifetime that only you know.
4. **`derive` functions are pure and memoized.** They may read their arguments only, they do no IO, and they don't touch State except through their arguments. Their results are immutable and may be shared, aliased and cyclic.
5. **The runtime may forget any derived result between events and rebuild it on next use.** That is the whole memory model for derived data. Within one event, anything you've touched stays put.
6. **Storing into State copies.** If you put a derived value into State, it becomes a plain value (`keep` is implicit). State can never point into the cache.
7. **Closures capture paths, not objects.** Inside a method, `self` *is* a path. When a closure runs as an event, its path is re-resolved against current State. If the key is gone, the handler doesn't run, and an optional `else` branch runs instead.
8. **Threads are worlds.** Worlds exchange values by message. The derive cache is shared by all worlds; it is immutable, so sharing is safe.

Eight rules. Rules 1, 2 and 8 are near-universal value/actor rules. The new ideas are rules 4, 5 and 7.

## 5. Under the hood

**State layer.** A persistent value tree with acyclic reference counting and in-place reuse when unique, as in Koka/Perceus. Values can't form cycles (rule 1), so RC is complete and never needs a collector. Mutation in a handler is in-place when unshared. Each State node carries a version stamp, which is bumped on write and propagated up the path, so the cost is O(depth).

**Derive cache.** A derive call is keyed by `(function id, argument version stamps)`. On a hit it returns the entry. On a miss it runs the function and stores the result. Each **entry is its own arena**. The function's whole result graph, internal cycles and parent pointers included, lives in one bump-allocated block, so evicting an entry is one `free`. An entry holds structurally shared snapshots of its inputs (cheap RC bumps on State nodes), so it can always be rebuilt even after State has moved on.

**Cross-entry links are recall links**: `{key, cached ptr, entry generation}`. Dereferencing checks the generation, which is one compare on the fast path. On mismatch it looks the key up and recomputes if needed. A link never dangles, because the key plus the held input snapshot can always rebuild the target.

**Eviction.** The cache keeps an LRU list and a byte budget. Each entry has `lastEpoch`. Each world increments its epoch per event, and the global safe epoch is the minimum over running worlds (epoch-based reclamation). The evictor frees cold entries whose `lastEpoch` is below the safe epoch. Freeing is O(1) per entry. Nothing is traced, scanned or counted. Old-version entries are never looked up again and drift to the cold end. That is how "invalidation" happens: for free, by not being asked for.

**G2:** pass, I believe. There is no tracing run and no stop-the-world. Eviction is cache policy, like an LRU, with O(1) work per freed entry. **Flag needs-john**: an analyst may say a budget-driven evictor running between events "feels like a collector". It does not decide liveness, which is the point.

**G3:** pass. `derive`, `world`, `on` and `state` are keywords, not annotations. `Keyed` and `List` are compiler-known containers (pending question, flagged).

**Purity check.** The compiler verifies that `derive` bodies call only other `derive` or pure functions, do no IO, and don't touch State except via arguments. Purity is what makes eviction unobservable. A chaos mode (`test --amnesia`) evicts *everything* after every event, which mechanically tests that the program doesn't depend on cache residency.

## 6. Scenarios (illustrative only — not a syntax decision)

**(a) File of unknown length into a list of lines.** This is a local value, grown in place, moved out on return. No cache is involved.
```
fun readLines(path: String) -> List of String {
  lines = List of String
  for line in File.open(path).lines { lines.add(line) }   // unique buffer, grows in place
  return lines                                              // moved
}
on Open(path) { state.doc.lines = readLines(path) }         // becomes State
```

**(b) Tree with parent pointers.** In State, the tree is a value tree, and a node reached by path knows its parent path (a zipper), so `parent` is free. If you want a real pointer graph, derive it: parent pointers inside one entry are ordinary pointers in one arena.
```
type Node { name: String, kids: Keyed of Node
  fun rename(n: String) { name = n; parent.touch() }        // self is a path; parent = path minus last step
}
derive outline(root: Node) -> Outline {                    // cyclic graph with parent ptrs, one arena
  o = Outline.from(root)                                    // o.kids[i].parent == o, real pointers
  return o
}
```

**(c) UI callback that calls `self.save()` and mutates the editor (the crux).** The view is derived; the closure captures the path `/editors[k7]`, not the editor.
```
type Editor { text: String, dirty: Bool
  fun save() { File.write(path, text); dirty = false }
  derive view() -> View {
    return Column {
      TextField(text, onChange: { t in text = t; dirty = true })
      Button("Save", onTap: { save() } else: { log("editor closed") })
    }
  }
}
on CloseEditor(k) { state.editors.remove(k) }               // the lifetime you know, said once
```
If the window closes first, the tap resolves `/editors[k7]`, finds nothing, and runs `else`. Nothing leaks and nothing dangles. A cycle can't exist either, because the closure holds a path, not a pointer.

**(d) Shared mutable cache used by two components.** A pure cache needs no code at all: both components call the same `derive`, and the memo table is shared.
```
derive thumbnail(img: Image, size: Int) -> Bitmap { ... }   // components A and B share it automatically
```
Mutable shared data (for example, both can invalidate or put) lives in State at a common ancestor. Both components hold its path, and handlers serialize access.
```
state { users: Keyed of User, panelA: PanelA, panelB: PanelB }
type PanelA { fun refresh(id) { root.users[id].stale = true } }   // root = world State path
```

**(e) Passing a large list to a function that mutates it.** It's a value, so the function takes it `inout`. It's unique, so the mutation is in place.
```
fun dedupe(xs: inout List of Int) { ... }
on Clean { dedupe(&state.samples) }                          // no copy: unique, mutated in place
```

**(f) Sharing data between threads.**
```
world Indexer { state { idx: Index }
  on Add(doc: Doc) { state.idx.insert(doc) } }               // Doc arrives as a value (moved)
spawn Indexer
indexer.send(Add(doc))
derive tokenize(d: Doc) -> Tokens { ... }                   // cache shared by all worlds, read-only
parallel for chunk in state.samples.chunks(1000) { score(chunk) }  // fork-join over a frozen borrow
```

## 7. What is new

- **Freeing without liveness.** Every scheme in the brief answers "is this still needed?" Amnesia's derived layer never asks. Safety comes from *rebuildability*, not from reachability. As far as I know, no general-purpose language uses incremental-computation machinery (Salsa, Adapton, React memo) *as its heap manager*.
- **Cycles become harmless by construction**, not by detection. They can exist only inside one derived entry, which is one arena and is freed whole, or across entries via recall links, which never pin anything.
- **Closures capture paths, and a dead path has defined semantics** (`else`). Round 1 had "callbacks become no-ops when captures die". The mechanism here is different: there is no capture-death tracking at all, just path resolution against current State, and the `else` branch is first-class.
- **Parent pointers are free in both layers**: zipper paths in State, intra-arena pointers in Derived.
- **A built-in, mechanically testable invariant** (`--amnesia` chaos mode) instead of lifetime reasoning.

## 8. Why it might be less crazy than it sounds, or more

**Less crazy.** UI frameworks already work this way. React, Elm, SwiftUI and Compose all treat the view tree as disposable output recomputed from a model, and their callbacks really are "messages to the model". Compilers built on Salsa (rust-analyzer) already run on an evictable memo database. Persistent values with RC and in-place reuse are proven (Koka, Lean 4). Amnesia makes the architecture good apps already use the *only* architecture, and lets the memory model fall out of it.

**More crazy.** Every program must be split into irreducible State and pure derivations. CLI tools, servers and simulations don't naturally think that way. A game whose entities target each other has a mutable cyclic graph *in State*, and Amnesia forces that into keys, which is O2's "handles for graphs" in a new coat. Recomputation also makes latency depend on cache pressure, so the same code is fast or slow depending on the budget.

**Self-assessment against the rubric** (rough): simplicity 3, safety 5, expressiveness 3.5, implementation risk 2, performance 2.5, concurrency 4, tooling/FFI 3, for a total of roughly **64**. That is competitive with round 1, not with O1 or O4. Its ceiling is the safety and cycle story. Its floor is the runtime engine.

## 9. Known weaknesses

1. **Recompute latency is unpredictable.** If an expensive derivation is evicted under pressure, the next frame stutters. Mitigations: budgets, pin hints, cost-aware LRU. But pin hints creep toward annotations (G3).
2. **Purity is viral.** Anything used in `derive` must be pure. Logging inside a derivation, randomness and timers all need escape rules. Each escape erodes rule 5's "you never notice".
3. **No IO in derive** means that file contents, network results and clock reads must first be stored in State. That is correct but adds handler ceremony, and large blobs in State are never evicted.
4. **Identity-less derived objects.** You can't compare two derived nodes by identity, and you can't hold one across events. Code that wants a long-lived handle must use a State key.
5. **Version-stamp and key overhead.** Every derive call hashes its argument stamps, and every State write propagates stamps up the tree. For fine-grained derivations (per list element) this can dominate.
6. **Granularity is a design skill.** If a `derive` is too coarse, everything recomputes; if it's too fine, the cache thrashes on bookkeeping. This is a new thing to learn, though it is not counted as a "rule".
7. **Implementation risk is high.** It needs an incremental-computation runtime (versioning, memo table, epochs, recall links, a concurrent cache) plus a purity checker plus persistent RC values with reuse analysis. This is much more than O1 for an AI-written compiler.
8. **C FFI.** Pointers into derived arenas are only stable within one event. Passing them to C code that retains them needs an explicit copy-out, a new escape hatch.
9. **Genuinely cyclic mutable State** (social graphs, entity systems, doubly linked lists you mutate) gets no help. It uses keys, and dangling keys become `else`/`none` checks the programmer must write.
10. **Debugging surprise.** "Why did my breakpoint in `view()` hit twice?" is because it was evicted and rebuilt. Tooling must show cache hits, evictions and rebuild reasons, or this will confuse people.
