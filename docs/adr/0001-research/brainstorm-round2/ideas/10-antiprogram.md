# 10. Antiprogram: every verb has an inverse, and freeing means running it

## 1. Name

**Antiprogram.** The compiler emits a second program, `~P`, alongside your program `P`. `~P` is made entirely of inverses: for every operation that *puts* something somewhere, `~P` holds the operation that takes it away and un-makes it. Memory is freed only by running pieces of `~P`. You never write `free`, a destructor, `weak`, an RC type or a lifetime.

## 2. The crazy premise

It breaks two assumptions that every sensible design keeps.

- **Assumption 1: freeing is a separate act from making.** Here it isn't. Freeing *is* making run backwards: un-making an object means reversing the operation that installed it, the same way `git revert` relates to a commit. Lifetime is no longer a property of objects or scopes. It is **the interval between a verb and its inverse**.
- **Assumption 2: a call's side effects on the outside world are permanent.** For one marked kind of call, the *dual verb* (`open` / `close`), they aren't. Everything `open` did to the heap is **provisional**: its field writes, its list insertions, its callback registrations, even its integer increments. The matching `close` reverts all of it, newest first, the way an STM undo log rolls back a transaction. The difference from STM is that this rollback is deliberate and is the normal way a lifetime ends.

## 3. Pitch

Programmers already know their non-nested lifetimes, and they already name them with verb pairs: open/close, show/hide, subscribe/unsubscribe, load/unload, put/evict, connect/disconnect. Every existing language makes them write the second verb by hand, mirroring the first one line by line: remove the listener, null the field, close the file, drop the window from the app's list. Forget one line and you get a leak or a stale callback. React's `useEffect` cleanup function is exactly this hand-written mirror. Antiprogram has the compiler write the mirror for you. Mark `fun open() undo close()` and the compiler derives `~open`, the exact reversal of whatever `open` did, and runs it when `close` is called or when the receiver dies. The same idea, scaled down, covers ordinary data: putting a value into a field or list makes that place its home, and removing or overwriting it there is the inverse that un-makes it. `~P` is a real artifact: `lang anti` prints it, tests check that `open; close` is an identity on the heap, the debugger can show "what closing this would do", and you can eject the generated inverse into source and hand-edit it.

## 4. The rules (everything a programmer must learn)

