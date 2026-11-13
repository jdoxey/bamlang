# 13 — Slow Match

## 1. Name

**Slow Match.** A slow match is the slow-burning cord gunners used to fire cannon. Every heap object in this language burns on one.

## 2. The crazy premise

**Sacred assumption broken: "an object lives as long as something refers to it (or owns it)."**

In Slow Match, references never keep anything alive. Not strong refs, not weak refs, not owning refs. Every object dies **on schedule**. The schedule is its *fuse*: a trigger given at birth, such as "when this scope exits", "after 5 minutes without use", "after 1 use", "when the window closes" or "when that other object burns". The only way to stay alive is to be renewed: by being used, by an explicit `relight`, or by hanging your fuse off something that is itself being renewed.

Consequences, stated up front:
- **Leaks are impossible by construction.** Every object has a finite trigger. Even the app root is a fuse that the event loop relights every turn, and it goes out when the loop stops.
- **Premature death is possible, but it is safe and diagnosable.** Touching a burnt object *fizzles* (a defined, catchable error), and the error carries the fuse's history.
- **Memory is a cache.** Under memory pressure the runtime may burn idle-fused objects early, least recently used first. A program is correct only if it tolerates that wherever it chose an idle fuse.

**Gates and assumptions broken:**
- **Determinism of death time.** Breaks it for wall-clock idle fuses and pressure eviction. Beat-counted fuses and test mode stay deterministic (see 5).
- **"A live reference implies a live object."** Breaks it outright. Every deref can fizzle.
- **G2 and G3.** Kept: no tracing, no counting, no annotations.

## 3. Pitch

Programmers know lifetimes in terms of *events and time*, not reference graphs. "Lives until the window closes." "Cached for ten minutes." "Fires once." "Belongs to this tree node." Every automatic scheme reverse-engineers those lifetimes from who-points-at-whom, gets cycles wrong, and leaks. Slow Match lets you state the lifetime directly as a fuse. The runtime keeps the fuses in a **forest**: each object hangs off exactly one parent fuse or one root trigger, and burning a node burns its subtree. A pointer is just an address plus a generation. Copying one costs nothing, there is no refcount traffic, and cycles of pointers are meaningless because pointers don't hold anything. The UI callback problem dissolves. The closure, the button and the editor all hang off the window's fuse, so they burn together when it closes. Whether they point at each other in a cycle is irrelevant.

## 4. The rules (everything a programmer must learn)

1. **Values vs objects.** Numbers, structs and strings are values, copied (strings copy-on-write). Instances of classes, `List` and `Map` are objects. They live on the heap and each has exactly one fuse.
2. **References never keep anything alive.** You may copy, store, capture and pass them freely.
3. **Default fuse = scope.** A new object burns when the scope that created it exits…
4. **…unless it escapes:**
   - *Returning* it moves its fuse to the caller's scope.
   - *Storing* it into a field, a container, a closure capture or an outer local **anchors** it to that holder, so it burns when the holder burns.
   - Only scope-fused objects are auto-anchored. Storing an already-anchored object somewhere else does not change its fuse.
5. **Explicit fuses.** `keep x <fuse>` replaces x's fuse with one of:
   - `for 5m` / `for 300 beats`: idle fuse, relit every time x is used
   - `for 3 uses`: burns on its 3rd use
   - `until <event>`: burns when the event fires, e.g. `win.closed`
   - `while y`: anchor to y
6. **`snuff x`** burns x (and its subtree) at the next turn boundary.
7. **Burning cascades** down the anchor tree, immediately and completely.
8. **Nothing non-scope burns mid-turn.** Burns triggered during a turn take effect at the turn boundary. Inside a turn, anything you could reach at the start stays valid.
9. **Fizzle.** Using a burnt object raises `Burnt`. You can handle it with `x else <expr>` or `if alive x`. An unhandled `Burnt` aborts the current turn (the event handler), not the program.
10. **Idle fuses are upper bounds.** Under memory pressure, idle-fused objects may burn early, LRU first.
11. **Threads.** `send x` moves x's whole subtree to another thread and re-anchors it there. Objects reachable from several threads burn only at the global epoch, after every thread has finished a turn.

That is 11 rules. Rules 1–4 cover 90% of code and need no new syntax.

## 5. Under the hood

