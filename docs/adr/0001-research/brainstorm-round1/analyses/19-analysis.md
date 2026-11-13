# Analysis 19: Dominion (dominator-relative references over a containment tree)

Analyst: independent. Sources: brief.md, CHARTER.md, ideas/19. Code is illustrative only, not a syntax decision.

## 1. The idea in three sentences

Every object has exactly one owner, so the heap is a tree rooted at each thread. A reference that does not own is stored as a position in that tree, not as an address: either "my nearest enclosing `Editor`" (`Up`) or "from our lowest common ancestor, follow this slot path, then check this uid" (`Link`). Following a reference walks the live tree and returns `none` if the target has gone. Removed subtrees go to a per-thread graveyard that is freed at inferred "quiescent points" (the end of a turn), so raw pointers on the stack need no borrow rules.

## 2. Prior art: what is new and what is a rename

Mostly a recombination of known pieces. The genuinely new part is narrow.

| Piece | Known as |
|---|---|
| Ownership tree; parent deletes children | Qt's QObject trees: parent destruction deletes children ([Qt docs](https://doc.qt.io/qt-6.9/objecttrees.html)). Also O4 and single ownership generally. |
| `link T` that reads as `none` once the target is gone | Qt `QPointer` ([KDAB](https://old-www.kdab.com/psa-qpointer-has-a-terrible-name)), O1 weak refs, O6 generation checks. |
| `outer T` (nearest enclosing ancestor of a type) | Flutter `findAncestorStateOfType` ([api.flutter.dev](https://api.flutter.dev/flutter/widgets/BuildContext/findAncestorStateOfType.html)), DOM `closest()`, SwiftUI/React context. |
| Owners as dominators | Ownership types (Clarke, Potter and Noble, OOPSLA 1998). My search for this returned only noise, so no URL. |
| Owning pointers plus checked non-owning pointers | Gel / "Ownership You Can Count On" (Dingle and Bacon), discussed for Nim and D ([D list](https://lists.puremagic.com/pipermail/digitalmars-d/2021-November/321376.html)). |
| Free at quiescent points | QSBR/RCU. CPython's free-threaded build uses it ([CPython QSBR](https://chromium.googlesource.com/external/github.com/python/cpython/+/18f3c59e57e5d30218210136060310310b10ff72/InternalDocs/qsbr.md)). Also ObjC autorelease pools drained once per run-loop turn. |
| Send a subtree in O(1); lend disjoint parts | Pony `iso`, Rust `Send` with `rayon::join`, Hylo. |

**Genuinely new:**
- Deciding up versus sideways with a dominance test when the reference is stored, instead of having the programmer choose weak or strong.
- Encoding sideways links as an LCA anchor plus a path, with no handle table.
- Automatically capturing `self` as an upward reference when the closure is stored inside `self`'s own subtree.

I know no shipped system that does these. The rest is relabelled.

## 3. Soundness: counterexamples

**C1. Moving an object silently breaks every link from outside.** A `Link` is a path from the LCA, so identity does not survive a move. Yet the idea offers moving a subtree as *the* answer to lifetimes that don't nest.
```
app.clock.onTick(fn() { editor.refresh() })   // Link(App, windows[#3].editor, uid)
tabs.tearOff(editor)  // move editor into windows[#9]; editor is alive
// tick: walk App -> windows[#3] -> .editor: uid mismatch -> none. Callback is dead, no error.
```
The same happens to a tree view's `selected: link Node` when the user drags that node to a new parent in (b). The editor is alive, but nothing outside it can find it. Fixing this needs a global uid-to-object index, and that index is O6.

**C2. Upward references rebind instead of failing.** The idea's "rebinding surprise" note is too narrow: this is not limited to nested same-class objects. Any move of the holder outside the target's subtree rebinds silently.
```
// Toolbar built inside Editor A; Save button's onTap captured Up(Editor, 0)
editorB.toolbar = move editorA.toolbar   // "toolbar follows focus" pattern
tap Save                                 // saves Editor B, not A
```
So the same capture rule gives two semantics: `Link` returns `none` after a move, while `Up` binds to a different object. A user cannot predict which applies without knowing where the tree's LCA lies.

**C3. Closures cannot own state.** Rule 5 says closures capture as links. Locals belong to the frame, and a frame-anchored link breaks when the frame returns.
```
fn makeCounter() -> fn() -> Int
  let c = Counter()            // contained by this frame
  return fn() { c.inc(); c.value }
let f = makeCounter()
f()                             // c died with the frame: no-op, returns none
// The DSL case is the same: let state = ToggleState(); Button { state.flip() }
```
This is a real G11 cost. Every piece of callback state needs a named field in some ancestor.

**C4. Deadlock: `send` is delivered only at the end of the turn.**
```
fn total(jobs: List of Job) -> Int      // non-root frame: no quiescent point inside
  for j in jobs { worker.send(move j) } // queued in the outbox
  var t = 0
  for _ in jobs { t += worker.receive() } // blocks forever: the outbox never flushes
```
Delivery is deferred because sender locals may hold raw aliases into the subtree, and the model has no alias tracking. Flushing early is therefore unsound. Synchronous request/response, which is the most common message pattern, deadlocks.

**C5. Use-after-free and data race: a raw pointer escapes `lock`.**
```
var p: Item
lock shared { s in p = s.items[0] }     // locals are unrestricted raw pointers
// thread B: lock shared { s in s.items.removeAt(0) }  -> B's graveyard -> freed at B's quiescence
p.count += 1                            // race, then use-after-free
```
Stopping this needs a scoped-escape (borrow) rule, which is exactly what the idea claims it doesn't have.

**C6. Turn-root inference cannot see through re-entry from C or nested run loops.**
```
fn onClose()                          // handler; a raw local follows
  let d = self.doc
  if Dialog.runModal("Discard?")      // nested event loop dispatches the autosave timer
    ...                               // the timer replaces self.doc; its handler returns
                                      //   = "quiescent point" -> old doc freed
  log(d.title)                        // use-after-free
```
GTK signal callbacks and `qsort` comparators that call back into a "turn root" have the same problem. A runtime nesting counter fixes it: free only at depth 0. The cost is that a long modal dialog grows the graveyard without bound.

**C7. Graveyard leak in a server loop.** A quiescent point needs "no borrowed locals live" at the loop back-edge.
```
fn main()
  let srv = Server(); let cfg = srv.config   // a borrow, live across every iteration
  loop { srv.handle(accept()) }              // each request replaces cache entries
// No quiescent point ever: the graveyard grows forever, an effective leak.
```

**C8. Further holes, smaller or fixable:**
- A borrow returned from a block-scoped local dangles: `fn pick(a,b)->Node {return a}; let n = pick(Node(), root)`. The claim that "destruction never happens while a non-root frame is live" contradicts rule 6, which destroys locals at scope end.
- Link caches hold `(pointer, version)` against a *per-thread* counter. After `send`, the receiver can match a stale version from the sender and dereference into the sender's heap. Detaches inside `together` must bump the parent's counter.
- An `outer App` or a lateral link resolved inside a `together` task reaches outside the lent subtree, so two tasks can race on `App.stats`.
- Writing to a link cache during a read is itself a write, which races between tasks.
- A cycle `Shared -> frozen tree -> same Shared` is possible unless frozen trees are banned from holding Shared handles.

## 4. Scenarios

- **(a) Works.** The fast path (a local list that never escaped) is plausible, and strings are values.
- **(b) Works for parent access.** `outer Node` is better than any covered option. But a `selected`/`focus` link breaks when a node is re-parented (C1).
- **(c) Partly.** The canonical case, a closure stored inside `self`, is solved structurally, and auto-unsubscribe for external callbacks is nice. But closures cannot own state (C3), moving the holder rebinds the capture (C2), and tearing off a tab kills external callbacks (C1).
- **(d) Works, with a forced design.** The cache must sit in a common owning ancestor. Swapping in a new cache makes the old links `none` rather than following the new one. That is acceptable but unusual.
- **(e) Works.** Pointer passing; old buffers wait in the graveyard, bounded by geometric growth.
- **(f) Hand-wave.** Request/response deadlocks (C4). Raw pointers escape `lock` (C5). `together` disjointness is never specified: is it checked statically or at runtime by ancestry? Links leaving a lent subtree race.

## 5. Gates

- **G2: pass.** The graveyard free is proportional to garbage, not to the live set. It runs at deterministic points, never traces, and is structurally an autorelease-pool drain. Flag: under C6/C7 the drain becomes rare and large, which *feels* like a GC pause even though it isn't one.
- **G3: pass, with the shared flag.** `link T` is a built-in reference kind with the same status as O1's `weak`, so it should be judged the same way. `outer T` is an expression. No user generics, macros or annotations. The `List of T` flag is pending (needs-john) for every option.

## 6. Scores

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity | 25 | 3 | The "seven rules" hide more. The contain-vs-`link` field choice *is* the weak/strong choice. Users also learn lend/move/copy, turn timing, `none` on every link read, `Up` rebind vs `Link` break, and send-at-turn-end. Every domain has to be fitted to a tree. |
| Memory safety | 15 | 3 | The intent is safe. C5, C6 and C8 are real use-after-free paths, and safety rests on escape and quiescence analyses where any bug is a use-after-free. |
| Expressiveness (b)(c)(d), OO | 15 | 3 | (b) and canonical (c) are best-in-class. They are offset by state-less closures (G11), move-breaks-identity, and silent no-ops. |
| Implementation risk | 15 | 2 | Novel runtime with no reference implementation: 24 B headers, LCA walks, path encoding, lazy slot maps, version caches, graveyard, outboxes, plus two load-bearing whole-program analyses. |
| Performance & predictability | 10 | 3 | No refcount traffic on locals is a real win. But `outer` and link reads are O(depth), links are fat, and any detach anywhere invalidates every cache on the thread, so a link's cost depends on unrelated code. Memory spikes at the end of a turn. |
| Concurrency | 10 | 2 | O(1) subtree transfer is good. Deadlock on send (C4), races via `lock` escape and links out of lent subtrees. |
| Tooling, debug, FFI | 10 | 3 | The tree view and "where resolution broke" are excellent ideas. Silent no-ops hurt. C re-entry breaks turn inference. Pointers given to C last only "until end of turn". |

**Total** = 25·3/5 + 15·3/5 + 15·3/5 + 15·2/5 + 10·3/5 + 10·2/5 + 10·3/5
= 15 + 9 + 9 + 6 + 6 + 4 + 6 = **55 / 100**

That is 28 below O1 (83) and 27 below O4 (82). The inventor's self-assessment of about 80 assumed Safety 5 and Expressiveness 5, and C1 to C6 do not support either.

## 7. Fatal flaw and salvageable kernel

**Fatal flaw:** identity is positional. A sideways link identifies "whatever is at this path from the LCA", not "this object". So moving a subtree, the idea's own remedy for lifetimes that don't nest, silently severs every external reference, and upward references silently re-target. Making links follow objects across moves needs a uid-to-object table, which is O6. Once that table exists, the LCA/path machinery is redundant. A second structural problem: turn-deferred destruction stands in for alias tracking, and it causes the send deadlock (C4) and the leak and modal-loop hazards (C6, C7).

**Salvageable kernel** (for O4, partly for O1):
1. **`outer T`.** A runtime-maintained owner back-pointer for objects that are owned rather than `shared`, kept up to date on move or insert. It can never be stale, because a child dies with its owner. This solves (b) without weak refs.
2. **Automatic upward capture.** When the compiler or runtime sees a closure being stored into `self`'s own owned subtree, it captures `self` through `outer` (uncounted) instead of strongly. This removes `[weak self]` for the canonical (c) case, with no syntax. Closures stored *outside* keep normal O4/O1 capture rules, which keeps closure-owned state working (avoids C3).
3. **The debugger's containment-tree view**, plus "why is this weak/outer `none`" diagnostics.
4. Optional: autorelease-style batching of frees at event-loop turns, as an *optimization* in O1. It must not carry safety load.

## 8. Verdict

**Kernel worth stealing.** Dominion is not a contender: its positional identity and turn-deferred safety create more surprises than they remove. But `outer T`, together with automatic upward capture of `self` for closures stored in self's own subtree, is a small, sound, annotation-free fix for the (b)/(c) crux, and it slots straight into O4.
