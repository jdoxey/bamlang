# 12 — Whereabouts

## 1. Name

**Whereabouts**: you never have an object, only its whereabouts, meaning a question that finds it.

## 2. The crazy premise

**Sacred assumption broken: a program holds references to objects.** Every language on the covered list has *something* that names a heap object: a pointer, an RC handle, a weak ref, a borrow, a generational index. Whereabouts has none. The heap is a database of tables, one per class. A variable of class type holds a **query**: the key values of the record, or any field predicate. Following a "reference" re-asks the question. If the answer is "nobody", that is a normal result, not a dangling pointer.

Consequences that every sane design treats as unavoidable but which vanish here:
- No aliasing between heap objects, so no reference cycles, ever. Nothing retains anything.
- No dangling: a query for a dropped record matches zero rows.
- No reference counting at all, not even hidden in the runtime for heap records.
- Lifetime is not "until unreachable". It is "until dropped, or until a declared condition about the world stops being true".

## 3. Pitch

Think of the program's memory as a small, fast, in-process relational database that the compiler designs for you. Classes are tables, fields are columns, and the key fields are the identity. `Editor(doc: d)` is not a pointer. It is the question "the editor whose document is d". Calling a method on a question runs it on every record that matches, and zero matches is fine. That is SQL `UPDATE ... WHERE` semantics, and it makes "missing" a non-event instead of a null crash. A record lives until you `drop` it or until its class's `exists while` condition goes false, for example "an Editor exists while its Window exists". The runtime enforces that condition incrementally on every write, the way a database enforces `ON DELETE CASCADE`. Closures capture only values, and keys are values, so a UI callback can't keep anything alive and can't create a cycle. Reverse navigation (a node's children, a document's editors) is free: you just ask, and the compiler builds the index because it has seen every question the program asks.

## 4. The rules

1. **Two kinds of type.** *Values* (numbers, text, structs, `List`, `Map`, closures) are copied, or moved on last use. *Records* are declared with `record` and live in their class's table. Nothing else exists.
2. **Records have keys.** Each record class names its key fields. `fresh` makes a never-reused 64-bit id. Keys are immutable. Creating a record whose key already exists is an error, unless you write `new or update`.
3. **A record-typed variable or field holds a question, not a record.** `e: Editor` stores Editor's key. `Editor(doc: d)` asks by any fields, key or not. Nothing is fetched until you use it.
4. **Questions match 0..n records.**
   - Calls and assignments through a question apply to *every* match: `Q.save()`, `Q.title = t`.
   - Reading a value out needs a count word:
     - `the Q`: exactly one, otherwise run the `else` arm.
     - `each Q`: loop over the matches.
     - `count Q`.
     - `if Q as x`: zero or one.
5. **`self` is implicit.** Inside a method, fields refer to the one record being run on.
6. **Records end in exactly two ways:**
   - `drop Q` removes every match.
   - The class's `exists while <condition>` goes false.
   
   The condition may refer only to classes declared *earlier* in the dependency order, or to the same class at a *strictly shorter key* (for example `path.parent`). The compiler checks this, so a chain of existence conditions always bottoms out.
7. **`on drop { }`** runs when a record leaves. Use it to release C resources or to notify.
8. **Closures capture values only.** A captured record is a captured key.
9. **`edit` parameters** mutate the caller's value variable in place, exclusively. It is the only parameter mode besides plain by-value.
10. **Concurrency.** All threads share one world. Code between two IO or `wait` points runs as one transaction. If two transactions conflict, one segment is re-run. Values cross threads by copy.

That is ten rules. Rules 3, 4 and 6 are the new ones. The rest exist in some form in every language.

## 5. Under the hood

