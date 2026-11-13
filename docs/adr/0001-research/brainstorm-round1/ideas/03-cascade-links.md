# 03 — Cascade Links: foreign-key memory with commit-time deletion

## 1. Name

**Cascade Links**, also called "Rows & Links". Every object is a row with exactly one owner. Every other reference is a foreign key that never keeps its target alive. Deletion follows `ON DELETE` rules, and it takes effect only at a **commit**.

## 2. Inspiration: how the database lens maps onto memory

| Database concept | Memory concept |
|---|---|
| A row exists until it is deleted | An object exists until its single owner lets go of it |
| Foreign key, `ON DELETE SET NULL` | An optional link (`T?`) becomes `none` when its target dies |
| Foreign key, `ON DELETE CASCADE` (the *referencing* row dies) | A required link (`T`) deletes the object holding it when its target dies |
| An index on a foreign-key column | A per-object reverse index of incoming links. It makes SET NULL and CASCADE O(links), and it also gives you inverse relations for free |
| Normalization: store a fact once, derive its inverse | Store `parent` and derive `children`. Bidirectional structures need only one stored pointer |
| A transaction sees a stable world. Deletes and cascades apply at commit | Stack references can't dangle because nothing is freed until the stack has unwound to a commit point. This replaces lifetimes and borrow checking |
| MVCC snapshots and first-committer-wins | Data shared between threads lives in versioned stores, accessed in `atomic` blocks. Old versions are freed when the oldest snapshot moves past them, with no tracing |

The key reframe is that in a database, references never own anything. Liveness comes from explicit membership (a row is in a table), and the referential-integrity rules define what happens to everything that pointed at a deleted row. Programs need the same thing. What ARC calls "weak" is just SET NULL. But databases have a second, missing tool, CASCADE-from-the-referencing-side: "I can't exist without you." That second tool solves the UI-callback crux.

## 3. Pitch

Objects form a single-owner tree, rooted in stack frames and globals. Any number of non-owning **links** can point at an object. Links never keep anything alive, so no reference counts are needed, and since links never own anything, no cycle can leak. When an object is deleted, the runtime uses the object's reverse index to empty every slot that pointed at it. An optional slot becomes `none`. A list element is removed. A **required** slot deletes the object that holds it, which cascades. Deletion is deferred to a **commit point** between events, so for the whole of a callback or message handler every reference on the stack stays valid. Functions can freely take and return references with no lifetime annotations, no borrow checker and no per-dereference checks. Closures capture links, which are required, so a callback is automatically deleted and unregistered the moment anything it captured dies. The programmer never writes `[weak self]` or `guard let self`. Data shared between threads lives in MVCC stores, used inside `atomic` blocks.

## 4. The rules: everything a programmer must learn

1. **Values copy.** Numbers, strings and small structs copy on assignment. Large strings use invisible copy-on-write.
2. **Each object has exactly one owner**: the local variable it was created in, an `own` field, or a collection marked `own`. A collection always belongs to the slot it sits in. `own` on a collection field means the collection also owns its elements. An object is deleted when its owner lets go: the scope ends, the slot is overwritten, the object is removed from the collection, or you write `delete x`.
3. **Every other reference is a link.** This covers plain fields, plain collection elements, parameters, non-owning locals and return values. Links never keep anything alive.
4. **When an object is deleted, every slot that pointed at it is emptied.** The slot's type decides how:
   - an optional slot (`T?`) becomes `none`;
   - a collection element is removed;
   - a required slot (`T`) deletes its holder too, and that cascade applies the same rule again.
5. **Deletes take effect at commit.** Until the next commit, everything you could see stays readable and valid. A deleted object is a "pending" row. Commits happen after each event, callback or message handler returns, and at an explicit `commit` statement. `commit` is legal only in `main` or a thread's body. A link held in a local of such a root function can't be used after a `commit`. The compiler checks this and tells you to fetch it again.
6. **Closures capture objects as required links**, and a function-typed slot owns the closure stored in it. So if anything a closure captured is deleted, the closure is deleted too, and its slot is emptied (rule 4). If a captured *owned* local isn't used after the closure is created, it moves into the closure.
7. **`move x into slot`** transfers ownership. Moving an object into its own subtree is a runtime error.
8. **Derived inverses.** `children: from Node.parent` declares a read-only collection of every `Node` whose `parent` links to `self`, in the order the links were made. You never store both directions.
9. **Threads don't share objects.** `send(move x)` moves a whole owned subtree to another thread. Links that would cross from one thread to another are emptied, exactly as if their target had been deleted.
10. **`shared` stores** are the only cross-thread mutable data. You read and write them only inside `atomic { }`. An atomic block sees a snapshot, and it reruns if another thread committed a conflicting write first. It can't do I/O or write the thread's own objects. Its result comes out as a value.

A smaller rule falls out of rule 5: a `for` loop iterates over the collection as it was when the loop started, like statement-level read consistency.

A programmer has to understand ten rules. Rules 8–10 can be learned late.

## 5. Under the hood

**Object header.** Each object has an `owner_slot*` and an `incoming*` pointer. `incoming*` points to a side table that is allocated only when the object first gets a heap link, as Swift does for weak refs. The header also holds 2 bits: pending-delete and visited.

