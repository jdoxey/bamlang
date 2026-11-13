# Analysis 07: Leasehold (deeds, leases, forfeiture)

Analyst: independent. Inputs: brief.md, CHARTER.md, ideas/07-leasehold-forfeiture.md only.
All code is *illustrative only, not a syntax decision*.

## 1. The idea in three sentences

Every heap object has one owning reference (a "deed") arranged in a tree, and every other reference is a free, storable, cycle-safe non-owning "lease". Each object keeps a register of the heap slots that lease it. When it dies, leases in optional places (`maybe` fields, collection elements) are cleared, and leases in required places (plain `lease` fields, closure captures) destroy their holder, which can cascade. Stack pins delay death until running calls return, wills hand property on at death, and threads only share things through `give`, `Escrow` (a lock) or `seal` (freeze).

## 2. Prior art

Each piece has prior art. Putting them together as the language's only reference model looks new.

| Piece | Prior art |
|---|---|
| Single owner plus non-owning refs, checked when the owner dies | Gel, "Ownership You Can Count On" (Dingle & Bacon): owning pointers plus counted non-owning refs; destroying an object that still has refs is a runtime error. Discussed for Nim's `owned` refs: https://www.mail-archive.com/nim-general@thregr.org/msg14485.html, https://digitalmars.com/d/archives/digitalmars/D/Ownership_You_Can_Count_On_355291.html |
| Same, but halting on violation | Vale's early "constraint references": https://vale.dev/guide/references |
| Per-object register of referring slot addresses, zeroed at dealloc | Objective-C's `__weak` side table (`weak_entry_t` holds referrer addresses): https://git.saurik.com/apple/objc4.git/blob/refs/heads/master:/runtime/objc-weak.h, https://mikeash.com/pyblog/friday-qa-2017-09-22-swift-4-weak-references.html |
| "Clear me" vs "kill me" chosen per relationship | Core Data delete rules Nullify / Cascade / Deny: https://developer.apple.com/documentation/coredata/configuring-relationships.md, https://cocoacasts.com/core-data-relationships-and-delete-rules. Also SQL `ON DELETE SET NULL` / `ON DELETE CASCADE` |
| Holder dies when the thing it depends on dies; "trap" opt-out | Erlang links (exit signal kills the linked process) vs monitors (notification only): https://learnyousomeerlang.com/errors-and-processes, https://www.erlang.org/docs/17/reference_manual/processes |
| Parent-child ownership plus auto-nulling observers | Qt QObject/QPointer (the idea cites this itself) |

**What is new:** applying the Core Data / SQL rule "a non-null foreign key cascades, a nullable one is set to null" to the whole heap, using the language's own optional type as the switch, and making closure captures a required "foreign key". That combination is a real contribution. Its two mechanisms, the side-table register and cascade-on-delete, are proven. The way they are combined is not.

## 3. Soundness: counterexamples

**CE1: forfeiture climbs the ownership chain and silently deletes user state.** Rule 6 sends forfeiture up through required deed fields.
```
class Editor { doc: Document; saveButton: Button; dirty: Bool
  init(log: Logger) {                       // log owned by LogRotator trust, which rotates hourly
    saveButton = Button("Save")
    saveButton.onTap = { self.save(); log.write("saved") }   // captures log: required lease
  } }
// An hour later LogRotator replaces the Logger:
//   old Logger dies -> closure forfeited -> Button.onTap is a required field -> Button forfeited
//   -> Editor.saveButton required -> Editor forfeited -> Window forfeited ...
```
Nothing traps. The window disappears, and the unsaved document is lost unless someone thought to write a `will`. This is a dangling-reference bug turned into silent data loss, which is worse than Swift's `unowned` trap. The idea also leaves undefined what happens when a cascade reaches a trust's required field, since trusts cannot die.

**CE2: closures cannot own what they capture, which breaks the DSL builder pattern (G11).**
```
fn counterView() -> View {
  let model = Counter()                       // deed, local
  return give VStack { Text(model.label); Button("+") { model.inc() } }
}   // model dies at return -> closure forfeited -> Button -> VStack forfeited
```
The caller gets back a view that is already dead. A `Timer.after(5s, { use(buf) })` callback on a local `buf` likewise never fires, and nothing reports it. Rule 4 makes every capture a lease, and no capture-by-`give` exists. A fix is easy to state, but it adds a rule, and every reader then has to tell a dying-capture from an owning-capture.

