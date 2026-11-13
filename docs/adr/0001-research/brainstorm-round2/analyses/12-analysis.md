# Analysis 12: Whereabouts

Analyst: independent. Inputs: brief.md, round2.md, CHARTER.md, ideas/12-whereabouts.md.

## 1. The idea in three sentences

The heap is an in-process relational database with one table per `record` class. A record-typed variable holds a key or query instead of a pointer, so following it re-runs the lookup; calls and writes apply to every match, and zero matches is a silent no-op. Records die only by `drop` or when their class's `exists while` condition goes false; that condition must refer only to earlier classes or to the same class at a strictly shorter key. Everything else is a value, and threads share the world through optimistic transactions whose boundaries are IO and `wait`.

## 2. Prior art: a known paradigm, with one new twist

- **Eve** (Chris Granger et al., 2014–2018): the whole program state is one record database. Code is `search`/`bind`/`commit` blocks over records matched by attributes, and blocks can't call each other directly. This is the closest ancestor of "the heap is a DB and references are questions". It was abandoned before reaching production use. https://hackernoon.com/the-rock-solid-foundation-for-eves-big-vision-225b80b91e11 , https://witheve.github.io/assets/docs/SyntaxReference.pdf
- **Out of the Tar Pit** (Moseley & Marks, 2006), "Functional Relational Programming": all essential state lives in relations, with no pointers. It was proposed but never built as a native language. https://www.recurse.com/blog/51-paper-of-the-out-of-the-tar-pit
- **ECS** (flecs, Bevy): typed tables, entity ids, queries. The idea calls itself "ECS promoted to the only heap model".
- **`exists while`** is SQL `ON DELETE CASCADE` or Core Data's delete rules, written as predicates. https://developer.apple.com/documentation/coredata/configuring-relationships.md
- **The heap as a relation** at the low level: paniq's "Low-Level Datalog". https://gist.github.com/paniq/484dfd1a25efd4d192e7a21de56550d3
- **The concurrency model** is STM. Microsoft dropped STM.NET in 2010 after a large investment. https://www.infoq.com/news/2010/05/STM-Dropped

**What is new:** two things. First, using the relational heap as the answer to the *memory-management* problem in a natively compiled, GC-free language. Second, the static well-foundedness rule (earlier class, or strictly shorter key), which guarantees that cascades terminate without any reachability analysis. The paradigm itself is not new; it is Eve/FRP plus ECS.

## 3. Soundness: counterexamples (illustrative only, not a syntax decision)

**C1. Silent data loss, because "missing is a non-event".**
```
record Account key id: fresh  balance: Money
fun transfer(from: Account, to: Account, amt: Money) {
  from.balance -= amt        // from exists
  to.balance   += amt        // `to` was dropped by a bug: matches 0 rows, no error
}
```
Money disappears and nothing is reported. The same happens in (c): if the Editor was cascaded away by mistake, `me.save()` does nothing and the user's edit is lost. Use-after-free became *silent* logic failure, which for a banking-style domain is worse than a crash. To be safe, every write that matters has to be spelled `the Q else {fail}`. Weakness #1 understates this: the danger is not `the` failing, it is plain writes *not* failing.

**C2. Atomicity changes when someone adds a log line.**
```
spawn { for job in each Job(state: .queued) {      // filter evaluated in segment 1
          log("claiming", job)                       // IO: commit point
          job.state = .running; run(job) } }
```
Two workers both see job J as queued in segment 1. Both commit at `log`. Each then sets `.running` in a later segment. A write-write conflict re-runs only the *loser's current segment*, and that segment no longer contains the `state == .queued` check. J runs twice. Any function that might do IO, including a debug print, silently moves the transaction boundary, so check-then-act is only atomic until somebody refactors. This is the classic problem with implicit transaction scopes.

**C3. A cancellation flag that is never seen.**
```
while not the Task(id: t).cancelled { crunch() }    // no IO inside: one transaction
```
The worker reads its own snapshot forever, so the UI thread's `cancelled = true` never becomes visible. Progress writes from the worker are also invisible until the loop ends. To make it work, the programmer has to know to insert `wait`.

**C4. Write skew, unless MVCC is serialisable.** "Optimistic MVCC per row" reads like snapshot isolation. Take two transactions, each checking "at least one OnCall row exists besides me" and each dropping itself. Both commit, and the invariant breaks. Making it serialisable means tracking read sets (SSI), which costs more and makes aborts more likely. The idea doesn't say which.

