# 01 — Witnesses

## 1. Name

**Witnesses**: objects exist only while something outside the object graph is watching them.

## 2. The crazy premise: which sacred assumption it breaks

Every sensible design ties liveness to the object graph. Something lives because something else points at it: an owner, a count, or reachability. **Witnesses cuts that link completely.** References never keep anything alive. An object lives only while it is *observed by a witness*. A witness is a node in a strict tree of observers, and each witness is anchored to something real outside the program: the process, a thread, an OS window, a socket, an HTTP request, a timer, a single event-handler invocation. The program never decides when a thing dies. Reality does, when the user closes the window, the peer hangs up or the handler returns. Pointer structure only decides *who can see what*.

Who observes the observers? Each witness is watched by the witness it was born in, and the root (the process) is watched by the OS. Observation never runs from object to object. It runs from the tree to the objects. So the object graph can have any shape, including cycles, and nothing ever counts it or traces it.

Assumptions broken:
- "Liveness follows references."
- "Removing the last reference frees the object." It doesn't: the object only goes *cold*. See rule 4.

The G2/G3 positions are argued in section 8. Determinism is kept.

## 3. Pitch

You never manage objects, only *witnesses*, and most witnesses are handed to you by the world. A window is a witness. A connection is a witness. Each `onTap` invocation is a tiny witness. Anything you build is seen by the witness you built it in. If you store it somewhere a longer-lived witness can see, that witness now sees it too. When the last witness that can see a thing ends, the thing is gone. Cycles are irrelevant, because nobody counts edges. Weak references are unnecessary, because a closure stored on a button doesn't keep the editor alive: the window does, and when the window goes, they all go together. If you need something to die before its surroundings (a cache entry, a session, a document), make it a witness itself. Holding a witness is a window onto it, not a grip on it.

## 4. The rules (everything a programmer must learn)

1. **Born seen.** Every object starts out seen by the witness whose code is running when it is created.
2. **Witnesses come from the world or from you.** Built-in witnesses: process, thread, window, connection, request, timer, test. Make your own with a `watch { }` block, or by declaring a `witness class`. Each witness is watched by the witness it was born in. **When a witness ends, every witness it watches ends too.**
3. **Seeing is transitive.** If a witness can see an object, it can see everything that object points at. Storing a reference anywhere a witness can see makes that witness see the target. This is automatic: there is no keyword.
4. **Death = unwitnessed.** An object dies when every witness that sees it has ended. Nothing else frees an object. Overwriting a field or popping it from a list does *not* free it. It goes cold until its witnesses end. Values (numbers, strings, structs, the list buffer itself) are different: they have no identity and are freed as soon as they are overwritten.
5. **Turns.** Each event handler, callback invocation, or iteration of a `for x in <event source>` loop runs inside its own short-lived *turn* witness. Locals belong to the turn. Temporaries die when the turn ends. Any end, whether `w.end()` or a window closing, takes effect when the current turn finishes. Nothing disappears under running code.
6. **A witness handle is a window, not a hold.** Storing a reference to a `witness class` instance does *not* make you see its contents. Touching it after it has ended raises a defined `Gone` fault. This is the only fault the model has, and you can test for it with `w.alive`. Use a witness class for anything that must die before the thing holding it.
7. **Entanglement.** An object seen by witnesses on two different threads is *entangled*. You may change it only inside `sync x { }`. The runtime checks this.

That is seven rules. There are no weak/unowned references, no capture lists, no cycle advice, no lifetimes and no moves.

## 5. Under the hood

