# Analysis 03: Cascade Links (also "Rows & Links")

Analyst: independent. Inputs: the brief, CHARTER.md, and ideas/03-cascade-links.md only.
All code below is *illustrative only, not a syntax decision*.

## 1. The idea in three sentences

Every object has exactly one owner, and every other reference is a non-owning "link". When an object dies, a per-object reverse index empties every slot that pointed at it. An optional slot becomes `none`, a collection drops the element, and a required slot deletes its *holder*, which can cascade. Actual freeing is deferred to "commit points" between events or at `commit` in `main` or a thread body, so stack references never dangle within a handler. Threads share data only by moving whole subtrees or through MVCC `shared` stores accessed in `atomic` blocks.

## 2. Prior art: new, or a recombination?

The pieces are mostly known. The combination is new as a language memory model.

| Piece | Prior art |
|---|---|
| Single owner plus links nulled on destroy | Delphi/FPC `TComponent` owner plus `FreeNotification`/`opRemove`, which notifies linked components so they drop references. It is also brittle when asymmetric: [fpc-devel](https://lists.freepascal.org/fpc-devel/2012-March/028694.html). Qt `QObject` parent ownership plus `QPointer` is the same pattern. |
| Required link deletes its holder (`ON DELETE CASCADE` from the referencing side) | Flecs ECS cleanup traits: `(OnDeleteTarget, Delete)` deletes entities whose relationship target is deleted. This is how `ChildOf` works ([Flecs ComponentTraits diff](https://github.com/SanderMertens/flecs/commit/e8a4646ae5788c430605e7317848460c7e66579d.diff), [flecs-sys](https://docs.rs/flecs-sys/latest/flecs_sys/bindings/static.EcsOnDeleteTarget.html)). It also mirrors SQL FKs and EF Core `OnDelete`. |
| Closure dies when a captured object dies (scenario c) | Qt `connect(sender, sig, context, lambda)`: "when *receiver* gets destroyed, the connection is severed automatically", and "if you capture *this* … you want *this* as your context object" ([KDE, 2026](https://planet.kde.org/kai-uwe-broulik-2026-04-24-qt-no-contextless-connect/)). boost::signals2 `slot::track` does the same. |
| Deferred free at event-loop boundaries | Cocoa autorelease pools drained per run-loop iteration. These are known to "miss" drains in C-style callbacks ([cocoa-dev](https://lists.apple.com/archives/cocoa-dev/2009/Apr/msg00409.html)). RCU and epoch-based reclamation work at quiescent points. |
| MVCC/STM for shared state | Clojure refs, Haskell STM. |

Two things are new as language semantics:
- (i) The **closure-capture rule** generalises Qt's single "context object" to *all* captures, and the compiler applies it automatically.
- (ii) **Nullability is reused as the cascade policy**, so `T` versus `T?` decides between CASCADE and SET NULL.

Commit deferral as a *replacement for borrow checking* is also a fresh framing, though it is autorelease semantics underneath. The idea is honest about most of this, but it does not mention Delphi, Qt or Flecs, which are the closest ancestors.

## 3. Soundness: counterexamples

**C1. An owned local in a root frame dangles after a cascade (memory-unsafe as specified).** Rule 5 forbids using *links* held in root locals after a `commit`. It says nothing about *owning* locals, which can be freed by a cascade.
```
fn main() {
  let app = new App()                         // app.sessions owns Sessions
  let view = new View(session: app.sessions[0])   // owned by main; REQUIRED link
  loop {
    pump(app)        // some handler logs out: app.sessions.remove(s)
    commit           // Session dies -> required link -> View deleted (holder)
    view.render()    // `view` is an owner local, not a link: rule 5 doesn't flag it -> use-after-free
  }
}
```
The same question applies upward. If an `own editor: Editor` field (required, not optional) loses its Editor to a cascade, rule 4 treats the owner slot as "a slot that pointed at it", so the parent Window is deleted too. The spec doesn't say whether that is intended. Fix: owned locals in root functions get the same stale check, and owner slots never propagate a cascade. Both fixes are cheap, but each adds a rule.

**C2. Sending a subtree while a stack link into it is live (a data race).**
```
fn onClick() {
  let batch = new Batch(rows: load())
  let first = batch.rows[0]          // stack link into the subtree
  worker.send(move batch)            // `batch` is unusable now, but `first` isn't
  label.text = first.text            // the worker thread may be mutating or freeing `first`
}
```
Rule 5's guarantee is per thread: nothing is freed until *this* thread commits. Once the subtree belongs to another thread, it runs on that thread's commit schedule. Catching this statically means tracking which links derive from which owner, and that is borrow checking. Fix: queue sends and deliver them at the sender's commit. The fix is plausible, but it isn't in the spec.

**C3. `send` silently deletes the thing sent.** `class Batch { own rows: List of Row; config: Config }` has a required link to an object on the sending thread. Rule 9 empties cross-thread links "as if deleted". The link is required, so `Batch` itself is cascade-deleted, and the worker receives nothing. Defined, but surprising.

**C4. Adding a log line silently kills a button (action at a distance).**
```
fn attach(button: Button) {
  let fmt = new Formatter()
  button.onTap = fn() { self.text = fmt.format(self.text) }
  log(fmt.name)      // fmt is now "used after", so rule 6 does NOT move it into the closure
}                    // fmt dies -> at commit the closure is deleted -> onTap = none. The button does nothing, forever.
```
There is no error and no crash, only missing behaviour. The commit log helps, but only if you know to look.

**C5. Reclamation and resource release depend on stack shape and on the optimiser.** `commit` is legal only in `main` or a thread body. Any long loop inside a library function keeps everything pending until it returns: `server.run()`, `game.loop()`, or `importCsv(10 GB)` with an LRU cache.
```
fn main() { importAll("huge.csv") }        // no commit is possible inside importAll
fn importAll(p) { for line in ... { let r = new Rec(line); lru.put(r.key, r) } }  // evictions pile up -> unbounded growth
```
Files show the same problem. A `File` is closed at scope end only if escape analysis proves the fast path. Otherwise it closes at the next commit:
```
fn main() {
  writeReport("out.txt")          // inside, f is passed to a non-inlined helper -> pending, not closed or flushed
  let s = File.read("out.txt")    // truncated read; on Windows, a sharing violation
}
```
Two fixes exist, and both cost something. One is to allow `commit` anywhere, which needs a "may-commit" effect that colours every caller and is invisible through function-typed slots. That is an annotation or an effect system, which strains G3. The other is to run deinit eagerly and defer only the free, which brings use-after-close. The same problem hits foreign event loops such as Cocoa, Win32 and GTK. When a C library drives the loop, the runtime can't tell a top-level event from a re-entrant callback. That is exactly the class Cocoa's pools miss.

**C6. The mutex-per-store fallback deadlocks.** `atomic { a.x += 1; b.y += 1 }` on thread 1 and `atomic { b.y += 1; a.x += 1 }` on thread 2. Stores are discovered dynamically, so per-store locks taken lazily can't be ordered. The fix is one global lock, or abort-and-retry, which is STM again. Under MVCC, long transactions can livelock or starve under first-committer-wins.

**C7. Spec gaps.**
- Rule 3 says return values are links, but (a) returns ownership. Does `let n = make()` own `n`? It depends on the callee body unless signatures say `-> own T`, which is O4's move rule under another name.
- Do plain local collections own their elements? `nodes.add(new Node())` on a plain list would vanish at commit.
- Commits run "after each … callback". If that includes a sort comparator, it's unsound. It must mean top-level only.
- Snapshot iteration for `for` loops implies COW or a copy on every loop over a mutable collection.
- Link slots in lists and maps need stable identities. Insert-at-front, sort and rehash must rewrite the incoming nodes of every moved element.
- Under MVCC, intrusive incoming lists are shared mutable metadata touched by every link store. Popular targets become write-conflict hotspots, and versioned copies break the "incoming nodes point at the target" invariant.

## 4. Scenarios

| | Verdict |
|---|---|
| (a) | **Works.** Trivial, apart from the return-ownership gap (C7). |
| (b) | **Works well.** Parent is `Node?` (SET NULL). `children: from Node.parent` is a real improvement on ARC. |
| (c) | **Works, best in class for the common case.** No `[weak self]`, auto-unsubscribe, the handler can close its own editor. Marred by C4 (silently dead callbacks) and by required callback slots cascading. |
| (d) | **Works.** Eviction maps cleanly to referential integrity (remove from `shown`, set `current` to none). `T` versus `T?` encodes "can I live without the cache". |
| (e) | **Works.** A link is passed and the list is mutated in place. Aliasing is unrestricted, as in Java/ARC. The for-snapshot cost is hidden. |
| (f) | **Partly hand-waved.** Subtree move is fine, but has C2 and C3. MVCC with reverse indexes is unspecified, and the fallback deadlocks (C6). |

## 5. Gates

- **G2: pass.** Commit visits only dead objects and their links, never the live heap. That is autorelease or RCU-style deferral, not a collection run. If the strictest reading counts any deferred reclamation, that is a needs-john footnote. I don't think it is warranted.
- **G3: pass, with the shared pending flag.** `own`, `T?`, `from X.f`, `shared` and `atomic` are keywords and types, not annotations or templates. It needs built-in `List of T` and `Map of K to V`, which is the same pending question as O1/O4. If C5 is fixed with a may-commit effect, G3 is at risk.

## 6. Rubric

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 3 | 10 rules plus implied ones (stale root locals, snapshot loops, capture-move inference). `T` versus `T?` silently decides delete semantics, which overloads a concept every other language uses only for nullability. |
| Memory safety | 15 | 4 | The core design is sound, and every reference is either valid or emptied. C1 and C2 are real holes as written, but each has a local fix. FFI raw pointers are valid only until commit. |
| Expressiveness (b, c, d, implicit self) | 15 | 5 | Better than ARC on all three: derived inverses, self-unregistering closures, cache invalidation. Implicit `self` is natural. |
| Implementation risk (AI-written, LLVM) | 15 | 2 | A novel runtime with no reference implementation: intrusive reverse indexes for every heap link, including stable identity across realloc, sort and rehash; the cascade worklist; escape analysis; the subtree-send walk; STM. Bugs here are heap corruption, not compile errors. |
| Performance & predictability | 10 | 3 | Heap links are about 5 words, and every link store does a list insert or remove. Memory peaks per event. Resource-close timing depends on the optimiser (C5). On the plus side, there are no atomic refcounts. |
| Concurrency fit | 10 | 3 | Isolated heaps plus STM is a good shape. Subtree send is O(n) and has C2/C3. Read-only shared data must go through `atomic`. The fallback deadlocks. |
| Tooling, debuggability & C FFI | 10 | 4 | `links_to`, the cascade log and the ER-diagram debugger are excellent. FFI handles are fine. Foreign event loops are awkward (C5). |

Total = (25·3 + 15·4 + 15·5 + 15·2 + 10·3 + 10·3 + 10·4) / 5
      = (75 + 60 + 75 + 30 + 30 + 30 + 40) / 5 = 340 / 5 = **68**

Compared with **O1 (83)** and **O4 (82)**: 15 and 14 points behind. It beats both on expressiveness (+1 or +2 levels, worth 3–6 points). It loses more on simplicity (−1 to −2 levels, 5–10 points), on implementation risk (−2 levels, about 6 points), and on performance. That puts it just below O3 (73) and O6 (71).

## 7. Fatal flaw and salvageable kernel

**Fatal flaw (as a whole model).** Safety rests on "nothing is freed until the stack has unwound to a commit point", so reclamation and resource release are tied to stack shape. Long loops inside libraries, batch code and foreign-driven event loops either grow without bound or need a may-commit effect. That effect is either an annotation (G3) or a function colour that lifetimes would have handled. A second-order flaw is the conflation of `T` versus `T?` with CASCADE versus SET NULL. It makes a type-level nullability choice silently destructive (C3, C4, and owner-slot cascades in C1).

**Salvageable kernel: "dependent closures" for O1 (or O4's `shared`).** A closure stored in a heap slot captures objects *weakly*, without the programmer writing it. If any capture has died, the closure is dead: the slot reads as `none` and invocation is a no-op. Swift-style weak side tables make this cheap, and cleanup can be lazy, so no reverse index is needed. This gives O1 scenario (c) without `[weak self]` or `guard let self`, generalising Qt's context-object rule to every capture.

Secondary steals:
- (i) Derived inverse collections (`children: from Node.parent`), built on O1's weak side table.
- (ii) A `links_to(x)` plus "why was this emptied" debug log, built on weak-ref zeroing.
- (iii) Optionally, autorelease-style deferral of *frees only* (not deinit) per event, as an optimisation that batches ARC releases.

## 8. Verdict

**Kernel worth stealing.** Not a contender. Scenario (c) is the best answer seen against this brief, but the commit-point foundation costs too much in simplicity, predictability and implementation risk to beat O1 or O4.
