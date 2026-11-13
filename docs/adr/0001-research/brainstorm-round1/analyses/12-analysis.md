# Analysis 12 — Circulation

Analyst: independent. Inputs: brief.md, CHARTER.md, ideas/12-circulation.md only.
All code is illustrative only — not a syntax decision.

## 1. Restatement

1. Every class instance has exactly one owner slot, so ownership forms a tree. Every other reference is a non-owning "loan".
2. The strength of a loan depends on where it is stored, not on anything the programmer writes:
   - A loan in a local or parameter *pins* the object. A free that is requested during the pin is deferred until the scope exits.
   - A loan in a field, collection or closure capture is registered on an intrusive per-object list, and is eagerly set to `none` when the owner drops the object.
3. A stored closure checks out all of its captures at each call. If any capture is gone, the body is skipped. Threads use `send`, `freeze`, `lend` and mutex-like `desk`s.

## 2. Prior art

The parts are known. The packaging is partly new.

| Circulation piece | Prior art |
|---|---|
| Single owner + non-owning refs, with counting to keep it safe | Gel / "Ownership You Can Count On" (Dingle & Bacon, IBM, 2007): https://researcher.watson.ibm.com/researcher/files/us-bacon/Dingle07Ownership.pdf (discussion: https://digitalmars.com/d/archives/digitalmars/D/Ownership_You_Can_Count_On_355291.html). From memory, not re-verified: Gel reports an error if an owner is destroyed while refs remain. Circulation instead defers the free for stack refs and nulls heap refs. |
| Stack borrows that pin and defer the free ("reading-room") | Vale borrow refs "tether" the object (https://vale.dev/guide/references). In hybrid-generational memory, a tethered object's free is deferred to the last tethering local or a queue (https://verdagon.dev/blog/hybrid-generational-memory). This is essentially the same mechanism. |
| Heap refs that turn to null when the target dies ("take-home") | Vale weak refs (same URL). ObjC zeroing `__weak` keeps a side table of referrer addresses and nulls them all at dealloc (https://opensource.apple.com/source/objc4/objc4-706/runtime/objc-weak.h.auto.html, https://mikeash.com/pyblog/friday-qa-2012-06-01-a-tour-of-plweakcompatibility-part-ii.html). Qt `QPointer` is nulled on QObject destruction (https://doc.qt.io/qt-6.9/qpointer.html). Circulation's "card" is ObjC's weak table, made intrusive. |
| freeze / send / mutex | Standard. Pony, Swift actors, and Rust `Arc<Mutex>` all have equivalents. |

What is genuinely new is the *policy*, not the mechanisms:
- (i) A reference's strength comes from where it is stored: stack refs are strong but nest, heap refs are always weak. So no reference kind is ever declared.
- (ii) All-or-nothing closure checkout as a language rule. Swift users write this by hand with `[weak self] guard let self`, and Rx-style "weakify" helpers wrap it.
- (iii) Ownership is inferred from the first heap store.

In terms of the covered options, this is O6 (Vale) with eager nulling instead of generation checks, plus (i), (ii) and (iii). That is a real contribution, but a narrow one.

## 3. Soundness: counterexamples

**C1. "First shelf wins" lets an observer steal ownership.** The inventor admits order-dependence. This example shows how bad it gets.
```
n = Node()
debugLog.recent.add(n)        // debug line added during triage -> debugLog OWNS n
tree.root.children.add(n)     // tree only holds a take-home loan
...
debugLog.recent.removeFirst() // ring buffer rotates -> n withdrawn
// tree.root.children[k] is now none; node silently vanishes from the tree
```
- Adding one logging line deletes data somewhere else.
- The same thing happens across function boundaries. `fun register(x) { registry.add(x) }` owns or lends depending on the caller's history. A library author can't know which, and neither can the reader.
- This also means "owner vs loan" is a runtime bit on each object, not a static property. The doc doesn't say this.

**C2. Conditional first store makes a collection hold a mix of owners and loans.**
```
for n in incoming {
  if n.urgent { urgentQ.add(n) }   // owner for urgent ones
  all.add(n)                        // owner for the rest, loan for urgent ones
}
urgentQ.clear()                     // urgent items vanish from `all` too
```
- `all` now holds a mix of owners and loans that the type system can't see.
- `all.clear()` frees half of its elements and only unlinks the other half.

**C3. `lend` races through take-home loans that cross the subtree boundary.**
```
sub = give tree.root.children[0]           // subtree whose root still has .parent -> tree.root
lend sub to spawn {
  r = rootOf(sub)        // walks .parent OUT of the lent subtree into home-branch items
  r.title = "x"          // writes a home item concurrently...
}
tree.root.title = "y"    // ...with the home thread. Data race. Non-atomic pin on r races too.
```
- `send` recalls loans that cross the boundary, but `lend` only retags the branch and hides the variable.
- Two fixes are possible:
  - Check the branch tag on every take-home dereference. That is a cost on every field read, plus a new runtime trap.
  - Recall the crossing loans on `lend`. That destroys the parent pointers, which aren't restored at the join.
- Neither fix is specified. The reverse direction has the same problem: a home field `selection` that points into the lent subtree.

**C4. A desk loan escapes through a pre-declared local.**
```
e = none
reserve stats { e = stats.entries[0] }   // local store, not a heap store -> no trap per rule 10
e.count += 1                              // unlocked mutation of desk-owned item; non-atomic pin
```
Rule 10 traps only on *stores outside the desk*. Locals assigned from inside a `reserve` also need a scoping rule, or a tag check on every pin.

**C5. Deadlock.** `reserve a { reserve b {..} }` on one thread and `reserve b { reserve a {..} }` on another. FIFO ordering doesn't prevent lock-order inversion. This is no worse than O1 or O4 with mutexes, but it is not addressed.

**C6. Zombie objects.**
```
fun pick() { h = Holder(); h.child = Node(); return h.child }  // h withdrawn at return; child pinned
c = pick()                // c: readable, mutable, but already withdrawn
self.current = c          // take-home loan to a withdrawn item -> immediately none
c.kids.add(Node())        // fresh node shelved inside a zombie; freed when c's scope ends
```
- Nothing dangles, but you get a live-looking object that "can't be kept". This is a new state users must understand.
- O1 has no such state: in O1 the returned reference simply keeps the object alive.

**C7. Closures that return values, or that mutate captured values.**
- Rule 8 makes a recalled closure "return `none`". So any capturing closure of type `(A)->B` really has type `(A)->B?`.
  - Example: a comparator `{ a, b -> a.rank(self.weights) < b.rank(self.weights) }` captures `self`.
  - If `self` is recalled during `sort`, the comparator returns `none`, and `sort` must handle it. That is surprising behaviour in a core library.
- Captured *values* such as `count = 0; xs.forEach { count += 1 }` aren't specified.
  - If values are copied into the closure, `count` stays 0. That breaks the accumulator pattern that DSLs (G11) rely on.
  - If they are boxed, the boxes are heap items with no defined shelf.

**C8. Async, generators and iterators.** If the language ever has coroutines, a suspended frame is a heap object holding reading-room pins.
- The idea's premise was "stack lifetimes always nest", and that no longer holds.
- A coroutine that is stored and never resumed pins its targets forever, which is a leak.
- A closure that awaits holds its all-or-nothing pin across the suspension.
- This isn't addressed. It matters for UI (G11).

**C9. Value records with item fields.**
- "Small records are values, copied." The idea doesn't say what happens when a record contains an item field.
  - Copying an owning field breaks the single-owner rule.
  - Copying a take-home field needs the intrusive links patched, and those links now point into stack memory.
- Either records can't contain items (an expressiveness hit), or every record copy or move runs link-patching code. That is a hidden rule plus a hidden cost.

No genuine use-after-free was found within the single-threaded rules. Eager nulling plus pin-deferred free is sound if implemented correctly. The holes are C3 and C4, which are races in the thread rules, and C1, C2 and C6, which are behaviour that is correct but surprising.

## 4. Scenarios

| | Verdict |
|---|---|
| (a) | **Works.** Value list, plain growable buffer, no loans. |
| (b) | **Works well.** Owner edges go down, loans go up, and removing a subtree nulls outside selections. This is the strongest showing. Parent pointers become a hazard across threads (C3). |
| (c) | **Works, and is the best in the brief for zero ceremony.** No cycle, no capture list, and safe re-entrant close. The costs are silent no-ops, the "no shelf" foot-gun, and optional return types (C7). |
| (d) | **Works if someone explicitly owns the cache.** Eviction while in use is safe. "Last user frees" lifetimes need a hand-written count. |
| (e) | **Works.** Pointer plus pin, no copy. Removed items stay readable while pinned, a mild zombie case. |
| (f) | **Partly hand-waved.** `send` and `freeze` are fine. `lend` is unsound as specified (C3). The desk escape hole is C4. Deadlocks are unaddressed (C5). Several runtime traps. |

## 5. Gates

- **G2: pass.** There is no tracing and no background run. Frees happen at overwrite, scope exit or `withdraw`. The recall walk is O(aliases) at a deterministic point, which is no more a "GC run" than ARC's cascading release is. The returns cart is drained by pin decrements, not by a collector.
- **G3: pass, conditional on the pending container question.** No annotations, generics or macros. `give`, `withdraw`, `freeze`, `send`, `lend`, `desk` and `reserve` are keywords. Item-holding `List`/`Map` need compiler-known element layout, since slots are 3 words with links. This is the same pending question as every option, so flag it for John but don't fail it.

## 6. Scores

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 3 | You never choose weak or strong. But the rules are implicit and dynamic: first-shelf order (C1, C2), zombies (C6), optional fields everywhere, closures returning `none`, plus `give`, `withdraw`, `freeze`, `send`, `lend` and `desk`. The rule count is about O4's, and it is harder to reason about locally than O1. |
| Memory safety | 15 | 4 | Single-threaded code never dangles, by construction, and has no leaks from cycles. The thread rules have race holes (C3, C4). Silent `none` hides logic errors. |
| Expressiveness (b, c, d, OO + self) | 15 | 4 | (b) and (c) are excellent and implicit `self` is free. (d) needs an explicit owner. There's no shared-lifetime case. Closure value and return semantics have gaps (C7). |
| Implementation risk (AI-written, LLVM) | 15 | 2 | Every item store relinks a doubly linked list. Buffers holding loans need relocation patching (realloc, sort, swap). A dynamic shelf bit. Pin-elision analysis. Cascade-skipping logic. Branch tags, desk-escape checks, and record-copy patching (C9). Many subtle invariants, and an error in any of them is memory corruption. |
| Performance & predictability | 10 | 3 | Fully deterministic with no atomics in the common case. But every slot is 3 words, a store touches up to 3 extra cache lines (costlier than an ARC retain/release), sort is O(n log n) relinks, recall spikes scale with aliases, and there are per-call pins on capturing closures. |
| Concurrency fit | 10 | 3 | Non-atomic by default is good, and freeze/send/desk is a reasonable trio. `lend` is unsound as written, there are several runtime traps, and deadlock isn't addressed. |
| Tooling, debuggability & C FFI | 10 | 3 | The circulation view is genuinely good and nulls are observable. But item fields aren't plain C layout (3-word slots). C code can't write item fields without calling into the runtime. Long-lived C pointers need `pin_forever`. |

Total = (25·3 + 15·4 + 15·4 + 15·2 + 10·3 + 10·3 + 10·3) / 5
     = (75 + 60 + 60 + 30 + 30 + 30 + 30) / 5 = 315 / 5 = **63**

Comparison:
- **O1 (83):** Circulation loses 20 points, mostly on simplicity (−10 vs an O1 score of 5), implementation risk (−6 to −9) and tooling/FFI. It wins only on (c) ergonomics and on having no possible cycles.
- **O4 (82):** O4 gets the "stack borrows are safe" benefit statically, with no pin traffic, and its `shared` RC covers "last user frees", which Circulation can't express.
- **O6 (71):** Circulation lands below O6, its nearest relative. It swaps cheap lazy generation checks for costly eager intrusive lists.

## 7. Fatal flaw and salvageable kernel

**Fatal flaw:** ownership is inferred from the order of heap stores at runtime ("first shelf wins").
- It is the one thing that makes the model annotation-free.
- It is also the thing that makes it non-local: a log line can delete a tree node (C1), and collections hold an invisible mix of owners and loans (C2).
- Making ownership explicit (`own`/`give` everywhere) fixes this, but then it becomes O4/O6 with eager weak refs.
- The intrusive-card runtime is the second-biggest problem. It is high-risk for an AI-written compiler, and it costs more per store than ARC.

**Kernel worth stealing.** In priority order:
1. **All-or-nothing weak checkout for escaping closures (into O1).**
   - Closures stored in heap slots capture class instances weakly by default.
   - On each call, the runtime upgrades all captures. If any is nil, the call is skipped. Otherwise each capture is held strongly for the call's duration.
   - This removes `[weak self] guard let self` and callback cycles in O1 with zero syntax, which is O1's main (c) weakness.
   - Non-escaping closures (`forEach`, `sort`) keep strong captures, which avoids C7.
2. **"Stack strong, field weak" as a default heuristic (into O4).** Parameter borrows are already stack-only in O4. Make stored non-owning references weak-and-nulled by default, so users never pick a reference kind.
3. **The debugger's circulation view** (owner chain, holders, pending free). It works for any RC or ownership model.

## 8. Verdict

**Kernel worth stealing.** Single-threaded safety is sound, and the treatment of (c) is excellent. The scheme loses to O1 and O4 on simplicity, implementation risk and runtime cost. Its one real new idea, all-or-nothing weak checkout for escaping closures, transplants cleanly into O1.