- **Sight classes.** Each object header has one word: a pointer to an interned, immutable *sight set* (for example `{window#4, turn#912}`). Objects with the same set are linked into that set's intrusive list. Each witness knows which sight classes contain it.
- **Store barrier.** On `holder.f = target` (or an assignment to a local of an enclosing turn), compare the two set pointers. If they are the same, or a cached result says `sight(target) ⊇ sight(holder)`, nothing happens. That is the common case. Otherwise run the *spread*: union the holder's set into the target's, move the target to the new class, and recurse into the target's references. The recursion stops at any object that already sees the holder's set. Sets only grow while their witnesses live, so each (object, witness) pair is spread at most once. Total spread work is bounded by memberships created, not by heap size.
- **Witness end.** For each sight class S that contains W, compute `S' = S − {W}`. If S' is empty, free every object in S's list (running `deinit`, in reverse creation order). Otherwise merge S's list into S' using union-find on class nodes. Headers are not touched, because they reach the new class via `find`. So surviving objects cost O(1) per *class*, and dead objects cost O(1) each. This is never a heap walk.
- **Why there are no dangling references.** Rule 3 maintains the invariant *for every edge y→x, sight(x) ⊇ sight(y)*. If x's set becomes empty, y's set must already be empty, so y dies in the same end. Nothing alive can point at the dead. Locals are covered by rule 5: ends are deferred to turn boundaries, and a turn's locals are gone by then. A `watch { }` block in straight-line code ends synchronously. The compiler inserts a spread on every assignment to a local declared *outside* the block and on the block's result, so anything escaping is seen by the outer turn.
- **Witness handles** are pointers to witness classes, checked through a generation word. That is the only runtime check on dereference, and it is never made on ordinary objects.
- **Entanglement.** Every witness has thread affinity. A sight set that spans two threads sets an `entangled` bit. Barrier updates for entangled objects take the header lock. When a reference is read out of an entangled object into a local, the object is *pinned* to the reader's current turn, and freeing a pinned object waits for that turn to end. Ordinary objects pay nothing.
- **Decoherence (optional, the quantum part).** Objects that sit untouched for N turns in a long-lived witness are, by construction, clustered by sight class. The allocator gives each sight class its own pages, so a cold page can be compressed and `mprotect`ed, and touching it faults it back in. Rule-4 garbage therefore costs compressed bytes, not RAM. This is really just witness-aware compressed swap.

## 6. Scenarios — illustrative only, not a syntax decision

**(a) Read a file into a growing list**
```
fun readLines(path) {
    lines = []                       // value buffer; grows/reallocs freely
    for line in File.open(path).lines { lines.add(line) }
    return lines                     // strings are values; nothing to witness
}
```
The file handle is a witness, so it closes when the turn ends. When the list buffer reallocates, the old buffer is freed immediately (rule 4, values).

**(b) Tree with parent pointers**
```
class Node { parent; children = []; name }
fun add(parent, name) { n = Node(parent: parent, name: name); parent.children.add(n); return n }
```
The cycles don't matter. The tree lives as long as the witness that sees the root. To delete subtrees inside a long-lived document, make `Node` a `witness class`. A child then sees its parent automatically, because it was born inside it. The parent holds its children as handles, and `child.end()` prunes that subtree.

**(c) UI callback capturing state: the crux**
```
witness class EditorWindow {        // also an OS window: user closing it ends it
    text = ""
    fun save() { Disk.write(path, text) }
    fun body() {
        Column {
            TextField(bind: text)
            Button("Save") { onTap: { save(); text = text.trim() } }  // captures implicit self freely
        }
    }
}
```
The closure is stored on the button and both are in the window's sight, so tapping runs the closure in a fresh turn. When the user closes the window, the window, button, closure and editor state all end together, and any timers or requests started under the window are cancelled. If the save must outlive the window:
```
app.watch { Http.post(url, text) { onDone: { log("saved \(path)") } } }
```
The request is now a child of `app`. Its closure sees the editor state, so that state survives until `onDone` finishes and is then freed. You never wrote a weak reference.

**(d) Shared mutable cache used by two components**
```
witness class Entry { value; stamp }
class Cache { entries = Map() ; fun get(k) { e = entries[k]; return e.alive ? e.value : nil }
              fun put(k, v) { entries[k]?.end(); entries[k] = Entry(value: v) }
              fun evict(k) { entries.remove(k)?.end() } }
app.cache = Cache()                  // components A and B both store app.cache
```
The entries are witnesses, so holding them is not a hold (rule 6), and eviction really frees. Values returned by `get` are only seen by the caller's turn, unless the caller stores them.

