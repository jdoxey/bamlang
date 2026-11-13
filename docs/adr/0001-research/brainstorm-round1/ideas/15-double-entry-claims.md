# 15 — Double-Entry Claims (owners, claims, write-offs)

## 1. Name

**Double-Entry Claims.** Every reference is written down in two places: in the slot that holds it and in the books of the object it points to. Objects never wait to be "collected". They close, and closing settles their books.

## 2. Inspiration: how the lens maps onto memory

| Accounting | Memory |
|---|---|
| **Account** (a ledger of one entity) | An instance of a `class`: identity, on the heap, can be referred to. |
| **Equity / controlling interest**: exactly one party owns the entity | Exactly one **owner** slot (a variable, field or collection element). |
| **Receivable / liability pair**: one transaction, two entries | A **claim** (non-owning reference). The holder's slot records it, and the target's **liability register** records where the slot is. |
| **Closing the company**: settle every liability before dissolving | Closing an account **writes off** every claim on it, eagerly. The account's own register says exactly which slots to visit. |
| **Derecognition**: a written-off receivable is removed from the books, not left as a zero line | A written-off claim in a collection is *removed*. A closure that depended on it is *cancelled*. |
| **Books open during the period** | While a method of an account runs, its books are **open**, and a close is deferred until they shut. |
| **Subsidiaries are consolidated, and are wound up before the parent** | Owned accounts close first, depth-first. |
| **Change of control**: claims from outside the new jurisdiction lapse | Sending an account subtree to another thread writes off claims on it held by the old thread. |
| **Escrow** | A `shared class`: any thread may hold claims, and one method runs at a time. |
| **Audit / trial balance** | Debug builds check that both sides of every entry match whenever an account's books shut. The tooling can always answer "who holds claims on X?" |

The key accounting idea is that **every obligation is booked on both sides**. ARC keeps a *count* of references. Generational references keep a *version stamp* and find out about dangling at dereference time. Double-entry keeps the *location* of every non-owning reference. So when the owner closes an object, the system knows each slot it has to fix, and it can fix them in ways that suit the slot. A field becomes empty. A list loses the element. A callback is unsubscribed.

## 3. Pitch

Objects form an ownership tree. Each object has exactly one owner, and it is freed deterministically the moment its owner lets go. There are no counts, no tracing and no lifetime annotations. Every other reference is a *claim*, and the target object keeps a register of where each claim is held. When an object closes, it settles its books. Claims in fields become `none`. Claims in collections disappear from the collection. Closures that captured the object are cancelled, so a button's `onTap` that captured a closed editor no longer exists, and code inside a closure never sees a dead `self`. Closing is deferred while the object's books are open, meaning while any of its methods, `with` blocks or dependent callbacks is running. Re-entrant "close the window from its own button" code is therefore safe. The programmer states one thing the compiler can't infer: *who owns what*. They never state *how long things live*.

## 4. The rules (everything a programmer must learn)

1. **Two kinds of type.** `class` instances are *accounts*: they have identity and can be referred to. Everything else (numbers, strings, `List`, `Map`, `record`) is a *value*: copied or moved, never shared, and freed when overwritten or when its holder goes away.
2. **One owner.** A slot whose type is a plain class name (`b: Button`, `List<Node>`) *owns* the object it holds. A new object is owned by the slot that receives it.
3. **Transfer.** Assigning an owner into another owner slot transfers ownership, and the source can't be used afterwards (compile error). `take x.f` moves an owner out of an optional field and leaves `none` behind. Collection `remove…` methods return the owner.
4. **Close.** When an owner slot is overwritten, set to `none`, or goes out of scope, its account *closes*. Accounts it owns close first, then it is freed.
5. **Claims.** Every other reference is a *claim*. A claim can be a slot declared `claim Editor`, a local copied from a field or parameter, or a captured variable. Claims never keep anything alive.
6. **Write-off.** When an account closes, every claim on it is written off. A claim in a field or variable becomes `none`. A claim in a collection is removed from the collection. A closure that captured it is cancelled, and calling it does nothing and yields `none`.
7. **Open before use.** `with e = x { … } else { … }` opens a claim. Inside the block, `e` is guaranteed live. A direct call `x.m()` on a claim is shorthand that opens `x` for that one call and traps if `x` has been written off.
8. **Closures.** A closure captures accounts as claims and values by copy. While it runs, everything it captured is open.
9. **Deferred close.** If an account is open when it is asked to close (a method of it is running, or it is opened by a `with` block or a running closure), the close takes effect the moment the last of these finishes.
10. **Parameters.** Values are passed read-only. `edit v` lends a value for in-place mutation without copying, and while it is lent, any other access to its account traps. Accounts are passed as claims, and they are open for the whole call.
11. **Threads.** Sending an owner to another thread moves its whole subtree, and claims on that subtree from the old thread are written off. A `shared class` is an *escrow* account. Any thread may hold claims on it, and its methods run one at a time.

