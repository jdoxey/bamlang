# ADR-0001: Memory management model

- **Status:** Proposed. In progress under `docs/PROCESS.md`; next step is in `docs/STATE.md`.
- **Date:** 2026-11-08 (revised after three adversarial reviews); 2026-11-09: John answered Q4, so threads are in v1; 2026-11-11: P1 closed, and a second-model review added O9 and put the O4 recommendation on hold.
- **Decided by:** Claude, under ruling R7 (2026-11-13). John may veto. Where this ADR says "John decides" or "needs-john", R7 now applies, except for charter changes.

## Summary

| Rank | Option | Total | Gates |
|---|---|---|---|
| 1 | O1 Pure ARC | 83.0 | Pass if P1, P2 = yes |
| 2 | O4 Simplified ownership + built-in RC | 82.0 | Pass if P1, P2 = yes |
| — | O7 ARC + cycle collector | 76.0 | **Ineligible**: fails G2 under the P1 test (2026-11-11) |
| 3 | O3 Values + CoW + RC identity type | 73.0 | Pass if P1, P2 = yes |

- **Update 2026-11-11: the O4 recommendation is on hold.** A review by a second model (Claude Fable 5.2; the earlier work was done with Opus) found two problems. See "Review of method" and O9.
  - **The rubric measured the wrong kind of simplicity.** John clarified G1 on 2026-11-11: the goal is simple rules that make it easy to reason about what the running program is doing, not complexity hidden from the programmer. The rubric counted rules to learn and barely penalised hidden work.
  - **A candidate was never scored: O9, owned values plus checked handles into pools.** It has no reference counts, no `weak` and no hidden work at free time.
  - **Next step:** hand-write one ~300-line program three ways (O1, O4, O9) for John to read, before any scoring or compiler spike.
- **Update 2026-11-09: John answered Q4, so threads are in v1. Concurrency weight is now 20, and O4 leads, 81.8 to 79.1.**
  - The earlier recommendation of O1 rested on concurrency not being a charter goal. That premise no longer holds.
  - **Recommended pick: O4**, conditional on the re-entrancy check in the spike (see Decision). If a synchronous callback that re-enters a `shared` owner traps, O4's Expressiveness drops to 4. O4 then scores 79.1 and ties O1.
  - Both brainstorm rounds point the same way:
    - 18 of 20 round-1 designs that checked aliasing at runtime raced through a surviving local.
    - 4 analysts independently concluded that the fix is O4-style static moves.
- *Before Q4 (kept for the record):* the rubric couldn't separate O1 and O4. The gap was 1 point, and eleven single-score changes and 7 of the 15 weight variants reversed it. The judgement pick was O1, for fewest rules and lowest compiler risk.
- **O3, the earlier pick, does not survive consistent scoring.**
- **Preconditions P1–P3 must be ruled on first.** P1 and P2 can void this ADR whatever the pick.

## Context

**Why now.** The memory model fixes the object header, the meaning of `=` and of parameters, closure representation, the C ABI and the cost of every RC operation. Atomic or not is an ABI choice, and Swift's late data-race retrofit took years [Swift510, SwiftVision]. Generics, the DSL, concurrency and the stdlib all depend on it.

**Constraints.** The compiler is ~95% agent-written, on LLVM, with CI on macOS, Windows and Linux. So silent-failure analyses are high-risk, and built-in debug checks are worth more than usual. Sanitizers are uneven: JetBrains documents ASan/TSan/UBSan on macOS and only ASan on Windows [JetBrains]. Upstream LLVM does list macOS for LSan [LSan], so macOS is a packaging question; Windows is a real gap.

**Evidence.** No study compares learnability across these models; scores are judgements tied to cited evidence.

**Scenarios:**
- (a) read a file of unknown length into a list of lines
- (b) tree with parent pointers
- (c) UI callback that captures and mutates its owner (`button.onTap` → `save()`), the G11 crux
- (d) shared mutable cache used by two components
- (e) pass a large list to a function that mutates it
- (f) share data between threads

## Charter

The table rates the two options the rubric can't separate. Caveats are in the Why column.

| Goal / problem | O1 | O4 | Why |
|---|---|---|---|
| G1 | serves | strains | O1: one kind of type plus the `weak` rule. O4 adds moves, use-after-move errors, `.copy()`, borrow exclusivity and a `shared` world. |
| G2 | serves | serves | Frees happen at count zero or scope end, and there is no collector. Conditional on P1. |
| G3 | neutral | neutral | Keywords only. Both need built-in parameterised types (P2). O4 also infers copyability and sendability, which other languages annotate. |
| G4 | strains | strains | See Syntax budget impact. O4 adds more. |
| G5, G7 | neutral | neutral | Not affected. |
| G6 | neutral | neutral | Container semantics follow the model. |
| G8, G10 | serves | serves | Deterministic destruction. A debug leak/cycle report on all three OSes. Tests can assert zero live objects. |
| G9 | strains | strains | Compiler-inserted RC/drop code needs correct coverage attribution. |
| G11 | strains | strains | An owner-capturing callback needs `weak` or a store handle. Under O4 the owner must also be `shared`. |
| P-C, P-GO, P-JAVA | avoids | avoids | Memory-safe outside `unsafe`. No tracing collector. |
| P-SWIFT | risks | avoids | O1 imports only Swift's ARC and `weak`. No `unowned`, capture lists, Sendable attributes or ownership modifiers. |
| P-RUST | avoids | risks | O4 keeps move and exclusivity errors, though not lifetimes. |
| P-PY ("too slow") | risks | avoids | O1 heap-allocates every user object. |

**Why the strains are acceptable.**
- **G4, G9, G11:** every eligible option strains these.
- **P-SWIFT (O1):** small, because O1 takes the smallest slice of Swift.
- **P-RUST (O4):** real. Lifetimes were only 204 of 340 reference-related Bronze-trial comments [Bronze], and O4 keeps users exposed to the other 136.
- **P-PY (O1):** the main argument for O4.

No row breaks a goal if P1 and P2 are "yes".

**Preconditions** (to be raised as `needs-john` issues, not yet opened). This ADR adopts no interpretation of G2 or G3. G3 is read as written: "must not **have**".

