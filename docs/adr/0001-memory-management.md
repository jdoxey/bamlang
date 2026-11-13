# ADR-0001: Memory management model

- **Status:** Accepted
- **Date:** 2026-11-13
- **Tier:** Full (history and 20+ idea analyses in `0001-research/`; the previous 742-line draft is `0001-research/draft-v1-full-history.md`)
- **Decided by:** Claude (ruling R7). John may veto by opening an issue.

## Context

The memory model fixes what `=` means, how parameters pass, what a closure captures, the object header, the C ABI and the cost of every free. Generics (D2), concurrency (D3), errors (D4), types (D5), the DSL (D7) and the stdlib all sit on it. Rulings that bind it: R1 threads in v1; R2/R3 reference counting is allowed but any work that inspects live objects is a GC; R4 debug-only tracing allowed; R6 "simple rules which make it easy to reason about how the program is working while it is running"; R9 three OSes.

## Charter

| Goal / problem | Effect | Why |
|---|---|---|
| G1 / R6 | serves | Three rules. No counts, no `weak`, no hidden work at free time. |
| G2 | serves | Frees happen at scope end or explicit `remove`. Nothing is counted or traced. |
| G3 | neutral | Needs built-in `List of T`, `Map of K,V`, `Pool of T`, `Handle of T` (decided in D2). No user templates. |
| G4 | strains | Adds `move`/`.copy()` and a `pool`/`handle` vocabulary. See Syntax budget. |
| G8, G10 | serves | Pools give a leak report (live entries at exit) with no tracing. Tests assert pool sizes. |
| G9 | neutral | No compiler-inserted RC code to attribute. |
| G11 | strains | A callback holds a handle, not the owner; the "gone" branch is written out. |
| P-C | avoids | Stale handles trap; no dangling pointers outside `unsafe`. |
| P-RUST | risks | Moves and use-after-move errors exist. No lifetimes, no stored borrows. |
| P-SWIFT | avoids | No ARC, `weak`, `unowned`, capture lists. |
| P-GO, P-JAVA | avoids | No collector. |
| P-PY | avoids | Values on the stack/in owner; no per-object header or count. |

The G4 and G11 strains are shared by every eligible option. No row breaks a goal.

## Criteria

Written before scoring; weights set by Claude from the charter and rulings (Q5).

| Criterion | Weight | What it measures |
|---|---|---|
| R6 Run-time transparency | 20 | Can you read the code and know when memory is freed, copied, shared or checked? Hidden work and silent skips score low. |
| Simplicity of rules | 20 | Number of distinct things to remember; loud vs silent mistakes. |
| Safety (P3, below) | 15 | Use-after-free, double free, races outside `unsafe`. |
| Expressiveness | 15 | Tree with parent links, shared cache, UI callback, worker thread written directly. |
| Concurrency | 10 | Threads (R1) without data races. |
| Implementation risk | 10 | What must work before the language is usable. |
| Performance | 10 | Throughput and predictability. |

## Options considered

Scored 1-5. Full list O1-O9 and the earlier scores are in the history file.

- **O1 Pure ARC** (Swift-like): every user type is a counted reference; `weak` breaks cycles.
- **O4 Simplified ownership + built-in `shared` RC kind**: moves and parameter borrows, with counted `shared` for hard cases.
- **O9 Owned values + checked pool handles**: values have one owner; identity lives in pools.
- **O9+ (chosen)**: O9 plus O4's parameter-borrow rule and move checking, and no `shared` kind at all.
- Rejected earlier: O7 cycle collector (fails G2 under R3); O5 full Rust (lifetime parameters fail G3); O8 manual (unsafe, P-C); O2/O3 value semantics (stored closures cannot reach their owner); O6 checked references (hidden aborts).

| | R6 20 | Simp 20 | Safety 15 | Expr 15 | Conc 10 | Impl 10 | Perf 10 | Total/100 |
|---|---|---|---|---|---|---|---|---|
| O1 | 2 | 3 | 4 | 5 | 2 | 5 | 3 | 63 |
| O4 | 4 | 3 | 5 | 5 | 4 | 3 | 5 | 80 |
| O9 | 5 | 4 | 4 | 4 | 4 | 4 | 5 | 84 |
| O9+ | 5 | 4 | 5 | 4 | 5 | 3 | 5 | 86 |

O4 vs O9+ is a 6-point gap and O9 vs O9+ is 2 (a tie), so the tie-break is the examples, which agree: no program needed a count (below).

## What the real examples taught

`docs/examples/chatsim/`, findings in `0001-research/chatsim-findings.md`. Four programs (C reference, ARC proxy, moves, handles) give identical output on a script covering all 11 listed cases, clean under ASan/UBSan/TSan.