**CE3: leases that already exist get past Escrow and seal, which is a data race.**
```
let st = Stats();  panel.stats = st          // heap lease, registered
let e = Escrow(give st)                      // deed moves; panel's lease survives
together {
  spawn { e.draw { s -> s.n += 1 } }
  panel.stats.n += 1                         // main thread, no lock: race
}
```
The same applies to `seal(give x)`: older mutable leases can still write to the "frozen" object. The fix is that giving a value into Escrow or seal must void or forfeit all of its existing leases. That is a cascade inside a constructor call, and it is not in the rules.

**CE4: register updates on sealed objects race across threads.**
```
let table = seal(give loadTable())
together { for c in chunks { spawn { let r = Row(); r.src = table; out.draw { l -> l.add(give r) } } } }
```
Every `r.src = table` appends to `table`'s non-atomic register from N threads. If the implementation does not register these leases, then after `together` the rows in `out` hold unregistered leases, and they dangle when `table` dies. Either way the "registers stay non-atomic" claim does not hold.

**CE5: a will's bequest gets forfeited anyway.**
```
class Document { lease editor: Editor ... }  // required back-link
will { if dirty { App.pendingSaves.add(give doc) } }
```
Step 2 runs the will and moves `doc`. Step 4 then voids `doc.editor`, which forfeits `doc`, which removes it from `pendingSaves`. Wills only work if the bequeathed graph has no required leases back to the dying object. That is a non-local condition, and the user has to know about it.

**CE6: the rule-7 trap is common, not rare.**
```
fn refresh(v: DetailView) {        // v.image is a required lease
  Caches.evictOlderThan(1.hour)    // forfeits v (pinned, deferred), voids v.image
  draw(v.image.pixels)             // trap
}
```
Any function that keeps an object on the stack across a call that may destroy things can hit this. So "required leases are always valid, no checks" really means "valid unless you are currently using the object". A trap needs either a check on each read or a guard-page sentinel. A guard page does not catch identity comparisons or passing the lease along without touching it. This is the same failure class as O6's generational check, just moved to a different place.

**Minor:** tombstones in a `List of lease T` are compacted when the list is unpinned, so an index saved earlier silently shifts to a different element. `xs.add` during a pinned iteration reallocates the buffer, and the rules don't say what happens to the iterator. Nested `draw` on two escrows in opposite order deadlocks, same as any mutex. `let x = make()` (deed) and `let x = cache.get()` (lease) look identical. A long-running `main` that holds a local lease pins that object forever.

## 4. Scenarios

- **(a) Growing list:** works. It is ordinary single ownership.
- **(b) Parent pointers:** works cleanly. `lease parent: maybe Node` is better than `weak` because no nil check is needed in the live tree.
- **(c) UI callback:** this is the best part for a closure that captures `self` of a long-lived owner. Auto-deregistration from `App.shortcuts` and the timer is genuinely better than O1. It fails for captured locals and builders (CE2), and it can cascade destruction upward (CE1). **Partially works.**
- **(d) Shared cache:** works well on one thread. The "drop the entry" vs "drop me" choice is elegant and new. A cache shared across threads goes through Escrow only.
- **(e) Mutating a large list:** works. The lease parameter plus a pin is simple, with no `inout`. Behaviour when the list reallocates during a pinned iteration is unspecified.
- **(f) Threads:** fork-join over give/escrow/seal is fine. CE3 and CE4 are real holes in the rules as written. Long-lived cross-thread sharing cannot be expressed. **Partially works.**

## 5. Gates

- **G2: pass.** No tracing. Death is deterministic: a worklist walks the dying object's own register and its owned subtree. Cascades are unbounded, as in RC, but they are not a GC run.
- **G3: needs-john.** There are no user-written templates, macros or annotations. `lease`, `maybe`, `will` and `trust` are keywords, not annotations. But `List of lease T`, `Map of K to V` and `Escrow(give Stats())` (an Escrow of Stats) are built-in parameterised types, and `lease` appears inside type arguments. That is the brief's pending question, plus one more modifier position.

