# Analysis 11 — Precedent-Bound Lifetimes ("Cells and Formulas")

Analyst: independent. Sources: brief.md, CHARTER.md, ideas/11 only.
All code is *illustrative only — not a syntax decision*.

## 1. Restatement

Every heap object has exactly one owner. Every other reference is a non-owning `link` that never
keeps anything alive. When an object dies, it eagerly notifies its dependents: link fields become
`none`, closures that captured it are destroyed (and their slots become `none`), and link-keyed
container entries are removed. Local and parameter links "pin" their target, so a death that
happens while code is using the object is put off until that scope exits.

## 2. Prior art

It is not a rename of O1–O8. It is, though, very close to a known pattern: the GUI-framework
object model, promoted into language semantics.

- **Qt QObject.** A parent owns its children. `QPointer` is a non-owning pointer that nulls
  itself. `connect(sender, signal, context, lambda)` breaks the connection when the sender *or*
  the context is destroyed: "Qt automatically removes all connections to or from an object when
  it is destroyed"
  ([SO via kiwix](https://kiwix.lema.org/stackoverflow.com_en_all_2023-11/questions/33357410/do-i-still-have-to-disconnect-a-lambda-from-a-signal-in-qt5-5),
  [qt-interest](https://lists.qt-project.org/pipermail/interest/2012-December/004977.html)).
  That is "formula disposed when a precedent dies" for one precedent chosen by hand.
- **Delphi TComponent.** An owner frees its owned components. `FreeNotification` registers a
  dependent "so it gets notified before another component is destroyed", so it can nil its field
  ([Embarcadero docwiki](https://docwiki.embarcadero.com/Libraries/Athens/en/System.Classes.TComponent.FreeNotification)).
  That is the deps-ring / link-blanking mechanism, done by hand.
- **Gel / Nim owned refs.** Single owner plus non-owning refs, with no GC. Nim's `owned ref`
  aborts if unowned refs remain when the owner frees the object
  ([Araq, "A new runtime for Nim"](https://nim-lang.org/araq/ownedrefs.html); Gel is Dingle &
  Bacon, "Ownership You Can Count On",
  [discussion](https://digitalmars.com/d/archives/digitalmars/D/Ownership_You_Can_Count_On_355291.html)).
  The Nim team found this "quite a pain to work with" and moved to ORC (same thread). Idea 11
  replaces "abort" with "blank and dispose". That is the right fix for Gel's pain point, but it
  is the same ownership burden.
- **Zeroing weak refs (ObjC `__weak`).** These are already cleared at dealloc, so the idea's
  claim that "O1 only blanks one hop, when read" undersells O1.

**Genuinely new as a language rule:**
- A closure's lifetime is `min(home slot, every captured cell)`, with the precedent set
  computed by the compiler and a guarantee that captures are non-null inside the body.
- Blanking cascades transitively through disposed formulas.
- Pins defer death rather than refusing it.
- Self-compacting link containers.
- "Paste-values" `send`.

The parts are known. The combination and the closure rule are new.

## 3. Soundness: counterexamples

**C1. Ownership cycles leak, despite the claim that "cycles that leak cannot exist".** Rule 3
says reading a local gives you a link, and rule 6 says pins only defer *death*, not moves. So:
```
let t  = Timer()
let tl = t                         // link (pinned)
let f  = { take t; t.count += 1 }  // formula OWNS t (rule 8)
tl.onFire = take f                 // t owns f, f owns t  -> unreachable, never freed
```
A tree version has the same shape: `let bl = b; a.children.add(take b); bl.children.add(take a)`.
Single ownership without a borrow checker does not stop you moving an ancestor into its own
descendant. The worst part is that the dev-build warning ("formula disposed because a local
precedent died") pushes users toward `take` capture, which is exactly how C1 arises in UI code.
**Fix:** on every `take` into a slot, walk the destination's owner chain and trap if the moved
cell is an ancestor. That needs an owner back-pointer in the header (16 B grows to 24 B) and
costs O(depth) per take. It is a missing rule.

**C2. Pinned `send` conflicts with rule 6 vs rule 10.**
```
func process(n: Node)              // n = pinned link into app.tree
  worker.send(take app.tree)       // rule 10: cut links crossing the edge
  print(n.name)                    // rule 6: n "always valid in its scope"
```
There are three ways out, and all are bad. Blanking `n` breaks rule 6, because a non-optional
local becomes `none`. Leaving `n` intact is a data race. Waiting for the pin to drop deadlocks,
because the pin belongs to the same scope. The only sound choice is for `send` to trap when any
cell in the subtree has `pins > 0`. That is a third, unstated runtime failure mode.

**C3. Zombies: deferred death is observable.** The idea's Drop(c) says that if `pins > 0` the
cell is only marked `dying` and the blanking waits.
```
let ed = tabs.current              // pinned for the whole of run()
tabs.remove(ed)                    // owner gone, ed now `dying`
loop { events.pump() }             // ed's onTap/timer formulas still fire;
                                   // `allEditors: List of link Editor` still lists it;
                                   // deinit (close file, release OS window) never runs
```
A long-lived pin in an event loop, or one held at the top of a worker, is an unbounded,
behaviour-changing leak and not just a memory cost. Users will ask "I removed it, why is it
still saving?"

**C4. Tombstone compaction shifts indices during an index loop.**
```
let n = observers.count            // List of link View
for i in 0 ..< n { observers[i].refresh() }   // refresh() drops a sibling view
```
An index loop is not an "active iterator", so a compaction can happen mid-loop. The result is a
skipped element or an out-of-bounds trap. It is safe, but surprising, and the idea admits it.

**C5. `deinit` resurrects links.** `deinit` runs after the deps walk. If `deinit` does
`registry.add(self)` or creates a formula over `self`, a new DepNode is spliced onto a cell that
is about to be freed, which gives a dangling link. Fix: trap on any link store to a non-`alive`
cell. That is cheap, but it must be specified.

**C6. Underspecified ownership mode of returns.** A return gives ownership if the function
"creates" the cell, and a link otherwise. Take `func getOrMake() -> Doc` that returns
`cache[k] ?? Doc()`: the caller cannot tell whether it owns the result, and the fresh `Doc` has
no owner. The signature has to say `-> take Doc` versus `-> Doc`, or the compiler infers
ownership non-locally. That is another rule and another spelling.

**C7. Silent `#REF!` in sharing patterns that are idiomatic in a DSL.**
```
let count = Counter()
row(Button("+", onTap: { count.inc() }), Button("-", onTap: { count.dec() }))
```
`count` cannot be `take`n into both closures. At scope exit both buttons quietly go dead. The
user has to lift the state into `self` or some ancestor. This is SwiftUI `@State` territory, and
it is G11's core case.

Deadlocks come only from `lock` ordering across two sheets, the same as O1/O4. Nothing dangles if
C5 is fixed. The real failures are leaks (C1, C3) and silent non-behaviour (C7).

## 4. Scenarios

- **(a) Works.** It takes the fast path, which is plain unique ownership.
- **(b) Works.** The `link parent` blanks correctly. The cost is `?.` on every parent access, and
  you must not `take` an ancestor (C1).
- **(c) Mostly works, and it is the best story here.** There are no capture lists, `self` is
  guaranteed alive in the body, and the self-removing "Close" button is handled by pins. But
  stored callbacks that capture locals silently die (C7), and `take` capture can leak (C1).
- **(d) Works if there is a natural common owner.** The link-keyed map that evicts itself is a
  real win. It fails to express genuine co-ownership, for example two plugins with no common
  ancestor. There is no RC escape hatch.
- **(e) Works.** The parameter is a pinned link, so there is no copy. Aliasing is memory-safe
  because links never point into a buffer.
- **(f) Partly hand-waved.** C2 is unresolved. `send` silently blanks outward links such as
  `job.config`. There is no long-lived immutable sharing outside a structured `parallel`.
  "Read-only" children need either a const/effect check or a runtime frozen bit, and neither is
  specified.

## 5. Gates

- **G2: pass.** There is no tracing or scan. All work is synchronous at drop or unpin, with
  cascades like ARC.
- **G3: needs-john.** The model needs built-in parameterised `List of` / `Map of`, including
  `List of link T` and `Map of (link K -> V)`, which are element modes the compiler must know
  about. `link` and `take` are type and expression keywords, not annotations, comparable to
  O1's `weak`. Same flag as the other options. Nothing more.

## 6. Score

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 3 | It has 10 stated rules plus at least 4 implicit ones (return mode, the `dying` state, the ancestor-take check, index shifting), and every cell needs an answer to "who owns this?". That is the Gel/Nim burden, which was judged painful in practice. |
| Memory safety | 15 | 4 | No dangling and no use-after-free (once C5 is fixed). But ownership-cycle leaks (C1) and zombie retention (C3) exist, so it is not the leak-free model it claims to be. |
| Expressiveness (b, c, d, self) | 15 | 4 | (c) and implicit `self` are excellent, and link-keyed maps are nice. There is no co-ownership, and shared local UI state needs lifting (C7). |
| Implementation risk (AI-written, LLVM) | 15 | 2 | Several hard pieces come together: intrusive DepNode rings that must be re-threaded when a container buffer reallocates, worklist cascades interleaved with `deinit`, pin elision needing purity/effect analysis, tombstones and compaction, subtree-severing `send`, per-store book checks, and ownership-mode inference. Each is fiddly, and they all interact. |
| Performance & predictability | 10 | 3 | Frees are deterministic, there are no atomics, and the fast path is `unique_ptr`. Costs: a 16–24 B header, 3-word link fields that write to the target's cache line, pin traffic, unbounded cascades, deferred-death retention, and O(subtree) `send`. |
| Concurrency fit | 10 | 3 | Per-thread books avoid atomics, and `send`, `parallel` and `sheet` are clean concepts. But C2 is open, blanking on `send` is silent, and long-lived shared immutable data is missing. |
| Tooling, debug, FFI | 10 | 4 | "Why blank?" provenance and "trace dependents" are best in class for G8. FFI pinning plus a handle table is sound. Structs holding intrusive links are awkward to expose to C. |

Total = (25·3 + 15·4 + 15·4 + 15·2 + 10·3 + 10·3 + 10·4) / 5
      = (75 + 60 + 60 + 30 + 30 + 30 + 40) / 5 = 325 / 5 = **65**.

That puts it 18 below O1 (83) and 17 below O4 (82). It is level with O5 and below O6 (71).
Against O4 specifically: it carries the same single-ownership burden, but stored links replace
`shared`. That buys a better (c) and costs much higher implementation risk, with no RC escape
hatch for (d).

## 7. Fatal flaw and kernel

**Fatal flaw (for adoption as *the* model).** It keeps the cost of single ownership (every cell
needs one owner, plus `take` discipline) and adds a large runtime notification machine on top.
It still fails to deliver its headline guarantee: C1 shows that ownership cycles leak unless
another runtime check is added. Within this rubric it cannot beat ARC on simplicity or O4 on
implementation risk.

**Salvageable kernel: closures as formulas.** Add this to O1 as a rule for *escaping, stored*
closures, the ones in `onTap`-style slots:
- Captured class references are held *weakly*.
- The closure is auto-released, and its slot set to nil, as soon as any captured object
  deallocates. This is Qt's context-object auto-disconnect, generalised to every capture.
- While the closure body runs, its captures are retained strongly, so `self` is non-optional
  inside the body.

Under ARC this is cheap: zeroing-weak side tables already exist, plus one notification hook. It
removes capture lists and `[weak self]` from the user's rule set (P-SWIFT), and retain cycles
through callbacks become impossible by construction.

Secondary steals:
- Self-pruning `List of weak T` and `Map of (weak K -> V)` as built-ins.
- "Why is this nil?" provenance in debug builds (G8).
- A dev-build warning when a stored closure is disposed because a *local* capture died. O1
  would need this too if it adopted the kernel.

## 8. Verdict

**Kernel worth stealing.**