- **Object header (16 B):** a 32-bit generation; a 32-bit fuse word (tag plus payload: deadline beat, remaining uses, or event slot); a parent pointer; and intrusive `first_child`/`next_sibling` links (packed as 32-bit arena offsets).
- **The fuse forest.** Each object has one parent (another object, a scope, or a root trigger), so the fuses form trees, never DAGs. Anchoring means unlinking from the old parent and linking under the new one: O(1). Burning walks the subtree with a worklist: cost proportional to what dies, like freeing a region. Nothing is ever traced from roots, and nothing is counted.
- **Scopes.** Scope-fused objects that provably don't escape go on the stack or a scope bump arena. Escapes are known at the store or return site, so the compiler inserts the anchor call there. Scope exit frees whatever is still scope-anchored.
- **Idle fuses** use a hierarchical timing wheel keyed by deadline. A use writes `deadline = now + len` and nothing more. When a bucket comes due, each entry is checked: if it was relit, it moves to a later bucket; otherwise it burns. Cost is about one wheel visit per object per wick length. That is a timer, not a reachability scan.
- **Use fuses** decrement on each use. The compiler counts statically where it can: a `for 1 uses` closure is freed right after it is invoked.
- **Event fuses.** An event source keeps a list of subscribed root fuses and burns them all when it fires.
- **Fizzle checks.** A pointer is `(addr, gen)`. A deref compares `gen` with the header's generation. Memory is type-stable per size class and released at turn boundaries, so a stale pointer always reads a valid header. Rule 8 means one check per object per function suffices, since nothing can burn until the turn ends. Checks on `self` and on scope-fused locals are elided.
- **Threads.** Generations are atomic for objects shared across threads. Reclamation of those objects is epoch-based, RCU-style.
- **Pressure eviction.** The allocator, on a soft limit, pops from the idle wheel's LRU end.
- **Test mode.** A virtual clock (`clock.advance(5m)` in tests) and pressure eviction switched off. Death becomes fully deterministic.
- **Tooling.** Every burn records `(beat, cause, parent chain)`. A fizzle prints, for example: `Editor#12 burnt at beat 4107: anchor Window#3 fired 'closed'; touched at beat 4108 by closure from editor.sl:41`. The debugger shows the fuse forest live.
- **FFI.** C gets raw pointers only inside a `pin x { ... }` block. A pinned object cannot burn until the block exits. C must not keep the pointer after that, which is the usual C contract.

## 6. Scenarios (illustrative only — not a syntax decision)

**(a) Read lines.**
```
fn readLines(path: String) -> List
  lines = List()                 // scope fuse
  for line in File.open(path).lines
    lines.append(line)           // strings are values: nothing to anchor
  return lines                   // fuse moves to caller's scope
```
The caller writes `self.lines = readLines(p)`, which anchors the list to `self`.

**(b) Tree with parent pointers.**
```
class Node
  parent: Node
  kids: List
  fn add(k: Node)
    k.parent = self              // anchored object stored: no fuse change
    kids.append(k)               // new k was scope-fused -> now anchored to kids, which is anchored to self
  fn moveTo(k: Node, other: Node)
    kids.remove(k)
    other.add(k)
    keep k while other           // explicit re-anchor; forgetting it means k burns with self (safe fizzle, clear message)
```
Parent and child pointing at each other is a non-issue because pointers hold nothing.

**(c) UI callback — the crux.**
```
class Editor
  doc: Doc
  dirty: Bool
  fn build(win: Window)
    b = Button("Save", onTap: fn()
      self.save()                // self captured: already anchored, nothing changes
      self.dirty = false)
    win.add(b)                   // b -> win, closure -> b (anchored at store into onTap)

app.onLaunch = fn()
  win = Window()
  keep win until win.closed      // root trigger
  ed = Editor()
  keep ed while win              // editor lives exactly as long as the window
  ed.build(win)
```
- The editor holds the button, the button holds the closure, and the closure holds the editor. That cycle is harmless.
- When the window closes, `win` burns at the turn boundary, and the window, button, closure and editor go together in one cascade.
- The callback can't fire after the editor dies, because it dies first or at the same time.
- Variants:
  - `after 3s, fn() {...}` gives the closure `for 1 uses` automatically, and it is freed after it fires.
  - A toast is `keep toast for 4s`.
  - A handler that should die with something *other* than its holder: `keep handler while ed`.

