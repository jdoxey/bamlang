# Analysis 15: Double-Entry Claims

Analyst: independent. Sources read: brief.md, CHARTER.md, ideas/15-double-entry-claims.md.
All code is illustrative only — not a syntax decision.

## 1. Restatement

Every `class` instance has exactly one owning slot. It is freed (closed) the moment that slot lets go, and everything it owns is freed with it.
Every other reference is a non-owning *claim*. The target records the claim's address in a per-object register, so on close it can visit each holder and fix it according to the slot kind: null a field, remove a collection element, cancel a closure.
A per-object "open" counter defers closing while any method, `with` block or capturing closure of that object is running. Threads get subtree transfer and lock-protected `shared class` monitors.

## 2. Prior art

This is a new combination, and the individual parts have well-known ancestors.

- **The register is Objective-C's zeroing-weak side table.** The ObjC runtime's `weak_table_t`/`weak_entry_t` stores, for each object, the *addresses* of the `__weak` variables that point at it, and zeroes them on dealloc. That is exactly what rule 6 does for the "field" case.
  https://opensource.apple.com/source/objc4/objc4-706/runtime/objc-weak.h.auto.html ,
  https://www.besthub.dev/articles/understanding-the-implementation-of-weak-pointers-in-the-objective-c-runtime-c854b3020d7e
- **Ownership tree plus two-sided notification is Delphi/VCL `TComponent`.** The Owner frees the components it owns. `FreeNotification` books the referrer in the target's list, and `Notification(opRemove)` lets referrers nil their fields. This is double-entry by another name, dating from the 1990s.
  https://docwiki.embarcadero.com/Libraries/Athens/en/System.Classes.TComponent.FreeNotification ,
  https://docwiki.embarcadero.com/Libraries/Rio/en/System.Classes.TComponent.Notification
- **Closure cancellation plus deferred close is the Qt object model.** In Qt, QObject parents delete their children, `QPointer` auto-nulls, a lambda connected with a context object is disconnected when that context is destroyed, and `deleteLater` defers deletion until control returns to the event loop.
  https://qtlabs.readthedocs.io/en/latest/lab1/qobject.html ,
  https://kiwix.lema.org/stackoverflow.com_en_all_2023-11/questions/33357410/do-i-still-have-to-disconnect-a-lambda-from-a-signal-in-qt5-5 ,
  https://planet.kde.org/kai-uwe-broulik-2026-04-24-qt-no-contextless-connect/
- **Owned plus non-owning references with a check at delete is Gel ("Ownership You Can Count On", Dingle and Ungar), later Nim's `owned ref` experiment and Vale's constraint refs.** Those systems *count* aliases and trap if any remain. This idea *settles* the aliases instead.
  https://www.mail-archive.com/nim-general@thregr.org/msg14485.html
- **Subtree send is Pony's `iso` / Rust's move-of-`Send`. `shared class` is a classic monitor.**

**What is genuinely new:** turning Qt/Delphi framework conventions into language semantics, with slot-kind-aware settlement (remove from collections, cancel closures) covering *every* non-owning reference. None of O1–O8 does that. The register itself is not new.

## 3. Soundness: counterexamples

### CE1. Use-after-free through interior pointers when the open check is elided (as specified)
Rule 10 only marks an account "lent" and checks it "once per open". §5 elides opens when the callee has no *may-close* effect. Overwriting a *value* field is not a may-close effect.
```
class Doc { lines: List<String>
  fn reset() { lines = List<String>() } }   // frees the old buffer; no owner slot touched → no may-close
class App { doc: Doc }
fn fill(edit xs: List<String>, app: claim App) {
  app.doc.reset()      // open of doc elided (reset has no may-close effect) → lent check skipped
  xs.add("boom")       // xs points into the freed buffer → UAF
}
fill(edit app.doc.lines, app)
```
There are two ways to fix it. Either the lent check is never elided, which means a dynamic exclusivity check on every method call through a claim (Swift-style cost), or a second effect ("may-mutate-value-field") is inferred, which makes the inference harder. The same hole exists for **read-only** value parameters if they are passed by reference, and the spec never says whether they are. Passing them by copy instead would copy a whole list on every call.