That is 11 rules. Rules 1–4 are ordinary single ownership. Rules 5–9 are the new part, and rules 6 and 9 are what users have to internalise.

## 5. Under the hood

**Account header** (about 32 bytes plus the register): an *equity pointer* (the address of the owner slot), a jurisdiction (thread id, or *escrow*), an `open` count, flags (`closing`, `lent`), and the **liability register**. The register is a growable array of entries `{slot address, kind ∈ {field, element, closure}, container header address}`.

**A claim slot** is `{account pointer, register index}`, 16 bytes.
- *Create or copy a claim:* push an entry into the target's register (O(1) amortised).
- *Drop a claim:* swap-remove its entry, and patch the moved entry's claim slot with its new index (O(1)).
- *Move a claim-bearing value* (for example, a list of claims reallocating, or a record that contains a claim): the compiler generates a fix-up that rewrites the slot address in each affected register entry. Types are known to be claim-bearing from their declarations, so this is inferred and never written by the user.

**Close** runs when an owner slot dies and `open == 0` (otherwise it sets `closing` and waits):
1. Run the fields' destructors. Owned accounts close recursively, and owned values are freed.
2. *Discharge* this account's own outgoing claims by removing its entries from other accounts' registers.
3. *Settle* the register:
   - `field`: write the void sentinel into the slot.
   - `element`: void the slot and bump the container's dead count. Iteration and `count` skip dead elements, and the container compacts when its owning account's books next shut.
   - `closure`: set the closure's cancelled bit.
4. Free the memory.

The cost is O(size of the subtree + number of liabilities). It is deterministic, happens at a known program point, and never pauses the world.

**Open count.** A non-atomic `++`/`--` around method calls on, and `with` blocks over, an account reached through a claim, and around closure calls for each captured account. The compiler elides these when it infers that the callee has no *may-close* effect, meaning it never overwrites an owner slot and never calls unknown code. This effect is inferred across procedures and never annotated.

**Owner cycles.** `a.child = a` would form an ownership loop and leak. A transfer into a field of account D walks D's equity chain, and if the moved account appears in it, it traps. The walk is O(depth). It is always on in debug builds and optional in release, because the failure is a leak, not memory unsafety.

**Escrow (`shared class`).** Holds a lock. Its open count and register are atomic or locked, and claim slots that point at escrow accounts are written atomically, because write-off may happen from another thread.

**Audit (debug builds).** Whenever an account's open count returns to 0, the runtime runs a *trial balance* on it: every register entry's slot must point back at this account with the matching index. The tooling gets:
- `audit.claims(x)`: every slot holding a claim on `x`, with its type and field name.
- `audit.chart()`: the whole ownership tree with per-subtree byte totals, a free memory profiler.

**C FFI.** You can pass `with`-opened accounts to C as raw pointers ("petty cash"), valid for the duration of the call. For C code that keeps a pointer, `ffi.claim(x, callback)` registers a C-side liability whose settlement calls the callback.

## 6. Scenarios

*All code is illustrative only — not a syntax decision.*

### (a) Read a file into a growing list of lines
```
fn readLines(path: String) -> List<String> {
  var lines = List<String>()
  for line in File.open(path).lines() { lines.add(line) }
  return lines                       // value moved out, no copy
}
```
Values only, no accounts, nothing to book. The list buffer grows by reallocation and is freed when its holder goes away. This case costs nothing extra.

### (b) Tree with parent pointers
```
class Node {
  name: String
  children: List<Node>           // owners
  parent: claim Node?            // claim, booked in the parent's register
  fn addChild(n: Node) { n.parent = self; children.add(n) }   // n transferred in
}
var root = Node("root")
root.addChild(Node("a"))
let a = root.children.removeAt(0)    // ownership comes back out to a local
other.addChild(a)                     // re-parented; the old parent claim is overwritten
```
Parent pointers are claims, so there's no cycle and nothing to make `weak`. When a subtree closes, children close first, which discharges their parent claims, so a child never sees a void parent. Outside references into a removed subtree (for example a "selected node" claim) are written off when it closes.