**(d) Shared cache used by two components.**
```
cache = Map()
keep cache until app.quit
fn thumb(url: String) -> Image
  img = cache[url] else nil
  if img == nil or not alive img
    img = decode(fetch(url))
    cache[url] = img             // anchored to cache
    keep img for 10m             // re-rooted on an idle fuse; pressure may evict sooner
  return img
```
Both components keep plain references. If an entry burns, their next use fizzles, and `thumb(url) else placeholder` handles it. Expiry and memory bounds come free.
- Caveat: the map's slot still holds a stale (generation-checked) pointer. `alive` detects it.

**(e) Large list mutated by a function.**
```
fn normalise(xs: List)
  for i in 0..xs.count
    xs[i] = xs[i] / max
normalise(self.samples)          // a plain reference: no copy, no borrow, no fuse effect
```

**(f) Threads.**
```
job = Batch(rows)
send job to worker               // whole subtree re-anchored to the worker's scope
results = Shared(List())         // built-in locked cell
keep results until pool.done     // shared: burns at the global epoch
```

## 7. What is new

- **Lifetime is a trigger, never a reachability fact.**
  - O1/O7: references count.
  - Regions: scopes own.
  - Round-1 single-owner schemes: owner variables own.
  - Here, nothing a pointer does affects lifetime, except the *first* store of a scope temporary, which anchors it.
- **Root triggers are time, use count and events,** not variables or scopes. Idle and use-count fuses don't exist in any listed option.
- **The forest is a fuse graph, not a pointer graph.** Pointers form arbitrary cycles while fuses form trees. Cycles stop being a memory-management concept.
- **Leak-freedom by construction.** In exchange, the failure mode moves to safe premature death with full provenance.
- **Memory as evictable cache** as a language-level contract, with pressure eviction built in.
- **Versus scope regions + `promote`** (the closest listed option): promotion targets a *finite fuse* instead of global, which fixes that option's leak.

## 8. Less crazy than it sounds, or more

**Less:**
- UI frameworks, servers and games already think this way: view lifetime equals window lifetime, sessions have idle timeouts, cache entries have TTLs, timers fire once.
- iOS already kills idle state under memory pressure.
- The runtime is mundane parts: generation checks (Vale), timing wheels (every kernel), intrusive trees, RCU epochs. Implementation risk is moderate.
- The fizzle error is *better* than a leak: you can see it, test it and diagnose it.

**More:**
- Every pointer deref is now a possible failure point.
- Pressure eviction means a program that passes tests can fizzle in production on a busier machine.
- "Correct" now includes "every idle fuse's holder copes with fizzles". That is a new, global, non-local correctness property that no compiler checks.

## 9. Known weaknesses

1. **Silent wrong anchoring.**
   - Rule 4's "first store anchors" picks an owner implicitly. Store a temp into a short-lived holder first and a long-lived one second, and it dies with the short one.
   - This is the single-owner problem back in disguise: the anchor tree *is* an ownership tree, just one whose roots are timers. Expect analysts to score this near round-1 single-owner ideas, plus or minus the trigger roots.
2. **Fizzle ergonomics.**
   - Any use of a non-local object can raise `Burnt`. Either code is littered with `else`, or turns get aborted halfway with mutations half-applied.
   - There is no transactional rollback. Aborting a turn mid-mutation can leave state inconsistent.
3. **Move-by-hand.** Moving a subtree between parents (tree re-parenting, list-to-list transfer) needs an explicit `keep x while y`. Forgetting it is a delayed, non-local bug, though always safe and well reported.
4. **Stale slots.** Containers fill with dead pointers (generation-checked) until overwritten. Caches need sweeping, either by user code or by an `alive` filter.
5. **Nondeterminism.** Wall-clock and pressure fuses make death timing environment-dependent. Test mode helps, but production behaviour differs from tests by design.
6. **Long turns.** Rule 8 defers non-scope burns to the turn boundary, so a long compute turn that snuffs or anchors many objects holds their memory until it yields. Scope-fused temporaries are unaffected.
7. **Concurrency.** The model gives lifetime safety across threads (epochs) but no data-race safety. `Shared` cells and locks are separate concepts to learn.
8. **Rule count.** 11 rules versus ARC's roughly 5. Simplicity scores below O1/O4 unless analysts credit "no weak refs, no cycles, no move semantics, no borrows" as removing more concepts than fuses add.

**Self-assessment:**
- **Gates:** G2 pass (timer wheel plus cascade, no trace). G3 pass (`keep` is a runtime statement; analysts may argue it is a lifetime annotation in disguise, so flag it).
- **Guess:** around 65–72. The UI story is strong, debuggability is strong and performance is good (zero RC traffic). The losses are on memory-safety *ergonomics* (fizzles) and simplicity.