**(e) Pass a large list to a function that mutates it**
```
fun normalise(list) { for i in 0..<list.count { list[i] = list[i].lower() } }
normalise(doc.lines)                 // lines is a value field; passed in-place (inout by default for values)
```
There is no spread, because nothing gains sight. If the list holds objects, the function mutates the objects themselves, and their sight is unchanged.

**(f) Sharing data between threads**
```
stats = Stats()                       // seen by main thread's witness
t = spawn { for job in queue { sync stats { stats.done += 1 } } }   // spawn args spread to thread witness
```
`stats` is now entangled, and mutating it outside `sync` is a checked fault. When thread `t` ends, `stats` returns to being seen by one thread only and is no longer entangled.

## 7. What is new

- **Liveness is decided by a tree of external observers, never by the object graph.** Regions get freed whole, but here an object may be seen by *any number* of unrelated witnesses at once, it moves between them automatically, and the regions are created and ended by reality (OS windows, sockets, handlers), not by lexical scope.
- **The sight-set invariant** (*target sees ⊇ holder sees*) is enforced by a monotone spread on store. It gives no-dangling safety without counts, traces or per-dereference checks, and cycles are a non-issue by construction.
- **Union-find sight classes** make ending a witness O(classes + dead objects), and surviving objects are never touched.
- **Turn witnesses** make "temporaries die at the end of the handler" a consequence of the model rather than a separate mechanism.
- **One weak-like construct** (`witness class`) doubles as the domain concept: Window, Session, Document, Entry.

## 8. Why it might be less crazy than it sounds, or more

**Less crazy.**
- Real UI and server programs already think this way. A request handler's garbage dies with the request, and a window's state dies with the window.
- The crux, (c), needs zero ceremony and has no cycle trap. O1 needs `[weak self]` reasoning there.
- Debugging is excellent: every byte is attributable to a witness, and the debugger can show the witness tree with memory per node.
- Objects never move, so C FFI is easy. Passing a pointer to C means pinning it to a witness.

**G2.** I claim a pass. There is never a collector run, and frees happen at deterministic, program-visible events. But the spread *is* a graph walk, triggered by a store. An analyst could call it incremental marking. **Flag: needs-john** on whether "a walk bounded by memberships created, run synchronously at the store" is allowed.

**G3.** I claim a pass. `witness class` is a declaration keyword, like `class`, not an annotation, and the model itself needs no generics.

**More crazy.**
- Rule 4 means a long-lived witness silently accumulates everything that ever passed through it.
- The user has to understand sight in order to understand memory use.
- Spread pauses are proportional to the size of the structure being published.

## 9. Known weaknesses

1. **Monotone sight = churn leaks.** A long-lived queue in `app` whose items are objects keeps every popped item until `app` ends. The fix (make items witness classes) is an idiom, and forgetting it leaks with no warning. Decoherence turns the leak into compressed cold pages, which only hides it. The tooling should report "witness `app` holds 1.2 GB cold, top creation sites…".
2. **Spread cost spikes.** Showing a 1M-node document in a second window walks the whole document. The fix is to make the document a witness class, which is another idiom the programmer has to know.
3. **Turn discipline.** Ends wait for turn boundaries. A compute-bound thread with no event loop never reaches a boundary, so ends it owns and pins it holds are stuck. You need `for x in source` turns or explicit `watch { }` blocks.
4. **Entanglement pins** add cross-thread coordination to frees and are subtle to implement correctly.
5. **`Gone` faults exist**, though only on witness-class handles. That puts it nearer O6-level safety than O1 for those types.
6. **Implementation risk.** The barrier fast path, interned sets with subset caching, union-find classes, per-class pages and pins add up to a novel runtime with no prior art to copy. It is risky for an AI-written compiler.
7. **`deinit` ordering** across several dead classes in one end is only "reverse creation order", which needs a creation counter per object.

**Self-assessment** (rubric weights):

| Criterion | Score (out of 5) |
|---|---|
| Simplicity | 3 |
| Safety | 4 |
| Expressiveness | 4 |
| Implementation risk | 2 |
| Performance | 3 |
| Concurrency | 3 |
| Tooling | 4 |

That gives **≈ 65 / 100**. The crux is excellent and the cycle problem is eliminated, but the idiom load for long-lived collections is real.