| # | Question for John | If "no" |
|---|---|---|
| P1 | Does freeing at count zero satisfy G2, "doesn't require a garbage collection run (like Java and Go do)"? The literature classes RC as GC [Bacon]. Also rule on a debug-only exit cycle report (traces, reclaims nothing) and on deferred-free queues drained at program points. | O1, O2 (counted CoW buffers), O3, O4 and O7 fail. Only O6 and O8 remain; the ADR is withdrawn. |
| P1 ruling | **Answered 2026-11-09 by John: YES.** In John's words: "reference counting is not garbage collection as a general rule — one is targeted, the other a blunt instrument". The exception is when a count reaching zero triggers too much processing, "for example, checking all dependencies in a tree"; that would be as bad as GC or worse. **Operational test (confirmed by John on 2026-11-11):** work triggered by a count reaching zero must be proportional to what is actually being freed (the dead objects plus the weak references to them), and must never inspect objects that stay alive. Any mechanism that examines live objects to decide whether they are alive is a GC run. | Passes: plain RC cascades, zeroing weak references, and deferred or incremental free queues. Fails: trial deletion and cycle collectors (O7/ORC; round-2 ideas 08, 16 and 18). So P1b is *no*. Ruled 2026-11-11: debug- and test-only tracing is allowed, and long release cascades are acceptable (an incremental queue is optional). |
| P1b | Would an *optional*, switch-off-able cycle collector break G2, as in CPython [PyGC]? | O7 becomes eligible. At 76 it doesn't change the pick. |
| P2 | Are compiler-built-in parameterised types consistent with "must not have templated types"? Users still couldn't define their own. The set: `List of T`, `Map of K,V`, `Optional of T`, function types, a weak/handle type, and `Mutex`/`Channel` if v1 has threads. | Every option fails. The ADR is withdrawn and G6 revisited. |
| P3 | Is memory safety required (no use-after-free, double free or data race outside `unsafe`)? If yes, John records that in the charter. | O8 stays eligible and Safety may be down-weighted. At Safety 5, O4 edges ahead (82.2 vs 81.1). |

## Options considered

**Folded in, not scored separately:**
- Inko-style counted borrows are a variant of O6, which is scored on them.
- Lobster inference and Perceus reuse are optimisations [Lobster, Perceus].
- Arenas and slot maps are stdlib facilities.

**Rejected before scoring:**
- MLKit regions need a tracing GC [MLKit].
- Cyclone regions are annotations, so they fail G3. Porting changed ~8% of code, and region annotations were 6% *of those changes*, ~0.5% of all code [Cyclone].
- V autofree still leaks [VReview].
- CHERI/MTE are absent on the targets.

**Labels.**
- Our-language code: **illustrative only — not a syntax decision**.
- "Rust (excerpt from a verified program)": taken from a program that compiled under rustc 1.97.0. The excerpt alone doesn't compile.
- Other real-language code was not compiled.

### Scenario (c) across all options

The naive code is `button.onTap = { save() }`, written inside the object that owns `button`.

| Option | What the naive code does | Fix |
|---|---|---|
| O1 | Compiles, but forms a cycle: owner → button → closure → owner. A lint flags direct self-capture, and the debug build reports the leak at exit. | Weak capture, or capture a store handle |
| O2 | Not expressible. An escaping closure can't hold a mutable link to its owner [Racordon]. | The button carries a message, and `update(&state, msg)` applies it |
| O3 | If the owner is a value, the closure captures a copy, so `save()` either fails to compile or mutates a stale copy [SwiftPitfall]. If the owner is an identity type, it behaves as in O1. | Use an identity type plus weak capture, or a handle |
| O4 | The owned value moves into the closure, so any later use is a compile error. | `doc = shared Document()`, then as O1 |
| O5 | E0502 / E0597 (verified) | `Rc<RefCell<…>>` plus clone-before-move (verified) |
| O6 | Compiles, captures a checked reference, and doesn't leak. If the owner dies first, Vale halts at the call and Inko panics at the drop. | The owner must outlive the button |
| O7 | Compiles. The collector reclaims the cycle when it runs. | None |
| O8 | Captures a raw pointer that dangles, unchecked, if the owner is freed first. Zig and Odin have no capturing closures, so this becomes `ctx: *anyopaque` plus a cast [ZigClosures]. | Manual discipline |

This DSL pattern avoids the cycle under every RC option, and under O2 via an intrinsic. It belongs to no single model:

```text
// Our language — illustrative only — not a syntax decision
view Counter {
    count = state(0)                                          // framework-owned slot; returns a handle
    body = column { button("+1", onTap = { count.set(count.get() + 1) }) }   // captures the handle
}
```

### O1 — Pure ARC

Every user type, `List` and `Map` included, is an RC reference. Cycles are broken with zeroing `weak`, and there is no collector.

```swift
// Swift (adapted from research notes) — pro, (d): freed exactly when the last holder drops it
final class Cache    { var entries: [String: String] = [:] }
final class Loader   { let cache: Cache; init(_ c: Cache) { cache = c } }
final class Renderer { let cache: Cache; init(_ c: Cache) { cache = c } }
```
```text
// Our language — illustrative only — not a syntax decision — con, (e): no isolation
snapshot = data        // alias, not a copy
normalize(data)        // snapshot changes too
```

### O2 — Strict mutable value semantics (Hylo-style)

No references. Parameters are read-only, `inout` (exclusive, marked at the call) or `sink` [HyloFn].

```hylo
// Hylo (from research notes) — pro, (e): in place, no aliasing possible
fun normalize(_ xs: inout Array<Float64>) { ... }
normalize(&data)
```
```hylo
// Pseudo-Hylo — illustrative only — not a syntax decision — con, (b): safe handles, but every step needs the whole tree
type Node { var value: Int; var parent: Optional<Handle>; var children: Array<Handle> }
```

### O3 — Values by default + CoW containers + one opt-in RC identity type

```swift
// Swift (from research notes) — pro, (a): a uniquely held buffer grows in place
var lines: [String] = []
while let line = readLine() { lines.append(line) }
```
```swift
// Swift (from research notes, caveat added) — con, (e): cost depends on code elsewhere
let snapshot = data      // shares the buffer
normalize(&data)         // O(n) copy at the first write, because snapshot is used below
print(snapshot[0])       // (if it weren't, an optimised build may skip the copy; a debug build won't)
```

Second cliff: without in-place projections, `groups[k].append(x)` copies the inner list on every call, so the loop is O(n²) [SE0154]. Swift formalised the fix only in 2025 [SE0474].

### O4 — Simplified ownership + parameter-only borrows + built-in `shared` RC kind

Assignment moves. Trivially copyable types copy (inferred), and other copies are explicit `.copy()`, as in Mojo [Mojo]. Borrows are parameter-only, so types carry no lifetimes. `shared` (RC + `weak`) covers (b), (c) and (d).

```rust
// Rust (excerpt from a verified program) — pro, (e): zero-copy exclusive borrow, statically checked
fn normalise(v: &mut Vec<f64>) {
    let max = v.iter().cloned().fold(f64::MIN, f64::max);
    for x in v.iter_mut() { *x /= max; }
}
```
```text
// Our language — illustrative only — not a syntax decision — con: a Rust hurdle stays
b = a          // move
a.append(4)    // compile error: use of moved value (write b = a.copy())
```

### O5 — Full Rust-style ownership with lifetimes

```rust
// Rust (excerpt from a verified program) — pro, (f): race-free disjoint mutation, no locks
thread::scope(|s| {
    let (left, right) = data.split_at_mut(2);
    s.spawn(move || for x in left.iter_mut()  { *x *= 10 });
    s.spawn(move || for x in right.iter_mut() { *x *= 100 });
});
```
```rust
// Rust — con: a lifetime parameter on a type, which fails G3
struct Parser<'a> { src: &'a str }
```

