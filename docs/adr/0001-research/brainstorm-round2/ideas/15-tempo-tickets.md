# 15 — Tempo: memory on a calendar, references as tickets

## 1. Name

**Tempo.** Every object is a *note*. It is born with a duration measured on a domain clock (frames, requests, keystrokes, windows, sessions) and it dies when that duration runs out. It dies whether or not anything still points at it. References are *tickets*, and every ticket carries the time it expires.

## 2. The crazy premise

**Sacred assumption broken: an object's lifetime follows its reachability, its owner or its scope.**

Every sensible scheme frees memory based on the program's *structure*: the last reference goes away (RC), the owner drops it (ownership), the scope exits (regions), or a tracer can't reach it (GC). Tempo ignores structure completely. Memory is freed on a **calendar**, and the calendar is written in the domain's own units. Being reachable doesn't keep an object alive, and being unreachable doesn't kill it early.

Two more assumptions fall as consequences:
- **A reference is not "valid until freed".** It is a ticket: a pointer plus an expiry stamp (clock, beat). Safety comes from comparing a timestamp, not from tracking who points where. Cycles, back-pointers and aliasing therefore cost nothing.
- **Collections are not stable.** A list or map of notes is a *roster*: a member whose note has ended silently vanishes from it.

Gates and assumptions:
- **G2: passes.** There is no tracing and no collector. A clock tick frees the objects whose beat has come due, like a timing wheel. Two operations walk a bounded set of objects: the first-home tie (rule 5, only objects born in the current call) and `freeze` (rule 11, only objects with the same note). Analysts should judge whether those walks count as a "run". I say they don't: neither is global and neither is periodic.
- **G3: needs-john.** A duration is a value expression at the birth site (`Image() for 200 requests`), much like a capacity argument. It is not part of any type, and no signature ever mentions a lifetime. Whether a `for` clause counts as an "annotation" is John's call.
- **Kept:** determinism (beats are program events, not wall time).
- **Kept but bent:** "memory is reclaimed promptly". Garbage can linger until its note ends. The bound is explicit and visible (see §9).

## 3. Pitch

You already know how long things live. You just know it in the domain's terms, not memory's: "this frame", "this request", "until the window closes", "200 requests after its last use". Tempo lets you say exactly that, once, at the point where a few *root* objects are born. Everything else inherits a tempo from where it first lands. The runtime keeps one timing wheel per clock. A tick frees whatever came due, and ending a clock instance frees everything on it. A pointer the program stores is a ticket stamped with its due beat, so dereferencing it is a check against a clock counter that is almost always in cache. A stale ticket is a deterministic "wrong note" trap, or it simply vanishes from a roster. You never think about cycles, weak refs, owners or borrows. You think about tempo, and the compiler draws your program as a **score**: one timeline per clock, showing every allocation site's note length, with clashes ("dissonance") marked in red.

## 4. The rules