**C5. Starvation.** A long main-thread segment that scans `each Node` is aborted again and again by short worker writes to Node. Optimistic schemes have no fairness, so UI latency is unbounded.

**C6. Halloween problem and ghost rows during broadcast.**
```
Employee(salary < 1000).raise()      // raise: salary *= 1.1 ; may also `drop` a peer
```
If matches are computed lazily, a row can be raised more than once. If they are snapshotted, a peer dropped by an earlier call still gets `raise()` run on it, because slots stay valid until the end of the transaction. Neither semantics is stated.

**C7. Order-dependent death when a write breaks an `exists while` condition.**
```
e.window = w2            // w2 not created yet: Editor's condition is false right now
new Window(id: w2)
```
If constraints are checked on every write ("incrementally on every write"), the Editor dies on the first line. If checking is deferred to commit, queries in the middle of the transaction see rows that "shouldn't exist". Either way, reordering two lines changes whether an object lives.

**C8. Cascade order and IO inside `on drop`.**
```
record Editor ... on drop { if dirty { promptSave(the Window(id: window.id)) } }
```
The cascade runs top-down, so the Window is already gone and `the` takes its else arm. This is the reverse of RAII destructor order, where children are cleaned up before their parent. Worse, `promptSave` is IO, which is a commit point, so the cascade commits *half done*. Other threads see the Window gone while its Editors are still alive.

**C9. Self-recursive trees can't cascade.** A UI view tree, a DOM or an AST has the shape `View exists while View(id: parent.id)`. That is the same class with a `fresh` key that is not shorter, so rule 6 rejects it. Path keys pass the check, but then reordering or reparenting a view re-keys its whole subtree and breaks every captured key, including `onTap` closures. The structure G11 most needs, a declarative layout tree, is exactly the one where cascading is weakest.

**C10. Shared lifetime can't be expressed.** "Keep a CacheEntry while component A *or* B uses it" would need CacheEntry to exist while some later class refers to it, which the ordering rule forbids. That is deliberate, because otherwise it would be RC. The only choices left are expiry timers or manual `drop`, so shared ownership in (d) is manual memory with a safe failure mode, meaning C1.

**C11. Stateful closures lose their writes.**
```
count = 0;  Button(onTap: { count += 1; label = "\(count)" })
```
Closures capture by value. Either each call increments a copy and the write is lost, or the closure value inside the row is mutated, which is semantics nobody has specified. Either way, every piece of local UI state has to become a record table with a key and an `exists while` condition. In a G11 DSL that is a lot of schema for a counter.

**C12. Hidden O(n) copies.** There is no CoW and no RC, so `show(the CacheEntry(url: u).body)` copies the whole body on every cache hit. "Restore value locals snapshotted at segment start" also copies large locals at every IO point, so a loop that logs once per iteration over a 1M-element local list costs O(n²). The idea calls this "cheap"; that is a hand-wave. Fixing it needs either read-only parameter borrows, which is O4's mechanism, or an undo log.

**C13. FFI calls versus commit points.** `pin the Q` is valid until the end of the transaction. If a C call is an IO point, the pin expires exactly when C receives it. If C calls are not IO points, a blocking `read()` or a C-owned event loop holds one transaction open indefinitely, and with it MVCC versions and conflicts. Toolkits that own the main loop, such as GTK, Cocoa and Win32, make this unavoidable.

**C14. MVCC needs version reclamation.** Old row versions must stay alive until no snapshot can see them. That needs epoch or vacuum-style reclamation (Postgres VACUUM, RCU), which is not tracing but is a background reclamation pass.

Nothing here leaks memory in the unsafe sense or dangles. Every failure is a *logic*, *atomicity* or *performance* failure.

## 4. Scenarios

- **(a) works.** Pure values with move on return.
- **(b) partial.** Path keys cascade but break when a subtree is moved (C9). Id keys can't cascade, and self-recursive classes are rejected by rule 6.
- **(c) works.** This is the best (c) answer seen so far: the callback holds a key, and a missing record is a no-op. The cost is C1 (silent loss), C11 (closure state) and ghost runs.
- **(d) partial.** Access from both components is good, and eviction by query is elegant. "Lives while used" can't be expressed (C10).
- **(e) works.** `edit` params work, but reading a field out of a record copies it (C12).
- **(f) hand-wave.** Race-free by construction is the claim. C2–C5 show that the atomicity unit is invisible and unstable.

## 5. Gates and charter