### O6 — Single ownership + runtime-checked non-owning references

Vale checks a generation on each dereference [ValeGR]. Inko counts borrows and panics when an owner is dropped with borrows still live [InkoMem].

**Scored entirely on Inko.** Inko ships an LLVM compiler from a small self-funded team [Inko011] and has working concurrency [InkoConc]. The notes rank it second for tractability. Vale never shipped threading [ValeRoadmap], and its successor language has generational references "temporarily disabled" [GoldenSpike].

```vale
// Vale (approximate syntax, from research notes) — pro, (b): a parent pointer looks ordinary
struct Node { name str; parent ?&Node; children List<Node>; }
```
```text
// Our language — illustrative only — not a syntax decision — con, (d): no shared ownership
cache = Cache(); loader = Loader(&cache)
drop(cache)    // runtime panic; Inko: "can't drop a value … as it still has 1 reference(s)"
```

### O7 — ARC + backup cycle collector (Nim ORC-style)

Nim's authors say ORC "can be considered a full-blown GC" [NimARC].

```nim
# Nim (corrected from research notes) — pro, (c): leaks under ARC, collected under ORC
type Editor = ref object
  onTap: proc ()                  # proc types default to the closure calling convention
proc save(e: Editor) = discard
proc newEditor(): Editor =
  let e = Editor()
  e.onTap = proc () = e.save()    # e -> closure env -> e
  e
```
```nim
# Nim — con: for ORC to approach ARC speed, Nim uses a pragma (an annotation, so G3)
type Node {.acyclic.} = ref object
```

### O8 — Manual memory + explicit allocators + debug checks (Zig/Odin-style)

```zig
// Zig, approx. 0.15 API (from research notes; readLines is hypothetical) — pro, (a)
var arena = std.heap.ArenaAllocator.init(dbg.allocator());   // dbg: DebugAllocator, reports leaks
defer arena.deinit();                                        // frees everything at once
const lines = try readLines(arena.allocator(), "input.txt");
```
```zig
// Zig (from research notes) — con, (e): unchecked even in ReleaseSafe
const first = &list.items[0];
try list.append(gpa, 0);     // may reallocate
first.* = 1.0;               // dangling write
```

### O9 — Owned values + checked handles into pools (added 2026-11-11, not yet scored)

This is O2's value semantics with O6's generation-checked handles as the language's only reference mechanism. Both brainstorm rounds kept reaching the underlying finding (long-lived state that doesn't nest needs identity plus explicit deletion) and filed it as a library tool. O2 was marked down mainly because its handles were unchecked. Nobody scored the combination.

**Rules a user learns (3, plus one open choice):**
1. Every value has one owner and is freed when the owner's scope ends.
2. Functions borrow their parameters for the duration of the call. A borrow can't be stored or returned.
3. Anything with identity (windows, sessions, tree nodes, cache entries) lives in a pool. You refer to it by a handle, you add and remove entries explicitly, and a lookup through a stale handle visibly fails.
4. *Open choice:* assigning a large value either copies implicitly (hides cost) or needs an explicit `.copy()` or move (a small Rust-style error). John's transparency goal points to explicit.

**What it removes:** reference counts, `weak`, cycles, and hidden work at free time. A handle is two integers and a lookup is one compare. It passes the P1 test trivially, because nothing is counted.

```text
// illustrative only — not a syntax decision
editors = Pool of Editor                 // owned by the app; freed with it
h = editors.add(Editor(doc))             // h is a handle: (index, generation)

button.onTap = {                         // (c): the closure captures h, a plain value
    if e = editors.get(h) { e.save() }   // the "it's gone" branch is explicit, not a silent skip
    else { log("editor closed") }
}

editors.remove(h)                        // explicit; later get(h) fails visibly
```

**Scenarios:**
- **(a) File into a list:** the list owns its buffer and frees it at scope end, as in O2 and O4.
- **(b) Tree with parent pointers:** nodes live in a pool, and parent and child links are handles.
- **(c) UI callback:** above. This answers Q11 with no silent skip.
- **(d) Shared cache:** the cache is a pool owned above both components, which hold handles.
- **(e) Mutate a large list:** a mutable borrow for the call, with no copy.
- **(f) Threads:** values move between threads, and pools sit behind a mutex. Q7 (atomic counts) disappears.

**Costs:**
- **Removal is manual.** A forgotten `remove` leaks until the pool dies. The leak is bounded and visible in the pool.
- **Stale handles are caught at run time**, not compile time.
- **Pools must be reachable.** Either they are passed down, or handles carry a pool pointer.
- **Code looks less like classic OO** and more like tables of things (P-C asks for native OO; methods with implicit `self` on values still work).
- **Not proven.** It hasn't been scored, reviewed adversarially or prototyped. Hylo and Vale show the ergonomics are the risk.

**Relation to O4:** O4 is this model plus a second, reference-counted model (`shared`) for the hard cases. O9 replaces that second model with pools.

## Evaluation

**Gates.**
- **G2:** depends on P1.
- **G3:** every option depends on P2.
  - **O5 fails G3** because of lifetime parameters on types. That is the only robust failure: `Send` and Rust's generic wrappers could become built-ins, as in O4.
  - **‡** marks a pass that also depends on an inference replacing something precedent languages annotate:
    - escaping closures and sendability (O2, O3, O4; Swift uses `@escaping` and `@Sendable`);
    - acyclicity (O7; Nim uses `{.acyclic.}`);
    - sendability (O1, but only if threads use non-atomic counts).

**Criteria.** The weights were **proposed by the coordinator, not set by John**. They are kept as the baseline, and Q5 asks John to confirm them.

The scores were written knowing the coordinator's prior was O3. To counter that anchoring, each criterion is justified side by side across all options below. Each criterion has one scope:
- **Cycles and `weak` count only under Simplicity.**
- Leaks are not memory-safety violations.
- Data races count only under Concurrency.

| Criterion | Weight | Scope | Charter anchor |
|---|---|---|---|
| Simplicity | 25 | Memory-model rules and syntax a user must learn; whether mistakes are loud or silent | G1, G4, P-RUST, P-SWIFT |
| Memory safety | 15 | Use-after-free, double free, dangling or out-of-bounds outside `unsafe`; static prevention vs runtime trap | P-C |
| Expressiveness | 15 | (a)–(e) written directly, without restructuring the design | G11, P-PY |
| Implementation risk (5 = low) | 15 | What must work before the language is usable, weighted by silent failure; includes in-place access paths | **None** (project constraint) |
| Performance & predictability | 10 | Throughput and hidden costs | P-PY, P-GO, P-JAVA |
| Concurrency | 10 | (f) under the minimum safe RC rule | **None** |
| Tooling & C FFI | 10 | G8/G9 on all three OSes; C interop | G8, G9, G10 |

**Scale.** 5 means best in the field. 3 means workable at a clear cost. 1 means disqualifying.

