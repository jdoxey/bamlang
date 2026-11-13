# 02 — Estates and Liens

## 1. Name

**Estates and Liens** (informally, "ledger memory").

## 2. Inspiration — how the lens maps onto memory

| Economics | Memory |
|---|---|
| **Estate**: land plus buildings, held under one title | A region of objects that are all freed together |
| **Deed**: the one document that says who owns an estate | A move-only owning handle to an estate's founding object |
| **Landlord / tenant**: a tenant's lease ends before the landlord's title | The title tree: an estate whose deed sits inside another estate is that estate's tenant |
| **Lien**: a creditor's claim that stops a sale from completing | A reference from one estate into another, counted per *estate pair* rather than per object |
| **Receivership**: a closed business that can't be wound up until its creditors are settled | An estate whose deed was dropped but which still has liens on it, so it is kept alive and read-only for new liens |
| **Settlement date**: trades clear at the end of the trading day, not in the middle of it | Freeing happens only at settlement points (an event-loop turn or a thread's top-level loop), never under a running function |
| **Bankruptcy court**: it unwinds creditors who only owe each other | At settlement, closed estates that hold liens only on one another are freed together |
| **Escrow**: an asset held by a neutral party during a transaction | A value passed for mutation is moved out of its home for the duration of the call |
| **Public record / trust** | Frozen estates that any thread may read / estates shared behind a lock |

The core economic idea: **the law tracks ownership between parties, not inside a household.** Nobody records who in a family owns the toaster. In the same way, pointers inside an estate are not tracked at all, whatever shape they take. Only claims that cross from one estate to another are counted, and they are counted per estate.

## 3. Pitch

The programmer already knows the non-nesting lifetimes: this window, this session, this document, this cache entry. Estates and Liens lets them say so with one keyword, `new estate`, and asks for nothing else. Every object lives in an estate. Pointers within an estate are plain pointers, so cycles, parent pointers and closures capturing `self` are free and need no weak references. An estate is owned by a deed stored in an ordinary field. When the deed is dropped (the window is removed from `app.windows`), the whole estate is freed in bulk at the next settlement point. A pointer from one estate into another is a *lien*. The runtime records it in a per-estate-pair counter at store time, with nothing written in the source. A lien keeps the target estate in receivership instead of letting it dangle. Function locals never hold liens, because nothing is freed until the stack has unwound to a settlement point. That removes the reference-count traffic ARC spends on locals. Lien cycles can only form between estates, never between objects. They are cleared at settlement by a small check over the closed estates, which never scans the heap.

## 4. The rules

1. **Values and objects.** Numbers, strings, structs, `List` and `Map` are *values*. Assigning one copies it (copy-on-write makes that cheap). A value is freed exactly when its owner overwrites or drops it. `class` instances are *objects*: they have identity and are shared by reference.
2. **Every object lives in an estate.** A new object goes into the *current estate*. Inside a method that is `self`'s estate. In a free function it is the caller's current estate. `X() in o` puts the new object in `o`'s estate instead.
3. **`new estate X()` founds an estate** with `X` as its first object and returns a **deed**. A deed can only be held in an `own` variable or field, and it moves rather than copies. When the deed is dropped or overwritten, the estate *closes*, and so does every estate whose deed is inside it.
4. **References are unrestricted.** Any object may point at any other object in any estate, cycles included. Nothing is ever freed out from under a reference you can still reach. A reference that crosses estates keeps its target's estate alive after it closes (receivership). This is automatic and invisible in the source.
5. **Freeing happens at settlement.** A closed estate is freed at the next settlement point: the end of an event-loop turn, or a `settle` statement in a thread's top-level loop. `estate { ... }` blocks are the exception. They create a scratch estate that closes at the end of the block, and an object reference may not leave the block through a local or return value. To keep an object, store it in a field.
6. **`lease` references are optional and revocable.** A `lease` field or capture does not keep its target alive. Reading it yields `none` once the target's estate has been freed.
7. **`mut` parameters use escrow.** A value passed as `mut x` is mutated in place, with no copy. While the call runs, its home (`x`, or `obj.field`) is empty. Reading the home during the call is a runtime error in debug builds and reads an empty value in release builds.
8. **Threads.** An estate belongs to one thread. You can share across threads in three ways. `send` a deed to another thread, which is allowed only if the estate has no liens to or from estates outside itself. `freeze` a deed to make a read-only record that any thread may read. Or put a deed in a `trust` (a lock) and use it inside `with t as x { }`. Inside that block, no reference may be stored from the trust's estate to another estate, or back. Values cross freely.

That is 8 rules. Rule 6 can be ignored by beginners: without it, the only downside is that memory is held longer.

## 5. Under the hood

**Allocation.** Each estate is a list of 64 KiB-aligned chunks with bump allocation. The chunk header points to the estate record, so `estate_of(p)` is `*(p & ~0xFFFF)` and objects carry no per-object header for memory management. Objects too large for a chunk get a dedicated chunk. Value storage (List buffers, strings) is *fixtures*: it is malloc'd, owned uniquely by its container and freed exactly. An estate keeps a fixture list so it can free leftover fixtures when it is wound up.

**Estate record** (in a never-freed slot table with a generation counter per slot):
`{gen, thread, state: open|closed|frozen|trust, title_parent, child_deeds, liens_out: small map estate→count, liens_in_total, chunks, fixtures}`.

**Store barrier.** The compiler adds a barrier only to stores of object references into object fields and closure captures. Locals get none. The barrier is:

```
illustrative only — not a syntax decision
store(p.f, new):
  old = p.f; p.f = new
  A = estate_of(p)
  if old and estate_of(old) != A: lien_dec(A, estate_of(old))
  if new and estate_of(new) != A: lien_inc(A, estate_of(new))   // traps if frozen/foreign thread
```

The fast path for a same-estate store is two masks and a compare. `lien_inc`/`lien_dec` bump `A.liens_out[B]` and `B.liens_in_total`. These operations are non-atomic, except on frozen estates.

**Deeds.** An `own` slot holds a pointer to the founding object. The compiler treats it as move-only, which is easy because it is a distinct slot kind with no type parameters. Dropping a deed marks the estate `closed` and records the edge in the parent's `child_deeds`. Closing cascades to child deeds. Moving a deed into another estate re-parents it in the title tree, and the lien counts stay correct with no extra work.

**Settlement.** Settlement runs at an event-loop turn boundary, or at `settle`. The compiler accepts `settle` only in a thread's entry function, and adds lien_inc/lien_dec for that function's own object-reference locals that are live across the `settle`. No other frames exist at that point. The steps are:
1. Collect C, the set of closed estates.
2. **Court.** An estate in C is *supported* if `liens_in_total` is greater than the liens it receives from members of C. That second number is computed by scanning `liens_out` of each member of C. Support then spreads along `liens_out` edges inside C.
3. Free every unsupported estate: drop its `liens_out`, free its fixtures and chunks, and bump the slot generation.
4. Repeat while the frees released further liens.

The cost is O(closed estates + lien-table entries), not O(heap). No object is visited.

**Estate blocks.** The compiler checks within one function that no object-reference local assigned inside the block is live after it, and that no `return` or `break` carries an object reference. At block exit the block's estate is wound up immediately if `liens_in_total` is 0. Otherwise it waits for settlement in receivership. This is safe because callers are suspended for the whole block, and callees have returned before it ends.

**Lease.** A lease is a fat pointer `(slot, gen, ptr)`. Reading it compares `gen` with the slot's generation and yields `none` on mismatch. The check is per estate, so it is one load and one compare.

**Escrow.** `f(mut obj.list)` moves the value out of `obj.list`, leaves an empty sentinel in its place (debug builds set a poison bit), passes the value by pointer, and moves it back on return. Unwinding also moves it back.

**Threads.** A `send` checks that `liens_out` is empty or points only at frozen estates, that `liens_in_total` is 0, and that the same holds recursively for child deeds. If the checks pass, it rewrites `thread` and transfers the chunks with no copying. `freeze` sets the frozen state: the store barrier traps on writes, and liens on frozen estates use atomic counts. A `trust` wraps the deed in a mutex. `with` sets a thread-local "jurisdiction" that the barrier consults.

**FFI.** A raw pointer passed to C is valid for the synchronous call, which the settlement guarantee covers. If C keeps the pointer, the program must call `pin(o)`. That creates a foreign lien held by a handle and released explicitly.

## 6. Scenarios

### (a) Read a file into a growing list of lines
```
illustrative only — not a syntax decision
fun readLines(path: String) -> List of String
    var lines = List()
    for line in File.open(path).lines()
        lines.append(line)          // buffer regrows; old buffer freed immediately
    return lines                    // moved out, no copy
```
Lines are values, so no estate is involved. The list's buffer is a fixture: regrowth uses realloc and frees the old buffer exactly. If the lines were `Line` objects, they would be bump-allocated in the caller's current estate.

### (b) Tree with parent pointers
```
illustrative only — not a syntax decision
class Node
    var name: String
    var parent: Node?
    var children: List of Node
    fun addChild(n: String) -> Node
        let c = Node(n)              // born in self's estate
        c.parent = self              // same estate: plain pointer, no barrier cost
        children.append(c)
        return c

own var doc = new estate Node("root")
doc.addChild("a").addChild("b")
doc = nil                            // whole tree freed at settlement; cycles irrelevant
```
Parent pointers are ordinary pointers within one estate, so no `weak` is needed. Removing a node from a live tree does not free it until the tree's estate closes. If subtrees are pruned often, give each one its own estate: `own var subtrees: List of Node` with `new estate Node(..)`. A child's `parent` then points back into the parent estate. That is a lien, which the court clears when both close together.

### (c) UI callback capturing `self` — the crux
```
illustrative only — not a syntax decision
class EditorWindow
    var text = ""
    var dirty = false
    var saveButton: Button
    init()
        saveButton = Button("Save")                  // in the window's estate
        saveButton.onTap = { self.save(); self.dirty = false }
        // closure object is in the window's estate; capturing self is same-estate: free
    fun save() { Disk.write(path, text) }

class App
    own var windows: List of EditorWindow
    fun open()  { windows.append(new estate EditorWindow()) }
    fun close(w: EditorWindow) { windows.remove(w) }  // deed dropped
```
The window, its button, the closure and the cycle between them form one estate. Closing the window drops the deed, and at the end of the event turn the whole estate is freed in one bulk operation. That is safe even if the close happens inside `onTap`, because nothing is freed mid-turn. No `weak self`, no `[unowned]`, no capture lists. A trickier case is a toolbar in a long-lived window that captures a document living in a separate estate. A strong capture keeps the document in receivership until the toolbar goes away. `lease doc` in the capture list makes the callback do nothing once the document is closed:
```
illustrative only — not a syntax decision
toolbar.onPrint = { lease doc -> if let d = doc { d.print() } }
```

### (d) Shared mutable cache used by two components
```
illustrative only — not a syntax decision
class Cache
    own var entries: Map of String to Entry
    fun get(k: String) -> Entry
        if not entries.has(k)
            entries[k] = new estate Entry(load(k))   // each entry is its own estate
        return entries[k]                            // plain reference out
    fun evict(k: String) { entries.remove(k) }      // closes that entry's estate

let cache = Cache()                                 // in App estate
own var search  = new estate SearchPane(cache)      // cache ref: lien on App estate (cheap, never closes)
own var preview = new estate PreviewPane(cache)
preview.current = cache.get("x")                    // lien: preview-estate → entry-estate
cache.evict("x")                                    // entry in receivership; preview still safe
```
Eviction never invalidates a component that is still using an entry. The entry is freed when its last lien is released. That happens when `preview.current` is overwritten or the preview's estate closes. If a component wants "use it only if still cached", it declares the field `lease`.

### (e) Pass a large list to a function that mutates it
```
illustrative only — not a syntax decision
fun normalize(mut xs: List of Float)
    let m = xs.max()
    for i in 0..xs.count { xs[i] = xs[i] / m }

normalize(mut self.samples)   // escrow: moved out, mutated in place, moved back; zero copies
```
The list cannot be aliased while it is being mutated, because it is not in its home during the call. No borrow checker is involved.

### (f) Sharing data between threads
```
illustrative only — not a syntax decision
own var job = new estate Batch(rows)
worker.send(job)                       // ok: Batch has no liens in or out; chunks transfer, no copy

let table = freeze new estate Lookup(load())   // public record: any thread may read
spawn { use(table.find(k)) }

let stats = trust new estate Stats()
spawn { with stats as s { s.count += 1 } }     // s's estate may not gain refs to/from this thread's estates
```
A `send` that fails (because the estate still has liens) is a runtime error naming the estate and field that hold the lien. Values such as strings and lists are copied across threads freely.

## 7. What's genuinely new vs. the covered options

- **The lifetime handle lives in a heap field, not in a scope.** Scope-bound regions (covered) tie a region to a lexical block and rely on promotion. Here an estate's lifetime is a deed stored in `app.windows` or `cache.entries`. That is exactly the non-nesting case the brief calls hard, and nothing has to be promoted to global.
- **Counting by estate pair, only for stores that cross estates.** ARC (O1/O7) counts every object and every local. This model counts nothing inside an estate and nothing on the stack. Cycles inside an estate are free, so the common UI and tree cycles never need `weak`.
- **Receivership instead of invalidation.** O6 (Vale/Inko) makes dangling references detectable and checks them on use. This model makes them impossible: a reference that crosses estates delays freeing. Revocation (`lease`) is opt-in and checked per estate.
- **Settlement as a language guarantee.** Quiescent-state reclamation (RCU-style) is raised to a semantic rule, "nothing is freed under a running function". That is what lets locals go uncounted and makes "close the window from inside its own button handler" safe.
- **A cycle check over closed estates, not a cycle collector.** O7 scans heap objects. The court looks at a graph whose nodes are the estates closed this turn, usually a handful.
- **Escrow for `mut`.** Exclusive mutation without a borrow checker or dynamic exclusivity flags on every access. The alias is simply not there during the call.
- **Thread transfer of whole estates**, checked in O(lien-table) at runtime with zero copy.

## 8. Known weaknesses

- **Landfill.** Objects discarded inside a long-lived estate (temporary objects made in methods of a long-lived object, nodes removed from a tree) are not freed until the estate closes. Mitigations: collections and strings are values, `estate { }` blocks exist for scratch work, and the programmer can use finer estates. A debug-only "vacancy audit" tool could trace an estate to report garbage. An explicit `refinance` (copy the live part of an estate from its root) would be tracing and needs John's ruling under G2.
- **One lien keeps a whole estate alive.** A 20-byte reference can keep a 50 MB document in receivership. The tooling must answer "why is estate X alive?" with an estate and a field, which debug builds can record per lien.
- **Settlement latency.** Long compute loops that never return to a settlement point accumulate closed estates. `settle` is only allowed in a thread's entry function, and nested modal event loops must not settle.
- **Court and G2.** The court is a reachability check, though only over closed estates. I'd argue it is not a GC run (no heap scan, timing is deterministic, cost is bounded by estates closed this turn), but it should be flagged `needs-john`.
- **Several errors appear only at runtime**: a `send` blocked by liens, a write to a frozen estate, a jurisdiction breach in `trust`, reading an escrowed home. They have precise messages, but they are not compile errors.
- **Choosing estates is a design decision.** It is where the programmer's knowledge of lifetimes is expressed, but it is still a decision. A wrong choice costs memory, not safety.
- **G3 questions.** `own` and `lease` are type-modifier keywords, similar to `weak`, and need a ruling. `List of X` / `Map of K to V` depend on the pending ruling on built-in parameterised containers.
- **Barrier cost.** Every object-reference field store pays the same-estate check. Frozen-estate detection on stores within an estate needs an extra state load.
