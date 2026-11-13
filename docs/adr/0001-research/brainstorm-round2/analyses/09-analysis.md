# Analysis 09: Standing Calls

Analyst: independent. Inputs: brief.md, round2.md, CHARTER.md, ideas/09-standing-calls.md only.

## 1. Restatement (3 sentences)

Any object with identity (window, session, cache) is a function call running on its own fiber stack. The call "stands" after its body ends: its locals are the fields, and its `on` handlers are methods that run on top of the frame, with implicit `self` provided by a static link. Inside a stack all data is a value (copied, moved at last use, or passed with `edit`). Across stacks the only connection is a generation-checked, non-owning **door**. A door call copies arguments in and results out, and can fail with `gone` or `busy`. A stack's memory is freed when it `stop`s or when its owner in an explicit ownership tree stops.

## 2. Prior art

The pieces all exist already. What is new is putting them together, mainly: *every identity-bearing object is an actor reached only through a non-owning handle, and there is no RC or GC anywhere*.

| Piece | Prior art |
|---|---|
| Object = activation record that outlives its body; methods see its locals | Simula 67 class bodies with `detach`/`resume`, on a GC heap (https://www.softwarepreservation.org/projects/ALGOL/manual/NR_report_743_Dahl_Myhrhaug_Nygaard_Simula-67-Common-Base-Language.pdf; https://www.cs.arizona.edu/classes/cs520/spring06/9coroutines.pdf) |
| No pointers; processes plus ports; the compiler inserts deletes | IBM Hermes (Strom & Yemini): no pointers, language-level processes and IPC, typestate-generated `delete`s (https://en.wikipedia.org/wiki/Hermes_(programming_language); https://research.ibm.com/publications/hermes-an-integrated-language-and-system-for-distributed-programming). This is the closest ancestor. |
| No heap, only processes and channels | occam. Kent's "dynamic occam" later had to add mobile data and dynamic allocation (https://www.cs.kent.ac.uk/projects/ofa/kroc/dynamic-occam-I.pdf) |
| Inside one stack: values, `edit`, non-escaping trailing blocks | This is **O2** (Hylo mutable value semantics: inout plus non-escaping closures) almost exactly |
| Doors = `(slot, generation)` handles | **O6**-style generation checks, applied at actor granularity |
| `busy` on self-call | Erlang `gen_server:call` already fails early with `calling_self` (https://build.opensuse.org/projects/home:Ledest:erlang:24/packages/erlang/files/2310-Fail-early-when-calling_self.patch?expand=0). Wait-for-graph deadlock detection is textbook database material. |
| Lanes (VM-reserved, never-moving growable arrays) | A known technique: "4GB per Vector" (https://probablydance.com/2013/05/13/4gb-per-vector/), zig-stable-array (https://github.com/rdunnington/zig-stable-array), the `virtual-buffer` crate (https://docs.rs/virtual-buffer) |

Honest label: **O2 inside each stack, plus Hermes/Erlang-style actors between stacks, plus O6 handles, with Simula's syntax for classes.** The new move is using that combination for *UI objects and callbacks*, which removes RC entirely.

## 3. Soundness: counterexamples (illustrative only, not a syntax decision)

**C1. Parent-initiated traversal fails, and the idea's own (b) gives silently wrong data.**
```
fn Shape(name) { var kids = List of Shape()
  on path() -> String { return (owner.path() else "") + "/" + name }
  on dump() { for k in kids { print(k.path()?) } } }
root.dump()   // root -> kid.path -> owner.path = root, which is in the chain -> busy
```
The result is that `else ""` prints `/a` instead of `/root/a`. There is no crash, just a wrong answer. Any upward navigation during a call that started at an ancestor hits this, and that is the normal case for scene graphs and DOMs. "`owner` is never `gone`" is true, but `owner` is very often `busy`.

**C2. Synchronous callbacks into the owner are dropped (lost update in the crux scenario).**
```
fn Editor() { let list = start ListView(onSelect: me.selected) in me
  on selected(i: Int) { current = i }
  on open() { list.select(3)? } }      // ListView.select fires onSelect -> Editor is busy
```
The framework convention `entry() else ignore` swallows the `busy`, so `current` is never updated. Delegate, observer, and "set the value, fire `changed`" patterns all break this way. The idea admits it, but it is not a corner case. It is how most UI toolkits are wired, and with `send` instead the ordering becomes asynchronous.

**C3. Bidirectional sync calls produce nondeterministic `busy`.** Thread 1 in A calls `B.x()` while thread 2 in B calls `A.y()`. Whichever thread walks the chain second gets `busy`, and which one that is depends on timing. Error paths therefore run at random, which is a logical race. The chain walk also needs a global lock, or a careful two-phase protocol, so that two concurrent walkers can't both miss each other and deadlock anyway. Waiting for setup (`start` followed by an early call) and blocking FFI/I/O must also count as wait-for edges, or real deadlocks get through.

**C4. `on { }` capture semantics are unspecified, which leaves a dangle-or-surprise hole.**
```
on view() -> View { var draft = ""
  return TextField(changed: on { t in draft = t }) }   // draft dies when view() returns
for name in names { var n = 0; add(Button(name, tap: on { n += 1 })) }   // in the body
```
There are three ways to resolve this, and each has a cost:
- Forbid captures of non-standing-frame locals. That is an unlisted escape rule.
- Copy them. Then `text` is captured by reference but `n` by copy, inside the same block.
- Give each iteration its own slot. That is a closure environment allocation, i.e. a hidden heap.

Every option is either rule 11 or a surprise.

**C5. Resources can't be plain copyable values.** `var f = open(path); let g = f` gives a memcpy of an fd, which means a double close or a shared cursor. Fixing it needs one of two things:
- a non-copyable value kind, which brings back O4 move semantics as a new rule;
- files and sockets as standing calls, which makes every `readLine` a fiber switch.

The same applies to locks, GPU buffers and every C handle.

**C6. Body locals are retained forever.** `fn Server() { var raw = readFile("huge.json"); cfg = parse(raw) }`: `raw` is a frame local, so it lives as long as the server stands. Liveness across all handlers can fix this, but the rules must say so.

**C7. There is no shared read-only parallelism.** Eight workers searching a 2 GB immutable index have two options. Either the index is copied 8× (16 GB), or all queries funnel through one `Index` stack, which runs one handler at a time and so gives zero parallelism. `peek` blocks also run serially, holding the cache stack. O1 and O4 share immutable data through a refcount.

**C8. The idea's own (f) has a logical race.** Main calls `total.value()` "later", but nothing joins the eight `Summer`s, so the printed total can be partial. A join or `await children` primitive is missing from the rules.

**C9. Leaks and lost messages.**
- A per-request `Session` that misses `stop` on one error path lives until the server stops. That is manual `free` at object granularity, which is safe but leaky.
- Pending `send`s to a stack that stops are silently dropped.
- A child's `on stop` that reports to its owner during a cascade hits `busy`, because the owner is running the cascade.

**C10. Invisible O(n) copies.** `let snapshot = doc.lines` followed by later use of `doc.lines` copies the whole list, because there is no CoW and the last-use move doesn't apply. Rule 1 says "you can't see this", but users still pay for it.

**C11. `me` inside a trailing block is ambiguous.** In `cache.peek(k) { b in me.save() }`, the block runs on the cache's stack. If `me` is dynamic, it means the cache. If it is lexical, it means Editor, which is in the chain, so the call is `busy`. Either way it surprises people.

None of C1–C11 produces a memory-unsafe access *if* C4 is resolved by a compile error. The failures are wrong answers, dropped events, retention, and performance cliffs.

## 4. Scenarios

- **(a) Works.** Lane growth plus O(1) relink is clean. The File-as-value issue (C5) needs a ruling.
- **(b) Partial.** A data tree uses indices, which is O2's answer. A living tree breaks on parent-initiated traversal (C1).
- **(c) Partial.** The simple tap → `me.save` case is cleaner than `[weak self]` and has no cycle. Synchronous delegate and observer callbacks fail with `busy` (C2), capture rules are open (C4), and invalidation after an external `send` needs a convention.
- **(d) Works.** A cache stack with copy-out or `peek`. The cost is a serial bottleneck and a copy on every hit.
- **(e) Works.** `edit` on the same stack, and relink at last use across stacks. A non-last-use copy is silent (C10).
- **(f) Partial.** No data races by construction. But there is no join (C8), no shared read-only data (C7), and `busy` is nondeterministic (C3).

## 5. Gates

- **G2: pass.** Nothing traces or scans reachability. Freeing happens by frame pop or by `stop` unwinding. Per-value tombstone compaction is triggered by mutation and bounded by the value's size, like a `Vec` realloc. Cycles can't leak memory because doors don't own anything.
- **G3: pass, with needs-john on the shared question.** `List of T`, `Map of K to V`, `block(T)` and entry/function types are compiler-known parameterised types, the same open question as O1 and O4. `edit` is a parameter mode, not an annotation, and door types are nominal.
- **Other charter strain.**
  - G4: `?`/`else` on every door call adds noise.
  - G8: a custom debugger is great, but lldb, sanitizers and profilers struggle with fibers, segmented stacks and offset-encoded values.
  - P-C/FFI: C callbacks have to switch onto a stack, and C can't keep pointers into lanes.
  - OO: there is implicit `self`, but no inheritance or interface story for doors, e.g. "any door with `on view()`".
  - G6: stdlib resource types need the C5 ruling.

## 6. Score

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity | 25 | 3 | There are 10 stated rules. In practice there are about 14, because of C4 capture rules, C5 resource kind, a join primitive, `me` in blocks, plus a design discipline ("values inside, stacks at edges"; when to use `send` rather than a sync call). The activation-record mental model is unfamiliar. |
| Memory safety | 15 | 4 | No dangling and no data races by construction. One point off: the spec leaves a dangle hole (C4) that only an unstated rule closes, and the runtime TCB is large (lanes, relink, cross-stack blocks). |
| Expressiveness (b,c,d,OO) | 15 | 3 | Implicit self is excellent and (d) is fine. (b) is degraded and (c) breaks for synchronous callbacks. There is no polymorphism over doors. |
| Implementation risk | 15 | 1 | It needs all of these: per-platform fiber switching, segmented or VM-reserved stacks, a VM lane allocator with a small-object tier, offset-based flat layout for *all* values including nested mutable maps, a scheduler, a race-free wait-for walk, static-link codegen, and a custom debugger. That is several research runtimes for an AI-written compiler. |
| Performance & predictability | 10 | 3 | Freeing is deterministic and there is no RC traffic inside a stack (a real win). Against that: 10–30 ns plus a lock per door call, copies across stacks, hidden O(n) copies, compaction spikes proportional to value size, and single-stack hot spots. |
| Concurrency fit | 10 | 4 | Race-free actors are built in and deadlock surfaces as a value. One point off for C3 nondeterminism, C7 (no shared immutable data) and the missing join. |
| Tooling, debug, FFI | 10 | 2 | The live tree of stacks is a fine tool. Native tooling and C FFI (pinning, callbacks, TLS on fibers) are awkward. |

Total = 25·3/5 + 15·4/5 + 15·3/5 + 15·1/5 + 10·3/5 + 10·4/5 + 10·2/5
= 15 + 12 + 9 + 3 + 6 + 8 + 4 = **57**.

That is below O1 (83) and O4 (82) by about 25, and below round 1's best (68) by 11. The self-assessment of 67 is too generous on implementation risk (2 → 1) and safety and concurrency (5 → 4).

## 7. What the premise teaches, and the kernel

**What the crazy premise teaches.**
1. **If references don't own, cycles disappear, and the hard problem becomes reentrancy.** (c) turns out to be a *reentrancy* problem disguised as a memory problem. ARC's `[weak self]` cycle and actor reentrancy (`busy`) are the same problem seen from two sides. Any design that removes cycles by making handles non-owning has to say what happens on synchronous call-backs. That is a useful test question for O1 and O4 as well.
2. **Non-nested lifetimes really are "stories".** Windows, sessions and editors end because of an event, not because a refcount reached zero. An explicit ownership tree with `start … in owner` captures that intent better than "the last strong reference happens to go away", and it makes "why is this alive?" a one-hop question.
3. **"No heap" collapses into O2 plus actors.** Removing the heap doesn't remove the allocator. It moves into lanes and slot tables. The real choice is between owning references (RC) and owning stories (explicit stop). Neither is free.

**Salvageable kernel, adoptable into O1 or O4.**
- **K1. Class = standing function (syntax only).** `fn Editor(doc) { var text …; on save() { … } }`. Locals are fields, `on` blocks are methods, and implicit self comes from the enclosing frame. This fits P-PY and G1 well and works on an RC-boxed frame in O1 or a `shared` frame in O4.
- **K2. Entries: `me.save` as a non-owning method reference.** It is a generation-checked or weak reference plus a method, and calling it returns `gone` once the object is dead. In O1 this removes the most common `[weak self]` cycle in (c) without a `weak` keyword at the call site. It overlaps round 1's "callbacks become no-ops when captures die", but adds an explicit failure value instead of a silent no-op.
- **K3. A built-in `actor` kind (from `start`, `send` and doors)** for O1 and O4 concurrency, with copy-in/copy-out and a mailbox, plus the **wait-for-chain check as a debug-mode deadlock and reentrancy detector** that reports `busy` with the cycle shown.
- **K4. Ownership-tree debugger view.** For O1, a "live objects by owner, and why alive" retain-path tool is G8 value at low cost.
- **K5. Pointer-stable VM-reserved Lists** as an optional stdlib optimization. This is known prior art and low priority.

## 8. Verdict

**Kernel worth stealing.** The full mechanism scores 57. It is O2 plus actors under a heavy, high-risk runtime, and its crux story fails on synchronous callbacks. The class-as-function syntax, non-owning `me.method` entries, and debug-mode `busy` detection are cheap, compatible upgrades for O1 or O4.