1. **Values and notes.** Numbers, `text`, and `struct` values are copied and have no tempo. Class instances, `List`, `Map` and closures are *notes*.
2. **Clocks.** Declare them as `clock frame`, `clock request`, `clock window` and so on. Start an instance with `w = window.start()`, advance it with `w.tick()`, and stop it with `w.end()`. Singleton clocks, like `frame`, tick directly. `forever` is built in. Every function call is also an implicit clock that ends at return.
3. **Tempo at birth (optional).** Write `X() for 3 frames`, `X() for this w` (until `w` ends), or `X() forever`.
4. **No tempo written means the first home decides.** An object takes the note of the first place it lands: a field, a collection, a returned value (the caller's destination) or a capture. If it never lands anywhere, it ends when the call that made it returns.
5. **A note can't end under a running call.** An object born in a call stays at least until that call returns, even if its first home has a shorter note. The memory stays; tickets stored elsewhere still expire on schedule.
6. **Notes only lengthen.** `renew x for 200 requests` moves the due beat later. Nothing can end a note early: there is no `free` and no `delete`.
7. **Tickets.** Every stored reference is a ticket. Reading through a ticket after its note ended is a **wrong note**: a deterministic trap that reports the clock, the beat and the line that ended it. Test first with `if x plays`. After a `renew`, old tickets still carry the old stamp and go stale early, so fetch a fresh one from the home.
8. **Rosters.** A `List` or `Map` holding notes hides members whose note has ended. A map whose values have finite notes is therefore a self-expiring cache.
9. **Closures take the shortest capture.** A closure's note is the earliest-ending note among its captures, not the note of its home. If any capture is silent, the closure is silent.
10. **Meter (optional).** `clock request within session` declares that a request always ends before its session does. The compiler uses this to compare notes across clocks for rule 9 and for dissonance checks.
11. **Voices.** Each thread is a voice. A clock belongs to the voice that ticks it, and only that voice may mutate notes on the clock. Other voices may read only notes that have been frozen with `freeze` (this freezes everything sharing the note), or they must go through `Guarded(x)`.
12. **Dissonance.** Storing a ticket into a holder that provably outlives it, on the same clock or through a `within` chain, is a compile warning. It is not an error, because the runtime check is the safety net.

That makes 12 rules. Rules 10–12 are needed only once you write multi-clock or multi-threaded code. A beginner who writes no `for` clauses at all lives entirely under rules 1, 4 and 7, and gets "everything lives as long as the thing that holds it first".

## 5. Under the hood

- **Clock table.** Each clock instance is a fixed slot in a per-process table: `{gen:32, now:64, voice, wheel}`. `end()` sets `now = MAX`, frees everything on the wheel, and bumps `gen` when the slot is recycled. The table itself is never freed.
- **Object header.** 24 bytes: `{wheel-link prev/next, clock-slot, due-beat, birth-frame-serial}`. Each `due` beat has its own list on the clock's wheel. A tick unlinks the list for `now` and frees each object (running an optional `on silence` hook, which is how files close). A `renew` relinks one object. Each tick costs O(objects due), and there is never a scan of live objects.
- **Ticket.** 16 bytes: `ptr:64, clock-slot:20, gen:12, due:32`, with beats counted relative to an epoch per clock. A deref compiles to: load `clocks[slot]`, compare `gen`, compare `now < due`, then branch. Because the check reads the clock, not the object, memory reuse is safe. A stale ticket to recycled memory always fails the check before it touches that memory.
- **Locals are not tickets.** Within a function, a pointer to a call-born object is proven valid until return (rule 5). Pointers to domain-noted objects held in locals are re-checked after any call that might tick their clock (an effect bit the compiler infers, not one the user writes). Escape analysis puts never-homed objects on the stack.
- **First-home tie (rule 4).** Call-born objects sit on a list for their frame. On the first store into a home, the runtime gives the object the home's note. It also re-notes every *same-frame* object reachable from it, which is usually zero to three objects. Returns use destination passing: a hidden `dest-note` argument means `return List()` is born directly with the caller's note.
- **Rule 5 mechanics.** If a note ends while the object's `birth-frame-serial` is still live on the voice's frame stack, the free is deferred to that frame's return list.
- **Rosters.** Iteration and lookup skip silent tickets and compact lazily. `count` is "members playing now".
- **Voices.** Freeing for a clock that other voices have pinned waits until each of them reaches a *barline*: the return to its event loop, a `send`, or an explicit `bar`. This is quiescent-state reclamation. A reader can't race a free, and no voice ever traces anything.
- **The score.** The compiler emits a per-clock timeline of allocation sites and their note lengths. The debugger shows the live heap as a piano roll: one row per clock, bars per beat. A wrong-note trap prints: "Editor ticket due end-of window#7; window#7 ended at ui.lang:88 (Window.close) 3 beats ago."
- **C FFI.** `pin x` gives a raw pointer and defers `x`'s free until `unpin`, or until the barline in a ticked clock. C never sees tickets.

## 6. Scenarios

*Illustrative only — not a syntax decision.*

**(a) Reading lines into a growing list**
```
fun readLines(path: text) -> List
  f = File.open(path)          // never homed: silent at return, on-silence closes it
  lines = List()               // homed by return: born with the caller's note
  for l in f.lines() { lines.add(l) }   // text values are copied; the buffer regrows internally
  return lines
doc.lines = readLines(p)       // lines gets doc's note
```
The internal buffer is private to the list, and you can't take a ticket into it. The old buffer is freed immediately when the list regrows.

**(b) Tree with parent pointers**
```
class Node
  parent: Node?   children: List   value: int
  fun add(v: int) -> Node
    c = Node(parent: self, value: v)   // first home is self.children, so c gets self's note
    children.add(c)
    return c
tree = Node(value: 0) for this document
```
The cycle (parent ↔ child) costs nothing. Removing a subtree doesn't free it. Its memory lingers until the document ends (§9).

**(c) UI callback capturing the editor (the crux)**
```
clock window
w = window.start()
class Editor
  text: text   view: View
  fun save() { ... }
  fun build()
    view = Button("Save", onTap: { save(); text = text + " (saved)" })  // implicit self
editor = Editor() for this w
editor.build()                       // button and closure land in editor, so they get w's note
App.keys.subscribe({ editor.onKey(k) })   // App.keys is forever, but the closure gets editor's note (rule 9)
w.end()                              // window closes: editor, button and both closures go silent
```
After `w.end()`, `App.keys` simply stops seeing the handler. No weak refs, no unsubscribe, and no retain cycle through `self`.

**(d) Shared mutable cache used by two components**
```
clock request
class Images
  cache = Map()                              // Images is forever, so is the map
  fun get(url: text) -> Image
    if img = cache[url] { renew img for 200 requests   return img }
    img = load(url) for 200 requests
    cache[url] = img
    return img
images = Images() forever
gallery = Gallery(images)    thumbs = Thumbs(images)   // both hold tickets to images
```
An entry expires 200 requests after its last hit, with no eviction code. A component that kept an old ticket to an `Image` must call `get` again after expiry.

**(e) Passing a large list to a mutating function**
```
fun normalise(xs: List) { for i in 0..xs.count { xs[i] = xs[i] / max(xs) } }
big = List() for this request
fill(big)   normalise(big)              // the ticket is passed and mutated in place, with no copy
```
Aliasing is allowed. Mutating a list while iterating it is caught by the usual version check.

**(f) Sharing data between threads**
```
clock job
table = buildTable() forever   freeze table        // frozen: every voice may read it
results = Guarded(List()) for this job             // shared and mutable, behind a lock
worker = spawn { for row in table { results.with { r -> r.add(score(row)) } } }
j.end()                                            // frees once worker passes a barline
```

## 7. What is new

- **Lifetimes are stated in domain time, not memory or scope terms.** Lifetimes that don't nest, like sessions, windows and cache entries, are first-class because they are just different clocks. They never have to nest, unless you choose to declare a `within` relation.
- **Timestamped tickets.** Safety comes from comparing a reference's own expiry stamp against a clock counter. This is unlike generations (O6), which check the object. Memory reuse is safe because the check never touches the object.
- **Reclamation is decoupled from reachability.** There is no RC traffic, no cycle problem and no weak/strong distinction.
- **"First home decides tempo"** replaces ownership. The home sets the duration but owns nothing: removing an object from its home frees nothing.
- **Rosters.** Expiry is visible in collections, which gives self-expiring caches and self-cleaning subscriber lists from one rule.
- **The score as the debugging model.** Memory is something you can see on a timeline, and its peak can be predicted per clock.

**Overlap with round 1, stated honestly:** rule 9 produces behaviour close to "callbacks that become no-ops when their captures die", but here it falls out of the general ticket rule rather than being a callback-specific mechanism. Clock ticks free memory the way Tick & World does, but notes have arbitrary per-object durations across many independent clocks, and nothing is "end of this tick by default".

## 8. Why it might be less crazy than it sounds, or more

**Less crazy:**
- Game engines already think in frame-lifetime allocators.
- Web servers think in request arenas.
- CDNs and DNS think in TTLs.
- Timing wheels are a decades-old, O(1) kernel technique.
- Fat checked pointers are what bounds-checked slices already are.
- Programmers really do know "until the window closes" better than they know owners.
- The beginner subset (rules 1, 4 and 7, and no `for`) behaves like region-per-root-object, with no annotations anywhere.

**More crazy:**
- Correct programs can trap because a note was too short, which happens to no programmer today.
- Garbage lingers for a whole note.
- A roster's `count` can change between two lines that mutate nothing.
- "The data vanished from my list" will be a new class of confusing bug, and the score view is the only real answer to it.

## 9. Known weaknesses

- **Lingering garbage in long notes.** A session-long editor that keeps replacing child objects accumulates them until the session ends. The mitigations are: prefer `struct` values for long-lived mutable state, give churny objects short notes plus `renew`, or start a sub-clock (`clock edit within session`). This is the regional-leak problem, moved into the domain's terms, not solved.
- **Too-short notes trap in production.** The wrong-note trap is deterministic and well reported, but it is still a runtime failure. Dissonance warnings catch only same-clock or `within`-related cases.
- **Cost.** Tickets are 16 bytes, versus 8 for a pointer. There is a header of 24 bytes per object, a check on every heap deref, and a clock-table load that is usually in L1.
- **Hidden work.** The first-home tie walk, `freeze`, and rule-5 deferrals are bounded but invisible, and the tie walk could surprise someone who builds a large graph inside one call before homing it.
- **Roster semantics** make index-based code fragile, because indices into a roster shift as members expire.
- **Clocks are global-ish design decisions.** Picking the wrong clock set early is a refactoring cost that ownership schemes don't have.
- **G3 status depends on John** accepting `for ...` birth clauses as expressions rather than annotations.
- **Self-assessment (rough):** simplicity 3, safety 4, expressiveness 4, implementation risk 3, performance 3, concurrency 3, tooling 4, for a total of about 68. It is safe and cycle-free, and it is honest about its leaks, but it has more rules than O1.
