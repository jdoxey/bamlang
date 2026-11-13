# Red-team review: ADR-0001 recommendation (O3)

- **Reviewed:** `/home/claude/reports/Memory management model ADR.md` (draft ADR-0001, status Proposed, 2026-11-07)
- **Against:** `/home/claude/lang-charter/docs/CHARTER.md`
- **Reviewer role:** adversarial. I attacked O3 only. I did not read the research notes or any other review, so this is independent of the work that produced the draft. Factual claims were checked by web search on 2026-11-07. The ADR's Rust snippets were recompiled locally with rustc 1.97.0.
- **Reviewed:** the ADR and charter as they stood. Neither was edited.

---

## 0. Verdict in brief

O3 is **defensible only as an explicit judgement call, not as the rubric winner**. The draft understates O3's costs in four places that matter:

1. **Threading is unsound as proposed (critical).** Decision 6 (non-atomic counts; "shared CoW buffers made unique on send") checks uniqueness only on the outer buffer. Nested CoW buffers (a `List[String]` holds one buffer per string) are still shared between threads, and their non-atomic counts race. The result is a use-after-free in "safe" code. It can be fixed, but the fix is either deep uniqueness on every send or atomic counts on CoW buffers. Either one changes the cost model and the Q3 options.
2. **Missing implementation pieces.** O3 cannot stay competitive, or even avoid O(n²) cliffs, without **in-place mutable projections** (`map[k].append(x)`, `obj.items.append(x)`). It also needs **compiler-synthesised copy/destroy for every aggregate type** and **runtime exclusivity checks**. The ADR charges projections to O2 but leaves them out of O3's implementation-risk score.
3. **The G11 mitigation is not free.** "Views as values, state in framework stores, handles" is the SwiftUI/React design. Those frameworks needed property wrappers (`@State`), result builders, heavy generics (`TupleView<…>`, `ModifiedContent<…>`) and positional state identity (React's Rules of Hooks). O3 moves the hard part of G11 into the DSL ADR, where it pushes against G3 and P-SWIFT.
4. **Scoring inconsistencies.** O4 is marked down for `RefCell`-style runtime panics, but O3 has the same failure class (dynamic exclusivity traps). The ADR concedes this in Consequences but not in the score. O3's "values can't form cycles or races" is false once a value may contain an identity reference or a closure.

Correcting just two scores (O3 simplicity 4→3, O3 implementation risk 4→3; both argued below) drops O3 to **70**, against O1's 77 and O4's 76. The ADR's own sensitivity table already shows that either change alone hands the win to O1. So the rubric no longer supports O3. What still supports it is the irreversibility argument (lists as values), and O4 supports that too.

**Recommendation:** do not accept the ADR as written. Re-present the decision as Q5 (a judgement between O1, O3 and O4), add the ten mandatory amendments in §5.2, and fix the factual errors in §3.

---

## 1. Attacks on O3

Severity: **Critical** (unsound or blocks a goal), **High** (changes the score or the decision), **Medium** (must be in Consequences), **Low** (editorial).

All code in this section is in our language and is **illustrative pseudo-syntax**, written in the ADR's own illustrative style.

### 1.1 Critical: "Values cross threads safely" is false under non-atomic counts with shallow uniqueness

Decision 6 says: *"Reference counts are non-atomic by default … Values cross threads by move, with shared CoW buffers made unique on send."* A value's top-level buffer can be unique while buffers inside it are shared with the sending thread:

```text
// illustrative only
names = ["alpha-long-string", "beta-long-string"]   // List[String]: 1 list buffer + 2 string buffers
first = names[0]                  // string buffer "alpha…": count 2 (non-atomic)
spawn(move names) { log(names[0]) }   // outer buffer is unique, so no copy: the move is "safe"
print(first)                      // thread 1 retains/releases "alpha…" buffer
                                  // thread 2 retains/releases the same buffer concurrently
                                  // → lost update on a plain count → premature free (UAF) or leak
```

If the outer buffer *is* shared, "made unique" copies it shallowly. That copy retains every element, so it adds *more* cross-thread sharing of the inner buffers.

The same hole applies to identity objects that the compiler "infers from their structure" are safe to send (Decision 6). Even an immutable identity object has a mutable reference count. Under non-atomic RC, an identity object is sendable only if its count is atomic or it is never shared.

**What a fix requires.** Pick one and put it in the Decision:
- **(D, recommended for v1) Atomic counts on CoW buffers and on any sendable identity type; non-atomic on non-sendable identity objects.** This is Swift's choice for buffers. It costs about 2.4× per buffer RC operation ([BRC](https://docs.rs/crate/biasedrc/latest/source/paper.pdf)), but buffer RC operations are far rarer than object operations in value-heavy code.
- **Deep "make unique" on send:** walk every reachable CoW buffer. This costs O(reachable) per send and is a hidden cost.
- **Koka-style recursive share-marking.** Koka's `tshare` "marks an object and its children recursively as thread-shared" ([Perceus TR](https://microsoft.com/en-us/research/uploads/prod/2020/11/perceus-tr-v4.pdf)). That is Q3 option (C), which the ADR defers as "later".

Q3 option (A), as written, is not a memory-safe option. It should be removed or reworded.

### 1.2 High: CoW cliffs the ADR misses. Nested and field mutation needs in-place projections

The ADR names one cliff: a second holder somewhere else. The larger cliffs come from **access paths**, not from stray holders:

```text
// illustrative only
groups: Map[String, List[Int]] = [:]
for e in events { groups[e.key].append(e.value) }
// Without an in-place mutable projection, this is get (inner list count → 2), append (O(n) copy), set back.
// O(n) per event → O(n²) total.

class Log { lines: List[String] = [] }       // identity type holding a value
for i in 0..<100_000 { log.lines.append("x") }
// In place only if `log.lines` is a mutable projection *and* the runtime proves exclusive access
// (see 1.6). Otherwise get/copy/set: O(n²).
```

Swift hit exactly this. SE-0154 records that mutating a dictionary value through its subscript *"introduce[s] an unnecessary copy of the array's contents even though `dict` is the sole holder of its storage"* ([SE-0154](https://github.com/apple/swift-evolution/blob/main/proposals/0154-dictionary-key-and-value-collections.md)). The real fix, coroutine `_modify` accessors, stayed underscored for years and was only accepted as SE-0474 "Yielding Accessors" in June 2025, targeting 6.4 ([acceptance thread](https://forums.swift.org/t/accepted-se-0474-yielding-accessors/80273)).

The ADR lists "`yield`-projection lowering" as an O2 implementation cost, but O3's implementation-risk justification ("exclusivity checks, CoW uniqueness") leaves it out. O3 needs it equally. It is not an optimisation: without it, everyday dictionary-of-lists code is quadratic.

**Required.** Stage 1 must include compiler-internal in-place projections for built-in subscripts and stored fields, even if users can't write their own. Add this to O3's implementation-risk justification and to Consequences.

### 1.3 High: Closure capture semantics are undecided, and every option has a cost

Decision 5: *"Escaping closures capture values by copy and identity objects by strong reference."* That leaves the most common UI and callback idiom undefined:

```text
// illustrative only
taps = 0
button.onTap = { taps = taps + 1 }    // escaping closure captured `taps` by copy
label.text = "taps: {taps}"            // what does the user see?
```

There are three possible semantics, and each one hurts:

| Rule | Consequence |
|---|---|
| Captured values are immutable (compile error above) | Every counter, accumulator or flag in a callback must become an identity object or a store slot. That is O2's "escaping closures can't mutate", which the ADR scores as a con for O2. |
| Closure mutates a private copy | Silent logic bug. Unlike Swift, JS, Kotlin, C# or Python (all capture variables by reference), the label never changes. |
| Captured `var`s are boxed (Swift's rule) | The box is a hidden heap identity inside value semantics. It can be captured by two closures or sent to a thread (a race), and it can form cycles (box → closure → object → box). |

Capture-by-copy also creates a **quadratic cliff** that no "second holder somewhere else" warning would explain:

```text
// illustrative only
items = loadItems()                        // 100k elements
for i in 0..<items.count {
    rows.add({ show(items[i]) })           // escaping closure copies `items` (count +1)
    items[i].seen = true                   // first write after capture: copies all 100k elements
}                                          // → O(n²) total
```

**Required.** Decide the capture rule in this ADR (not the DSL ADR), because it fixes the closure representation, which the ADR itself lists under "Why decide now". Add the capture-then-mutate cliff to Consequences.

### 1.4 High: The G11 mitigation imports SwiftUI's machinery (G3, P-SWIFT)

The Counter example (`count = state(0)` inside a value view) hides three problems.

**(a) Positional state identity.** If a view is a value that is rebuilt on every render, `state(0)` must return the *same* slot on each rebuild. Frameworks do this by keying slots on position in the view tree. SwiftUI calls this "structural identity", and React's version comes with the "Rules of Hooks".

```text
// illustrative only
view Row {
    body = row {
        if showBadge { badge(state(0)) }  // slot keyed by position?
        counter(state(0))                 // when showBadge flips, does counter get badge's old slot?
    }
}
```

SwiftUI hides this behind the `@State` property wrapper. The ADR's P-SWIFT guard bans property wrappers but offers no replacement mechanism.

**(b) Heterogeneous children need generics or type erasure.** `column { text(…); button(…) }` is a list of different value types. SwiftUI makes that cheap with generic `TupleView<(Text, Button<…>)>` and `ModifiedContent<Content, Modifier>` built by result builders. Without user generics (G3), every child becomes a boxed existential, which brings heap boxes and dynamic dispatch and makes diffing harder. The MVS paper the ADR cites is explicit about exactly this: C#'s value types *interacting with interfaces* lead to "counter-intuitive situations" ([Racordon et al.](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf)). That is the boxing problem, and the ADR misquotes it as a copy-versus-alias point (see §3).

**(c) Stale handles are O2's index problem moved into the DSL.**

```text
// illustrative only
view Clock {
    t = state(0)
    onAppear = { timer.every(1s, { t.set(t.get() + 1) }) }   // escaping closure holds a handle
}
// After the view is unmounted, the slot is freed. The timer fires and t.set → "missing":
// silently ignored? trap? The timer itself is never cancelled (no owner).
```

The ADR counts "stale indices turn into logic bugs the compiler can't see" against O2, then accepts the same thing for O3's DSL.

**(d) Cycles return as soon as real apps leave the counter example.** View models that do network or disk I/O are identity objects: `vm → request → completion closure → vm`. That cycle lives outside the DSL, so the store design doesn't help.

**Required.** Change Q4(a). It should not be "do you accept views as values?". It should be "do you accept that the DSL ADR must solve positional state identity and heterogeneous children *without* property wrappers, result-builder attributes or user generics, and that if it can't, G3 or the memory model is reopened?" The tie-breaker judgement leans on G11 being solvable this way, so this is a dependency, not a deferral.

### 1.5 High: Values containing identity references break the ADR's own safety claims

O3's Safety row says *"Values can't form cycles or races."* That holds only if values never contain identity references or closures, and nothing in the Decision forbids either:

```text
// illustrative only
class Node  { meta: Meta = Meta() }
struct Meta { owner: Node? = nil; tags: List[String] = [] }
n = Node(); n.meta.owner = n        // cycle through a value. Decision 4's lint (closure stored into
                                    // the object it captures) never fires.

struct Doc { text: String; cache: Cache }   // Cache is an identity type
undo.push(doc)                       // the "snapshot" shares `cache`; undo does not restore it
spawn(move doc) { … }                // the value is "moved", but `cache` is still reachable from
                                     // thread 1 through other references → race on a non-sendable object
```

Other leaks of identity semantics that the Decision must define:
- **`==` and hashing** for values with identity fields (deep, by identity, or not allowed?).
- **What a default "read-only borrow" means for an identity-typed parameter.** `func show(n: Node) { n.count = 0 }` mutates through a read-only parameter.
- **What `inout` means for an identity-typed parameter** (rebind the reference, or nothing?).
- **Copying `List[Node]`** is O(1) at the buffer level, but a CoW copy later retains every node (O(n) RC traffic), and the copied list shares the nodes.

**Required.** Either (i) values containing identity references or closures are a recognised sub-kind that the compiler infers as not snapshot-safe and not sendable, with transitive inference stated, or (ii) they are restricted. Then correct the Safety and Consequences text ("Snapshots, undo and diffing are just copies", "Values cross threads without races").

### 1.6 High: Dynamic exclusivity traps are `RefCell` panics under another name (scoring inconsistency)

Consequences admits: *"An `inout` access to a field of an identity object can't be proven exclusive statically, so it needs a runtime check, as Swift's dynamic exclusivity enforcement does."* That runtime check traps:

```text
// illustrative only
class Model { items: List[Int] = [] }
func fill(xs: inout List[Int], m: Model) {
    xs.append(1)
    print(m.items.count)      // reads m.items while it is under exclusive (inout) access
}
fill(&model.items, model)     // runtime trap (Swift: "Simultaneous accesses … modification requires exclusive access")
```

This is the same failure class the ADR uses against O4 in its Safety row: *"needs a runtime check that can panic, as `RefCell` does"*. O3's Safety (4) and Simplicity (4) scores don't reflect it. The static half also produces compile errors in ordinary code: `swap(&x[i], &x[j])` is rejected (verified, [P2676R0](https://www.open-std.org/Jtc1/sc22/wg21/docs/papers/2022/p2676r0.pdf)). `items.appendAll(items)` is rejected too, unless the compiler silently copies the argument.

That undermines the third leg of the tie-breaker: *"O3 fails with a silent slowdown … O4 fails with a compile error."* O3 also fails with compile errors (exclusivity, mutating a `let`) and with runtime traps. The real difference from O4 is the absence of **use-after-move** errors, which is narrower than the ADR implies.

### 1.7 Medium-High: Move at last use is a semantic change, not just an optimisation

Decision 1: *"The compiler turns a copy into a move at last use, as an optimisation, never as a semantic rule."* Consequences: *"files, sockets and Windows `HANDLE`s close exactly once at scope end."* These contradict each other once identity objects have destructors or weak observers:

```text
// illustrative only
file = LogFile("out.txt")      // identity; closes in deinit
registry.watch(weak file)      // weak observer
doLongWork()                   // file's last use was line 2. If its lifetime ends there,
                               // it closes and the weak ref goes nil before doLongWork runs.
```

Swift hit this and introduced "lexical lifetimes" in 5.7. The current rules extend lifetimes of class references for weak/unowned access and external side effects, while CoW types are destroyed at last use, and this "does still trip people up sometimes" ([Swift Forums](https://forums.swift.org/t/what-is-the-current-status-of-lexical-lifetimes/76587/2)). Swift also needed `withExtendedLifetime`, which is a generic function.

**Required.** State the lifetime rule: lexical (scope-end) lifetimes for identity objects and anything with a destructor, last-use for plain CoW values. Count the rule in the concept inventory.

### 1.8 Medium: The cycle lint only catches the trivial case

Decision 4: *"The compiler flags an escaping closure that is stored into an identity object and captures that same object."* Real cycles are usually indirect, or go through library calls:

```text
// illustrative only
class Editor {
    toolbar = Toolbar()                       // identity; owns Buttons
    init() { toolbar.onSave({ save() }) }     // Toolbar.onSave stores the closure in a Button:
}                                             // Editor → Toolbar → Button → closure → Editor. No lint.
```

Catching this needs interprocedural escape and alias analysis across modules (and across third-party GitHub packages, G7). The general problem is undecidable. The lint is still worth having, but the ADR should say it catches only direct self-capture and that the debug exit report is the real safety net. The exit report also misses cycles in long-running processes that never exit cleanly (GUI apps, servers), so add an on-demand "live cycle report" API.

### 1.9 Medium: FFI is harder than "a natural retained context"

- **Ownership of `void*` context.** When C stores an identity object as `void* ctx`, someone must hold the +1. That needs explicit retain/release or an "unretained" pointer form. Swift's answer is `Unmanaged<T>`, a generic. Decision 3 says *"No `unowned` and no unsafe-unretained references"*. FFI needs exactly that, behind an `unsafe` boundary, and the ADR should say so.
- **Pinning buffers.** `c_start_stream(samples.pointer)`, followed by `samples.append(x)`, reallocates or CoW-copies, and C then writes freed memory. A scoped "borrow the buffer for the duration of this call" API is needed. Swift's is `withUnsafeBufferPointer`, which is closure-based and generic.
- **Foreign-thread callbacks.** Audio, networking and OS thread pools call back on threads the language didn't create. With non-atomic counts, any retain/release in such a callback races. The rule must be "C callbacks may touch only atomic-count or thread-confined state", and the compiler can't check that across the C boundary.
- **C-compatible value layout.** A value with a CoW field can't be passed as a C struct. That implies an inferred "C-layout-compatible" subset of value types.

O3's Tooling/FFI score of 4 (ahead of O1's FFI story) is generous.

### 1.10 Medium: Generics pressure. O3 quietly needs many built-in parameterised types (G3)

The ADR treats Q4 (built-in parameterised containers) as equal across options. For O3 the list is longer than `List`/`Map`/`Arena`/handle store:

| Needed by O3 | Why |
|---|---|
| `Optional[T]` | `weak` is "optional-typed" (Decision 3) |
| `List[weak T]` or `Weak[T]` | Observer lists are the canonical weak use. Without a weak element modifier or a generic wrapper, users write one wrapper struct per type. |
| `State[T]` / `Handle[T]` | The DSL store handle in the Counter example (`count.get()` returns `T`) |
| `Mutex[T]`, `Channel[T]` | Identity objects aren't sendable (Decision 6), so shared mutable state across threads needs typed built-ins |
| Function types `(A) -> B`, plus escaping and sendable variants | Decision 5 needs an "escaping" type form. §1.1 implies a sendable distinction too, since closures sent to `spawn` must not capture non-sendable identity objects. Inference fails once a closure is stored in a `List[() -> ()]` and its captures are erased. |
| Scoped buffer pointer and unretained reference for FFI | §1.9 |
| Generic algorithms on built-ins (`map`, `filter`, `sort`) | `map` is `List[T] → (T → U) → List[U]` |

Users also can't write their own CoW containers, such as a `Deque`, `PriorityQueue` or `OrderedMap` for G6 or third-party G7 libraries. That would need a generic buffer plus an "is uniquely referenced" intrinsic.

**Required.** Q4(b) should list the actual set above, so John rules on the real scope of "built-in parameterised", not a three-item version.

### 1.11 Medium: The complexity inventory and syntax budget are undercounted (G1, G4, P-SWIFT)

Concepts a user of O3 must learn, against Swift's core memory model:

| Concept | Swift | O3 as drafted |
|---|---|---|
| Value vs reference kinds | struct/class | yes |
| Mutating methods on values | `mutating` | **yes, but not in the budget** (needs a keyword or an `inout self` convention) |
| Immutable vs mutable bindings | `let`/`var` | **yes** (needed for the meaning of mutation; errors such as "cannot mutate a let") |
| `inout` + call-site `&` | yes | yes (0–1 operator) |
| Exclusivity (static errors + dynamic traps) | yes | yes |
| `weak` + optional unwrapping | yes | yes |
| Weak capture form | `[weak self]` capture list | **yes** ("a single weak-capture form", Decision 10), yet the Syntax budget says "Not added: capture lists" |
| Escaping vs non-escaping closures | `@escaping` | yes (type form) |
| Capture semantics (copy, strong, boxed?) | boxed vars | undecided (§1.3) |
| Sendability | `Sendable` | yes (inferred, but users still meet "not sendable" errors) |
| CoW cost model ("who else holds this?") | yes | yes |
| Lifetime end rule | lexical lifetimes | undecided (§1.7) |
| `unowned`, `consume`/`borrowing`, `~Copyable` | yes | excluded |

O3 keeps about 11 of Swift's ~14 core memory-model concepts and excludes mostly the *advanced* ones. The P-SWIFT guard in Decision 10 excludes *spellings* (attributes, wrappers, macros). It does not remove the *semantics* users must learn. "Swift's core model without Swift's surface area" is accurate, but P-SWIFT ("overly complicated, too many features") is largely about that core plus SwiftUI and concurrency. O3 then commits the DSL ADR to rebuild the SwiftUI part (§1.4).

**Required.** Fix the syntax-budget contradiction (weak capture form against "no capture lists"), add the mutating-method marker and `let`/`var`, and score O3 Simplicity **3** (the same as O4, which the ADR marks down for "aliasing-XOR-mutation errors and a second, RC-based world"; O3 has both).

### 1.12 Medium: Debug and release disagree about copies; debugging and coverage costs are understated (G8, G9)

- **The ADR's own Swift example depends on the optimisation level.** `let snapshot = data; normalize(&data)` copies only if `snapshot` is still live. Under Swift's rules, CoW values are destroyed at last use ([Swift Forums](https://forums.swift.org/t/what-is-the-current-status-of-lexical-lifetimes/76587/2)). So with `-O` and `snapshot` unused, no copy happens; with `-Onone` it does. A debug-build "large CoW copy" warning (Q6) will therefore report copies that release builds don't make, and a debug-build *error* (one of Q6's choices) would reject correct programs.
- **Debug builds can be asymptotically slower.** Without move-at-last-use, `data = transform(data)` copies on every call in debug builds (O(n) instead of O(1)). G8 depends on debug builds being usable on real data sets.
- **Debugger formatters on three platforms.** Debugger formatters are needed for LLDB (macOS), GDB (Linux) and Visual Studio/WinDbg (Windows; natvis plus CodeView/PDB, not DWARF). That is three formatter systems and two debug-info formats, all written by an agent. `inout` parameters appear as pointers. Values moved at last use show garbage in optimised builds. The iterative release worklist (Decision 7) loses the call stack that caused a free, which is exactly what you need when chasing a "who freed this" bug.
- **Coverage.** Uniqueness branches and implicit scope-end destructors must get artificial or line-0 locations. Otherwise LLVM source-based coverage shows branches the user can't cover.

### 1.13 Medium: The fallback to O1 is neither cheap nor well triggered

Consequences: *"If the stage-1 compiler shows CoW uniqueness or exclusivity checking to be harder than rated, O1 is the documented fallback … `List` becomes a reference type, which has to happen before any public release."*
- This contradicts the irreversibility argument, which says flipping `List` "silently changes the meaning of every program". By stage 1 that includes the agent-written stdlib and test suite.
- "Harder than rated" is not a measurable trigger. Give exit criteria, for example: stage-1 pass rate on the differential oracle (§2.3), zero known value-semantics violations, and copy counts on the canonical-pattern suite.
- O1 has the same §1.1 threading hole if it also uses non-atomic counts, so falling back doesn't remove that work.

### 1.14 Low: Smaller issues

- **Deferred freeing and the G2 definition (Decision 7).** A deferred-free queue drained on a timer or threshold arguably "reclaims memory … independently of program points". State that queues are drained only at program points (allocation, explicit yield).
- **Worklist release and destructor order.** Iterative release changes destruction order compared with recursion, and destructors can re-enter (touch objects queued for release). Define the order and forbid resurrection (Swift traps when `self` escapes `deinit`).
- **One-word header plus zeroing weak.** This forces a side table, as Swift has, with its own allocation and atomicity. Say so in the runtime section.

---

## 2. Implementation risk for an AI-built LLVM compiler

### 2.1 The hardest pieces of O3, ranked

| # | Piece | Why it's hard | Fails silently? |
|---|---|---|---|
| 1 | Synthesised copy/destroy/move for every aggregate: structs, enums with payloads, optionals, closure contexts, nested CoW and identity fields | This is Swift's "value witness" problem without generics. Each type needs correct retain/release of every RC'd field, including tag switches for enums and partially initialised values on error paths | **Yes**: leak or latent UAF that appears only after the allocator reuses memory |
| 2 | Uniqueness checks combined with +0 borrows and move-at-last-use | A borrowed parameter that doesn't bump the count makes a shared buffer look unique, so in-place mutation becomes visible through another variable | **Yes**: wrong results, no crash. This is the worst class |
| 3 | In-place projections for subscripts and fields (§1.2) | Coroutine-like lowering (Swift `_modify`), interaction with dynamic exclusivity | Perf: **yes** (silent O(n²)). Correctness: sometimes |
| 4 | Static exclusivity checker, including closures that capture variables under `inout` | False negatives give aliasing bugs; false positives give G1 pain | False negatives: **yes** |
| 5 | Dynamic exclusivity runtime (access sets, thread-local) | Must cover identity fields, globals and captured boxes; cost on every access | Missed check: **yes** |
| 6 | Escape analysis for closures (stack vs heap context) | A stack context that actually escapes is a UAF | **Yes** |
| 7 | Atomic vs non-atomic RC split and send rules (§1.1) | Wrong inference gives data races on counts | **Yes**: intermittent, platform-dependent. TSan exists only on Linux/macOS |
| 8 | Weak references (side table, zeroing, deinit resurrection) | Ordering of zeroing against destruction | Partly |
| 9 | RC optimisation passes (pair elimination, move-at-last-use) | The classic source of subtle miscompiles. LLVM's ObjC ARC optimiser is the cautionary precedent | **Yes** |
| 10 | Cleanup on every exit path (early return, error propagation, unwinding) | Every scope exit needs releases | Leak: **yes** |
| 11 | Debug info (DWARF + CodeView) and coverage mapping for synthesised code | Two formats, three debuggers | Mostly yes (wrong display, phantom gaps) |

Pieces 1, 2, 3 and 7 are absent or understated in the ADR's O3 implementation-risk row (*"The work beyond O1 (exclusivity checks, CoW uniqueness) is rated moderate and easy respectively"*). The ADR also reports that its own notes rank "MVS + CoW" third for tractability, behind plain RC and Inko-style owned values. **O3 implementation risk should be 3, not 4.**

The ADR's mitigation ("the baseline … is always correct, and optimisations can be switched off for differential testing") is sound for pieces 9 and part of 2. It does nothing for 1, 4, 5, 6 and 7, which are part of the baseline.

### 2.2 What fails silently, and why that matters here

The charter's AI-written compiler means bugs will be found by tests, not by reviewers who know the codebase. O3's characteristic failure is **an aliasing violation that produces wrong output without crashing**: `snapshot` changes after `data` is mutated. Sanitizers don't detect it, because no invalid memory access occurs. Only a semantic oracle catches it. That is a test-infrastructure requirement O1 doesn't have to the same degree, because under O1 aliasing is the specified behaviour.

### 2.3 Tests O3 needs (add to Consequences as stage-1 entry criteria)

1. **Semantic oracle.** A small reference interpreter that implements value semantics by *eager deep copy*: no CoW, no RC, no moves. Every test program runs on both, and output must match. This is the only reliable detector for failure class 2.
2. **Differential builds.** `-O0` vs `-O2` vs each RC/CoW optimisation switched off individually, all on the full corpus.
3. **Random program generation** (Csmith/YARPGen-style) biased toward aliasing patterns: copy-then-mutate, `inout` of nested paths, closures capturing then mutating, values holding identity references, early returns inside loops, enums with RC payloads.
4. **A debug runtime on all three OSes.** Header magic checked on every RC operation, freed memory poisoned, a live-object registry with allocation stacks, and zero live objects asserted at the end of every unit test (G10). This fills most of the sanitizer gap regardless of LSan status (§3).
5. **Copy-count golden tests.** A runtime counter of CoW buffer copies, with exact expected counts for canonical patterns in both debug and release (append loop: 0; `map[k].append`: 0; `obj.field.append`: 0; capture-then-mutate: 1; send of a nested list: as specified).
6. **Compile-fail and compile-pass corpora** for exclusivity, escaping, sendability and mutation of `let`s. The pass corpus guards G1 against false positives.
7. **Mutation testing of the compiler itself.** Seed bugs (drop a retain, drop a uniqueness check, swap atomic for non-atomic) and require the suite to catch each one. This is the direct measure of whether silent failures would be noticed, and it matters most for an agent-written compiler.
8. **Threading:** TSan runs on Linux and macOS for every concurrency test, plus a stress test of the §1.1 scenario.
9. **Cycle-lint corpus** with known direct and indirect cycles, publishing the false-negative rate.
10. **Scripted debugger tests:** LLDB on macOS and Linux, GDB on Linux, CDB on Windows, checking the display of CoW values, identity objects, `inout` parameters and closures.
11. **Coverage golden files** (llvm-cov) for programs dominated by synthesised code.
12. **Stress:** release of a 10M-node chain (no stack overflow), weak zeroing during destructor re-entry, and large-graph release latency.

### 2.4 Re-scoring

| Change | Reason | O3 raw | O3 total |
|---|---|---|---|
| ADR base | — | 390 | 78 |
| Simplicity 4→3 | §1.6, §1.11: exclusivity errors and traps, mutating marker, capture rules, lifetime rule; parity with O4's 3 | 365 | 73 |
| Implementation risk 4→3 | §2.1: pieces 1, 2, 3, 7 missing; the ADR's own notes rank it third | 350 | **70** |

O1 stays at 77 and O4 at 76. I did not red-team O1 and O4 to the same depth. O1's and O4's non-atomic-RC threading stories have the same §1.1 exposure, and O4's Tooling 5 may be generous. Even so, O3 does not regain the lead on the rubric.

---

## 3. Fact-check of load-bearing claims

| # | Claim in ADR | Result | Source and notes |
|---|---|---|---|
| 1 | Swift spent about 32% of execution time on RC (BRC, 2018) | **Verified** | ["causes Swift programs to spend 32% of their execution time performing RC operations"](https://docs.rs/crate/biasedrc/latest/source/paper.pdf). This is the average across programs (42% for client programs), on 2018-era Swift |
| 2 | An atomic increment costs 2.4× a plain one | **Verified** | ["slows down the operation by 2.40x"](https://docs.rs/crate/biasedrc/latest/source/paper.pdf) (13.84 ns vs 5.77 ns per increment, microbenchmark) |
| 3 | About 16% of objects in Java benchmarks are cyclic garbage | **Verified (inferred)** | Table 7 caption: "on average 84% of objects can be collected by reference counting without a cycle collector" ([Shahriyar et al.](https://core.ac.uk/download/156633347.pdf)). Highly skewed: hsqldb 73%, eclipse 53%, six benchmarks under 1%. The average hides the risk |
| 4 | Lobster inference removes about 95% of RC ops, on the author's own programs | **Verified** | ["remove around 95% of runtime reference count operations"](https://aardappel.github.io/lobster/memory_management.html). No benchmark set is named, and the ADR's caveat is correct |
| 5 | Nim authors: ORC "can be considered a full-blown GC"; ARC "fully deterministic"; ARC FFI needs no foreign-thread registration | **Verified** | All three are in the [ARC/ORC intro](https://nim-lang.org/blog/2020/10/15/introduction-to-arc-orc-in-nim.html). "Full-blown GC" is not in the ORC post, but the ADR cites both posts. "Generational and incremental GC", "can be measurable in practice" and "can be crucial" are in the [ORC post](https://nim-lang.org/blog/2020/12/08/introducing-orc.html) |
| 6 | "Swift … introduced Sendable in 5.7, reached full isolation only in 5.10" | **Partly wrong** | swift.org's 5.10 post does say "Swift 5.7 introduced `Sendable`…" ([Swift 5.10](https://www.swift.org/blog/swift-5.10-released)), but `Sendable` (SE-0302) shipped in **Swift 5.5** ([HWS](https://hackingwithswift.com/swift/5.5/sendable)). Full isolation in 5.10 is verified. Reword as "introduced in 5.5, made the basis of checking in 5.7" |
| 7 | Swift 6.2 MainActor-by-default is a "dialect" | **Verified (attribution)** | Massicotte: "This is known as a 'language dialect'" ([massicotte.org](https://www.massicotte.org/default-isolation-swift-6_2)). This is a blogger's characterisation, not Apple's |
| 8 | SE-0365 (implicit `self` after `[weak self]` unwrap) is Swift 5.8 | **Verified** | ["Available from Swift 5.8"](https://www.hackingwithswift.com/swift/5.8/implicit-self-weak-capture) |
| 9 | Polonius reached nightly in August 2026 after about a decade | **Verified** | [Rust blog, 2026-08-04](https://blog.rust-lang.org/2026/08/04/enabling-polonius-alpha-on-nightly) |
| 10 | Vale's successor (2026-09-17) has generational references "temporarily disabled" | **Verified** | Post dated September 17, 2026. Side note: "Generational references are temporarily disabled, hopefully coming back soon." The successor is Valen, with group borrowing ([verdagon.dev](https://verdagon.dev/blog/golden-spike-reviving-vale-valen)) |
| 11 | Hylo was targeting compiler 1.0 in Q4 2026 | **Verified** | 2026-06-22: "release a 1.0 of the compiler by Q4 of this year" ([Hylo #1905](https://github.com/orgs/hylo-lang/discussions/1905)) |
| 12 | Bronze trial: lifetimes were 204 of 1,143 coded comments, inside 340 about references | **Verified** | "We received 1,143 comments … 340 pertained to references, of which 204 were about lifetimes" ([Coblenz et al.](https://arxiv.org/pdf/2110.01098)) |
| 13 | 59% found Rust harder to learn | **Verified, with a caveat** | "Most participants found Rust more difficult to learn than other languages (I = 7, S = 59%)" ([Fulton et al.](https://par.nsf.gov//servlets/purl/10357735)). The population is 178 self-selected Rust-community survey respondents. Say so |
| 14 | A third of Google developers were productive within two months | **Verified** | "a third of respondents become as productive using Rust as other languages in two months or less" ([Google OSS blog](https://opensource.googleblog.com/2023/06/rust-fact-vs-fiction-5-insights-from-googles-rust-journey-2022.html)) |
| 15 | Generational references +10.84% vs unsafe; naive RC +25.29%; one benchmark | **Verified** | BenchmarkRL terrain generator ([GR v1](https://verdagon.dev/blog/generational-references-v1)) |
| 16 | Cyclone: "region annotations were about 6% of ported code" | **Wrong** | About **8%** of code changed when porting, and "only 6% (of the 8%) were region annotations", so about 0.5% of code ([Grossman et al.](https://www.cs.umd.edu/~mwh/papers/GrossmanMJHWC02.html)). The rejection may still stand on G3, but the number overstates the annotation burden about twelvefold |
| 17 | "macOS lacks LeakSanitizer and MemorySanitizer, and Windows has essentially ASan only" | **Partly wrong** | CLion's page lists only ASan, TSan and UBSan for macOS, ASan (clang-cl) for Windows, and MSan as Linux-only ([JetBrains](https://www.jetbrains.com/help/clion/google-sanitizers.html)). But **upstream LLVM lists macOS as a supported LSan platform** ([LLVM LeakSanitizer.rst](https://llvm.googlesource.com/llvm-project/+/refs/heads/main/clang/docs/LeakSanitizer.rst)). It is Apple's Xcode clang that doesn't ship it. This project targets LLVM directly, so LSan on macOS is a toolchain-packaging question. The debug-runtime argument survives but is weaker |
| 18 | Atomic RC slowdowns of 5–59% in Koka | **Verified** | "a slowdown from 5% (rbtree) up to 59% (nqueens)" ([Perceus TR](https://microsoft.com/en-us/research/uploads/prod/2020/11/perceus-tr-v4.pdf)). The same paper's `tshare` is *recursive*, which supports §1.1 |
| 19 | Large-graph release spikes of about 10 µs | **Verified** | "unmodified Koka can occasionally get latency spikes of around 10 µs or higher" ([Lam & Parreaux](https://lptk.github.io/files/ctrc-2024-05-09.pdf)) |
| 20 | Discord's Rust "had no latency spikes" compared with Go 1.9 | **Verified** | Go 1.9.2 ([Discord](https://discord.com/blog/why-discord-is-switching-from-go-to-rust)) |
| 21 | C# value types give "counter-intuitive results" (as evidence for the `a = b` copy/alias pitfall) | **Wrong as quoted** | The paper says the interaction of C# value types *with interfaces* is "sometimes leading to counter-intuitive situations" ([Racordon et al.](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf)). The issue is boxing, not assignment. Fix the quote. The correct reading is more damaging to O3's DSL plan (§1.4b) |
| 22 | Swiftlet "significantly slower than Swift"; Swift slower than C++ only above 90% mutating operations | **Verified** | Both are in the same paper. The cause given is a "key missing optimization", reference-counter (uniqueness) checks |
| 23 | P2676R0: "memory safety by construction"; `swap(&a[i], &a[j])` rejected | **Verified** | The paper's example uses `x`, not `a` ([P2676R0](https://www.open-std.org/Jtc1/sc22/wg21/docs/papers/2022/p2676r0.pdf)) |
| 24 | SR-13888: Swift shipped spurious CoW copies | **Not verifiable** | bugs.swift.org redirects to GitHub issue swiftlang/swift#56286, which this session couldn't open. The claim is plausible, but the ADR should quote the issue's title |

Summary: 19 verified (some with caveats), 3 wrong or partly wrong on substance (#16 Cyclone, #17 LSan, #21 C# misquote), 1 partly wrong on version (#6 Sendable), 1 not verifiable (#24).

---

## 4. Code-example audit

The Rust snippets were compiled with rustc 1.97.0 in a scratch harness (`/tmp/rtcheck`). Swift, Nim, Zig and Hylo compilers are not installed here, so those were checked by reading.

| Example (ADR section) | Labelled? | Correct as claimed? | Notes |
|---|---|---|---|
| Swift `Cache`/`Loader`/`Renderer` (O1 pro) | "Swift (from research notes)" | Yes | Needs `import Foundation` for `Data`. Trivial |
| Swift `EditorController` with `[weak self]` (O1 con) | Swift | Yes | `guard let self else` is SE-0345 (5.7). Implicit `self` afterwards is SE-0365 (5.8). The commented strong version compiles and leaks. `Button` is undefined (fine for an excerpt) |
| Our-language O1/O3 `Editor` leak, O1 alias, O4 move, O3 `Counter` | "illustrative only" | Labelled correctly | The `Counter` example is semantically underspecified (§1.4a): `state(0)` in a rebuilt value view needs positional identity |
| Hylo `normalize`/`parallel_sum`, message loop, `Node` | "planned API / pseudo-Hylo, illustrative" | Labelled correctly | — |
| Swift `lines.append` / `normalize(_ xs: inout [Double]) { ... }` (O3 pro) | "Swift (from research notes)" | Mostly | `{ ... }` is not valid Swift. Label it as an excerpt |
| Swift `let snapshot = data; normalize(&data) // HIDDEN full copy` (O3 con) | Swift | **Only conditionally** | The copy happens only if `snapshot` is live after the call, or at `-Onone`. CoW types are destroyed at last use under Swift's rules. The copy also happens at the first write inside `normalize`, not at the call. Add "…and `snapshot` is used afterwards" |
| Rust `normalise(&mut big)` (O4) | "Rust (verified)" | Compiles once wrapped in `fn main` with `let mut big = vec![…]`; output `[0.25, 0.5, 1.0]` | It is a fragment, not compilable as shown. Label "verified (excerpt)" |
| Rust `thread::scope` + `split_at_mut` (O5) | "Rust (verified)" | Compiles once wrapped; output `[10, 20, 300, 400]` | Fragment. `move \|\| for … {}` is valid |
| Rust `Rc<RefCell<Document>>` button (O5) | "Rust (verified)" | Compiles and runs once wrapped | The claimed E0502 (naive version, printing `doc.saved` while the closure holds `&mut doc`) and E0597 (`Box<dyn FnMut()>` defaulting to `'static`) **both reproduce** exactly |
| Vale `Node` / `onTap` (O6) | "approximate syntax" | Labelled correctly | — |
| Nim `Editor` / `onTap` (O7 pro) | "Nim (from research notes)" | Semantics right (an ARC cycle that ORC collects) | Won't compile as shown: `save` is undeclared, and Nim needs it declared before use. Ironically, `{.closure.}` is itself a pragma (an annotation), and it is redundant here because procedural types default to closure |
| Nim `{.acyclic.}` (O7 con) | Nim | Yes | — |
| Zig `DebugAllocator` / `ArenaAllocator` (O8 pro) | "approx. 0.15 API" | Plausible for 0.14/0.15 | `readLines` is hypothetical |
| Zig `Button` / `onSave` (O8 con) | Zig | **Inconsistent** | `onSave` is shown at top level but referenced as `Editor.onSave`, so it must be declared inside `Editor`. Otherwise the point is right |
| Zig `first = &list.items[0]; append; first.* = 1.0` (O8 con) | Zig | Yes | This is the 0.15 unmanaged `ArrayList` API, and it is unchecked in ReleaseSafe |

All our-language pseudo-syntax is correctly labelled "illustrative only". Every real-language block is labelled with its language. The "verified" label should say "excerpt", because none of the three verified Rust blocks compiles standalone.

---

## 5. Conclusion

### 5.1 Is O3 still defensible?

**Yes, but only as a judgement, and only with amendments.** On the ADR's rubric with corrected scores, O3 is third (about 70, against O1 77 and O4 76). Two of the three tie-breaker legs survive in weakened form:
- **Irreversibility (lists as values): survives.** It is the strongest argument, and it rules out O1, not O4.
- **Staging close to O1's runtime: weakened.** Synthesised aggregate copy/destroy, projections and the send rules are stage-1 necessities, not later optimisations.
- **"Slowdown, not compile error": weakened.** O3 also has exclusivity compile errors and runtime traps (§1.6). What separates it from O4 is only the absence of use-after-move errors.

If John's priority is G1 for everyday data code, with no move errors, O3 remains a reasonable choice. If his priority is getting a correct agent-built compiler fast, the corrected scores favour **O1**. Under equal weights they favour **O4**. The ADR should present this as a real choice (Q5) and not as "Adopt O3".

### 5.2 Mandatory amendments if O3 is kept

Add to **Decision**:
1. **Threading soundness (§1.1).** Replace Q3(A). CoW buffers and any sendable identity type use atomic counts (or a recursive share flag); only non-sendable identity objects use non-atomic counts. State the transitive rule for values that contain identity references or closures.
2. **Projections (§1.2).** In-place mutable projections for built-in subscripts and stored fields are part of the stage-1 baseline.
3. **Capture semantics (§1.3).** Choose immutable captured values, private copies, or boxed variables, and state the consequences.
4. **Lifetime rule (§1.7).** Lexical lifetimes for identity objects and destructor-bearing values; last-use only for plain CoW values.
5. **Identity inside values (§1.5).** Define `==`, hashing, snapshot behaviour and sendability of values containing identity references, and what read-only and `inout` parameters mean for identity types.
6. **FFI (§1.9).** An `unsafe` boundary with unretained/retain intrinsics and scoped buffer pinning. Rule out RC operations from foreign-thread callbacks unless counts are atomic.

Add to **Consequences** and **Scores**:

7. Score O3 Simplicity 3 and Implementation risk 3, or rebut §1.6, §1.11 and §2.1 explicitly. Make O4's `RefCell` penalty and O3's dynamic-exclusivity penalty consistent.
8. List the CoW cliffs: nested and field mutation, capture-then-mutate O(n²), debug/release divergence, and debug-build asymptotic slowdown. Change Q6 so the "large copy" diagnostic is reported from a release-mode profiler, not as a debug-build error.
9. Make the §2.3 test infrastructure (deep-copy oracle, copy-count goldens, compiler mutation testing, debug runtime on all three OSes) an explicit stage-1 entry criterion, and give the O1 fallback measurable triggers and a deadline before the stdlib is written.
10. **Open questions.** Rewrite Q4(a) as the real DSL dependency (§1.4: positional state identity and heterogeneous children without wrappers, result builders or user generics). Rewrite Q4(b) with the full built-in parameterised list (§1.10). Fix the syntax-budget contradiction about capture lists and add the mutating-method marker and `let`/`var` (§1.11).

Also fix the factual items in §3: Cyclone (#16), LSan on macOS (#17), the C# misquote (#21), and the `Sendable` version (#6). Fix the conditional Swift snapshot comment and the "verified" excerpt labels in §4.

### 5.3 If the amendments can't be met

If amendment 1 or 2 can't be done in stage 1, or the DSL dependency in amendment 10 has no G3-compatible answer, O3 should give way to **O1**, adopted before any stdlib is written. O1 still needs amendments 1 (atomic counts for anything shared), 6 and 9. O4 is the alternative if John accepts use-after-move errors in exchange for the most predictable performance.
