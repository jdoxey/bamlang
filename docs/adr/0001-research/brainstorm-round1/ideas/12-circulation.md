# 12 — Circulation

## 1. Name

**Circulation**: single ownership, plus *reading-room loans* that pin and *take-home loans* that get recalled eagerly.

## 2. Inspiration

A library owns every book exactly once: it has one shelf mark in the catalogue. Everyone else only ever has a **loan**. Loans come in two kinds that behave differently:

| Library | Memory |
|---|---|
| Catalogue entry / shelf mark | The single **owner** slot of an object (a field, collection slot, global, or local) |
| **Reading-room** use: you read it at the desk and give it back before you leave the building | A loan held in a **local, parameter or temporary**. It is bounded by a stack frame. While it exists, the book can't be pulped. |
| **Take-home** loan: recorded on the book's circulation card | A loan stored in a **field, collection or closure capture**. The object's *card* lists every slot that holds one. |
| **Recall notice** | When the object is withdrawn, the runtime walks the card and empties every take-home slot right away. |
| **Deaccessioning** (withdrawal) | The owner drops the object. Take-home loans are recalled immediately. The storage is pulped once the last reading-room reader leaves. |
| **Reference-only** items | **Frozen** objects. They are immutable, any branch may consult them, and they are safe to count across threads. |
| **Interlibrary loan**, due back on a date | Lending a subtree to a spawned task. It is "due" at the join, and the home branch can't touch it until then. |
| **Reservation / hold queue** | A **desk**: a mutable object shared between threads. You `reserve` it, holds are served in FIFO order, and you get exclusive use. |

The key move: *stack references keep things alive, heap references never do, and heap references are cleared eagerly.* Stack lifetimes always nest, so counting them can't leak. Heap aliases are where cycles and dangling pointers come from, so those never own, and the owner actively calls them back.

## 3. Pitch

Every object lives on exactly one shelf: its owner. Ownership forms a tree, so cycles of ownership can't exist. Every other reference is a loan, and you never write which kind. The *place* you put it decides. A loan in a local is a reading-room loan. It is guaranteed valid for as long as you hold it, because withdrawal waits for reading-room readers to leave. A loan in a field or closure is a take-home loan. It is registered on the object's circulation card, and when the object is withdrawn the runtime clears it to `none`. A loan never dangles and never extends a lifetime. Closures get one special rule. On every call they check out all their take-home captures at once. If any capture has been recalled, the closure doesn't run. So a button whose editor has gone does nothing, and an editor that closes itself mid-callback stays intact until the callback returns. There are no annotations, no lifetime parameters, no weak/strong choice, no tracing, and no cycle collector. The cost is a pin counter on locals, plus an intrusive linked list for heap aliases.

## 4. The rules

1. **Values and items.** Numbers, booleans, strings and small records are values, and they are copied. Class instances are *items*. They live on the heap at a fixed address and are never copied implicitly.
2. **One shelf.** Every item has exactly one owner: a field, a collection slot, a global, or a local.
3. **First shelf wins.** A new item is owned by the local that receives it. The first time you store that local into a field or collection, ownership moves there, and the local continues as a reading-room loan. Storing it anywhere afterwards makes a take-home loan. Returning an owning local hands it to the caller.
4. **`give` moves a book between shelves.** `a.x = give b.y` moves ownership and empties `b.y`. Without `give`, storing an item that already has a shelf only lends it.
5. **Reading-room loans are always valid.** A loan held in a local, parameter or temporary can never be freed under you.
6. **Take-home loans can come back empty.** A loan held in a field or collection reads as optional: `if p = self.parent { ... }`.
7. **Withdrawal.** An item is withdrawn when its shelf is overwritten or emptied, when its owner is withdrawn, or when you write `withdraw x`. At that point every take-home loan to it becomes `none`. Its storage, and its own subtree, is freed once the last reading-room loan to it ends.
8. **Closures check out all-or-nothing.** On each call, a closure checks out every captured item. Captures always behave as take-home loans, and `self` is one of them. If any capture has been recalled, the body is skipped and the call returns `none`. Otherwise every capture is pinned for the duration of the call.
9. **Branches (threads).** Each thread is its own branch. An item crosses to another branch in one of three ways:
   - `send x`: transfer the subtree.
   - `freeze x`: make it reference-only, i.e. immutable and readable everywhere.
   - `lend x to spawn { ... }`: an interlibrary loan, due at the join. `x` can't be used in the lending scope until then.
10. **Desks.** `desk x` makes a mutable item shareable between threads. You reach it only inside `reserve d { ... }`, which gives exclusive access in FIFO order. A loan from inside a desk can't be stored outside the desk; doing so traps.

That is ten rules. In everyday single-threaded code you meet rules 1–8. Rules 4, 9 and 10 are rare.