### CE2. In-place iteration over owners can be invalidated by the loop body
```
class Tree { children: List<Node>
  fn grow() { for c in children { children.add(Node("x")) } } }  // owners can't be copied, so the loop iterates in place
```
`add` reallocates the buffer under the iterator. Nothing in the 11 rules covers this. Accessing `self` inside your own method is not an "open". The likely fix is a modCount-style trap (Java's `ConcurrentModificationException`), which is effectively a 12th rule plus a check per container.

### CE3. Any captured account kills the closure, not just `self`
```
saveButton.onTap = fn() { log.info("tap"); self.save() }  // captures self AND log
app.log = Logger("new.log")                                 // log rotation closes the old logger
// → onTap is cancelled. Save silently stops working.
```
Swift's `[weak self]` pattern only fails on `self`. Here the callback's lifetime is the *minimum* over everything it captured, and the rules give no way to say "this capture is incidental".

### CE4. Locally-owned state captured by declarative UI (G11)
```
fn counterView() -> View {
  let model = CounterModel()                    // local owner
  return Column { Text(fn() { model.label() })  // captures a claim
                  Button("+", fn() { model.inc() }) }
}                                               // model closes here → both closures cancelled → dead UI
```
The SwiftUI/React "state owned by the view" pattern needs explicit ownership plumbing: a field on some view, or `View.own(x)`. That is not in the rules, and closures cannot co-own state. This is the brief's crux in its DSL form, and here it is handled by hand-waving.

### CE5. Collections that change at a distance break value semantics
Rule 1 says `List` is a value ("never shared"), yet write-off mutates it remotely:
```
class Gallery { visible: List<claim Image>; thumbs: List<Thumb>; selected: Int }
cache.evict("k")   // Image closes → removed from `visible` only
// thumbs[i] no longer matches visible[i]; `selected` now points at a different image
let n = visible.count; doWork(); assert(visible.count == n)   // may fail with no write to `visible`
```
The `Map<claim K, V>` case is worse. When K closes, the entry is removed and V, which may be an owner, closes too. That gives a cascade triggered from inside another object's settlement.

### CE6. "A child never sees a void parent" is false
```
child.work()      // child is open; root is not
  └ callback sets  app.root = none   // root closes now; child's close is deferred; child.parent is written off
  └ self.parent.name                  // traps (rule 7 shorthand)
```
This is memory-safe, but it is a crash at a distance. Claims behave like implicitly-unwrapped optionals: nullable, with a direct call trapping.

### CE7. Incompletely specified pieces
- **Cancelled closure "yields none".** Every call to a closure that captures an account must then return `T?`, which also affects comparators and `map` callbacks. Alternatively the closure's type has to reveal that it captures accounts. Neither option is specified.
- **`send` only writes off claims *on* the subtree.** Claims and closures *from* the subtree to old-thread accounts are not mentioned. Without writing them off, the result is a data race. With it, `send` is an O(subtree) walk, not "cheap".
- **Deadlock.** Escrow method A calls escrow B on one thread while B calls A on another. This is a classic monitor deadlock, and nothing in the rules orders the locks.
- **Atomic claim slots.** Escrow claims are 16-byte `{ptr, index}` pairs written by other threads during write-off, so they need 128-bit atomics or a lock. Swap-remove also patches *another* holder's slot, which can be on another thread's stack.
- **Resurrection.** If a destructor or settlement step makes a new claim on an account that is closing, the spec does not say what happens.

## 4. Scenarios

| | Verdict |
|---|---|
| (a) | **Works.** Values only. Caveat: read-only parameter passing (copy or reference) is unspecified (see CE1). |
| (b) | **Works.** Parent is a claim, so there is no `weak` and no cycle. The "never sees void parent" claim is overstated (CE6), and a deep owner chain closes by recursion (risk of stack overflow). |
| (c) | **Works for the stated `self` case,** and better than ARC: no `[weak self]`, and the close-from-own-button case is safe. **Hand-waves** for incidental captures (CE3), local DSL state (CE4) and the type of a cancelled closure's return. |
| (d) | **Works with restructuring.** It forces a common ancestor owner. Auto-pruning of `List<claim Image>` is nice, but it desyncs indices and parallel lists (CE5). |
| (e) | **Works on paper.** Soundness depends on the lent check never being elided (CE1). Per-account lending also gives false-positive traps, e.g. a callback that reads `doc.title` while `doc.lines` is lent. |
| (f) | **Partial.** Escrow covers counters and subtree send covers handoff. Outgoing claims on `send`, monitor deadlock and 16-byte atomic slots are unaddressed (CE7). |

## 5. Gates

- **G2: pass.** Nothing traces. Close is eager and deterministic, at a known program point. Deferred close and deferred container compaction are bookkeeping, not a collector run. The debug-only trial balance is not a GC.
- **G3: pass, with flag.** `claim`, `edit` and `shared class` are keywords at the level of O1's `weak`. The may-close effect is inferred, not annotated. It relies on built-in `List<T>`/`Map<K,V>`, including `List<claim T>`, which is the same pending question as O1/O4 → flag for John, not a fail.

## 6. Score

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 3 | 11 stated rules plus about 3 implied ones (iteration, the type of a cancelled closure, outgoing claims on send). No lifetimes, but users must design an ownership tree and reason about deferred close and write-off at a distance. |
| Memory safety | 15 | 3 | Designed so claims cannot dangle, but as specified it has interior-pointer UAF holes (CE1, CE2), a cross-thread race on send, and owner-cycle leaks in release. All fixable, with added dynamic checks. |
| Expressiveness (b)(c)(d), OO/G11 | 15 | 4 | (b) is clean and (c) is best in class for `self`. Weakened by forced single owners (d), the capture-minimum lifetime (CE3) and local DSL state (CE4). |
| Implementation risk (AI-built, LLVM) | 15 | 2 | Claims need stable addresses (this works against mem2reg/SROA). Also needed: move fix-ups for every claim-bearing value, swap-remove patching, dead-slot compaction, interprocedural may-close inference through closures and virtual calls, a deferred-close state machine and atomic escrow write-off. Book corruption is silent in release builds. |
| Performance & predictability | 10 | 3 | Deterministic, and owner moves are free. But a claim costs 16 B plus a 24 B register entry, against 8 B for a pointer. Every claim copy or drop or closure creation touches the target's register. A list reallocation rewrites N entries, and a long-running holder stalls frees. |
| Concurrency fit | 10 | 3 | Subtree send and monitors are simple and adequate. But deadlock-prone, coarse, needs atomic 16 B slots, and the send semantics are incomplete. |
| Tooling, debug, C FFI | 10 | 4 | `audit.claims(x)` and the ownership-tree memory profile are genuinely excellent for G8. FFI via `with` plus `ffi.claim` is workable. C APIs that take ownership map awkwardly. |

Total = (25×3 + 15×3 + 15×4 + 15×2 + 10×3 + 10×3 + 10×4) / 5
= (75 + 45 + 60 + 30 + 30 + 30 + 40) / 5 = 310 / 5 = **62**.

That is 21 below O1 (83) and 20 below O4 (82). It is ahead of O8 (60) and behind O2 (67). Even if every hole were fixed cleanly (safety 4, simplicity unchanged), it would reach about 65. The gap comes from implementation risk and per-reference runtime cost, which no amount of specification removes.

## 7. Fatal flaw and kernel

**Fatal flaw (as a whole model).** It moves the hard part from the type system into a runtime ledger that must stay exact across every move, copy, reallocation, thread hop and optimisation pass. Making it sound needs dynamic exclusivity checks it does not yet have (CE1, CE2). Its signature feature, closures dying with *anything* they captured, makes callback lifetime the minimum over the captures, which surprises users exactly in G11 code (CE3, CE4). It is more machinery than ARC for comparable safety. The one problem it really solves, (c), can be solved more cheaply within O1.

**Salvageable kernel.** Slot-kind-aware settlement, applied only to *weak* references in O1 (or to O4's `shared`):
1. **Auto-cancelling weak captures.** A closure that captures `self` weakly (or by default, for `self` only) is *removed* from its event source when `self` dies, instead of guarding with `guard let self`. Only `self` triggers this, never incidental captures. This is Qt's context-object rule as a language default, and it removes `[weak self]` ceremony from G11 code.
2. **Weak collections that prune themselves:** `List<weak T>`. This is the NSHashTable `weakObjects` idea, at the cost of an explicit note that it mutates at a distance.
3. **Deferred dealloc while a method of the object is running,** which ARC can get by retaining `self` for a method's duration. This makes "close the window from its own button" safe.
4. **A debug-build reverse-reference side table** (ObjC-style) behind `audit.claims(x)` and an ownership/retain-tree memory view, serving G8 at zero release cost.

## 8. Verdict

**Kernel worth stealing.** It is not a contender: 62 against 83/82, mainly because of implementation risk and runtime cost. But auto-cancelling weak-`self` closures and the debug reverse-reference audit are worth adding to O1.
