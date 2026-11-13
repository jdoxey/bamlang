# Analysis 06: Charge & Decay

Analyst: independent. Sources read: brief.md, CHARTER.md, ideas/06-charge-and-decay.md.
All code is *illustrative only, not a syntax decision.*

## 1. Restatement (3 sentences)

Every object has exactly one owner, and the owner is whichever lasting slot (field, container entry, closure, global) the object is stored in first; every later store or pass makes a non-owning "link". Links are registered on the target, so when the owner drops the object, every link to it is nulled ("vacuum") at the same moment, and the object and its owned subtree are destroyed depth-first. Containers and callback lists automatically drop dead link entries, closures whose captures died become no-ops, and destruction is deferred while a local or method is still using the object; threads are separated by universe tags, with `send` / `freeze` / `Chamber` for sharing.

## 2. Prior art: is it new?

It is mostly a recombination of known pieces, with one genuinely new twist: deciding ownership **at runtime, per slot**, by first store.

| Feature in 06 | Prior art |
|---|---|
| Owner tree, children destroyed with parent | Qt `QObject` parent/child ownership ([devgenius](https://blog.devgenius.io/qts-qobject-memory-management-how-parent-child-hierarchies-delete-objects-for-you-afb4346cf8a9), [QObject man page](https://www.mankier.com/3/qobject.3qt)) |
| Links nulled when target dies | Qt `QPointer`, Obj-C `__weak` zeroing weak refs, `weak_ptr` |
| Decayed closures leave callback lists | Qt auto-disconnects a connection when its receiver/context object is destroyed ([Qt forum](https://forum.qt.io/post/179857)) |
| Decay deferred while in use | Qt `deleteLater`; Swift/ObjC ARC keeps `self` alive for the duration of a call |
| Self-cleaning containers | `NSHashTable.weakObjects`, Java `WeakHashMap` |
| Owned pointer + non-owning refs, killed target is checked | Gel / "Ownership You Can Count On" (Dingle & Bacon), which traps where 06 vacuums ([nim-general](https://www.mail-archive.com/nim-general@thregr.org/msg14485.html), [D forum](https://digitalmars.com/d/archives/digitalmars/D/Ownership_You_Can_Count_On_355291.html)); this is O6 territory |
| "Owner = first variable/field/element it is assigned to" | **Lobster** infers exactly this at *compile time*, with RC as the fallback ([Lobster memory management](https://aardappel.github.io/lobster/memory_management.html)) |
| send / freeze / chamber | Pony `iso` / `val` / actor-or-`tag` ([Pony tutorial](https://tutorial.ponylang.io/capabilities/reference-capabilities.html)) |

**New:** the runtime "charged/neutral" tag bit set by store order, plus building zeroing-weak and auto-disconnect into the core semantics instead of a library. Section 3 shows that the runtime landing rule is where most of the trouble comes from. Lobster's compile-time version avoids it by falling back to RC.

## 3. Soundness: counterexamples

### CE1. The crux scenario (c) creates an ownership cycle and a leak under the stated rules

Rule 3: a new object has no owner until it lands. During `init`, the Editor has not been stored anywhere yet, because `self.editor = Editor()` does the store *after* init returns. Rule 8: a closure *links* captures "that already have an owner". So `self` is ownerless when the closure is created, and the closure, which rule 3 lists as a lasting place, becomes its **owner**.

```
class Editor {
  init() {
    saveButton.onTap = { self.save() }   // closure captures ownerless self -> closure OWNS Editor
  }                                      // closure lands in saveButton.onTap (owned by Editor)
}
app.editor = Editor()                    // Editor already owned -> app.editor is a LINK
app.editor = none                        // unlinks only; nothing decays
```

The result is the cycle Editor → saveButton → closure → Editor, with no external owner, so it is leaked forever. The idea's claim that "the only way to tie a knot is `take`" is false. The pitch's sentence "`self` is never captured as an owner" is an **unlisted 13th rule** that contradicts rule 8 as written. The `onUndo` closure is worse: if it were the first capture, the long-lived *toolbar* would own the Editor.

Patching it with "`self` is always captured as a link" still leaves the same bug for any other fresh local:

```
func makeButton() -> Button {
  let b = Button("ok")
  b.onTap = { b.flash() }   // closure owns b (b ownerless); b.onTap owns closure -> cycle
  return b                  // b is owned -> caller receives a link to a leaked cycle
}
```

Patching it with "closures never own captures" swaps the leak for silent death:

```
let counter = Counter()
button.onTap = { counter.inc() }  // link only; counter decays at end of scope
                                  // -> closure decays -> button silently does nothing
```

There are three possible rules and each one leaks, needs a special case, or fails silently. This is the core problem.

### CE2. Changing the selection deletes a tree node

```
let n = Node("x")
self.selection = n        // first lasting store -> selection OWNS n
root.children.add(n)      // link
self.selection = other    // n decays -> silently vanishes from root.children (rule 7)
```

The idea calls this "accidental capture". Its consequence is silent data loss: the order of two lines decides whether the tree keeps the node.

### CE3. Remove-then-keep (the undo pattern) is either resurrection or loss

```
let n = doc.children[0]      // pin
doc.children.removeAt(0)     // links vacuum at once (selection, thumbs gone), decay pending
undoStack.add(n)             // n.owner == null now?
```

- If this store re-owns n, a half-dead object is resurrected. Its incoming links were already destroyed, and undo cannot restore them.
- If the store makes a link to a decaying object, the entry vacuums and self-removes, so the undo stack is silently empty.

The correct code is `undoStack.add(take doc.children[0])`. Moving objects between owners is everyday code (undo, drag-reorder, reparenting, handing to a worker), so "10 is rare" is wrong. Move semantics comes back, just less visibly.

### CE4. Re-entrant close is underspecified

```
closeButton.onTap = { self.window.close(); self.status = "closed" }
```

`close()` drops the Editor, and the closure's captured `self` is a link cell, so it vacuums at once and, under rule 8, the closure decays *while running*. Rule 9 pins "an object running a method", but the object running here is `window`, not `self`. So `self.status` either traps, which contradicts the scenario's "safe" claim, or captures must be pinned on closure entry, which is yet another unstated rule.

### CE5. Non-nesting shared ownership (the brief's hard case) is pushed back onto the programmer

```
let doc = Document.open(p)
win1.doc = doc            // win1 owns
win2.doc = doc            // link
win1.close()              // doc decays under win2 -> vacuum trap / blank window
```

There is no "last one out" ownership. The two choices are:

- Manually `take` and re-home the document on every close (manual lifetime management).
- Park it in a root registry and remove it by hand. Forgetting to remove it is a leak, which is the "scope-bound regions" weakness the brief already lists. Removing it early is a trap.

So for exactly the lifetimes the brief calls hard, this is manual memory management with safe traps.

### CE6. Thread rules are enforced at runtime only, sometimes silently

```
enter stats as s { s.best = self.candidate }   // candidate owned in this universe
                                               // -> cross-universe link: trap (or vacuum per rule 11)
```

Other thread problems:

- `send` vacuums boundary links *silently*.
- A crystal held in a foreign thread is a pin, which is a strong count. The same field is therefore strong in one thread and weak in another.
- Nested `enter a {enter b{}}` in one thread against `enter b {enter a{}}` in another deadlocks, as with any lock-based design.

### CE7. Self-shrinking lists break index code outside `for`

Scenario (e) uses a `while i < xs.count` loop. That is not an "iteration", so rule 7 does not defer removals. If `xs` holds links and any call in the body decays an element, the indices shift and an element is skipped or processed twice. This is memory-safe but silent.

## 4. Scenarios

- **(a) Works.** Strings are values, and the file decays at scope end. No issue.
- **(b) Works, with a sharp edge.** Parent links work. Correctness depends on store order (CE2), and reparenting needs `take`.
- **(c) Hand-wave.** As written, it leaks via an init-time ownership cycle (CE1). It needs an unlisted self-capture rule, and mid-run vacuum is underspecified (CE4). Auto-pruning callbacks are a real win once patched.
- **(d) Works if there is a composition root.** Eviction propagation is elegant. Without a natural single owner it falls into CE5.
- **(e) Works.** Pass-by-link with defined aliasing. Index shifting only matters for lists of links (CE7).
- **(f) Mostly works.** The send/freeze/chamber trio is clean, Pony-like. Violations show up as runtime traps or silent vacuum, not compile errors.

## 5. Gates

- **G2: pass.** There is no tracing; work is proportional to the subtree and its links. Crystals are effectively atomic RC, which is counting, not a GC run.
- **G3: needs-john.** There are no annotations, and `take`/`freeze`/`is here` are operators. It does need compiler-known parameterised `List of T`, `Map of K to V`, `Set of T`, and `Chamber(x)`, the same pending question as the other options. Nothing else in the model requires templates.

## 6. Score

| Criterion | W | Score | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 2 | 12 stated rules, plus 1–2 unstated ones (self capture, closure pins). Ownership depends on store order, so you can't read it off the code; `take` is needed for everyday moves. ARC is ~4–5 rules. |
| Memory safety | 15 | 4 | No dangling or UAF, thanks to vacuum and deferred decay. But leaks via closure-capture cycles (CE1), and vacuum traps are a null-like crash class. |
| Expressiveness (b, c, d, OO) | 15 | 3 | Trees and caches read nicely, and implicit self is fine. (c) is broken as specified, and there is no shared ownership for non-nesting lifetimes (CE5). |
| Implementation risk (AI-written, LLVM) | 15 | 2 | A novel runtime with no reference implementation: tagged slots, link cells, pending-decay states, iteration-aware deferred removal, closure decay, universe retagging, resurrection semantics. Many state interactions. |
| Performance & predictability | 10 | 3 | Deterministic. Costs: a 4-word header, a heap cell per stored link, a branch on every store, pins. Probably ARC-level or worse. |
| Concurrency fit | 10 | 3 | A good model (send/freeze/chamber), but it is checked at runtime, sometimes silently, and strong/weak semantics differ by thread. |
| Tooling, debuggability, C FFI | 10 | 3 | The "who owns this, who links to it" debugger view is excellent. Tagged-pointer slots and link cells complicate C struct interop and debugger pretty-printers. |

**Total** = 25·2/5 + 15·4/5 + 15·3/5 + 15·2/5 + 10·3/5 + 10·3/5 + 10·3/5
= 10 + 12 + 9 + 6 + 6 + 6 + 6 = **55**

This is 28 below O1 (83) and 27 below O4 (82). It lands just under O8 (60), mainly because of simplicity (−10 vs a 4) and implementation risk (−9 vs a 5). Even generous rescoring (simplicity 3, implementation 3, concurrency 4) only reaches 66, which is still well short.

## 7. Fatal flaw and salvageable kernel

**Fatal flaw:** the runtime landing rule. Ownership is decided by store *history* rather than by anything visible in the code. That one choice causes:

- the init-time self-capture cycle (CE1);
- silent deletion by store order (CE2);
- the resurrection-or-loss ambiguity (CE3);
- the absence of any answer for shared non-nesting lifetimes (CE5).

The headline claim, "no cycles possible except via `take`", does not survive the crux scenario. Lobster shows that the same intuition works when done statically with an RC fallback, and that is essentially O1/O4 with optimisation.

**Salvageable kernel, for O1 (ARC):**

1. **Escaping closures capture `self` weakly by default, and a closure whose `self` is gone is a no-op.** Under ARC there is no init-time problem, because the caller retains the object during init.
2. **Compiler-known callback lists (`Event`/`onX`) and weak-entry collections that prune dead entries automatically.** This is Qt-style auto-disconnect. Together with item 1, it removes `[weak self]` / `guard let` boilerplate from scenario (c) while keeping ARC's simple strong-by-default rules.
3. **A debugger "why is this alive" chain** (retain path) and **vacuum-style traps that report the free site.**

**For O4:** the **send / freeze / chamber** triad is a clean, small concurrency surface, ideally checked at compile time via the `shared` kind rather than at runtime.

## 8. Verdict

**Kernel worth stealing.** It is not a contender: it scores 55 against O1's 83 and O4's 82, and its central mechanism fails the crux scenario. Weak-`self`-by-default closures plus auto-pruning callback lists are a real improvement to add to O1.