- **Case 20 (re-entrancy) broke every model once.** ARC panicked on the first bot reply; moves needed a `mem::replace` trick to call a stored callback; handles needed a snapshot and copies of anything read from a pool. Rule that falls out: **callbacks receive the world as a parameter and capture only plain values and handles.**
- **Case 12/14/15/17** (freed when last user leaves, deleted target, dead `self`, cycle) were all solved by ids/handles with no counts. Under ARC they were solved only by writing `Weak` in four places that nothing forced.
- O4 needed zero `Rc` for chatsim. O1 is the only model with a silent failure (strong capture leaks, no diagnostic).
- Sizes: C 224 lines, ARC 185, moves 181, handles 168.
- Honesty: Swift and Zig are not installed here, so ARC is a Rust proxy (its `RefCell` traps are louder than real ARC).

## Decision

Adopt **O9+**.

1. **Ownership.** Every value has one owner and is freed when the owner's scope ends. `=` and passing by value *move*. Copying is spelled `.copy()` (Q14: explicit).
2. **Borrows.** A parameter is borrowed for the duration of the call. A borrow cannot be stored, returned or captured by a closure that escapes. Mutation requires `mut` at the call site.
3. **Identity lives in pools.** `Pool of T` owns entries. `pool.add(x)` returns a `Handle of T` (index plus generation, a plain copyable value). `pool.get(h)` returns an optional borrow; a stale handle gives `none`, never a crash or a read of reused memory. Parents, observers, timers and cross-thread references are handles. `pool.remove(h)` is explicit and frees the entry.
4. **Closures** capture values by move or copy, and handles. They cannot capture a borrow that escapes. Self-capture is therefore a handle capture (Q11).
5. **Threads.** Values move between threads over channels. A pool shared between threads is wrapped in `Mutex of Pool` (a built-in type; see D3). Handles are sendable; borrows are not.
6. **Safety (P3: yes).** No use-after-free, double free or data race outside an `unsafe` block, which exists only for C FFI.
7. **Debug builds** report pool entries still live at exit and poison freed slots (R4: reclaims nothing).
8. **Not in v1:** `shared`/reference counts, `weak`, cycle collection, user generics, lifetimes.

Resolves Q5 (weights above), Q11, Q14, and P3. P2 (built-in containers under G3) is decided in D2 and this ADR assumes it holds.

## Review (separate reviewer, 2026-11-13) and mandatory mitigations

The reviewer did not invent O9+. Findings kept: iterator invalidation and pool growth need a borrow rule; returned references and string slices are illegal, so slicing allocates (hidden copy); List indices go stale silently; deleting a subtree is a manual walk; handle plumbing is verbose (G4); declarative trees (G11) must either hide pools or expose them; mutex-wrapped pools serialise; built-in `Pool`/`List` are generics under another name (G3 ceiling for user code, accepted: users cannot define their own `Stack`; D2 decides).

**Mandatory requirements on later ADRs:**
1. **No mutation of a pool or List while a borrow or iterator of it is live** (compile time). Provide `ids()`/`snapshot()` for loops that remove. This also fixes case 20.
2. **Debug report:** pool occupancy at exit and a "pool grew past N" warning (R4). `Handle of T` is tied to its pool type; generation is 32 bits and exhaustion traps rather than wraps.
3. **Callback convention:** a stored callback takes the world and handles as parameters and captures only copyable values. The language supplies take-and-restore for self-calls so users never write `mem::replace`.
4. Slicing returns an owned copy in v1; a non-storable slice view is allowed only as a call-scoped borrow (D5/D10).

**Re-open trigger:** if two or more of the first real programs (chatsim in M4, the D7 DSL corpus) need a user-built reference-count layer on pools, add O4's `shared` kind. The reviewer would pick O9+ over O1 and, with this trigger, over O4.

## Consequences

- **Easier:** reasoning about free time; leak reports; no ABI-level count decision; no atomic/non-atomic split.
- **Harder:** a forgotten `remove` leaks (visible in the pool, bounded); "tables of things" style rather than classic object graphs (P-C asks for native OO; methods on values still work, D5); each cross-object reference needs a pool in scope.
- **Rules out:** shared ownership without a pool, weak references, finalizers.
- **Revisit if:** DSL/UI examples in D7 cannot be written without a counted `shared` kind. A veto reopens this ADR.

## Syntax budget impact

New: `move` is implicit (no keyword). `.copy()` method. `mut` marker at call sites and parameters. Built-in types `Pool of T`, `Handle of T`. Possible `if let`-style binding for `pool.get`. No annotations or macros.