## 5. Under the hood

**Item header**, 16 bytes:
- `pins`: u32, non-atomic. Frozen items use an atomic variant.
- `card`: the head of an intrusive doubly linked list of take-home slots.
- `flags`: withdrawn, frozen, and a branch id (the thread, or the desk that the item belongs to).

**Take-home slot** (3 words): `target`, `next`, `prev`. These are fields typed as items, collection elements holding loans, and closure captures.
- Storing into a slot is O(1): unlink from the old card, link into the new one.
- When a list buffer holding loans is reallocated, the compiler-generated relocation patches the neighbours' links. This is O(n), but realloc is already O(n).

**Reading-room loans** cost an increment on entry and a decrement at scope exit.
- The compiler skips both when it can see that no call or store in the scope could withdraw anything. This conservative check covers leaf loops, arithmetic and getters.
- `self` in a method is a reading-room loan, pinned by the caller.

**Withdraw(x):**
1. Set `withdrawn`.
2. Walk the card, setting every slot's `target` to null.
3. If `pins == 0`, free x now. Otherwise push x onto the thread-local *returns cart*. When a pin decrement reaches zero on a withdrawn item, it frees it.
4. Freeing pushes x's owned fields onto an iterative worklist, so a long list can't overflow the stack.
5. Recall is skipped for slots that live inside items in the same cascade. Parent pointers in a dying subtree aren't walked twice.

None of this is GC. There is no tracing and no background run. Every free happens at a statically known kind of point: an overwrite, a scope exit, or a `withdraw`.

**Closure call.** The closure call's prologue loads each capture slot. If one is null, it returns `none`. Otherwise it pins every capture, and the epilogue unpins them. A closure literal is a heap item owned by the slot it is first stored in (rule 3), for example `button.onTap`.

**Threads.**
- `send` walks the subtree. It recalls take-home loans that cross the boundary in either direction, then retags the branch id. Sending a subtree that is still pinned elsewhere traps.
- `freeze` deep-marks the subtree. References to it from other branches are atomic pins rather than card entries. A frozen graph can only point at frozen items, so pins can't form a cycle.
- `lend` retags to the child task and restores the tag at the join. The compiler hides the variable until the join.
- A desk is a mutex with a FIFO hold queue. Stores check branch tags, and a store across branches traps.

**Lints and tooling.**
- A lint flags any item owned only by a local but captured by a closure that is stored to the heap: *"this item has no shelf; it will be withdrawn at end of scope."* This is the main foot-gun, and it is cheap to detect.
- The debugger gets a **circulation view** for any item: its owner chain, pin count, every take-home loan holder, and whether it is withdrawn and awaiting return.
- **C FFI:** items never move, so a pointer handed to C is valid for the duration of a reading-room loan. To hand C a long-lived pointer, call `withdraw`-guarded `pin_forever` / `unpin`.

## 6. Scenarios

*All code is illustrative only — not a syntax decision.*

### (a) Read lines

```
fun readLines(path) {
  lines = List()                       // local owns the list
  for line in File.open(path).lines() {
    lines.add(line)                    // strings are values: copied in
  }
  return lines                         // owning local -> ownership to caller
}
```
The list owns a growable buffer of values. No loans are involved and there is zero overhead beyond `Vec`.

### (b) Tree with parent pointers

```
class Node {
  children = List()                    // owns its children
  parent                               // take-home loan, optional
  fun add(child) {
    children.add(child)                // fresh child -> shelved here (rule 3)
    child.parent = self                // self is a loan -> take-home loan
  }
}
fun rootOf(n) { while p = n.parent { n = p }  return n }
```
Ownership goes down the tree and loans go up. Removing a subtree (`children.removeAt(i)`) withdraws it. Its internal parent loans die with it, and no recall walk is needed. Any outside loan into the subtree, for example `selection = node` in a field, becomes `none`.

### (c) UI callback (the crux)

```
class Editor {
  text = ""
  window
  fun build() {
    window = Window()
    saveBtn = Button("Save")
    window.add(saveBtn)                // window shelves the button
    saveBtn.onTap = { save()  window.close() }   // captures self as take-home loan
  }
  fun save() { Disk.write(text) }
}
app.editors.add(Editor())             // the app's list is the editor's shelf
```
- **There is no cycle.** The app owns the editor, which owns the window, which owns the button, which owns the closure. The closure's link back to the editor is only a loan.
- **The editor is removed while the button is still referenced somewhere**, for example by an animation. The closure's capture is recalled, so tapping does nothing. This is Swift's `[weak self] guard let self` with nothing written.
- **`save()` or `window.close()` withdraws the editor during the call.** The editor and its subtree are pinned for the call, so they stay readable. They are freed when the closure returns, at a deterministic point.
- **Implicit `self` (P-PY) works**, because the capture is automatic.

