# ADR-0001: Memory management model

- **Status:** Accepted
- **Date:** 2026-11-13
- **Tier:** Full (see `docs/PROCESS.md`)
- **Examples:** `docs/examples/chatsim` (also `docs/examples/widgets`)
- **Decided by:** Claude (ruling R7). John may veto by opening an issue.

## Context

The memory model fixes what `=` means, how values are passed, what closures capture, how threads share data, the C ABI
and the object header. Generics (D2), concurrency (D3), errors (D4), OO (D5) and the DSL (D7) all build on it. It is the
hardest decision to reverse. The history is in `0001-research/adr-0001-history-to-2026-11-13.md`: three adversarial
reviews, two 20-idea brainstorms, and the O1/O4 near-tie.

## Charter

| Goal / problem | Effect | Why |
|---|---|---|
| G1 (as clarified in R6) | serves | Six rules. Every free, copy and lookup failure is visible in the source. Mistakes are compile errors or traps, except a forgotten `remove`. |
| G2 (R2, R3) | serves | Nothing is counted or traced. Freeing is scope end or an explicit `remove`, proportional to what is freed. |
| G3 | neutral, depends on D2 | `Pool of T`, `Handle of T`, `List of T` are built-in parameterised types. Whether that counts as "templated types" is P2, decided in D2. |
| G4 | strains | `.copy()` appears (7 times in the 280-line widgets program), plus `if x = pool.get(h)` blocks. |
| G5, G7 | neutral | |
| G6 | serves | Containers are plain owned values. |
| G8, G9, G10 | serves | Debug builds report live pool entries at exit; tests can call `pool.expect_empty()`. No inserted RC code to attribute for coverage. |
| G11 | strains | UI callbacks capture handles, and cross-pool cleanup is written in `drop`. widgets shows it works, at a cost. |
| P-C | avoids | Use-after-free, double free and dangling access are compile errors or traps. |
| P-RUST | risks | Moves and use-after-move errors return, but without lifetimes or borrow annotations. Borrows last one call. |
| P-SWIFT | avoids | No `weak`, `unowned`, capture lists or Sendable attributes. |
| P-GO, P-JAVA | avoids | No collector. |
| P-PY | risks | Handles must be looked up through their pool, so a relational method reads `users.follow(a, b)`, not `a.follow(b)`. |

**Why the strains are acceptable.** G4 and G11 are strained by every eligible option: O1 needs `weak` and capture
choices, and O4 needs `shared`, `Rc` and snapshots. The P-RUST risk is the easier half of Rust: no lifetimes, no
stored references and no borrow syntax. No goal is broken.

## Criteria

From `0001-research/rubric-v2.md`, written before the port results came back. Weights were set by Claude under R7,
which closes Q5.

| Criterion | Weight | Anchor |
|---|---|---|
| Run-time transparency (no hidden work; aliasing, copies, frees and skipped callbacks visible) | 20 | R6, G1 |
| Simplicity (memory rules to remember; mistakes loud) | 20 | R6, G1, G4, P-RUST, P-SWIFT |
| Safety (no use-after-free, double free or dangling access outside `unsafe`) | 15 | R6, P-C |
| Concurrency (cross-thread data safe by construction) | 15 | R1 |
| Expressiveness (chatsim and widgets shapes written directly) | 10 | G11, P-PY |
| Implementation risk (5 = low) | 10 | project constraint |
| Performance | 5 | P-PY, P-GO, P-JAVA |
| Tooling and C FFI | 5 | G8, G9 |

**P3 is decided: memory safety is required.** R6 asks for "more helpful and safe than C".

## Options considered

The full field (O1–O9) was scored in the history file. Options ruled out before this round:
- **O5** (Rust lifetimes) fails G3.
- **O7** (ARC plus a cycle collector) fails G2 under R3.
- **O8** (manual memory) fails P3.
- **O2** (strict value semantics) and **O3** (values plus CoW plus RC) trailed on expressiveness and implementation risk.
- **O6** (Inko-style checked borrows) panics when an owner dies with borrows outstanding.

The three finalists, each written as real code:

1. **O1, pure ARC** (Swift): every object is reference-counted, and cycles are broken with `weak`.
   - Pros: the shortest program (292 lines), and familiar.
   - Cons: strong or weak is chosen by hand per field, and a wrong choice leaks silently. ARC protects lifetime, not
     data: Swift 6 could only be satisfied with `@unchecked Sendable` and `nonisolated(unsafe)`. Atomic retain/release
     happens on nearly every line.