| Option | G2 | G3 | Simp | Safety | Expr | Impl | Perf | Conc | Tool | Raw | **Total** | Draft | Eligible |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| O1 Pure ARC | P1 | P2 ‡ | 4 | 5 | 5 | 5 | 3 | 2 | 4 | 415 | **83.0** | 77 | Yes |
| O4 Simplified ownership | P1 | P2 ‡ | 3 | 4 | 5 | 4 | 5 | 4 | 5 | 410 | **82.0** | 76 | Yes |
| O7 ARC + cycle collector | P1, P1b | P2 ‡ | 5 | 5 | 5 | 3 | 2 | 1 | 3 | 380 | **76.0** | 76 | After P1b |
| O3 Hybrid MVS + CoW + RC | P1 | P2 ‡ | 3 | 4 | 5 | 3 | 4 | 3 | 4 | 365 | **73.0** | 78 | Yes |
| O6 Ownership + checked refs (Inko) | Pass | P2 | 3 | 4 | 4 | 4 | 3 | 4 | 3 | 355 | **71.0** | 66 | Yes |
| O2 Strict MVS | P1 | P2 ‡ | 3 | 5 | 2 | 3 | 4 | 4 | 3 | 335 | **67.0** | 67 | Yes |
| O5 Full Rust ownership | Pass | **Fail** | 1 | 5 | 4 | 1 | 5 | 5 | 5 | 325 | **65.0** | 59 | No |
| O8 Manual + allocators | Pass | P2 | 2 | 2 | 4 | 4 | 5 | 2 | 3 | 300 | **60.0** | 54 | Unless P3 or Q8 = yes |

The total is Σ weight × score ÷ 5. All figures in this section come from `scripts/adr0001_scores.py`, pasted unchanged.

### Justifications, side by side

**Simplicity.**
- **O7: 5.** One rule.
- **O1: 4.** Adds the silent `weak` rule. The lint catches only direct self-capture. Cyclic garbage averages ~16% of objects in Java benchmarks, heavily skewed [Shahriyar]. Pervasive sharing "makes logic errors more likely" [AppleSvC].
- **O2: 3.** `inout` plus a marker, exclusivity errors (`swap(&x[i], &x[j])` is rejected [P2676]), a mutating marker, non-mutating escaping captures, hidden copies, handle idioms.
- **O3: 3,** the weakest 3. O2's rules, plus O1's for identity types, plus runtime exclusivity traps. Choosing between its two kinds of type needs a guide [AppleSvC].
- **O4: 3.** No lifetimes, but keeps move and exclusivity errors and `.copy()`, plus O1's rules inside `shared`.
- **O6: 3.** Owner versus borrow, moves, runtime panics.
- **O8: 2.** Lifetimes live in the programmer's head; allocators everywhere [ZigDocs].
- **O5: 1.** 59% of 178 self-selected respondents found Rust harder to learn [Fulton]. A third of Google developers were productive within two months [GoogleRust].

**Safety.**
- **5:** O1, O7 (zeroing `weak`, no `unowned`); O2 (static only); O5.
- **4:** O3 and O4 share one trap class: runtime exclusivity on identity fields (Swift checks class properties dynamically [SE0176]) or on `shared` mutation (`RefCell`, verified). O6's main references are runtime-checked.
- **2:** O8. Checks are "disabled by default" in its fast modes [ZigDocs].

**Expressiveness.**
- **5:** O1, O3, O4, O7. (a)–(e) are direct with RC + `weak`; the rules are charged to Simplicity.
- **4:** O6 ((d) needs an owner that outlives its borrowers); O8 (no capturing closures in Zig/Odin); O5 (graphs often restructured into indices; no self-referential structs [RustGoals]).
- **2:** O2. (b), (c) and (d) need restructuring [Racordon].

**Implementation risk.**
- **O1: 5.** RC insertion and a weak side table. No soundness-critical analysis, and no projections (containers are references).
- **O4: 4.** The move checker and borrow exclusivity are soundness-critical, plus RC and a `shared` check. Projections can follow stage 1: without them `map[k].append(x)` is a compile error or an O(1) move-out/in, not O(n²).
- **O6: 4.** Moves plus counted borrows; failures are loud [Inko011].
- **O8: 4.** Cheap compiler, but the stdlib is silent-failure code.
- **O2: 3.** Dataflow, exclusivity, `yield` projections and CoW. Uniqueness optimisations are required in practice (Swiftlet is "significantly slower than Swift" [Racordon]). Hylo is pre-1.0 [Hylo1905].
- **O3: 3,** the weakest 3. O2's machinery, with projections required at stage 1 [SE0154], plus O1's runtime, dynamic exclusivity and transitive sendability. Silent wrong-result risk when a +0 borrow meets a uniqueness check. Ranked behind Inko-style by the notes.
- **O7: 3.** Adds a trial-deletion collector.
- **O5: 1.** Polonius took ~a decade [Polonius]; Carbon had no safety design by 2025 [Carbon].

**Performance.**
- **5:** O4, O5, O8.
- **4:** O2, O3 (hidden CoW copies; O3 also pays RC and checks on identity types).
- **3:** O1 and O6.
  - O1: every object is a counted heap allocation; Java is adding value classes for this reason [Valhalla]. Swift's 32% RC figure [BRC] is dropped, because it measured an O3-shaped language with atomic counts.
  - O6: borrow-count traffic. Vale's +10.84% [ValeGR1] doesn't apply.
- **2:** O7 (adaptive collection threshold [NimARC]).

