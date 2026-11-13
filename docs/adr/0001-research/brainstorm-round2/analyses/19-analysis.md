# Analysis 19: PIDs (every object is a process)

Analyst: independent. Sources read: brief.md, round2.md, CHARTER.md, ideas/19-every-object-a-pid.md.
All code below is illustrative only — not a syntax decision.

## 1. The idea in three sentences

Every `class` instance is an isolated "cell" with its own heap, its own monitor (one thread at a time) and a parent (the cell that created it). References are generation-checked handles: handles to ancestors are uncounted and are claimed never to dangle, while all other handles are counted like file descriptors. A cell dies on `exit`, when its parent dies, or when no counted handle is left ("EOF"). When it dies, its descendants die first and its heap is freed whole, and faults kill only the faulting cell.

## 2. Prior art

The memory model and the concurrency model are both mostly known. The combination is new.

- **Object = process, reference = capability, call = IPC.** This is KeyKOS/EROS, where every object is a "domain" invoked through keys ([MIT 6.858 KeyKOS notes](https://css.csail.mit.edu/6.5660/2011/lec/l05-keykos.txt), [KeyKOS paper](https://pdos.csail.mit.edu/6.828/2009/readings/keykos.pdf)). The `--isolate` mode is KeyKOS's model with a compiler in front.
- **Object = monitor = isolation unit, with synchronous calls.** This is close to Eiffel SCOOP: separate objects, one processor per region, exclusive access. Its known weakness is deadlock, which is the same weakness found below ([Eiffel exclusive access](https://www.eiffel.org/doc/solutions/Exclusive_Access), ["Coffman deadlocks in SCOOP"](https://arxiv.org/pdf/1409.7514)). Java's "every object is a monitor" is a weaker version.
- **A process-only language with compiler-inserted deletes.** IBM's Hermes had processes and ports, no shared memory, and typestate that generated `delete` operations ([Wikipedia](https://en.wikipedia.org/wiki/Hermes_(programming_language))).
- **Per-process heaps freed whole on exit, plus let-it-crash and supervision.** This is Erlang/OTP. Erlang still runs a GC per process; PIDs swaps that for per-cell value semantics.
- **Up-tree references are safe because the tree bounds lifetimes.** This is owners-as-dominators ownership types (Clarke/Potter/Noble, [dblp](https://dblp.org/rec/conf/oopsla/ClarkePN98)) enforced at runtime. It is also Swift `unowned` made sound by kill-cascade. From memory, not searched: Samba's `talloc` hierarchical allocator also frees a parent with all its children and supports counted cross-references.

**What is new:** "handles held by descendants don't count, and parent death overrides counts". Together these give hierarchical RC in which back-pointers are structurally free. I have not seen that exact rule in a language.

## 3. Soundness: counterexamples

**C1. The factory kills its product (data loss, the biggest problem).** Rule 2 makes the creator the parent, and rule 5(ii) makes parent death override counts.
```
fn loadDoc(path: String) Document {
  loader = Loader(path)        // temporary cell
  return loader.load()         // Document is spawned inside Loader, so parent = loader
}                              // loader's last handle drops -> EOF -> loader dies -> Document dies
d = loadDoc("a.txt")           // d is already `gone`
```
Builders, parsers, connection pools, `http.get()` returning a `Response` cell, and `db.query()` returning a `ResultSet` all hit this. The fix is either an `adopt` at every call site, or an implicit "returned cells re-parent to the receiver" rule. The second is really move/ownership transfer, i.e. O4 with extra steps. Weakness 8 in the idea mentions this case for components. In practice it applies to every method that constructs and returns a class.

**C2. One fault takes down the whole call stack.** Rule 8 says an uncaught `gone` is a fault, and the caller of a crashed cell receives `gone`.
```
App.loop -> Window.paint -> Document.render -> xs[i]   // index error
// Document crashes and its subtree dies. Window gets `gone`, which is uncaught, so Window crashes.
// App gets `gone`, which is uncaught, so App crashes and the program exits.
// Every cell on the stack has lost its whole heap.
```
This is exception propagation in which every frame's object is destroyed. "A fault kills one cell, not the program" holds only where someone wrote `or`. By default it is worse than a plain exception.

**C3. A stale listener kills a shared service.** There is no weak handle and no external `kill`, so closing a document means `doc.close()`, which calls `exit`. That leaves a closure in `Settings` holding the now-dead doc handle:
```
settings.onChange = { doc.reflow() }    // the closure lives in Settings
doc.close()                             // doc exits
settings.set("font", 12)                // doc.reflow() raises `gone` inside Settings -> Settings crashes
                                        // every pane holding Settings now gets `gone` -> cascade (C2)
```
If nobody calls `exit`, then `doc` <-> `settings` is a cross-branch cycle under `App` and leaks until the app exits. O1 fixes this case with `weak`. PIDs has no equivalent.

**C4. Up-walk vs down-walk deadlock in scenario (b).** Rule 9 means a thread keeps every monitor on its call chain.
```
T1: leaf.path() -> holds leaf, calls mid.path() -> holds mid, calls root.path()   // waits for root
T2: root.render() -> holds root, calls mid.render()                              // waits for mid
```
The detector raises `gone` in whichever thread closed the cycle. Which thread that is depends on scheduling. Under C2 that `gone` then crashes a tree node and frees its subtree. So two threads touching the same tree is nondeterministic data loss. The SCOOP literature above documents the same failure class. The two-account transfer (`a.transferTo(b)` running concurrently with `b.transferTo(a)`) is the textbook case. The idea's claim that determinism is preserved does not hold once threads exist.

**C5. Task waits the detector can't see.** The kernel tracks monitors, not `Task.wait()`:
```
class Editor { fn build() { t = go compiler.run(self); t.wait() } fn progress(p: Int) {...} }
// compiler.run calls editor.progress(...) and blocks on Editor's monitor, which build() still holds.
// The cycle goes through a Task, so it is never detected: a silent hang.
```
Any UI cell that waits on background work that reports back to it hangs. The idea needs another rule, either "never wait while inside a cell" or async-only calls.

**C6. A cross-cell `mut` lend aliases through re-entry (safety hole).** Rule 9 allows re-entry on the same call chain:
```
class A { px = List of Float(1_000_000)
  fn run() { b.normalise(mut px) }
  fn poke() { px.clear() } }
class B { a: A
  fn normalise(mut xs: List of Float) { a.poke(); xs[999] = 1 } }   // re-enters A and clears px while it is lent
```
If `xs` aliases `px` (the zero-copy claim), this writes past the end of a cleared buffer. If it doesn't alias, writes are lost and the call isn't zero-copy. The fix is a dynamic exclusivity check (Swift's simultaneous-access enforcement), which is one more mechanism and one more trap to learn. The argument "the caller is parked, so no one can observe" is wrong, because the parked caller can be re-entered.

**C7. "Heap freed whole" vs copy-on-write page remap.** A `List of String` remapped across cells carries pointers into the sender's arena. If the sender then dies and "its heap is released whole", the receiver's strings dangle. The two features are compatible only if remapped buffers are reference-counted. Then the heap is not freed whole, and the result is Swift's COW ARC under the hood. Remapping a list of handles also has to recount every handle for the new holder, so it is O(handles), not O(pages).

**C8. Closure semantics are unspecified at the crux.** Take `saveButton.onTap = { editor.save(); editor.dirty = false }`, written in `EditorWindow` and stored in `Button`. Which cell does it run in?
- If it runs in Button, it cannot touch the window's private fields (rule 3), so implicit `self` inside closures breaks.
- If it runs in Window, the closure is effectively a handle to Window, and invoking it is a cross-cell call. That is fine, but it must be stated, and rule 11's "held by the cell that stores it" counting then misdescribes it.

Separately, value capture by copy breaks a common DSL idiom:
```
count = 0
button.onTap = { count += 1 }   // mutates a copy; every piece of mutable UI state needs its own cell
```

**C9. `adopt` is a hidden trace.** Recomputing the counting bits of the adopted subtree means finding every handle inside values, lists and closures in those cells' arenas, plus borrowed locals on threads currently inside those cells. That is a mark pass over the subtree. It is bounded and explicit, so it arguably passes G2, but it is not the "rescan handle fields" the idea describes.

**C10. Death while dying.** A parent whose death is deferred (a thread is still inside a descendant) can still accept calls and spawn new children. The idea needs a "dying" state with defined call semantics. This is minor but unspecified.

## 4. Scenarios

| | Verdict | Why |
|---|---|---|
| (a) | **works** | Values inside one cell. `File` closes on EOF. |
| (b) | **partial** | Parent pointers are free and safe single-threaded. Concurrent walks deadlock and then lose data (C4). Each node costs a monitor plus 64–96 B. |
| (c) | **partial** | Window-subtree lifetime is neat and the sibling cycle dies with the parent. Closure execution cell and capture semantics are a hand-wave (C8). Stale callbacks crash cells (C3). |
| (d) | **works** | The cache cell serialises access. `get` copies `Doc` out on every call. Check-then-act across calls is still racy at the logic level. |
| (e) | **partial** | Fine within one cell. The cross-cell zero-copy `mut` is unsound under re-entry (C6). |
| (f) | **partial** | Data-race freedom is real. Deadlock becomes a crash (C4), hidden hangs are possible (C5), and read-sharing is serialised or needs an unwritten rule 12. |

## 5. Gates and charter

- **G2: pass.** Counted handles plus tree kill involve no tracing in the steady state. The deadlock detector is not GC. Caveat C9: `adopt` performs a bounded subtree scan. This is an explicit, user-invoked operation, but John should know it is there.
- **G3: pass**, apart from the shared pending question about built-in `List of T` / `Map of K to V`. That is the same needs-john item as every other option. `mut`, `on exit` and `on child crash` are syntax, not annotations.
- **Other goals:**
  - G1 is strained. There are 11 stated rules plus about 4 missing ones: factory re-parenting, closure execution cell, `mut` exclusivity, read-only sharing. The struct/class split also becomes a performance decision.
  - P-SWIFT: this is Swift's struct/class split plus actors plus `unowned` fused into one model, which is the feature density P-SWIFT objects to.
  - G8 benefits (the `--isolate` mode, deterministic deadlock reports).

## 6. Score

| Criterion (weight) | Score | Justification |
|---|---|---|
| Simplicity (25) | 2 | 11 rules plus about 4 missing ones. "Lifetime is decided by who created you, not who uses you" goes against ARC/GC intuition (C1). Crash and `gone` semantics need discipline. |
| Memory safety (15) | 4 | Generation-checked handles, and no aliasing within a cell. Holes C6 and C7 need extra machinery, but both are fixable. |
| Expressiveness (15) | 3 | (b), (d) and implicit self are good. Factories (C1), the lack of weak handles (C3), and closure semantics plus copy captures for DSLs (C8) all hurt. |
| Implementation risk (15) | 2 | Cell table, per-object monitors, migrating threads, ancestry walks, `adopt` rescan, wait-for graph, crash unwinding across cells, COW remap. `--isolate` with OS processes or CHERI is a project in itself. |
| Performance (10) | 2 | A CAS plus a generation check on every cross-object call and every external getter, O(depth) store checks, and per-object overhead. The style pushes code toward structs. |
| Concurrency (10) | 3 | Race freedom by construction is a real win. Synchronous nested monitors make deadlock routine (SCOOP's experience), and resolving one destroys state. |
| Tooling/FFI (10) | 3 | `ps`/`lsof` debugging and `extern cell` sandboxing are attractive. Pointer-heavy C APIs don't fit "nothing crosses by reference", and `--isolate` is costly to build. |

**Total** = (25×2 + 15×4 + 15×3 + 15×2 + 10×2 + 10×3 + 10×3) / 5 = (50+60+45+30+20+30+30) / 5 = 265 / 5 = **53**

The inventor's self-assessment was about 71. This is 30 below O1 (83), 29 below O4 (82), and 15 below round 1's best (68). It sits in the lower half of the round-1 band of 47–68. The drop from 71 comes mainly from C1/C2 (simplicity) and C4/C5 (concurrency and implementation risk).

## 7. What the premise teaches, and the kernel

**What the premise teaches.**

1. In ARC, parent pointers are hard because nothing guarantees the parent outlives the child: someone else can hold the child strongly. If death cascades down a tree regardless of counts, ancestor references become free and safe. The price is that outside holders must tolerate `gone`. So the real choice is between "weak parent" (O1) and "child handles can die" (generation checks, O6). Neither is free. PIDs picks the second and hides it.
2. Isolation can substitute for proof. Once nothing is shared by reference, memory safety and race freedom come from one mechanism. But synchronous calls between isolated units bring back deadlock, which is the problem locks had. Isolation only pays off if calls are asynchronous (Erlang, Pony) or there are few units (actors per subsystem, not per object).
3. "Who created it" is real, cheap information that ARC languages throw away.

**Salvageable kernel.**

- **K1. Creation-tree leak checking (an O1 debug mode).** In debug builds, record each object's creator. When a creator is released, or at a user checkpoint such as "window closed", report its creations that are still alive, with the retaining path. This finds O1's cycle and observer leaks (C3) without a collector and without touching release semantics. It is the same idea as Android's LeakCanary. Cost: one pointer per object in debug only.
- **K2. `extern cell` for C FFI (an O1/O4 hardening tool).** An opt-in build flag runs a named C library in a separate process with marshalled calls, so a C memory bug crashes that library rather than the program. Useful for P-C, and cheap to define because it is library-granular, not object-granular.
- **K3. Monitor-guarded `shared` for O4 (a SCOOP-style option).** If O4's `shared` kind were optionally a monitor (a single entrant, checked by the runtime), (d) and (f) would become race-free with no `Send`/`Sync`. This is only safe if it comes with a no-nested-waits rule or async calls; adopt with eyes open after C4 and C5.
- Not worth stealing: per-object cells, parent-kill overriding counts, crash-kills-cell as the default.

## 8. Verdict

**Kernel worth stealing.** As a memory model it is a dead end: C1 (factories kill their product) and C2 (crash cascade) contradict how OO code is written, and C4/C5 make concurrency worse, not better. K1 (creation-tree leak reports for O1 debug builds) is cheap and directly targets O1's main weakness. K2 is a nice FFI hardening option.