- **Tables.** Each record class is a slot-array table plus a key→slot hash index. A key value carries a hidden *slot hint* `(id, slot)`. A lookup checks `table[slot].id == id` and falls back to the hash only on a miss. So the common case is a generational-index lookup: one load and one compare. *Semantically*, though, it is still a query. A miss is "no match", never UB.
- **Compiler-built indexes.** Programs are compiled whole (G7 deps are source). The compiler collects every query *shape*, for example `Editor(doc:)` or `Node(parent:)`, and gives each shape a hash multi-index that is kept up to date on writes. There are no dynamic queries, so no shape is ever unindexed. `Node(parent*: n)` is the transitive-closure form. It is computed with set semantics, so it terminates even on cyclic data.
- **Existence maintenance.** `exists while` compiles to triggers on the tables the condition mentions. Dropping a Window walks the `Editor(window:)` index and drops the matching rows, which cascade further. Work is proportional to the rows that actually die, and nothing is traced from roots. Because of the well-foundedness check (rule 6), the maintenance is plain cascading and needs no fixpoint or delete-and-rederive. Time conditions such as `expires > now` register in a timer heap.
- **Freeing.** A dropped row disappears from queries immediately. Its slot is reclaimed at the end of the current transaction, so method frames running on that row stay valid. Within a transaction, slots never move, so the compiler resolves `self` and any repeated lookups once per method.
- **Values.** Values have no aliases because no references exist. Copy on assignment, move on last use (local liveness only), and `edit` for in-place mutation. Value buffers need no RC and no CoW.
- **Concurrency.** Optimistic MVCC per row. The transaction boundaries are IO calls and `wait`. Re-running a segment means restoring the value locals snapshotted at the segment start, which is cheap because locals are values. IO is the commit point, so it is never repeated.
- **FFI.** A C pointer is a value of type `Foreign`, stored in a record whose `on drop` frees it. Passing a record to C copies its fields into a C struct. `pin the Q` gives a raw pointer valid until the end of the transaction.
- **Debugger.** The heap *is* a database. In the debugger you can type `Editor(doc: "a.txt")`, `count Node`, or "why does this row exist?", which shows its `exists while` chain. A leak report lists rows in condition-less tables, with their age.

## 6. Scenarios (illustrative only — not a syntax decision)

**(a) File → list of lines.** Pure values. No records needed.
```
fun readLines(path: Text) -> List of Text {
  lines = List of Text()
  for line in File.open(path).lines { lines.add(line) }   // grows; moved out on return
  return lines
}
```

**(b) Tree with parent pointers.** Two styles.

Style 1: path-keyed. Existence is well-founded because `path.parent` is strictly shorter. Dropping a node cascades to its whole subtree.
```
record Node key path: List of Text
  label: Text
  exists while path.isEmpty or Node(path: path.parent)
  fun parent -> Node { return Node(path: path.parent) }   // a question
  fun children -> each Node { return each Node(parentPath: path) }  // indexed reverse lookup
```

Style 2: id-keyed, with an explicit subtree drop.
```
record Item key id: fresh
  parent: Item                                   // holds a key; may name nobody
  fun subtreeDrop { drop Item(parent*: self); drop self }
```
In both styles, children are not stored. You ask for them. Parent and child can't form a cycle because neither holds the other.

**(c) UI callback, the crux.**
```
record Window key id: fresh
record Editor key id: fresh
  window: Window
  doc: Text
  dirty: Bool
  exists while Window(id: window.id)
  fun save { File.write(doc, render()); dirty = false }
  fun build {
    me = self                                    // a key value
    new Button(window: window, label: "Save", onTap: { me.save() })
  }
record Button key id: fresh
  window: Window
  label: Text
  onTap: fun()
  exists while Window(id: window.id)
```
`drop Window(id: w)` removes the window, then every Editor and Button in it. A late tap on a Button that is already gone can't happen, because the Button left the dispatch table. If a closure stashed elsewhere runs later, `me.save()` matches nothing and does nothing. That is not a special no-op mechanism. It is the universal meaning of a question nobody answers. There is no capture list, no `weak`, and no cycle to break.

**(d) Shared mutable cache used by two components.**
```
record CacheEntry key url: Text
  body: Bytes
  lastUsed: Time
  expires: Time
  exists while expires > now
// component A
if CacheEntry(url: u) as c { c.lastUsed = now; show(c.body) } else { fetchInto(u) }
// component B, unrelated, same world
drop CacheEntry(lastUsed < now - 10.minutes)     // bulk eviction is just a query
```
Neither component owns the cache, and neither holds it. Both ask the world.

**(e) Pass a large list to a function that mutates it.**
```
fun dedupe(edit xs: List of Text) { ... in place ... }
dedupe(edit lines)                         // value in a local
dedupe(edit the Doc(id: k).lines)          // or a record field, mutated in its row
```

**(f) Sharing data between threads.**
```
spawn { for job in each Job(state: .queued) { job.state = .running; r = run(job); Result.new(job: job, out: r) } }
spawn { for r in each Result() { log(the r.out); drop r } }
```
The world is shared and nothing is a pointer, so there are no data races by construction. Two workers claiming the same Job is a write conflict, and the loser's segment re-runs. A typical Mutex+Arc program becomes a set of plain queries.