- **G2: pass.** Nothing is traced and nothing is reclaimed by reachability. MVCC version reclamation (C14) is epoch-based, not a GC run, but flag it if "no collection pass of any kind" is the intended reading. With the idea's own fallback (one world per thread, values copied between worlds), it is a clean pass.
- **G3: pass**, with the shared **needs-john** flag on `List of T`, `Map` and the iterator type `each Node`. `record`, `key`, `exists while`, `fresh` and `edit` are keywords, not annotations.
- **Other goals:**
  - **G1 is strained.** Every class becomes a schema-design decision: keys, existence conditions, query cardinality.
  - **G4 is strained.** `the … else` appears wherever the code needs safety.
  - **P-PY is partial.** Implicit `self` works, but inheritance and polymorphic dispatch over tables are unspecified.
  - **G8 and G10 are strongly *helped*.** You get a heap REPL, `assert count Editor(window: w) == 0`, and "why does this row exist?".

## 6. Score

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity | 25 | 2 | Only 10 rules, but rules 3, 4, 6 and 10 are large: cardinality words, broadcast, schema and existence design, invisible transactions, and value-only copying everywhere |
| Memory safety | 15 | 5 | No pointers, no dangling, no UB on a missing record. The failures are logic failures (C1), not memory failures |
| Expressiveness (b, c, d, OO) | 15 | 3 | (c) is excellent. (b) and (d) are partial, stateful closures need tables, and OO inheritance is unspecified |
| Implementation risk | 15 | 1 | Incremental trigger and constraint maintenance, MVCC with segment re-execution, whole-program query shapes plus range indexes, Halloween semantics, FFI and transaction interplay |
| Performance & predictability | 10 | 2 | The slot-hint fast path is fine. Against it: index write amplification, copies out of rows, snapshot copies, abort and retry, cascade spikes |
| Concurrency fit | 10 | 3 | No data races, but implicit boundaries (C2), invisible flags (C3), write skew (C4) and starvation (C5) |
| Tooling, debug & FFI | 10 | 3 | The DB-style debugger and leak tests are outstanding. Against it: FFI only through per-transaction pins and copies, and re-executed segments hit breakpoints twice |

Total = 25·2/5 + 15·5/5 + 15·3/5 + 15·1/5 + 10·2/5 + 10·3/5 + 10·3/5 = 10 + 15 + 9 + 3 + 4 + 6 + 6 = **53**.

With the per-thread-world fallback, implementation risk goes 1→2 (+3) and concurrency stays at 3, giving roughly 56. Either way it is well below O1 (83) and O4 (82), and below round 1's best (68). The inventor's self-score of 68 overrates simplicity and implementation risk.

## 7. What the premise teaches

1. **Most "pointers" in application code are relationships, not ownership.** Relationships want three things ARC and borrows don't give: reverse navigation (children, a doc's editors), cascade (close a window and its parts go), and safe absence. The UI crux (c) gets easier as soon as identity is a value that may name nobody. Weak refs and generational handles already do that, but piecemeal.
2. **"Missing is a non-event" is safe but swallows errors.** Any adopted form must make absence *loud by default on writes* and quiet only where you opt in, as with `?.` in Swift.
3. **Lifetime as a declared, statically well-founded condition** is a new middle ground between reachability (RC/GC) and manual free. The well-foundedness check is the bit worth remembering: a cascade that the compiler proves terminates, with no inference.
4. **A heap you can query is a debugging superpower**, and that does not depend on the rest of the mechanism.

**Salvageable kernel (adoptable into O1 or O4):**
- **Debug-build live-object registry (strong recommendation).** In debug and test builds the runtime keeps a per-class list of live instances. The debugger gets `count Editor`, `Editor where doc == "a.txt"`, and "why is this alive?", which shows the retain chain under O1 (the inverse of `exists while`). The unit-test library gets leak assertions such as `assert live(Editor) == 0` after closing a window. It is cheap, needs no new language rules, and directly serves G8, G9 and G10. It also catches O1's main weakness, cycle leaks, in tests.
- **Optional:** a compiler-known `Table` store with declared cascade and automatically maintained reverse indexes, for relationship-heavy data in (b) and (d). It is an upgrade to the already-covered "slot maps as library tools" and should be kept out of the core model.

## 8. Verdict

**Kernel worth stealing.** As a memory model it is the Eve/FRP relational heap, carrying a high-risk STM layer and a silent-no-op failure mode. Its debug and query view of the heap, plus leak assertions in tests, should go into O1 or O4.