### (c) The crux: a UI callback capturing enclosing state
```
class Editor {
  text: String
  dirty: Bool
  saveButton: Button                       // owned by the editor
  init(toolbar: claim Toolbar) {
    saveButton = Button("Save")
    saveButton.onTap = fn() { self.save(); self.dirty = false }
    toolbar.add(fn() { self.save() })      // stored in an object the editor does NOT own
    let close = Button("Close")
    close.onTap = fn() { self.window.editor = none }   // closes the editor from inside itself
  }
}
```
- `self` is captured as a claim, and the closure is booked in the editor's register as a `closure` entry.
- When the editor closes, the toolbar's closure is *cancelled*. The toolbar is left holding a no-op that its list compacts away, so it never calls into freed memory. There is no `[weak self]`, no `guard let self`, and no manual unsubscribe.
- Inside the closure, `self` is always live, because running the closure opens the editor's books.
- The "Close" button sets the editor's owner slot to `none` *while the editor's closure is running*. That close is deferred until the closure returns (rule 9), and then it runs. There is no use-after-free and no special case.
- The editor's own `saveButton` closes before the editor does, so its closure goes with it.

### (d) A shared mutable cache used by two components
```
class ImageCache { entries: Map<String, Image> }      // the cache owns the images
class App { cache: ImageCache; gallery: Gallery; preview: Preview }
class Gallery { cache: claim ImageCache; visible: List<claim Image> }
// in App.init:  gallery = Gallery(cache)   preview = Preview(cache)
fn evict(key: String) { entries.remove(key) }          // the Image closes
```
Both components claim the cache. One account must *own* it, here `App`, the common ancestor. Evicting an image closes it, and every component's `List<claim Image>` loses that element automatically (derecognition), so neither component holds a stale entry. If the cache itself is replaced, both components' `cache` fields become `none`.

### (e) Pass a large list to a function that mutates it
```
fn normalise(edit lines: List<String>) { for i in 0..lines.count { lines[i] = lines[i].trim() } }
normalise(edit doc.lines)      // lent in place, zero copy
```
`doc` is open and marked `lent` for the call, so any other path that tries to open `doc` meanwhile (for example a callback with a claim on it) traps. This is exclusivity checked once per *open*, not once per field access.

### (f) Sharing data between threads
```
shared class Stats { hits: Int; fn add(n: Int) { hits += n } }
var stats = Stats()
spawn fn() { for job in queue { stats.add(1) } }   // captures an escrow claim: allowed
var batch = Batch(load())
send(worker, batch)            // transfers the whole subtree; local claims on it written off
```
A closure passed to `spawn` may capture only values and claims on escrow accounts, and the compiler checks this from the types. A running worker keeps `stats` open, so if `main` drops `stats`, the close waits until the worker finishes with it. Moving whole subtrees is cheap, because internal references are owners and every claim from outside is listed in a register.

## 7. What's genuinely new compared with the covered options

- **Reverse registry instead of counts or generations.** O1/O7 count, O6 stamps and checks, and regions free in bulk. Here each object records *where* its non-owning references are held. Nothing is ever kept alive by a claim (unlike ARC), and dangling is fixed *eagerly at the moment of close* rather than discovered at dereference time (unlike Vale).
- **Settlement that depends on the slot.** Because the registry knows the *kind* of each holding slot, a write-off can **remove collection elements and cancel closures**, not just null a pointer. That fixes callback and observer lifetimes (scenario c) and stale cache views (scenario d) without weak-self ceremony or manual unsubscription. No covered option has "closures die with what they captured".
- **Deferred close via open books.** Re-entrancy safety comes from a per-account "period" counter at method and closure granularity, not from per-pointer RC or borrow tracking.
- **Change-of-control thread transfer.** A subtree moves between threads, and the registry tells the runtime exactly which outside references must lapse.
- **Auditability as a feature.** "Who references this object?" and "what owns all this memory?" are always answerable at runtime, which gives debugging and profiling (G8) for free.

## 8. Known weaknesses

- **No shared ownership.** Some account must be named as the owner of every shared thing (scenario d forces a common ancestor). This is deliberate, but it will chafe when no natural owner exists.
- **Claims cost more than RC increments.** Creating or copying a claim is a register push, and moving a claim-bearing value needs fix-ups. A large `List<claim T>` that reallocates rewrites one register entry per element. Hot loops should open claims once (with `with`) and not copy them around.
- **Implementation risk.** Move fix-ups for claim-bearing types, compaction of containers with dead elements, effect inference to elide open counts, and atomic write-off for escrow are each subtle. Bugs in fix-ups corrupt the books, so the debug-build audit is essential.
- **Silent cancellation can hide bugs.** A callback that "just stops firing" because something it captured closed is safe, but it can surprise people. Tooling should log cancellations in debug builds.
- **Deferred close can stall frees.** A long-running closure or thread that captured an account holds it open indefinitely. Memory isn't leaked, but freeing it is postponed.
- **Rule count (11)** is higher than O1's. Rules 6 and 9 do a lot of work in few words, and users must really understand them.
- **G3 flag.** `List<Node>` and `List<claim Image>` rely on built-in parameterised containers, which the brief lists as a pending question.