### (d) Shared mutable cache

```
class App {
  cache = Cache()                      // App is the shelf
  feed = Feed(cache)                   // Feed.cache field: take-home loan
  search = Search(cache)               // Search.cache field: take-home loan
}
class Feed {
  cache
  init(c) { cache = c }
  fun show(id) {
    if c = cache {
      e = c.get(id)                    // reading-room loan to the entry
      c.evict(id)                      // entry withdrawn... but pinned by e
      render(e.body)                   // still valid; freed at scope exit
    }
  }
}
```
Both components mutate through their loans; single-threaded aliasing is allowed. A component that keeps `self.current = entry` gets `none` after eviction, so stale-entry bugs turn into visible `none` instead of being kept alive silently.

### (e) Mutate a big list in a function

```
fun dedupe(xs) { ... xs.removeAt(i) ... }   // param = reading-room loan, mutable
dedupe(self.lines)                           // no copy, no move, no annotation
```
Parameters are reading-room loans, so passing is a pointer plus a pin. Items removed inside the function are withdrawn. If the caller still holds a local loan to one, that loan keeps it readable until the caller's scope ends.

### (f) Threads

```
config = freeze loadConfig()                  // reference-only: any thread reads
stats  = desk Stats()                         // shared mutable, hold queue

lend chunk = give self.bigBuffer to spawn {   // interlibrary loan, due at join
  process(chunk, config)
  reserve stats { stats.count += 1 }
}                                             // join: chunk back home here

worker = Worker()
send worker to spawn { worker.run() }         // permanent transfer
```
- Pins and cards stay non-atomic, because a branch only ever touches its own items.
- Atomics appear only on frozen pins and desk locks.

## 7. What's genuinely new compared with the covered options

- **Loan kind comes from the storage location, with no annotation.**
  - Stack aliases are *strong but nest*. They are counted and can't leak, because frames end.
  - Heap aliases are *never strong*. They are weak and eagerly recalled.
  - O1 makes heap aliases strong and needs `weak` annotations to break cycles. O4 and O6 forbid or check borrows. Here, which strength a reference gets is decided by where it lives, not by what the programmer chooses.
- **Eager recall through an intrusive circulation card, not a lazy check.** O6 (Vale) leaves the dangling pointer and checks a generation on each dereference. Here every heap alias is nulled at withdrawal. That makes `none` observable in the debugger, and dangling bits never exist even transiently.
- **Deferred withdrawal pinned by stack loans.** Freeing an item that is in use is *safe and deterministic*: the free waits until the scope ends, rather than trapping as Inko's borrow counts do, or being forbidden at compile time as in Rust.
- **All-or-nothing closure checkout.** This semantic rule solves (c) directly:
  - callbacks can't resurrect or extend their target;
  - they can't create cycles;
  - they can't observe a half-dead target;
  - they need no capture lists.
- **The first store becomes the owner.** Ownership comes from data flow into the heap, so you rarely write a move. `give` exists only for re-shelving.
- **Frozen-only cross-thread counting.** Immutability rules out cycles, so atomic pins are restricted to exactly the items where they're provably leak-free.

## 8. Known weaknesses

- **Silent no-ops.** A callback that quietly doesn't run can hide bugs. The lint and the debugger's "recalled capture" log help, but some users will want it to trap.
- **The "no shelf" foot-gun.** An object created in a setup function, captured by a callback, but never stored in a field, vanishes at scope end. The lint catches the common case, not all cases.
- **No "last user frees" lifetimes.** A session that should live while *anyone* uses it needs an explicit owner, plus a user-written count or `withdraw`. RC does this for free.
- **Memory cost of take-home slots.** Each slot is 3 words. Collections of loans are fat, and buffer relocation must patch links. That is extra implementation surface for an AI-written compiler, though it is mechanical.
- **Recall cost isn't O(1).** Withdrawing a popular item walks every loan to it, so the latency spike is proportional to the number of aliases. It is predictable, but not free.
- **Order-dependence of rule 3.** Swapping two store statements can change which field owns the object. The rule is learnable, but it is an action-at-a-distance hazard, and refactoring tools must preserve it.
- **Runtime traps in thread rules.** `send` while pinned and cross-branch stores into a desk trap at runtime rather than failing at compile time.
- **Optional fields everywhere.** Every item-typed field reads as optional. `if p = self.parent` will be written a lot.
- **Self-assessment:**
  - G2: pass.
  - G3: pass, assuming `List`/`Map` are compiler-known.
  - Simplicity: about 8 core rules, somewhat more than O1, but with no weak/strong decisions.
  - Expressiveness for (b), (c), (d): strong.
  - Main risks: implementation complexity of the cards, and silent no-ops.