**Two kinds of links:**
- A **stack link** (a parameter, a local or a return value) is a raw pointer with zero overhead. Rule 5 makes it safe: no object is freed while the frame that holds the link is alive, because a commit only runs once the stack has unwound to the event loop or root.
- A **heap link** (a field, a collection element or a closure capture) is a target pointer plus a node in the target's intrusive doubly linked incoming list, `{holder, slot, kind, prev, next}`. It costs O(1) to create, overwrite or destroy. The compiler knows which slots hold heap links from the field declarations, so it emits register and unregister calls only at stores to those slots.

**Drop.** When an owner lets go, the runtime marks the object pending and pushes it onto the thread's pending list. There is a fast path. An owned local whose scope ends with an empty incoming list, and whose address escape analysis proves never leaves the frame upward, is freed immediately. Most temporaries take this path, and so do resources like `File`, so they close deterministically at scope end.

**Commit**, as a worklist:
```
while pending not empty:
  o = pop; skip if visited; mark visited
  push every object o owns (its subtree)
  for each incoming link L of o:
     optional slot  -> set none
     collection     -> remove element
     required slot  -> push L.holder
  unregister o's own outgoing heap links from their targets
free everything visited
```
This is O(objects deleted + links touched). There is no tracing of live objects. It is the same work ARC does when it frees a tree, plus the link-emptying. The event loop calls `commit()` after each handler. `main` and thread bodies call it at their `commit` statements and at exit.

**Derived inverses (rule 8)** reuse the incoming list, filtered by slot ID. Their cost is already paid.

**Move check (rule 7).** Before a move, the runtime walks the destination's owner chain to make sure the object isn't moved into its own subtree. This is O(depth).

**Shared stores (rule 10).** Each store object keeps a version chain. Every write inside `atomic` copies the object into a private version, using copy-on-write per object. At block end, the runtime validates the write set against the store's global commit timestamp, using first-committer-wins. On a conflict it discards the private versions and reruns the block. Superseded versions go on a retire list stamped with the commit timestamp. When any atomic block ends, versions older than the minimum active snapshot are freed. This is epoch reclamation, done at transaction boundaries, with no tracing. Deletions inside a store follow rule 4 at atomic commit. An implementation could ship v1 as "one mutex per store" with the same semantics minus the concurrency, and upgrade to MVCC later.

**Compiler work.** The compiler classifies every slot as value, own, link, optional link, required link or function-typed. It emits register and unregister calls at heap-link stores. It runs one escape analysis that only enables the fast path, so it is never needed for safety. It checks rule 5's stale root locals and rule 10's restrictions on atomic blocks. There is no lifetime inference, no region analysis and no borrow checker.

**Tooling.**
- `links_to(x)` lists everything that points at `x`, like querying an FK index.
- A debug commit log records every cascade, for example "Button#12.onTap emptied because Editor#3 was deleted, because Window#1.editor was overwritten at editor.lang:88".
- The debugger can draw the "schema" (the own and link edges) as an entity-relationship diagram.

**C FFI.** A pointer passed to C is a stack link, valid until commit. To hold one longer, C asks the runtime for a registered handle, which is a heap link with SET NULL semantics: `lang_handle_get(h)` returns NULL once the target is gone.

## 6. Scenarios (a)–(f)

All code is *illustrative only — not a syntax decision*.

**(a) Read lines into a growing list**
```
fn readLines(path: String) -> List of String {
    let file = File.open(path)          // owned by this local
    let lines = new List of String
    for line in file.lines() { lines.add(line) }   // strings are values
    return lines                        // ownership moves to the caller's slot
}                                       // file: no links -> freed and closed now (fast path)
```
Nothing new to learn here. The list owns its buffer and grows normally.

**(b) Tree with parent pointers**
```
class Node {
    name: String
    own children: List of Node     // owns the subtree
    parent: Node?                  // link: SET NULL
    fn add(n: String) -> Node { return children.add(new Node(name: n, parent: self)) }
}
let a = root.add("a")      // a stack link, valid for the rest of this event
root.children.remove(a)    // at commit: a and its subtree are freed, and any outside links to them are emptied
```
The normalized alternative stores the relationship once and derives its inverse:
```
class Org    { own people: List of Person }
class Person { boss: Person?   reports: from Person.boss }   // firing a boss sets reports' boss to none
```
Parent pointers are just links. They form cycles with the ownership edges, but links don't own anything, so nothing can leak.

**(c) UI callback capturing `self` (the crux)**
```
class Editor {
    text: String
    fn attach(button: Button) {
        button.onTap = fn() { self.text = trim(self.text); self.save() }   // captures self: required link
    }
}
class Window {
    own toolbar: Toolbar           // the Save button lives here and outlives editors
    own editor: Editor?
    fn closeDocument() { editor = none }   // at commit: Editor deleted -> closure deleted -> button.onTap = none
}
```
The closure body uses `self` directly. Whenever the closure runs, it is the start of an event, so its captures are guaranteed alive: if any had died, the closure would already have been deleted at the previous commit. That gives four properties:
- **No cycle.** The toolbar owns the button, the button owns the closure, and the closure only links to the editor.
- **No leak.** Closing the editor frees it.
- **No crash.** The closure can't run against a dead editor.
- **No manual unsubscribe.** The callback disappears on its own.

