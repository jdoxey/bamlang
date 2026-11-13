# 04 — Reincarnation (crash-only lives with a pointer-free durable store)

## 1. Name

**Reincarnation.** Every event runs in a fresh *life*. When the life ends, its whole heap and stack are dropped, as if the process had been rebooted. Only the **durable store** passes from one life to the next. The store holds values and IDs and never holds pointers.

## 2. The crazy premise

**Sacred assumption broken: "a program is one long-running process whose heap persists."**

Here the process image is disposable. Conceptually the program reboots before every event, every UI frame and every iteration of a `beat` loop. No pointer from one life can exist in the next, because nothing from that life survives. A second assumption breaks as a side effect: **a function call runs exactly once.** A life can be thrown away halfway and rerun after a crash or a transaction conflict, so lives have to be safe to rerun. The language arranges this; see rule 8.

Gates and assumptions affected:
- **G2 passes.** There is no tracing. Life memory is freed by resetting a pointer. Store memory is freed by explicit delete plus epoch reclamation that is bounded by life length (see 5). Flag the epoch scheme for John in case he counts it as GC-like. I think it isn't, because nothing is ever traced.
- **G3: needs-john.** The model needs built-in parameterised containers (`List of T`, `Map of K to V`) and a built-in ID type per record (`Editor.id`). There are no user generics.
- **Program shape is broken on purpose.** Code can't block halfway through a function waiting for a user action. It has to end the life and be woken by the next event. Every interactive program is an event-driven state machine.

## 3. Pitch

Make the program an event handler, and make each handler run disposable. Inside a life you get C-like freedom: plain references, aliasing, cycles, parent pointers, in-place mutation. There is no ownership, no counting and no borrow checking, and nothing is ever freed while the life runs, so a use-after-free can't happen. When the life returns, its arena is reset in O(1). Anything you want to keep, you write into the **durable store**: a typed tree of records, lists and maps declared with `durable`. The store contains IDs, never references, so nothing in it can dangle into a dead life. Store changes commit atomically at the end of the life. A crash (panic, failed bounds check, exceeding the life's memory budget) rolls the store back to where it was, so crashes become ordinary, recoverable events. Callbacks that outlive a life aren't closures. They're messages, data that wakes a new life later. Memory leaks are impossible in life memory because no life lasts long. In the store, a leak can only be a visible "thing you forgot to delete", sitting in a tree you can inspect.

## 4. The rules

1. **Your program is handlers.** `main`, event handlers, `frame` and each iteration of a `beat` loop all run as separate *lives*. When a life ends, everything it allocated is gone.
2. **Inside a life, everything is an ordinary reference.** Alias, share, build cycles and mutate freely. Nothing is freed until the life ends.
3. **`durable` declares what survives.** Durable types may contain values (numbers, strings, structs, `List`, `Map`) and record IDs, but not references.
4. **Writing into the store copies; reading from the store gives a view.** `store.x = v` deep-copies `v` in. Reading `store.x` gives a view that is valid for the rest of this life.
5. **Durable records have IDs.** `add` returns an ID and `delete` removes the record. Looking up a deleted ID gives `none`. Deleting a record deletes everything nested inside it.
6. **A closure that escapes the life becomes a message.** It may capture only values and durable IDs, and captures are copied when the message is created. In a method of a durable record, `self` is the record's ID, re-resolved in each life.
7. **A life commits or crashes.** If the life returns normally, all its store writes apply atomically. If it crashes, the store is untouched and the triggering event is reported as failed.
8. **Output happens at commit.** Printing, writing files and sending on the network are queued and performed only after a successful commit. Inputs a life reads are logged, so a rerun sees the same inputs.
9. **Threads share only the store.** Each thread runs its own lives. Two lives that commit conflicting store writes don't both win: the loser reruns automatically, which is safe because of rules 7 and 8.
10. **Long work uses `beat`.** `for x in source beat { ... }` makes each iteration a fresh life. Anything an iteration needs to carry forward has to go in the store.

That is ten rules. Rules 2, 3 and 7 are the core. The rest follow from them.

## 5. Under the hood