2. **O4, ownership plus a `shared` RC kind** (Rust):
   - Pros: the compiler's thread check is the best of the three.
   - Cons: chatsim needed both models at once (owned values *and* `Rc`/`RefCell`/`Weak`), plus names-as-references
     to dodge a cycle. Re-entrancy hit E0502 and was fixed with a hidden per-message snapshot. It was the longest
     program (469 lines).
3. **O9, owned values plus generation-checked handles into pools** (C model):
   - Pros: no counts, no cycles, and nothing runs at free time beyond the freeing itself.
   - Cons: the adversarial review (`0001-research/review-o9.md`) found a fatal hole and five serious ones. They
     led to **O9-S**, below.

**Combination considered:** O9 with an optional `shared` RC kind (that is, O4). Rejected for now: it brings back a
second model, cycles and hidden work, which is the R6 cost. Adding it later wouldn't break existing programs, so it
stays available.

## What the real examples taught

`0001-research/chatsim-lessons.md` has the full table. All versions produce byte-identical output in CI on
Linux, Windows and macOS (Swift is skipped on Windows).
- `docs/examples/chatsim/c/`: reference version, 359 lines, three hand-written "null every pointer" walks.
- `o1-swift/`: the naive strong capture leaked silently (LeakSanitizer: 1012 bytes); only alive counters showed it.
- `o4-rust/`: `Rc<User>` was forced by callbacks; rooms were referred to by name to avoid a cycle; and there was the
  re-entrancy snapshot.
- `o9-c/`: no cleanup walks, no cycles. About 12 stale-handle branches, many unreachable. A forgotten `remove` gives a
  zombie, not a crash.
- `docs/examples/widgets/o9s-c/`: the O9-S model on a UI-shaped program (tree, a callback closing its own window, an
  observer unsubscribing itself, a shared cache).
  - 3 deferred drops and 2 adds during a borrow ran correctly.
  - `traps.c` shows a double mutable borrow, a wrong-pool handle, a stale `pool[h]` and a zombie at `expect_empty` all
    trapping.
  - It also found eight gaps in the rules, all decided below.

## Decision

**Adopt O9-S: owned values, moves, call-length borrows, exclusivity, and checked handles into pools.**

### Rules a programmer learns (six)

1. **One owner.** Every value has one owner and is freed when the owner's scope ends, or when it is overwritten or
   removed.
2. **`=` moves.** Assigning or passing a non-trivial value into storage moves it. Using a moved-from variable is a compile
   error, from a check local to the function. Copies are explicit: `x.copy()` (closes Q14). Numbers, booleans,
   enums and handles copy implicitly. The error message suggests `.copy()` and states its cost.
3. **Borrows last one call.** Parameters are borrowed for the call. A borrow can't be stored, returned, or captured by a
   closure that outlives the call. Getters return copies or handles.
4. **Exclusivity.** While a place is being written, nothing else may access it.
   - The compiler checks named paths in one function, including overlapping arguments (`append_all(a, a)` is an error)
     and mutating a list while iterating it.
   - List elements and pool entries are checked at run time. Shared borrows may coexist, but a write while another
     borrow is live traps, in debug and release builds.
5. **Identity lives in pools.** `Pool of T` holds entries; `Handle of T` (index, generation, pool id) names one.
   - `if w = pool.get(h) { … } else { … }`: a stale handle takes `else`. `pool[h]` and `with w = pool[h] { … }` trap on
     a stale handle.
   - The borrow is shared unless the block writes through `w`; the compiler infers which.
   - `add` never moves existing entries (segmented storage). `add(v, owner = h)` makes `h` own the new entry.
   - `remove(h)` stales `h` and its owned subtree at once. Drops run when the last borrow in the subtree ends: the
     owner's `drop` first, then owned entries in creation order, by a work list.
   - Using a handle on the wrong pool traps. A slot whose generation would wrap is retired.
   - `pool.handles()` returns a new list, a visible copy.
6. **Threads share nothing implicitly.**
   - Owned values move into threads and channels.
   - Shared mutable data is a `Mutex of T`, reached only inside `lock m { … }`. A thread re-locking a mutex it already
     holds traps.
   - Module-level variables, pools included, are main-thread state. The compiler infers over the call graph that
     spawned code never reaches them; there is no annotation. D3 details this.

**Closures (Q11):** closures capture by move or by copy, and handles copy. A callback whose target is gone takes an
explicit `else`. Nothing is skipped silently.

**Debug and test tools (R4: they reclaim nothing and never ship in release builds):**
- an exit report of live pool entries;
- `pool.expect_empty()`;
- poisoning of freed slots;
- a lock-order checker.

### Scores (`0001-research/adr0001_scores_v2.py`)