The tap handler can even close the editor itself. The editor stays valid until the handler returns.

**(d) Shared mutable cache used by two components**
```
class App      { own cache: ImageCache   own gallery: Gallery   own preview: Preview }
class ImageCache {
    own entries: Map of String to Image
    fn get(url: String) -> Image? { ... }
    fn evict(url: String) { entries.remove(url) }
}
class Gallery  { cache: ImageCache    shown: List of Image }   // required link; a list of links
class Preview  { cache: ImageCache?   current: Image? }        // optional link: survives a cache swap
```
Both components mutate the cache through links. Evicting an entry removes it from `Gallery.shown` and sets `Preview.current` to `none` at commit. That is the "cache entry with a non-nesting lifetime" case, handled by referential integrity. Choosing `ImageCache` or `ImageCache?` is the schema decision: "can this component exist without the cache?"

**(e) Pass a large list to a function that mutates it**
```
fn normalise(xs: List of Float) {
    let m = max(xs)
    for i in 0..xs.count { xs[i] = xs[i] / m }
}
normalise(model.scores)        // passes a stack link: no copy, mutated in place
```
Parameters are links, so there is no `inout`, no borrow and no copy. Even if `normalise` somehow caused `model.scores` to be deleted, the list stays valid until commit.

**(f) Sharing data between threads**
```
let batch = new Batch(rows: load())
let w = spawn fn(b: own Batch) { process(b) }
w.send(move batch)                 // the whole owned subtree moves; cross-thread links are emptied

shared stats = new Stats           // an MVCC store
// on any thread:
let seen = atomic { stats.hits += 1; return stats.hits }   // snapshot, commit, rerun on conflict
```
There are two mechanisms. Moving whole subtrees is fast, has no locks, and is the common case. A `shared` store is for genuinely shared mutable state. Readers never block writers. A data race is impossible, because thread-local objects can't be reached from another thread, and shared objects can only be reached inside `atomic`.

## 7. What's genuinely new compared with the covered options

- **Required links that cascade-delete the *holder*** (`ON DELETE CASCADE` from the referencing side). O1 and O4 only have weak/SET NULL. This "dependent existence" is what makes callbacks unregister themselves (scenario c) without weak-self boilerplate or null checks inside the closure. As far as I know, no mainstream language has it.
- **Commit-deferred deletion as the safety mechanism for stack references.** It replaces lifetimes (O5), parameter-only borrows (O4), runtime borrow counts (Inko, O6) and per-dereference generation checks (Vale, O6). Functions can return references into structures freely, with no annotations and no checks.
- **Eager emptying of every referencing slot through a reverse index.** Liveness comes from single ownership with *no counts at all*. This is unlike O1 and O7, where weak refs sit beside strong counts. Cycles are impossible to leak by construction, so no cycle collector is needed.
- **Normalization: derived inverse relations** (`from Node.parent`), paid for by the same reverse index. Bidirectional graphs never need two stored pointers.
- **One rule (rule 4), keyed off type nullability, covers weak refs, observer removal, cache-entry invalidation and cascading subtree deletion.** No separate `weak`, `unowned` or `unowned(unsafe)` kinds are needed.
- **MVCC stores as the thread-sharing primitive**, with version reclamation at transaction boundaries. STM exists elsewhere, but it isn't in the covered list, and here it doubles as the reclamation scheme for shared data.

## 8. Known weaknesses

- **Link overhead.** A heap link costs about 5 words, against 1 for a pointer. Graph-heavy code with many links pays in memory and in the work of registering and unregistering them.
- **Surprising, far-reaching cascades.** One delete can remove distant objects, for example a required `onTap: fn()` slot taking a whole button with it. The commit log mitigates this but doesn't prevent it. Callback slots should be optional or collections, and the style guide must say so.
- **Memory is held until commit.** A long handler that removes many heap objects keeps them until it returns. Batch programs must place `commit` in `main`'s loop. The rule about stale root locals after a commit is a small learning cost.
- **Logic staleness within a transaction.** A pending-deleted object is still readable until commit. This is memory-safe, but code can act on an object it just removed.
- **Single ownership forces a choice of owner** for genuinely co-owned data. That design work is the same as choosing strong versus weak in ARC, just framed as schema design.
- **`own` is a field keyword.** It is not an annotation, but analysts should confirm it doesn't strain G3. Built-in `List of T` and `Map of K to V` are needed, which is the pending G3 question.
- **Atomic blocks have restrictions** (no I/O, no writes to thread-local objects, reruns on conflict), and the MVCC runtime is the riskiest part to build. The mutex-per-store fallback reduces that risk.
- **No tracing GC (G2 passes).** But commit-time reclamation and epoch reclamation of shared versions are deferred work. A strict reader might ask John whether "commit" counts as a collection run. I'd argue it doesn't: it touches only dead objects and their links, never the live heap.