- **Life arena.** Each thread has a bump arena. A growing `List` in a life reallocates geometrically, and old buffers stay where they are until the life ends. Waste is at most about 2x, and stale pointers into old buffers read stale data but remain memory-safe. Reset is one pointer store. Each handler has a memory budget (default 64 MB, overridable per handler). Going over it is a crash under rule 7, not an OS kill.
- **Stack.** The stack is also discarded at life end. No coroutine or continuation state ever spans lives, so there's no need for async machinery.
- **Durable store.** The store is a value tree of tables, rooted at module-level `durable` declarations. It is MVCC: each life starts from a snapshot version, and reads go to the snapshot plus the life's own write set. Durable `List` and `Map` are chunked persistent structures (64-element chunks with path copying), so writing one element copies O(log n) chunks, not the whole container.
- **IDs.** An ID is (table, slot, generation), checked on lookup, in the style of slot maps and Vale. The new part is that IDs are the only cross-life link the language has at all.
- **Commit.** Commit validates the life's read set against current versions, which is optimistic concurrency. If validation passes, it publishes the write set and runs the queued effects. Blocks the commit replaces go on a limbo list tagged with the commit's epoch. **A limbo block is freed once every life that started before that epoch has ended.** Since every life is short by construction, limbo drains within roughly one event's duration. The crash-only premise is what makes epoch reclamation cheap and bounded. A long-running thread would otherwise stall it indefinitely.
- **Messages and callbacks.** The compiler turns every escaping closure into a closure record: a code pointer plus a copied capture block allocated outside the arena (in the store's message queue or in the UI's per-frame tree). Delivery starts a life, resolves the captured IDs and calls the code. If an ID no longer resolves, the message is dropped with a debug log.
- **Resources.** A file handle opened in a life is closed at life end. That is deterministic, with no destructors to write. A handle that must persist (a socket, a window) is stored as a field in a durable record, and deleting the record closes it. If a life opens a durable resource and then crashes, the open is undone.
- **Parallelism inside a life.** `parallel for` freezes the parent arena read-only, runs each iteration as a child life with its own arena, and copies the results back.
- **FFI.** A pointer passed to C is valid until the life ends. If C needs to keep a pointer longer, the memory has to be a `durable Buffer`, which is pinned and freed only on explicit delete plus epoch.

## 6. Scenarios

*Illustrative only — not a syntax decision.*

**(a) File of unknown length into a list of lines**
```
fn main(args) {                       // one life
    lines = List of String
    for line in File.open(args[0]).lines() { lines.add(line) }   // arena growth
    print(count_words(lines))         // queued, emitted at commit
}                                     // arena reset; file closed
// If the lines must outlive this life:
durable docs: Map of String to List of String
fn on_open(path) { store.docs[path] = File.read_lines(path) }   // copied into store
// A 100 GB file: for line in File.open(p).lines() beat { store.total += len(line) }
```

**(b) Tree with parent pointers**
```
// In a life: plain refs, cycles fine
class Node { parent: Node?, kids: List of Node, name: String }
root = Node(name: "r"); kid = Node(name: "k", parent: root); root.kids.add(kid)
// Durable: IDs
durable class DNode { parent: DNode.id?, kids: List of DNode.id, name: String }
fn rename_parent(n: DNode.id) {
    if p = store.lookup(store.lookup(n).parent) { p.name = "renamed" }   // none if deleted
}
```

**(c) UI callback capturing enclosing state (the crux)**
```
durable class Editor {
    text: String
    dirty: Bool
    fn save() { File.write(path, text); dirty = false }   // self = Editor.id
    fn view() {                                          // runs every frame, in a life
        Column {
            TextField(text, onChange: { t -> text = t; dirty = true })
            Button("Save", enabled: dirty, onTap: { save() })   // message capturing self's ID
        }
    }
}
// Tap → new life → resolve Editor.id → run save() → commit → File.write performed.
// The UI tree is rebuilt every frame (immediate mode), so a stale callback lasts at most one frame.
```

**(d) Shared mutable cache used by two components**
```
durable cache: Map of String to Bytes (capacity: 10_000)   // built-in eviction policy optional
fn thumbnails_frame(url) { img = store.cache[url] ?? fetch_and_put(url) ... }
fn preview_frame(url)    { img = store.cache[url] ?? fetch_and_put(url) ... }
fn fetch_and_put(url) { b = Http.get(url); store.cache[url] = b; return b }
// Both components see one cache. Concurrent puts to the same key: one life reruns.
```