## 7. What is new

- **No reference type exists at all**, unlike O2, which keeps handles as an escape hatch. Identity is a *content-addressed question*, so aliasing, cycles, retain/release and dangling are not dealt with case by case. They cannot be expressed.
- **Missing is a non-event.** Broadcast semantics over 0..n matches replaces both null and weak refs. You need `the` only when you actually need a value.
- **Lifetime by declared truth.** `exists while` is a condition over the world, kept up to date like a database constraint. It is not reachability, so it is not GC. The compiler's well-foundedness check (earlier class or strictly shorter key) rules out cyclic existence statically.
- **Reverse navigation is free.** Parent→children, doc→editors and window→buttons are queries backed by compiler-chosen indexes. Nobody maintains back-pointer lists.
- **The heap is inspectable as a database**, in the debugger, in tests (`assert count Editor(window: w) == 0` after closing), and in leak reports.
- It is like ECS promoted from library pattern to the *only* heap model, with typed tables, implicit `self`, closures and transactions.

## 8. Why it might be less crazy than it sounds, or more

**Less crazy:**
- Games already do this (ECS), web backends already do this (the DB is the heap, and rows reference rows by key), and Datomic, Erlang ETS and Smalltalk images are cousins.
- The slot hint makes the fast path the same as Vale/slot-map handle performance.
- The well-foundedness rule is a syntactic check, not inference.
- For the crux scenario (c), it is the only design here where the right answer needs zero extra concepts. The callback holds a key, and the key may name nobody.

**More crazy:**
- Every hop between objects is a lookup, with possible broadcast. Programmers raised on pointers will find `the` friction everywhere.
- The concurrency model is STM, and STM has a long history of disappointing in practice.
- Domain keys bring database ABA semantics into application code. Drop the editor for "a.txt", open a new one for the same file, and old closures now talk to the new editor. Sometimes that is a feature. `fresh` keys avoid it.

**Self-assessment (out of 100):**

| Criterion | Score (1–5) | Weighted |
|---|---|---|
| Simplicity | 3 | 15 |
| Safety | 5 | 15 |
| Expressiveness | 4 | 12 |
| Implementation risk | 2 | 6 |
| Performance | 3 | 6 |
| Concurrency | 4 | 8 |
| Tooling/FFI | 3 | 6 |
| **Total** | | **≈68** |

If analysts judge STM too risky, the fallback is one world per thread with values copied between worlds. That costs about 4 points of concurrency and gains about 3 of implementation risk.

## 9. Known weaknesses

1. **Null crashes reborn as `the` failures.** Memory-safe and explicit about where they happen, but the logic bug class survives. Programmers may write `the` everywhere.
2. **Logical leaks in condition-less tables.** A root record nobody drops lives forever. It is safe and visible in the debugger, but it is still a leak. This is the honest equivalent of a "forgotten free".
3. **Schema design burden.** Choosing keys and `exists while` conditions is database design. Moving a path-keyed subtree means re-keying it, which breaks keys held elsewhere. Id-keyed trees avoid that, but they lose cascade and need an explicit `parent*` drop.
4. **Accidental broadcast.** `Editor(doc: d).close()` closes *all* editors on that doc. That is sometimes right and occasionally a surprise.
5. **Performance unpredictability.**
   - A cascade drop can delete thousands of rows synchronously. It is predictable and caused by the program, like freeing a large RC tree, but it is a latency spike.
   - Every query shape adds index maintenance on writes.
6. **The gates:**
   - **G2 passes.** There is no tracing and no collection run. Work is triggered only by writes and is proportional to the rows that die.
   - **G3:**
     - `key`, `exists while` and `record` are keywords, not annotations.
     - `List of T` and `Map` are the pending built-in-container question. **Flagged.**
     - The transaction boundary is implicit, so no annotation is needed there.
   - **Determinism:** concurrent programs are serialisable but their schedule is not deterministic, the same as any threaded language.
7. **FFI friction.** C APIs that want long-lived pointers into your objects get only `pin` (valid per transaction) or copies. Callbacks from C must carry keys, which is fine for `void*` user-data but awkward for intrusive structures.
8. **Implementation risk is concentrated in four places:**
   - incremental index and trigger maintenance,
   - MVCC with segment re-execution,
   - whole-program query-shape analysis,
   - the debugger's query REPL.
   
   Each is well understood in databases but new to an LLVM language runtime.