## 6. Scores

| Criterion | W | Score | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 3 | Everyday code needs only give, lease and maybe, but there are 10 rules, plus capture-by-give (needed), plus the required/vacatable consequences, plus action at a distance. Users will ask "why did my callback or window vanish?". More to learn than O1's ARC plus weak. |
| Memory safety | 15 | 3 | No UB by design on one thread, but CE3/CE4 are races under the rules as written, and CE6 shows the trap path is mainstream. Patchable to about 4. |
| Expressiveness (b,c,d,G11) | 15 | 4 | (b) and (d) are excellent and (c) for `self` is the best seen. Builders and captured locals break (CE2), and the upward cascade is hazardous (CE1). |
| Implementation risk (AI-written, LLVM) | 15 | 2 | Several novel runtime mechanisms have to work together: per-object registers, 16-byte lease slots with index fix-ups on reallocation, a tombstone/compaction scheme tied to pins, a whole-program may-destroy analysis for pin elision, reentrant wills inside a worklist cascade, escrow escape analysis, and VOID-sentinel traps. There is no reference implementation to copy. |
| Performance & predictability | 10 | 3 | Reads are free and there are no atomics. Each heap lease store is a register append (which may allocate). Headers are 2–3 words and leases are 16 bytes. List reallocation scatters writes into n other registers. Cascade latency is unbounded and its extent is hard to predict. |
| Concurrency fit | 10 | 3 | Structured and non-atomic, which is good. Restrictive, with holes CE3/CE4. Nothing beyond fork-join plus locks. |
| Tooling, debug & C FFI | 10 | 3 | The forfeiture log and deed-chain view are strong debugging tools. But FFI is awkward: C code that holds a pointer is an unregistered lease, 16-byte lease fields don't match C struct layout, and C needs a pin/handle API. |

**Total** = (25·3 + 15·3 + 15·4 + 15·2 + 10·3 + 10·3 + 10·3) / 5 = (75 + 45 + 60 + 30 + 30 + 30 + 30) / 5 = 300 / 5 = **60**.

Compared with the references, that is 23 below O1 (83) and 22 below O4 (82), level with O8 (60). It loses mainly on simplicity (−1 to −2 against both) and implementation risk (−3 against O1). It beats both only on expressiveness for (c) and (d). Even if every hole were patched (safety 4, simplicity unchanged), the total would be 63, still well below O1 and O4.

## 7. Fatal flaw and salvageable kernel

**Fatal flaw.** Forfeiture makes a broken reference destroy its holder. Because rule 6 climbs required ownership fields, a small transient dependency can silently destroy user-visible, stateful objects far away (CE1, CE2, CE5). The same is true without the climb whenever forfeiture is the default for captures. Swift's `unowned`, Vale and Gel all trap instead, because "crash with a report" is safer than "quietly delete the window". On top of this, the register-based runtime is the highest-risk build in the comparison for an AI-written compiler.

**Kernel worth stealing (for O1 or O4), with forfeiture limited to closures and vacatable slots only.** Leasehold's best result is: *a closure registered in a collection is removed automatically when an object it captured non-owningly dies.* In O1 terms:
- Escaping closures capture `self` (and other class refs) **weakly by default**. Keep strong capture as an explicit opt-in.
- A closure whose weak capture has died is **expired**. Calling an expired closure is a no-op. A built-in `Callbacks` / `List of closure` drops expired entries the next time it is iterated or compacted.
- Inside the closure body, `self` is non-optional, because the body only runs after the runtime has checked liveness once at entry. This removes `[weak self]` and `guard let self`, at the cost of one check per closure call instead of one per dereference.

That gives (c) auto-deregistration with no new ownership vocabulary, no registers (it uses the existing weak/side-table mechanism) and no upward cascade. It also maps to Core Data's "Nullify" rule applied to subscriptions. A secondary kernel: O4's built-in `shared` cache could offer an optional "evict means clear the weak holder's map entry", i.e. a vacatable `Map of K to weak V` (needs-john under G3).

## 8. Verdict

**Kernel worth stealing.** It is not a contender (60 vs 83/82). It is also not a dead end: closures that expire on weak capture and drop out of their registry would make O1 noticeably better on scenario (c).