**(e) Large list passed to a function that mutates it**
```
fn normalize(xs: List of Float) { m = max(xs); for i in 0..len(xs) { xs[i] /= m } }
fn main() { xs = load_samples(); normalize(xs) }    // in a life: by reference, in place, no copies
fn on_tick() { normalize(store.samples) }           // durable: chunk-level copy-on-write, O(touched chunks)
```

**(f) Sharing data between threads**
```
durable jobs: Map of Job.id to Job
fn on_submit(spec) { id = store.jobs.add(Job(spec, state: .queued)); spawn work(id) }  // message: ID only
fn work(id) {                         // a life on a worker thread
    j = store.lookup(id) ?? return
    j.result = crunch(j.spec)         // big read-only data: zero-copy view of the store snapshot
    j.state = .done                   // commit; conflict → rerun
}
```

## 7. What is new

- **The process heap is disposable by design, not just collected in turns.** Round-1 tick schemes deferred frees to a tick boundary while the heap stayed continuous and pointers could survive. Here no pointer survives, ever. The only thing that crosses a life is a pointer-free store.
- **Crash = rollback = the memory-safety story.** Out-of-memory, panics and bounds failures abort the life and undo its store writes. Memory-safety bugs that remain (there should be none) get contained per event.
- **One mechanism, several payoffs.** Reruns make optimistic STM threads possible. Short lives make epoch reclamation trivially bounded. Logged inputs plus the store snapshot give **deterministic record/replay debugging** for free. Code that keeps no state between lives can be **hot-reloaded** between any two events.
- **Callbacks are defunctionalised by the language.** Escaping closures become messages that capture IDs, which suits immediate-mode declarative UI (G11).
- **OO with implicit `self`, where `self` is an identity, not an address.**

## 8. Less crazy than it sounds, or more?

**Less crazy:** Erlang and OTP ("let it crash"), PHP's per-request share-nothing model, game engines' per-frame arenas, React and Dear ImGui's rebuild-every-frame UI, Elm's `update(model, msg)`, and databases' MVCC all exist and work. Reincarnation fuses them into the language's memory model. Most real programs are already event loops over durable state that is persisted somewhere. Here the persistence target is just RAM. The life arena is the cheapest allocator there is, and most allocations in a UI or server die within one event anyway.

**More crazy:** a commit costs more than a pointer write. Every store write goes through MVCC with persistent structures, so compute-heavy programs that keep large mutable state (simulations, editors with huge buffers, compilers) pay a copy-on-write and validation tax on their hottest data. Retained-mode native toolkits (AppKit, Win32) expect long-lived object graphs with real callbacks. Wrapping them means building a shadow store, which is a lot of work.

## 9. Known weaknesses

1. **Architecture tax.** Straight-line interactive code ("ask, wait, ask again") must become a state machine in the store. That is a big learning cost for scripts and CLIs, and arguably it violates G1 in spirit even though the rule count is small.
2. **Two worlds.** Life types and durable types differ (references versus IDs). People will ask "why can't I store this `Node`?", and the answer is rule 3. That has the same flavour as Swift's struct/class split.
3. **Store leaks are logical, not impossible.** Forgotten map entries stay forever. You can see them in the store inspector, but nothing reclaims them.
4. **Implementation risk is high.** MVCC with persistent containers, read-set validation, effect queuing, input logging for reruns, closure defunctionalisation and epoch limbo are each moderate. Together, for an AI-written compiler, they are a lot. The arena half is trivial. The store half is a small embedded database.
5. **Performance cliffs.** Hot durable data is slower than O1/O4 in-place mutation. Retry storms can happen under contention. A single huge life can hit its budget and crash where ARC would just have used more memory.
6. **Rerun semantics surprise people.** Logging and printing are deferred (debug prints need a "print now" escape hatch). Wall-clock reads are logged values. Inputs that can't be logged (mmap, shared memory from C) break rerun safety.
7. **FFI.** Life-lifetime pointers are easy to reason about, but C callbacks into the language must start a life, and C libraries that keep pointers forever need pinned `durable Buffer`s.

**Self-assessment (rough):** Simplicity 3, Safety 4, Expressiveness 3, Implementation risk 2, Performance 3, Concurrency 4, Tooling 4 (replay and hot-reload are strong, FFI is weaker). Total about **64**. Its value to the project is probably as a donor, not a winner. The **per-handler arena plus crash-rollback** half could be bolted onto O1 or O4 as an opt-in `life { }` mode for request handlers and frames, with the pointer-free store as an optional library.
