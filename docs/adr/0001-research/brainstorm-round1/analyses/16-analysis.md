# Analysis 16 — Kinship (family-tree ownership, upward kin, turn orphanage)

Analyst: independent. Inputs read: brief.md, CHARTER.md, ideas/16-kinship.md only.
All code is *illustrative only — not a syntax decision*.

## 1. Restatement (3 sentences)

Every object has exactly one owner, so the heap is one ownership tree. A field or a
closure capture may hold a plain, uncounted pointer to an ancestor, or to a `let`
member of an ancestor, because the tree guarantees the ancestor outlives it. Other
local references ("visits") are made safe by deferring every free to the end of the
current event-loop turn, which is the "orphanage". The remaining cases use
self-unlinking subscription cards ("clubs") and generation-checked handles
("contacts").

## 2. Prior art

The parts all exist already. The combination and the "ancestor = lifetime proof"
framing as the *primary* mechanism is fairly new.

| Kinship part | Prior art |
|---|---|
| One guardian, children die with parent, built-in parent accessor | Qt's QObject object tree: parent owns children, `parent()` is maintained, deleting a parent deletes the children ([Qt object trees](https://doc.qt.io/qtforpython-5/overviews/objecttrees.html), [devgenius overview](https://blog.devgenius.io/qts-qobject-memory-management-how-parent-child-hierarchies-delete-objects-for-you-afb4346cf8a9)) |
| Orphanage drained at end of turn | Qt `deleteLater` (deferred to the event loop), and Cocoa autorelease pools. Epoch reclamation in concurrent code. |
| Clubs / cards | Combine `AnyCancellable` (cancel on deinit) ([Donny Wals](https://www.donnywals.com/what-exactly-is-a-combine-anycancellable/), [Apple](https://developer.apple.com/documentation/combine/anycancellable.md)), RxJS `Subscription`, Qt auto-disconnect on destroy |
| Ancestor-pointing references are safe | Ownership types / owners-as-dominators ([Clarke, Potter, Noble, OOPSLA'98](https://dblp.org/rec/conf/oopsla/ClarkePN98); [Ownership Types: A Survey](https://www.springerprofessional.de/en/ownership-types-a-survey/4070988)). The kin rule is a runtime-checked, annotation-light cousin of that work. |
| Owned pointers plus checked non-owning refs | Gel, "Ownership You Can Count On" (Dingle/Bacon) ([D forum summary](https://lists.puremagic.com/pipermail/digitalmars-d/2021-November/321376.html)). Vale (O6). |
| Self-contained subtree sent to a thread | Pony `iso`, and Verona regions ([Reference Capabilities for Flexible Memory Management](https://arxiv.org/pdf/2309.02983)) |
| Contacts | O6 generational handles, as the idea itself says |

The genuinely new bit is using a *safe* upward pointer, checked at adoption, as the
default way to answer `weak self` and parent pointers, inside a language with unique
ownership. Qt has the tree but leaves upward pointers raw and unsafe. Ownership types
have the dominator property but need type parameters, which G3 forbids.

## 3. Soundness: counterexamples

**C1. Unanchored kin survives a turn: use-after-free.** Kin is validated at adoption.
But a fresh object or closure carries its kin before it is adopted, and the idea's
own scenario (d) relies on this: `SearchPanel(cache)` is built before `App.search`
holds it. Nothing stops it staying in a turn-root local:
```
// main (a turn root)
let h = editor.makeHandler()        // closure, kin -> editor, owned by local h
app.editors.clear()                 // editor orphaned
settle                              // no *visits* live, so settle is legal; editor freed
h()                                 // dangling kin -> UAF
```
To fix it, any object holding unvalidated kin must be treated as a visit (turn-bound)
until it is adopted. That is a new state the user has to learn.

**C2. A visit escapes a `Guarded` lock: data race and UAF across threads.**
```
family
  spawn { let e = cache.lock({ c -> c.get("k") })   // returns a visit, not "stored in a field"
          longWork(e) }                               // used with the lock not held
  spawn { cache.lock({ c -> c.remove("k") }) }        // orphan goes to *this child's* orphanage,
                                                      // which drains when its task body ends
```
Rule 3 forbids only storing visits in fields, so returning one from the lock closure is
legal as written. The fix has two parts. Lock closures may return only values or
`take`n subtrees, which is a lifetime-like rule. Orphans made under a family-shared
`Guarded` must go to the parent's orphanage.

**C3. Freeze vs a pre-existing visit: data race.**
```
let raw = loadCorpus();  let v = raw.items[0]
let corpus = freeze(take raw)
family { spawn { read(corpus.items[0]) };  v.text = "x" }   // parent writes while the child reads
```
This is only safe if `freeze` deep-flags the subtree and *every* write checks the
frozen flag at run time. That costs a branch on every store. The other option is a
static frozen type, which brings in a type distinction.

**C4. Adopting into your own descendant: leaked ownership cycle.**
```
let gc = a.child.child                  // visit
gc.slot = take a.child                  // a.child's subtree now owns itself; unreachable, never orphaned
```
Every owning store needs an O(depth) "target is not a descendant of the moved object"
walk, unless the object is provably fresh. The idea does not state this check.

**C5. `self` dies at `await`.** `self` arrives as a parameter, so it is a visit, and
visits cannot survive the turn (rule 9: `await` ends a turn).
```
fn save() async
  await disk.write(text)
  self.dirty = false          // illegal: self is a visit across an await
```
The workaround is `let me = contact(self) … me.reach()?.dirty = false`, which is
`weak self` again, in exactly the async-UI code G11 cares about.

**C6. Memory spikes within a turn (not a leak, but surprising).**
```
fn simulate()                            // called from a click handler, so not a turn root
  for i in 0..1_000_000
    self.state = step(self.state)        // old state orphaned; a caller may visit it, so it can't free early
```
All million states stay alive until the handler returns, and `settle` is illegal
here. Escape analysis cannot prove there is no visit further up the stack.

**C7. Transparent containers make moves O(n).** An element of `editor.lines` reports
`editor` as its guardian. So `self.lines = readLines(p)` or `take` of a whole list must
rewrite n guardian pointers. If lists were opaque objects instead, `guardian as? Node`
in (b) would return the List, so the design has to accept this cost.

**C8. A club mutated during dispatch.** A "logout" notification whose handler closes
windows unlinks other cards in the same club during iteration. That either hits rule
10 (trap) or needs careful tombstoning in the intrusive list. It is fixable, but the
spec's "unlinked eagerly" is the textbook bug.

**C9. `farewell` order.** Children are freed before parents, so a parent's `farewell`
that walks its children touches freed memory. Moving them in `farewell` triggers
adoption checks, which can trap inside a destructor. Two phases fix it: run all
farewells, then free.

C1, C2 and C3 are real memory-safety holes in the rules as written. All three can be
patched, and each patch adds a rule or a run-time cost.

## 4. Scenarios

- **(a)** Works. It is plain move semantics. Moving the list into a field costs O(n)
  guardian rewrites (C7).
- **(b)** Works well. The automatic `guardian` is the best answer to (b) among
  ownership models. Its result is dynamically typed (`as?`).
- **(c)** Works for the canonical case (button under `let toolbar` captures `self`),
  and the `Card` handles the timer. It breaks for list rows capturing model items
  (`ForEach(model.items) { item in Button { delete(item) } }`): the item is owned by
  the model, not by the view, so the row needs a contact. It also breaks for `self`
  after `await` (C5).
- **(d)** Hand-waves part of it. It works only because the cache is a `let` member of
  a common ancestor. A replaceable cache, or one document shared by views in different
  windows (the brief's non-nesting case), falls back to O6 contacts.
- **(e)** Works: references with no copies, made safe by the orphanage. Aliased
  mutation is guarded only by rule 10.
- **(f)** Partly works. Structured `family` plus `freeze`/`Guarded`/emancipated `send`
  is a sound shape, but C2 and C3 are holes as written.

## 5. Gates

- **G2: pass.** The orphanage frees only what was explicitly dropped, at a
  deterministic program point, and its cost scales with the garbage, never the live
  heap. That is Qt `deleteLater` or an autorelease pool, not a collection run. A large
  drain causes a pause proportional to what was dropped, the same as an RC cascade.
  John may still want to confirm, as the inventor asked, but I see no tracing.
- **G3: pass, with the same pending flag as O1/O4.** `kin`, `let`, `take` and `freeze`
  are keywords, comparable to O1's `weak`. The model leans on compiler-known
  parameterised built-ins: `List of`, `Map of`, `Guarded(...)`, and `Club`/`Card`,
  which must be typed by the callback signature. That is the brief's pending
  container question, and here it covers more types.

## 6. Scores

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 2 | 12 stated rules plus about 4 implied (param modes, unanchored kin, lock-closure escape, farewell order). Large vocabulary: guardian, visit, kin, fixed, orphan, turn, turn root, settle, club, card, contact, family, freeze, Guarded, emancipation. Strictly more than O4. |
| Memory safety | 15 | 3 | Safe by intent, but C1–C3 are holes as written. Failures are runtime traps at adoption, far from the cause. |
| Expressiveness (b, c, d, OO) | 15 | 3 | Best-in-class (b) and canonical (c). Non-upward links (model items, shared documents, replaceable caches) and async `self` fall back to optional contacts. |
| Implementation risk (AI-written, LLVM) | 15 | 2 | Novel runtime with no reference implementation: guardian upkeep through transparent containers, subtree kin walks, has-outward-kin propagation, static kin proofs, visit liveness across `await`, escape analysis for early free, deep freeze, family orphanage hand-off. |
| Performance & predictability | 10 | 3 | No RC traffic. Against that: a 16 B header, O(depth) adoption checks, O(n) container moves, per-write frozen checks (C3), memory spikes within a turn, and pauses at drain. |
| Concurrency fit | 10 | 3 | Structured lending plus isolated send is a good shape with no atomics, but the lock and freeze rules need tightening. |
| Tooling, debuggability, C FFI | 10 | 4 | A path from the root for every object, a per-subtree census and two-path trap messages are excellent. FFI pointers are turn-bound, and a long-held one needs a contact. |

Total = (25·2 + 15·3 + 15·3 + 15·2 + 10·3 + 10·3 + 10·4) / 5
      = (50 + 45 + 45 + 30 + 30 + 30 + 40) / 5 = 270 / 5 = **54**.

Against O1 (83) and O4 (82), Kinship scores 28–29 points lower. Almost all of the gap
is simplicity and implementation risk, which carry 40% of the weight. It beats O1
only on (b), on RC cost, and on the debugger.

## 7. Fatal flaw and salvageable kernel

**Fatal flaw (for contention):** the ancestor rule solves the *nesting* links (parent
pointers, `self` captured under `self`). O1 already handles those with one `weak`
keyword. The links the brief calls hard are the non-nesting ones: sessions, windows,
cache entries, model items captured by view rows, and `self` across `await`. Kinship
sends those to O6-style contacts with optional reach. The user pays O4's ownership
rules, plus kin, turns, the orphanage, clubs and contacts, and the hard case stays
about as hard. It is not unsound beyond repair, but it spends a large complexity
budget for a small gain.

**Salvageable kernel (for O4, which already has unique ownership):**
1. *Upward-capture inference.* When the compiler can prove that a closure or field is
   stored down a `let`-owned path of the object it captures, compile the capture as a
   non-counted pointer, with no `weak self` and no RC. Under O1 this is unsound,
   because the holder could be shared elsewhere. Under O4's unique ownership it holds.
2. *Built-in `guardian` for uniquely owned objects.* The runtime keeps the parent
   pointer up to date on move, which gives (b) without `shared`/`weak`.
3. *Clubs/Cards in the stdlib*, for O1 or O4: registries never own observers, and
   dropping the card unsubscribes. This is the AnyCancellable pattern, made the only
   sanctioned observer API.
4. *Ownership-path debugger and census*, which works for any unique-ownership model.
5. Optionally, *deferred drop to end of turn* for objects removed from containers
   during dispatch: the Qt `deleteLater` idea, used as a targeted safety net in O4
   rather than as the main safety mechanism.

## 8. Verdict

**Kernel worth stealing.** It is not a contender at 54 against 82–83. Upward-capture
inference and the auto-maintained `guardian`, both under O4's unique ownership, plus
Card-based clubs, are good additions to O4.
