# Analysis 03 — Tape & Keepsake

## 1. Restatement

Inside one "life", nothing is ever freed: everything is bump-allocated on an append-only tape, so no reference can dangle and cycles don't matter. Durable state must sit in top-level `keep var`s whose types are reference-free values. At idle moments, or under memory pressure, the runtime copies those values into a fresh segment, throws away everything else, and re-runs `main`, which rebuilds windows, caches and threads from the kept values.

## 2. Prior art

Each piece is known; what is new is putting them together as a language's memory model.

- **Restarting to reclaim memory** is *software rejuvenation* (Huang, Kintala et al., 1995; [pwg.org summary](https://pwg.org/archives/ipp/2018/019474.html), [Hanmer PLoP 2010](https://hillside.net/plop/2010/papers/ACMVersions/papers/hanmer.pdf)). In production it shows up as Apache `MaxRequestsPerChild` and Unicorn worker-killer.
- **Restart as the normal path, with state held outside the process** is *crash-only software / microreboot* (Candea & Fox; [OSDI'04](https://www.usenix.org/legacy/events/osdi04/tech/full_papers/candea/candea_html/), [Wikipedia](https://en.wikipedia.org/wiki/Microreboot)).
- **Never free; the process ends first** is Java's Epsilon no-op GC ([JEP 318](https://openjdk.org/jeps/318)) and the classic "missile" story ([Old New Thing](https://devblogs.microsoft.com/oldnewthing/20180228-00/?p=98125)).
- **Carrying state across a code swap** is Erlang/OTP `code_change` ([AppSignal](https://blog.appsignal.com/2018/10/16/elixir-alchemy-hot-code-reloading-in-elixir.html)), and Elm/Flutter hot reload, which preserve the model value.
- **Copying the live data out of a set of roots** is a Cheney semispace copy. **Address order as age** is the standard property of bump allocation that generational collectors rely on.
- **Relation to round 1:** this is the "freed at end of tick" family with a tick of minutes and a root set the type system enforces.

**What's new:** a *type-checked, reference-free* root set. That makes the identity graph (cycles, closures) something you never need to traverse. The rest of the design is a new name for known parts.

## 3. Soundness: counterexamples

*All code is illustrative only — not a syntax decision.*

**C1. The handover delta is unsound as stated, and the result is a dangling root.** The handover copies only nodes with address > T. A root that is re-pointed after T to an *older* value never gets copied.
```
keep var doc = loadBig()          // nodes at addresses < T
class Undo { var prev: Doc }       // not kept
u.prev = doc; doc = Doc{}          // snapshot at T copies the tiny Doc{}
doc = u.prev                       // undo, after T: the root now points below T
// handover: re-read the root, copy nodes > T → nothing copied → munmap → doc dangles
```
Undo stacks, `swap` and "restore defaults" all do this routinely. **Fix:** at handover, trace the new roots fully and use the copy memo to skip nodes already copied. That is correct, but it is now plainly a tracing copy.

**C2. Lost state turns into lost data.** Rule 4 resets non-kept fields, and the scenario (c) code itself leaves `dirty` non-kept.
```
// user types (docs[id].text updated, dirty = true) → idle → rebirth → dirty = false
onClose: { if dirty { promptSave() } }   // no prompt → window closes
```
If the keepsake isn't persisted, unsaved edits are gone. Chaos mode finds this only for paths the test actually exercises.

**C3. Non-idempotent I/O runs twice.** An in-flight request lives in a non-kept closure.
```
http.post("/transfer", body, onDone: { r -> keepLedger = keepLedger.add(r) })
// rebirth before the response arrives → the callback is gone → main sees no record → user/app retries → second transfer
```
Treating "pending I/O" as non-idle avoids this, but then websocket and long-poll apps are never idle (C5).

**C4. A batch job that allocates and discards per item runs out of memory.**
```
main
  use f = File.open("50GB.log")
    for line in f.lines()          // each line is a fresh String on the tape
      if line.contains("ERR") { n += 1 }
```
ARC runs this in constant memory. Here the whole of `main` is one event, so the 8 GB hard budget is reached with no idle point and the program fails. The only way out is to restructure into events with a kept cursor. Rule 8 calls this "performance, not safety", but in practice it decides whether the program completes.

**C5. Livelock or starvation.** A non-`finish` worker that allocates heavily hits the soft budget. Rebirth kills it, `main` restarts it, it allocates again, and it never finishes. Marking it `finish` blocks rebirth up to the deadline, after which it is killed and the work is lost. Servers and games with no idle point never get a rebirth at all.

**C6. Stray timers can write stale data.** Rule 1 means nothing is ever freed, so there are no destructors. A closed `Editor` keeps its timers and subscriptions.
```
class Editor { var buf: Text; init { Timer.every(30s) { Disk.write(path, self.buf) } } }
// close the window, reopen the same doc as a new Editor, edit, save → the old timer overwrites with the stale buf
```
This is the "lapsed listener" bug from manual memory management, back again. Observers registered in `view()` also pile up and fire N times until the next rebirth.

**C7. FFI pointers dangle across rebirth.** A kept window id is re-bound, but the OS-side userdata (Win32 `GWLP_USERDATA`, an `NSView` delegate) still points into the old tape. A `WM_PAINT` dispatched between `munmap` and `main` re-registering its callbacks is a use-after-unmap. The runtime has to intercept every toolkit callback; the design states this but does not solve it.

**C8. Secrets can't be wiped (critical for banking/IAM code).** A password or OAuth token is an immutable `String`. It can't be zeroised, stays on the tape until rebirth, and the tiering sinks it, compressed, into an SSD page file. If the keepsake is persisted for crash recovery, kept tokens are written to disk too. Debug journaling records every past value. Any secure-memory API would have to break rule 1.

**C9. Threads race on kept state.** Nothing says whether threads may touch top-level `keep var`s. If they may, then `docs[id].text = t` (read the root, path-copy, write the root) loses updates under contention. If they may not, a thread's durable result travels over a `Channel`, and messages in flight are dropped at rebirth.

**C10. `main` re-runs its side effects.** Splash screens, "app started" analytics, first-run dialogs and socket handshakes all repeat on every rebirth unless each is guarded by a kept flag. Every program must therefore keep `main` idempotent.

**C11. Address space runs out (minor; round 2 waives feasibility).** 2^44 bytes per thread per life, never reused, against a 2^47 user VA on x86-64, is about 8 thread-lives. Reusing ranges after `munmap` fixes this trivially.

## 4. Scenarios

| | Verdict |
|---|---|
| (a) file → lines | **Works** for the stated task. Streaming with discarded temporaries fails at scale (C4). |
| (b) tree + parent ptrs | **Works** within a life with zero rules. Durable trees need ids (O2 pain, confined to durable state). |
| (c) UI callback `self.save()` | **Partial.** Memory-safe, with no weak dance. But non-kept state resets silently (C2), there are no destructors (C6), and toolkit re-binding is hand-waved (C7). |
| (d) shared cache | **Works.** Plain shared object; goes cold at rebirth; evictions are free. |
| (e) mutate a large list | **Works**, but only via the separate `Buffer` class. Value `List` needs `data = f(data)`. |
| (f) threads | **Partial.** Sharing immutable data with no atomic RC is excellent. Thread kill/restart at rebirth (C5), races on kept state (C9) and lost channel messages are unaddressed. |

## 5. Gates

- **G2: fail** (John may overrule). Rebirth is triggered by memory pressure (soft and hard budgets). It traces the reachable value graph from a root set, copies it with a sharing memo, runs on a background thread, then does a pause where all threads stop. That is a concurrent copying collector by every functional definition. The C1 fix makes the tracing explicit. "O(keepsake) not O(heap)" is true of every copying GC. "Not tracing identity objects" only means that the type system keeps them out of the root set. The real difference from Java/Go is that discarded state is lost rather than kept, which makes it more burdensome than a GC, not less. The inventor's "needs-john" is a fair escalation, but the honest default is fail.
- **G3: pass, with a flag.** `keep` and `finish` are storage-class or modifier keywords, not annotations. `List of T`, `Map of K to V`, `Buffer of T` and `Locked(T)` are built-in parameterised types, which is the pending question.
- **Other charter strain:**
  - G1: every program must be architected Elm-style.
  - P-SWIFT: the class/struct two-kinds rule plus duplicate value and object collections.
  - P-GO / P-JAVA: the user-visible downsides of GC (working-set bloat, pauses at uncontrolled times) come back.
  - G8: big plus.
  - G10: chaos mode helps testing.

## 6. Score

| Criterion | W | S | Why |
|---|---|---|---|
| Simplicity | 25 | 3 | "Nothing dies" is the simplest possible memory rule. But every piece of state now needs a "survives rebirth?" decision, `main` must be idempotent, and there are two kinds of types and collections. The burden moves; it doesn't vanish. |
| Memory safety | 15 | 4 | No UAF within a life. FFI dangles across rebirth (C7), the stated delta is unsound (fixable, C1), and secrets can't be zeroed (C8). |
| Expressiveness (b,c,d,OO) | 15 | 4 | (b), (c) and (d) are trivial within a life, with implicit `self`. Durable graphs need ids, and there are no destructors. |
| Implementation risk | 15 | 2 | A naive version (serialise keeps, `exec` self) is easy, but the promised one needs: persistent RRB/HAMT values, transient inference (safety-critical escape analysis), a concurrent copier, cross-thread stop, native window re-binding on three OSes, userland tiered paging, and hot-reload schema matching. |
| Performance & predictability | 10 | 2 | Allocation is the fastest possible and there's no RC. But resident memory ≈ live objects × page size, rebirth timing is nondeterministic, the `main` rebuild stalls, persistent values are 2–5× slower, and there's SSD churn. |
| Concurrency | 10 | 3 | Immutable sharing without atomics is a real win. Threads are killed at rebirth, there's livelock (C5), kept-state races are unspecified (C9), and a stop-all-threads handover pause is required. |
| Tooling, debug & FFI | 10 | 4 | Birth-time addresses, reverse stepping, hot reload and crash recovery are excellent. C pointers are stable within a life but not across rebirth, and leak profiling means little. |

**Total** = (25·3 + 15·4 + 15·4 + 15·2 + 10·2 + 10·3 + 10·4) / 5
= (75 + 60 + 60 + 30 + 20 + 30 + 40) / 5 = 315 / 5 = **63**

The inventor's self-score was ≈71.

| Comparison | Score | Gap |
|---|---|---|
| O1 Pure ARC | 83 | −20 |
| O4 Simplified ownership | 82 | −19 |
| Round 1's best | 68 | −5 |

It is also gated by G2.

## 7. What the premise teaches

1. **(b), (c) and (d) are hard only because reclamation happens *during* an unbounded run.** If the question "what survives?" is asked only at a few transition points, with a typed answer, cycles and callbacks stop costing rules. The difficulty doesn't disappear. It moves to the boundary, where it becomes serialisation plus lost-state bugs. So any scheme can be judged by where it puts that boundary and how often programmers have to think about it.
2. **A reference-free type is a lifetime proof that needs no annotations.** If a value has no references in it, it cannot point into anything that is about to die. That is the one way to get bulk-free safety without lifetime inference or region annotations.
3. **"View = f(state)" really does dissolve the UI cycle problem**, but only for the derived layer. Durable state still needs ids. That is the same lesson O2 teaches, applied to the durable part only.
4. **No-free collides with security.** A model where nothing is overwritten cannot zeroise secrets. Any adopted model should keep an explicit "wipe" primitive.

**Kernel worth stealing into O1/O4:**
- **(i) A `batch`/phase region whose exit value must be a reference-free value type.** Inside it, allocation is a bump with no RC traffic. On exit, the result is copied out and the arena is dropped whole. Safety follows from the type check alone, with no lifetimes. It suits compiler passes, request handlers, file parsing and per-frame scratch work. It goes beyond the covered "scope regions + promote" because nothing can be promoted except reference-free values, so there is nothing to leak.
- **(ii) A "never-free" debug allocator mode with birth-event tags.** Under ARC/O4 it gives perfect detection of use-after-release in FFI or unsafe code, and answers "who allocated this, during which event". It is cheap to build.
- **(iii) Value-state hot reload plus chaos-restart as an opt-in app framework feature**, not as the memory model.
- **(iv) Immortal or frozen immutable globals that skip atomic RC** when shared across threads (compare Python's immortal objects).

## 8. Verdict

**Kernel worth stealing.** As a memory model it fails G2 in substance, and it breaks batch jobs, servers and secret handling. Its stated handover delta is unsound. It scores 63, below round 1's best. The reference-free-exit region (i) and the never-free debug allocator (ii) are cheap, need no annotations, and fit cleanly into O1 or O4.