Cells are after the review's corrections:

| Option | Transp | Simp | Safety | Conc | Expr | Impl | Perf | Tool | Total |
|---|---|---|---|---|---|---|---|---|---|
| O9-S | 4 | 3 | 5 | 4 | 3 | 3 | 4 | 4 | **75.0** |
| O4 | 3 | 2 | 5 | 5 | 3 | 2 | 3 | 5 | 68.0 |
| O1 | 2 | 3 | 3 | 2 | 5 | 4 | 3 | 4 | 60.0 |

- **How solid the lead is:** O9-S leads at base weights by 7 and with equal weights by 5. Raising Concurrency or
  Tooling by 10 narrows it to 4.5, which is a tie under PROCESS.
- **Tie-break by the examples, as PROCESS requires:** O9-S had no hidden work and no possible cycle, and it was the
  only port with a single model. O4 needed two models at once in a 300-line program.
- **Reversibility:** adding a `shared` kind later moves toward O4 without breaking programs. O1 could never take
  reference semantics back.

### Questions closed

| Question | Answer |
|---|---|
| P3 | Memory safety required. |
| Q5 | Weights as above. |
| Q11 | Handles plus explicit `else`. |
| Q14 | Explicit `.copy()`. |
| Q7 (atomic RC) | Gone: nothing is counted. |
| P1/P1b | Closed by R2 and R3. |
| P2, built-in parameterised types under G3 | Passed to D2. |
| Q15, G11 scope | Passed to D7. |

## Consequences

**Easier:**
- Reasoning about the running program: no destructor runs because of a stray copy elsewhere.
- Threads: no count needs to be atomic, and there's no sendability inference over the whole graph.
- C interop: plain structs and integer handles.
- Coverage: no compiler-inserted RC code to attribute.

**Harder:**
- Identity-heavy code (trees, UIs, graphs) is written as pools plus handles, which feels less like classic OO.
- Cross-pool cleanup goes in `drop` by hand.
- A forgotten `remove` of a root entry is a zombie. It can be found only with `expect_empty` or the exit report.
- Shared caches keep hand-written use counts.

**Compiler work:**
- A function-local move checker and exclusivity checker, both soundness-critical but local.
- Per-entry borrow flags.
- Segmented pools.
- A call-graph check for main-thread state.

**Ruled out:**
- `weak` and RC as the default, and cycle collection.
- References stored in structs.
- Lifetime syntax.

**Passed to later ADRs:**
- D2: how `Pool of T`, `List of T` and `Handle of T` exist under G3.
- D3: channels, `Mutex of T`, the main-thread rule.
- D4: optional handles (`none`) and whether a trap is an error value.
- D5: methods on pool entries (implicit `self` is the borrowed entry).
- D7: UI callbacks and the widgets pattern.
- M4: the conformance tests take `traps.c`'s cases.

## Syntax budget impact

Not "None". The spellings are D6's job.

| Item | Count |
|---|---|
| Keywords | `drop` (type cleanup), `lock`, `with` (trapping borrow block) |
| Operators | 0 (`pool[h]` is indexing) |
| Grammar | `if x = expr { } else { }` binding form (shared with D4's optionals) |
| Library, not syntax | `.copy()`, `Pool of T`, `Handle of T`, `Mutex of T`, `expect_empty` |

Rules to remember: 6 (O1 had 5 with silent failures; O4 had 9).

## Adversarial review log

| Finding (`review-o9.md`, widgets `NOTES.md`) | Verdict | Change |
|---|---|---|
| F1 mutable aliasing outside pools (fatal) | Accepted | Rule 4, exclusivity |
| F2 pool lock traps in dispatch | Accepted | Segmented pools and deferred drop |
| F3 manual cascades | Accepted | `add(v, owner = h)` |
| F4 zombie is not milder than a leak | Accepted | Debug report and `expect_empty`; costs listed |
| F5 where pools live | Accepted | Main-thread module state; D3 details |
| F6 wrong object through a handle | Accepted | Pool id, typed handles, retire on wrap |
| F7 move errors (P-RUST) | Partly | Explicit copy kept for transparency; error hint required |
| F8 lock re-entry | Accepted | Trap, and a debug lock-order checker |
| F9 stale-branch noise | Accepted | `pool[h]` and `with` |
| F10 no returned borrows | Accepted as a cost | Stated |
| widgets: one flag is too coarse | Accepted | Shared and mutable borrows, inferred |
| widgets: replacing a running closure | Accepted | Writes through `pool[h]` are checked |
| widgets: owner removed while borrowed, drop order, `none`, pool iteration | Accepted | Rules 5 and D4 |