1. **Make, never free.** `make T(...)` creates an object. There is no delete, destructor, `weak`, `shared`-RC or lifetime syntax.
2. **Home is the first place you put it.** A *put* is storing into a field, adding to a container, passing as an argument to a dual verb, or returning from a call (which hands the value to the caller's put). Until its first put, the local variable holding an object is its provisional home. A value that is never put anywhere is un-made when its call returns.
3. **Every put has an inverse.** Overwriting a field, removing from a container, or the end of the call that held a provisional home is the inverse of a put. The inverse un-makes the object and everything homed inside it, depth first.
4. **Other references are visitors.** Putting an already-homed object somewhere else makes a visitor reference. When the object is un-made, every visitor reference to it becomes `none`, and reading a cleared non-optional field traps with the site that un-made it. **Exception: references that point *up* the home tree are never cleared,** for example child→parent or a button's closure→the editor that owns the window. The holder always dies first.
5. **Locals never dangle.** If something you hold in a local is un-made during your call, the local keeps a detached but intact copy alive until your function returns.
6. **Dual verbs.** `fun open() undo close()` declares a pair. Calling `open` starts a *lasting span* owned by the receiver. Everything `open` and its callees do to memory that existed before the call is recorded and provisional. Calling `close` runs `close`'s body first (your hand-written part of the antiprogram), then the generated `~open`, which reverts those effects newest first and un-makes what `open` made. If the receiver is un-made while spans are open, those spans close first, newest first. Callbacks that run *later*, after `open` has returned, are ordinary calls, and their effects are permanent.
7. **`keep` makes one effect permanent.** Writing `keep <statement>` inside a dual verb, or inside anything a dual verb calls, exempts that effect from reversal. Library code uses `keep` for effects that must survive whoever called it, such as cache fills or logs.
8. **The antiprogram is visible and testable.** `lang anti` prints the inverse of every dual verb. Each dual verb gets a generated test that `open(); close()` leaves the reachable heap unchanged. In debug builds the program finishes by running all of `~P`, and the heap must then be empty; anything left over is reported by allocation site. `lang anti --eject open` copies the generated inverse into `close`'s body as editable code, and debug builds then check your edited version against the tape on every run.
9. **Threads.** `send x to t` moves `x`'s home subtree to thread `t` (visitors to it are cleared), or copies it if it is small. Shared mutable state lives inside a built-in `shared` object. Things can only be homed inside it, and you only visit them under `lock`.

The everyday subset is rules 1–5, and in that subset they behave like "things live where you put them". Rules 6–7 are the part that is new.

## 5. Under the hood

- **Object header:** home slot pointer, home depth, generation, and a visitor-list head (kept in a side table).
- **Reference-store barrier** for `t.f = v`:
  - If `v` has only a provisional home, home it at `t.f`.
  - Otherwise, if `t` is a home-descendant of `v`, do nothing. The check walks `t`'s home chain up to `v`'s depth; in UI code that is usually one or two hops.
  - Otherwise, append `(slot address, t.gen)` to `v`'s visitor list.
  - If the old value in `t.f` was homed *at that slot*, run its inverse.
- **Inverse (un-make):**
  1. Close any lasting spans owned by the subtree, newest first.
  2. Post-order over the home subtree: for each visitor slot that still holds this object and has a matching generation, set it to `none`.
  3. Hand the memory to the **shadow thread**, unless a local pins it. The compiler maintains pins only for locals that live across a call that might un-make.

  The shadow thread is the only part that really runs "alongside". It returns memory to the allocator and has no effect the program can observe.
- **Lasting-span tape (Bennett's history tape).** During the dynamic extent of a dual verb, every write to an object older than the span is logged as `(slot, gen, old value)`. A nested dual-verb call is logged as "opened span X → undo: close X". Writes to objects made inside the span are not logged, because they are un-made anyway. The compiler clones functions into a taped version and an untaped version, as STM implementations do, so code outside dual verbs pays nothing. The tape is bounded by what `open` itself did, not by how long the window stays open.
- **Reverting** an entry writes the old value back if the target's generation still matches. The write goes through the normal barrier, so reverting `self.window = w` is itself the inverse put that un-makes `w`.
- **`keep`** suppresses the tape entry. The compiler re-homes any span-made objects reachable from the kept write into the target's home, statically where it can and at runtime otherwise.
- **Placement optimisation.** Escape analysis allocates an object directly in its eventual home's arena chunk, so a home subtree is mostly contiguous. Un-making a big subtree releases whole chunks.
- **Determinism.** Reverts and visitor clearing happen synchronously at the inverse. Memory reuse is asynchronous but invisible. There is no tracing. The "heap unchanged" test digest walks the heap, but only in tests.

## 6. Scenarios (illustrative only — not a syntax decision)

**(a) Read lines into a growing list**
```
fun readLines(path: String): List of String
    f = File.open(path)              // dual verb, homed in this call
    lines = List of String()
    while line = f.readLine()  lines.add(line)   // each line homed in a list slot
    return lines                     // put into the caller; f's span closes at return → file closed
```

**(b) Tree with parent pointers**
```
class Node
    name: String
    parent: Node?                    // points up: never cleared
    children = List of Node()
    fun add(c: Node)  c.parent = self; children.add(c)   // children slot is c's home

root.add(make Node("a")); a = root.children[0]
a.add(make Node("a1"))
selected: Node? = a.children[0]      // visitor
root.children.remove(a)              // inverse: a and a1 un-made, selected → none
```

**(c) UI callback capturing editor state (the crux)**
```
class Editor
    text = ""
    window: Window?
    fun open() undo close()
        window = make Window("Editor")              // provisional write to self
        b = make Button("Save")
        b.onTap = { self.save(); text.append("\n") } // closure → editor points up: never cleared
        window.add(b)
        App.windows.add(window)                      // provisional insert into a global list
        keep self.timesOpened += 1                   // survives close
    fun close()  self.save()                         // hand-written part; ~open runs after it

// `lang anti` prints:
// ~open:  App.windows.remove(window)   // revert
//         self.window = none           // revert → un-makes Window, Button, closure
```
If `onTap` itself calls `close()`, the running closure is pinned as a local (rule 5) and freed once it returns. The edits `onTap` made to `text` are permanent, because they happened after `open` returned.

**(d) Shared mutable cache used by two components**
```
class Cache
    entries = Map of String to Image()
    fun get(k: String): Image
        if !entries.has(k)  keep entries[k] = load(k)   // permanent even inside someone's open()
        return entries[k]
    fun evict(k: String)  entries.remove(k)             // inverse put: image un-made
class Thumb   image: Image?                             // visitor; becomes none on evict
a.image = cache.get("x"); b.image = cache.get("x")
```

**(e) Large list passed to a mutating function**
```
fun normalise(xs: List of Float)  for i in xs.indices  xs[i] = xs[i] / xs.max
normalise(samples)        // passing is not a put: zero copy, mutation is permanent
// inside a dual verb the writes would be taped: O(writes), or one buffer snapshot
```

**(f) Threads**
```
totals = shared Map of String to Int()
w = Thread.start { lock totals { totals["n"] += 1 } }   // Thread.start undo join
big = readLines("huge.txt")
send big to w2           // home subtree moves; using `big` afterwards is a compile error
```

## 7. What is new

- **Lifetime as verb-to-inverse.** Programmers state the non-nested lifetimes they know as domain verbs they would write anyway, not as types or annotations.
- **Automatic reversal of side effects on *other* objects.** Removing listeners, nulling fields and pulling items out of registries all happen without code, so a stale callback cannot exist by construction. O1 and O4 both need hand-written deregistration code.
- **An undo log used as the lifetime mechanism.** This is STM's undo log, or Bennett's uncomputation, with rollback as the normal end of a lifetime instead of an abort.
- **The antiprogram as an artifact.** It can be printed, diffed in code review, ejected and edited, and tested as a generated `open; close` heap identity.
- **Leak detection by construction.** Running all of `~P` at exit must leave an empty heap.
- **Time-travel debugging for spans.** The tape already holds every value that was overwritten.
- **One mechanism for memory and resources.** Files, sockets, windows and memory all close through the same inverse.

## 8. Less crazy than it sounds, or more

**Less:** React effect cleanups, SwiftUI's `onDisappear`, Go's `defer`, command-pattern undo stacks, database savepoints and Emacs undo all show that people understand "this pairs with that, and the second one reverses the first". Bennett proved in 1973 that any computation can be uncomputed given its history. For plain data, rules 1–5 behave like ordinary single-home ownership, which is predictable and fast. The tape is paid for only inside dual verbs, which are rare and coarse: one per window, subscription or level load.

**More:** "close undoes *everything* open did, including `x += 1`" is a genuinely new mental model, and it will surprise people. `keep` discipline in libraries is load-bearing. A cache fill or log write in a library that forgets `keep` gets rolled back when some unrelated window closes.

## 9. Known weaknesses

1. **Provisional-by-default is a sharp edge.** A callee two libraries deep can have its effect silently reverted. Mitigations are `lang anti` listings, generated identity tests and warnings on taped writes into globals, but this is still the biggest risk.
2. **"First put is home" depends on order.** `pending.add(n); root.add(n)` makes `pending` the home, so removing `n` from `pending` un-makes a live tree node. The compiler can warn when one function puts the same new object into two places. It cannot always prove the right order.
3. **Visitor clearing produces runtime `none`s and traps.** These are safe and well-reported, but they are run-time failures. The plain-put layer overlaps with round 1's "single owner plus auto-cleared refs". The new material is concentrated in rules 6–8.
4. **Implementation risk is high for an AI-written compiler:** store barriers with home-depth walks, visitor side tables, function cloning for taping, re-homing on `keep`, local pins and placement analysis.
5. **Performance.** Every reference store pays for the barrier. Heavy visitor graphs make un-making O(visitors). A dual verb with a large dynamic extent produces a large tape.
6. **Threads are coarse.** You either move whole home subtrees, copy, or lock a `shared` object. There are no fine-grained shared references.
7. **C FFI.** C code can't have its pointers set to `none`. Objects handed to C are pinned for the duration of the call. Long-term retention needs an explicit handle object homed on the language side.
8. **Ejected inverses drift.** A hand-edited `close` can drift from the source. Debug builds detect the drift by diffing against the tape, but release builds trust you.

**Gates.** G2: **pass**, because there is no tracing, and the heap walk happens only in tests. G3: **pass**, because `undo` and `keep` are keywords and hand edits live in ordinary method bodies, not in a sidecar annotation file. It does rely on built-in `List`/`Map` (flag). Determinism is preserved: reverts and clears happen at program-defined points.

**Self-assessment.** Simplicity 3, safety 4, expressiveness 4, implementation risk 2, performance 3, concurrency 3, tooling 4: about **66**. It wins on (c) and on debuggability, and loses on implementation risk and surprise.