**Concurrency.**
- **5:** O5.
- **4:** O2 (no shared mutable state); O4 (free moves, structural sendability like Rust's `Send` [Nomicon]); O6 (shares nothing; `uni` sends [InkoConc]).
- **3:** O3 (atomic buffer counts; transitive non-sendability). Swift's precedent: Sendable in 5.5 [HWSSendable], full checking in 5.10 [Swift510], then a MainActor-default "dialect" in 6.2 [Massicotte].
- **2:** O1 (every object is shareable, so a sendability layer is needed over everything, or all-atomic counts); O8.
- **1:** O7 (would trace objects under concurrent mutation; Nim's variant is experimental [NimMM]).

**Tooling/FFI.**
- **5:** O4, O5 (plain structs; owned/borrowed mirrors C).
- **4:** O1, O3 (deterministic destruction and cycle reports on all three OSes; inserted RC code needs coverage attribution and three debugger formatters).
- **3:** O2 (C contexts are indices); O6 (no checks across FFI); O7 (cyclic handles close only when the collector runs); O8 (sanitizer reliance).

### Sensitivity: each weight ±10, renormalised (script output)

| Variant | O1 | O4 | O3 | O6 | O2 | O8 | O7 (gated) | O5 (fails G3) | Eligible winner |
|---|---|---|---|---|---|---|---|---|---|
| Base | 83.0 | 82.0 | 73.0 | 71.0 | 67.0 | 60.0 | 76.0 | 65.0 | O1 |
| Simp 35 | 82.7 | 80.0 | 71.8 | 70.0 | 66.4 | 58.2 | 78.2 | 60.9 | O1 |
| Simp 15 | 83.3 | 84.4 | 74.4 | 72.2 | 67.8 | 62.2 | 73.3 | 70.0 | O4 |
| Safety 25 | 84.5 | 81.8 | 73.6 | 71.8 | 70.0 | 58.2 | 78.2 | 68.2 | O1 |
| Safety 5 | 81.1 | 82.2 | 72.2 | 70.0 | 63.3 | 62.2 | 73.3 | 61.1 | O4 |
| Expr 25 | 84.5 | 83.6 | 75.5 | 71.8 | 64.5 | 61.8 | 78.2 | 66.4 | O1 |
| Expr 5 | 81.1 | 80.0 | 70.0 | 70.0 | 70.0 | 57.8 | 73.3 | 63.3 | O1 |
| Impl 25 | 84.5 | 81.8 | 71.8 | 71.8 | 66.4 | 61.8 | 74.5 | 60.9 | O1 |
| Impl 5 | 81.1 | 82.2 | 74.4 | 70.0 | 67.8 | 57.8 | 77.8 | 70.0 | O4 |
| Perf 20 | 80.9 | 83.6 | 73.6 | 70.0 | 68.2 | 63.6 | 72.7 | 68.2 | O4 |
| Perf 0 | 85.6 | 80.0 | 72.2 | 72.2 | 65.6 | 55.6 | 80.0 | 61.1 | O1 |
| Conc 20 | 79.1 | 81.8 | 71.8 | 71.8 | 68.2 | 58.2 | 70.9 | 68.2 | O4 |
| Conc 0 | 87.8 | 82.2 | 74.4 | 70.0 | 65.6 | 62.2 | 82.2 | 61.1 | O1 |
| Tool 20 | 82.7 | 83.6 | 73.6 | 70.0 | 66.4 | 60.0 | 74.5 | 68.2 | O4 |
| Tool 0 | 83.3 | 80.0 | 72.2 | 72.2 | 67.8 | 60.0 | 77.8 | 61.1 | O1 |
| All equal | 80.0 | 85.7 | 74.3 | 71.4 | 68.6 | 62.9 | 68.6 | 74.3 | O4 |

**Single-score changes (±1) that change the winner** (script output):

```
O1 Simp 4->3: winner O4 (O4 82.0, O1 78.0)
O1 Safety 5->4: winner O4 (O4 82.0, O1 80.0)
O1 Expr 5->4: winner O4 (O4 82.0, O1 80.0)
O1 Impl 5->4: winner O4 (O4 82.0, O1 80.0)
O1 Perf 3->2: winner O4 (O4 82.0, O1 81.0)
O1 Conc 2->1: winner O4 (O4 82.0, O1 81.0)
O1 Tool 4->3: winner O4 (O4 82.0, O1 81.0)
O4 Simp 3->4: winner O4 (O4 87.0, O1 83.0)
O4 Safety 4->5: winner O4 (O4 85.0, O1 83.0)
O4 Impl 4->5: winner O4 (O4 85.0, O1 83.0)
O4 Conc 4->5: winner O4 (O4 84.0, O1 83.0)
```

**What the results show.**
- No single change puts O3, O6 or O2 first.
- **Alternative readings (script output):**
  - Escaping-capture traps also charged to Expressiveness (O3 = O4 = 4): O1 83.0, O4 79.0, O3 70.0.
  - "O1+" (ARC objects with CoW containers): 69.0.
- **O3** would need either a prototype showing its CoW, projection and exclusivity machinery is cheap to build correctly, or evidence that value-default semantics cut user errors more than its two kinds of type cost.

## Review of method (2026-11-11, Claude Fable 5.2)

A second model reviewed the work to date. Its findings limit how much weight the scores above can carry.

- **The precision is false.** Gaps of 1–3 points rest on weights proposed by the coordinator (Q5 is still open) and on one AI analyst per idea. Nothing was compiled or run, apart from the Rust and C++ excerpts.
- **The brainstorm's convergence is weaker evidence than it looks.** Sixteen analysts reaching kernel K1 were sixteen runs of the same model with the same priors, not independent confirmations.
- **The rubric measured the wrong kind of simplicity.** It counted rules to learn. John's clarification of G1 (below) is about reasoning on the running program. Hidden work was barely penalised: refcount traffic, silently skipped callbacks (K1), hidden copies, and aliasing through `b = a` under O1.
- **Scenario (c) dominated.** If G11 means DSL syntax rather than a UI framework, much of the case for reference counting weakens. G11's scope is still undecided.
- **One candidate was never scored:** O9.

**John's clarification of G1 (2026-11-11), recorded verbatim for the charter owner to act on:** the goal is "being more helpful and safe than C, without having too many different things for programmers to try to remember ... a simple programming language (not necessarily simple to write with all the complexity hidden away, but simple rules which make it easy to reason about how the program is working while it is running)".

This ADR does not edit the charter. If John wants this reading to bind future ADRs, he adds it to G1.

**Consequences for this ADR:**
- The O4 recommendation is on hold until O9 has been compared with O1 and O4.
- Any re-scoring needs a criterion for run-time transparency and local reasoning (no hidden work, no aliasing surprises), with weights John confirms.
- **Next step, before scoring or a spike:** hand-write one ~300-line program three ways in pseudo-syntax (O1, O4, O9): a small editor with a tree, a cache, a callback and a worker thread. John's reaction on reading them is the measure of G1 and G4.
- P2 and P3 don't depend on the model and can be answered now.

## Decision

**Nothing is adopted yet.** John still decides (Q3).

**Update 2026-11-11: the O4 recommendation below is on hold** until O9 has been compared with O1 and O4 (see "Review of method").

**Update 2026-11-09: Q4 is "yes", so threads are in v1. The recommended pick is now O4.**

| | Simp 25 | Safety 15 | Expr 15 | Impl 15 | Perf 10 | Conc **20** | Tool 10 | Weighted sum | Total (/110 → /100) |
|---|---|---|---|---|---|---|---|---|---|
| O4 | 3 | 4 | 5 | 4 | 5 | 4 | 5 | 450 / 5 = 90 | **81.8** |
| O1 | 4 | 5 | 5 | 5 | 3 | 2 | 4 | 435 / 5 = 87 | 79.1 |
| O4 if re-entrancy traps (Expr 4) | 3 | 4 | 4 | 4 | 5 | 4 | 5 | 435 / 5 = 87 | 79.1 (tie) |

- **Why O4.** Its compile-time moves are the only eligible mechanism that stops data races through surviving aliases.
  - Without them, every thread-safety rule becomes a runtime check.
  - 18 of 20 round-1 designs that relied on runtime checks failed exactly here.
  - O1 would need a sendability retrofit over every type, which is the Swift 5.5→6 lesson (P-SWIFT).
- **Condition.** The spike must include a synchronous observer/delegate callback that re-enters a `shared` owner part-way through a mutation.
  - If that traps, the tie is broken by judgement.
  - The fix to try first is narrowing the exclusivity trap from the whole object to individual fields.
- **Now live:** Q7 (atomic RC policy) and the `Mutex`/`Channel` members of P2. Under O4, prefer Q7 option (B): atomic counts only for `shared` data that can be sent, non-atomic for data proven thread-local.

**Earlier recommendation (before Q4), kept for the record: O1.**

*Judgement (opinion, not evidence):*
1. **G1 is first and heaviest.** O1 has 5 memory-model rules to O4's 9, and its one silent rule also exists inside O4's `shared`. The charter names Rust's learning curve as a problem, and O4 keeps Rust's move and exclusivity errors.
2. **Project risk.** O1 is the only eligible option with no soundness-critical static analysis, and the debug runtime can check every RC operation.
3. **O1's weak cells aren't charter goals.** Concurrency isn't a goal, and performance appears only as P-PY. RC elision [Lobster] recovers part of the gap.

*What favours O4 (judgement):*
- **Irreversibility.** After the first public release, O1's types and `List` stay references. O4 keeps values, and could later relax use-after-move into implicit copies without breaking programs.
- **Threads.** v1 threads would force a sendability retrofit onto O1 (the P-SWIFT lesson).
- **Performance.** O1 has a lower ceiling.

**Switch to O4 if** Q4 is "yes", if `List` must be a value, or if Simplicity is weighted 15 (O4 84.4 vs O1 83.3).

**What would settle it:**
- **John's answers to Q4 and Q5.** At Concurrency 0, O1 leads 87.8–82.2. At 20, O4 leads.
- **A 2–3 week spike.** Build minimal O1 and O4 front ends on one IR, then measure three things:
  1. how many seeded soundness bugs the tests catch (the Impl gap);
  2. how many fixes per 1k lines it takes to port (a)–(f) plus a ~1k-line UI sample (the Simplicity gap, the likeliest flip);
  3. a one-million-record benchmark.

**Model specifics.**
- **If O1:**
  - Every user type is an RC reference. Scalars are values, `String` is immutable, and `List`/`Map` are references.
  - There is no `inout`.
  - Closures share captured locals, which are boxed.
- **If O4:**
  - Non-copyable values move. Trivially copyable types copy (inferred). Other copies are `.copy()`.
  - Resources are move-only.
  - Borrows are parameter-only.
  - `shared` is RC + `weak`, and overlapping mutation of it traps.
- **Either:**
  1. Zeroing, optional-typed `weak`, with one capture form. No `unowned`. Unretained pointers only behind `unsafe` FFI.
  2. No runtime cycle collector (P1b: no). The debug runtime runs on all three OSes. Debug and test builds may trace (ruling P1(b)) but never reclaim. It provides:
     - header checks;
     - poisoning of freed memory;
     - a leak and cycle report at exit;
     - an on-demand live-cycle report for long-running apps.

     The lint covers direct self-capture only.
  3. A one-word header (count plus flags) with a "shared" bit reserved. Weak references use a side table.
  4. Release:
     - uses an iterative worklist with a defined destruction order;
     - resurrecting an object in its destructor traps;
     - deferred frees drain only at program points (P1).
  5. Lexical lifetimes for anything with a destructor or weak observers.
  6. FFI:
     - exported `retain`/`release`;
     - borrowed passing for the duration of a call;
     - scoped buffer pinning;
     - foreign-thread callbacks touch only atomic-count state.

**Minimum safe concurrency rule** (O1, O2, O3, O4, O7):
- **Atomic counts.** A count that more than one thread can touch is updated atomically.
- **Sends.** Top-level uniqueness on send is **unsafe**: a sent `List of String` still shares its string buffers, and their non-atomic counts race, which leads to use-after-free. A send must do one of these:
  - make every count it can reach atomic;
  - share-mark everything reachable, recursively (Koka `tshare` [Perceus]);
  - prove the whole graph is unique.
- **Sendability.** If inferred, it is transitive through fields, captures and containers.
- **v1 without threads** (Q4 "no"): non-atomic counts, with the shared bit reserved.

The policy is Q7.

**Constraints passed to other ADRs (not decided here):**
- **ADR-00xx DSL** (if Q9 is yes):
  - views are immutable descriptions;
  - state is framework-owned and addressed by handles;
  - callbacks capture handles, not owners;
  - positional state identity and heterogeneous children are solved without property wrappers, result-builder attributes or user generics. If that can't be done, G3 or this ADR is reopened.
- **ADR-00xx Concurrency:** spawn and async API, actors versus channels, sendability diagnostics.
- **ADR-00xx Generics:** the built-in set (P2).
- **ADR-00xx Syntax:** spellings.
- **ADR-00xx Stdlib:** whether `Arena` and a handle store ship. A stale handle returns "missing" [Slotmap].
- **Stage-1 entry criteria:**
  - the debug runtime on all three OSes;
  - differential builds, with each optimisation switched off in turn;
  - compiler mutation testing;
  - copy-count goldens and a deep-copy oracle, if CoW is ever adopted.

This ADR introduces no property wrappers, macros, result-builder or Sendable-style attributes, `unowned`, lifetime syntax or user-facing `sink`/`consume`/`borrowing`. That binds no later ADR; only the charter binds permanently.

## Consequences

These assume O1.

**Easier:**
- One kind of type, with semantics familiar from Java and Python.
- No move errors and no exclusivity errors.
- Files and handles close exactly once.
- The simplest compiler.
- (b), (c) and (d) are direct.
- C interop through retain/release.

**Harder:**
- Silent `weak` mistakes, guarded only by the lint and the debug reports.
- A heap allocation plus a count per object; RC elision is the main lever against this.
- Snapshots need explicit copies.
- Threads later need sendability over every type.
- Coverage attribution for inserted code.
- Debugger formatters on three platforms.

**Ruled out:** value semantics as the default after the first public release.

**Under O4 instead:**
- Easier: values and predictable performance.
- Harder: move and exclusivity errors, and a soundness-critical move checker.
- Nothing irreversible beyond move-by-default.

## Syntax budget impact

This is not "None". Memory-model items only.

| Item | O1 | O4 | O3 (for reference) |
|---|---|---|---|
| Keywords | `weak` | `weak`, `shared`, a mutable-borrow modifier | `weak`, an identity-type keyword, `inout` |
| Operators | 0 | 0–1 call-site mutation marker | 0–1 (`&`) |
| Grammar | weak-capture form | weak-capture form, escaping-closure type form, mutating-receiver marker | weak-capture form, identity declaration, escaping-closure type form, mutating marker |
| `let`/`var` load-bearing | no | yes | yes |
| Library, not syntax | — | `.copy()` | — |
| Depends on | optional-type ADR (unwrapping `weak`) | same | same |

**Rules users must learn.**

- **O1 (5 rules):**
  1. `=` aliases.
  2. An object is freed deterministically when its last strong reference goes.
  3. Back-references and self-capturing stored closures must be `weak`, or they leak silently.
  4. A `weak` reference becomes nil when its target is freed.
  5. Closures share the locals they capture.
- **O4 (9 rules):**
  1. `=` moves, and using a moved value is an error.
  2. Trivially copyable types copy.
  3. Other copies are `.copy()`.
  4. Borrows can't be stored, returned or captured by an escaping closure.
  5. A value can't be passed mutably twice in one call.
  6. `shared` aliases, and the `weak` rule applies to it.
  7. Overlapping `shared` mutation traps.
  8. Resources are move-only.
  9. Mutating methods need the receiver marker.
- **O3 (11 rules):**
  1. `=` copies values and aliases identity types.
  2. `inout` needs a call-site marker.
  3. Exclusivity errors.
  4. Runtime exclusivity traps.
  5. A mutating marker.
  6. `let`/`var`.
  7. Escaping closures copy values.
  8. Hidden CoW copies.
  9. Values holding identity references are only shallow snapshots.
  10. The `weak` rule.
  11. Identity objects alias.

## Open questions for John (by impact)

1. **P1 — G2 and RC. CLOSED.** Answered YES on 2026-11-09, with follow-ups answered on 2026-11-11:
   - **(a)** The test is confirmed. Work at count zero must be proportional to what is freed, and live objects are never inspected.
   - **(b)** Debug- and test-only tracing is allowed: N1 leak checks, the exit report and the N3 `weak` advisor. It reclaims nothing and never ships.
   - **(c)** Long cascades in release are acceptable. An incremental free queue may be added later as an optimisation, but it isn't required.
   - **P1b follows from (a): no.** A cycle collector inspects live objects, so O7 is ineligible.
2. **P2 — G3 and built-in parameterised types.** **Yes/no.** "No" means every option fails and G6 is revisited.
3. **The pick.** Choose one: **O1**, **O4** (leads on score since Q4, but on hold) or **O9** (unscored). Wait for the three-way comparison in Q13.
4. **Concurrency in v1?** **Answered 2026-11-09: YES.** Concurrency weight is now 20, and O4 leads 81.8 to 79.1 (see Decision).
   - No: Concurrency weight 0. O1 leads 87.8 to 82.2. v1 ships non-atomic counts and no threads.
   - Yes: Concurrency weight 20. O4 leads 81.8 to 79.1.
5. **Weights.** These were proposed by the coordinator, not you: 25/15/15/15/10/10/10. Implementation risk and Concurrency (25 points between them) have no charter anchor. **Confirm, or give new weights.**
6. **P3 — is memory safety required?** **Yes/no.**
   - Yes: O8 is out, and you record the requirement in the charter.
   - No: Safety may be down-weighted. At weight 5, O4 leads 82.2 to 81.1.
7. **Atomic RC policy** (only if Q4 is yes). Pick one:
   - **(A) Always atomic.** Simplest. Costs 5–59% in Koka [Perceus]; an atomic op is 2.4× a plain one [BRC].
   - **(B) Atomic for anything sendable or shared**, non-atomic where the compiler proves the object is thread-local.
   - **(C) A per-object shared flag, set recursively on publish.** Fastest, but the hardest to get right, and it complicates TSan.

   Non-atomic counts with top-level uniqueness on send are not offered, because they are unsafe.
8. **Should the charter's P-\* problems act as gates?** **Yes/no.** If yes, O8 is out (P-C). O4 must then show it doesn't bring back P-RUST, and O1 that it doesn't bring back P-SWIFT. Scores don't change.
9. **DSL coupling.** Bind the DSL ADR to the constraint listed under Decision? **Yes/no.** If no, UI code uses reference widgets with `weak` captures, and G11 strain rises for every RC option. The pick doesn't change.
10. **Large hidden copies** (only relevant for O3 or CoW containers). Choose **warn**, **error** or **nothing**. Debug and optimised builds copy differently, so any diagnostic should come from release-mode profiling.
11. **Closures and `self`** (from the brainstorms). Choose (a) K1 silent skip with a debug log, (b) K1 with an explicit `else`, or (c) N2 anchor teardown plus N1 leak tests. Under O9 the question disappears: callbacks capture handles.
12. **Add John's 2026-11-11 reading of G1 to the charter?** **Yes/no.** If yes, John edits G1, and the rubric gains a run-time transparency criterion.
13. **Is O9 a candidate?** **Yes/no.** If yes, the three-way hand-written program comes next, and Q3 waits for it.
14. **Under O9 or O4: implicit copy or explicit `.copy()`/move for large values?** Pick one.
15. **Is G11 DSL syntax only, or does it include a UI framework in v1?** This sets how much scenario (c) should count.

## Adversarial review log

| Reviewer · finding | Verdict | Change, or reason |
|---|---|---|
| Audit B1 · charter text and G2 definition drafted in the ADR | Accepted | Both removed. P1–P3 added, each with its "no" outcome, as `needs-john` items |
| Audit M1/M3 · G3 read as "require"; inconsistent gates | Accepted | Gate reads "must not have". O5 fails on lifetimes only. ‡ applied by one rule |
| Audit M2 · G2 definition gaps (O7, deferred frees, exit report) | Partly | No definition adopted. The cases go to John in P1 |
| Audit M4 · cycles/`weak` counted three times | Accepted | Scopes defined; cycles count under Simplicity only. O1 Safety and Expr go 4→5 |
| Audit M5, Steelman A/B, Red team 1.6/1.11/2.1 · O3 Simp/Impl overstated; O3 trap ≈ `RefCell` | Accepted | O3 Simp 3, Impl 3. O3 and O4 both Safety 4 |
| Steelman C · O4 Expr understated | Accepted | 5, the same as O1 and O3 |
| Steelman · O2 Expr 2→3 | Rejected | (b), (c), (d) still need restructuring. Safe handles fix safety, not structure |
| Steelman · score O6 as Inko | Accepted | Applied to every cell |
| Steelman · 32% RC figure is O3-shaped | Accepted | O1 Perf re-justified [Valhalla] |
| Steelman / Red team · recommend O4 / O1 | Partly | Rescored to a tie; decided by labelled judgement. O3 dropped |
| Steelman · O1+ voids irreversibility | Partly | Scored 69; it carries O3's CoW costs |
| Steelman · "a silent slowdown beats a compile error" | Accepted | Dropped |
| Audit M6 · one-sided sensitivity | Accepted | ±10 on every weight, equal weights, full flip list |
| Audit M7/M8 · weights' origin; unanchored criteria | Accepted | Attributed to the coordinator; anchoring disclosed; Q5 added. G4 folded into Simplicity, since a new criterion would need new weights |
| Audit M9 · O8 consequence wrong | Accepted | Recomputed |
| Audit M10 · O8 vs P-C; thin P-SWIFT check | Partly | P-* gates are Q8. Rule counts replace the exclusion list |
| Audit M11 · scope creep | Accepted | Moved to "Constraints passed to other ADRs" |
| Audit M12–M15 · syntax budget, question order, fallback contradiction, template | Accepted | All fixed. O3→O1 fallback removed |
| Audit minor · drop Sources | Rejected | The owner checks sources. Kept compact, with tags |
| Red team 1.1 · threading hole | Accepted | Minimum safe rule added; unsafe option removed |
| Red team 1.2 · projections missing | Accepted | Charged to O2 and O3 at stage 1, and to O4 later |
| Red team 1.3 · capture rule | Accepted (O1/O4) | O1 shares captures; O4 moves/copies. O3 trap shown in (c) |
| Red team 1.4 · DSL imports SwiftUI machinery | Accepted | Q9 now covers positional identity and children |
| Red team 1.5, 1.7–1.10, 1.12, 1.14 | Accepted | Lifetimes, lint scope, FFI, P2 list, debug/release copy caveat and release order added |
| Red team 2.3 · test infrastructure | Partly | Condensed into stage-1 criteria |
| Red team §3 · Cyclone, C#, LSan, Sendable, SR-13888 | Accepted | Fixed and re-checked. C# quote replaced by [AppleSvC], SR-13888 by [SE0154] |
| Red team §4, Steelman §4 · code examples | Accepted | Nim, Zig, Swift caveat, Rust excerpt labels, O1 caption, O2 handles and the O8 strawman all fixed |

## Sources

- **[AppleSvC]** Apple, Choosing Between Structures and Classes — https://developer.apple.com/documentation/swift/choosing-between-structures-and-classes.md
- **[Bacon]** Bacon et al., Unified Theory of GC, OOPSLA 2004 — https://web.eecs.umich.edu/~weimerw/2014-4610/reading/bacon-garbage.pdf
- **[BRC]** Biased Reference Counting, PACT 2018 — https://docs.rs/crate/biasedrc/latest/source/paper.pdf
- **[Bronze]** Coblenz et al., Bronze trial — https://arxiv.org/pdf/2110.01098
- **[Carbon]** Carbon roadmap — https://docs.carbon-lang.dev/docs/project/roadmap.html
- **[Cyclone]** Grossman et al., Cyclone regions — https://www.cs.umd.edu/~mwh/papers/GrossmanMJHWC02.html
- **[Fulton]** Fulton et al., SOUPS 2021 — https://par.nsf.gov//servlets/purl/10357735
- **[GoldenSpike]** Ovadia, Golden Spike / Valen — https://verdagon.dev/blog/golden-spike-reviving-vale-valen
- **[GoogleRust]** Google, Rust fact vs fiction — https://opensource.googleblog.com/2023/06/rust-fact-vs-fiction-5-insights-from-googles-rust-journey-2022.html
- **[HWSSendable]** Sendable, Swift 5.5 — https://hackingwithswift.com/swift/5.5/sendable
- **[Hylo1905]** Hylo roadmap #1905 — https://github.com/orgs/hylo-lang/discussions/1905
- **[HyloFn]** Hylo tour: functions — https://docs.hylo-lang.org/language-tour/functions-and-methods.md
- **[Inko011]** Inko 0.11 (LLVM compiler) — https://inko-lang.org/news/inko-0-11-0-released
- **[InkoConc]** Inko: concurrency — https://docs.inko-lang.org/manual/main/getting-started/concurrency
- **[InkoMem]** Inko: memory management — https://docs.inko-lang.org/manual/latest/getting-started/memory-management
- **[JetBrains]** CLion sanitizers — https://www.jetbrains.com/help/clion/google-sanitizers.html
- **[Lobster]** Lobster memory management — https://aardappel.github.io/lobster/memory_management.html
- **[LSan]** LLVM LeakSanitizer — https://llvm.googlesource.com/llvm-project/+/refs/heads/main/clang/docs/LeakSanitizer.rst
- **[Massicotte]** Default isolation, Swift 6.2 — https://www.massicotte.org/default-isolation-swift-6_2
- **[MLKit]** Elsman & Hallenberg, JFP 2021 — https://www.cambridge.org/core/services/aop-cambridge-core/content/view/782D317A9B811CD99FA0E924A35B6A58/S0956796821000010a.pdf/integrating_region_memory_management_and_tagfree_generational_garbage_collection.pdf
- **[Mojo]** InfoWorld, Mojo 1.0 — https://www.infoworld.com/article/4173158/first-look-at-mojo-1-0.html
- **[NimARC]** Nim ARC/ORC intro — https://nim-lang.org/blog/2020/10/15/introduction-to-arc-orc-in-nim.html
- **[NimMM]** Nim memory management — https://nim-lang.org/docs/mm.html
- **[Nomicon]** Rustonomicon, Send and Sync — https://rust.googlesource.com/rust-lang/nomicon/+/refs/heads/drop/src/send-and-sync.md
- **[P2676]** P2676R0 Val object model — https://www.open-std.org/Jtc1/sc22/wg21/docs/papers/2022/p2676r0.pdf
- **[Perceus]** Perceus TR — https://microsoft.com/en-us/research/uploads/prod/2020/11/perceus-tr-v4.pdf
- **[Polonius]** Rust blog, Polonius alpha — https://blog.rust-lang.org/2026/08/04/enabling-polonius-alpha-on-nightly
- **[PyGC]** Python gc — https://docs.python.org/3/_sources/library/gc.rst.txt
- **[Racordon]** Implementation Strategies for MVS — https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf
- **[RustGoals]** Rust Project Goals 2026 — https://goals.rust-lang.org/2026/roadmap-borrow-checker-within.html
- **[SE0154]** SE-0154 — https://github.com/apple/swift-evolution/blob/main/proposals/0154-dictionary-key-and-value-collections.md
- **[SE0176]** SE-0176 — https://github.com/apple/swift-evolution/blob/master/proposals/0176-enforce-exclusive-access-to-memory.md
- **[SE0474]** SE-0474 accepted — https://forums.swift.org/t/accepted-se-0474-yielding-accessors/80273
- **[Shahriyar]** Down for the count?, ISMM 2012 — https://core.ac.uk/download/156633347.pdf
- **[Slotmap]** slotmap — https://docs.rs/slotmap/
- **[SwiftPitfall]** Value type + escaping closure pitfall — https://forums.swift.org/t/a-pitfall-with-value-type-escaping-closure/50161
- **[Swift510]** Swift 5.10 — https://www.swift.org/blog/swift-5.10-released
- **[SwiftVision]** Approachability of data-race safety — https://forums.swift.org/t/prospective-vision-improving-the-approachability-of-data-race-safety/76183
- **[Valhalla]** Valhalla value objects — https://openjdk.org/projects/valhalla/value-objects
- **[ValeGR]** Vale generational references — https://verdagon.dev/blog/generational-references
- **[ValeGR1]** Generational references v1 — https://verdagon.dev/blog/generational-references-v1
- **[ValeRoadmap]** Vale roadmap — https://vale.dev/roadmap
- **[VReview]** V review — https://n-skvortsov-1997.github.io/reviews
- **[ZigClosures]** Closures in Zig — https://www.openmymind.net/Closures-in-Zig/
- **[ZigDocs]** Zig docs — https://ziglang.org/documentation/master/

**Provenance of verified items.** The verified Rust excerpts, the E0502/E0597 errors and the `RefCell` panic come from the research team's rustc 1.97.0 tests (2026-11-07). The scores and sensitivity figures come from `/home/claude/scripts/adr0001_scores.py`.
