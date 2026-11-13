# Adversarial review of O9 (Opus reviewer, 2026-11-13)

The reviewer did not invent O9. The text is condensed from its report; the counterexamples are kept verbatim
(illustrative syntax).

**Bottom line:** O9 as written has one fatal soundness hole and two serious ergonomic holes. Corrected scores:
O9 70 vs O4 68, a tie. With the fixes (variant "O9-S"), O9 is about 75 and wins. The chatsim port flattered O9
three ways:
- global pools hid where pools live;
- hand-copied callbacks hid the dispatch trap;
- no hierarchies hid manual cascading deletes.

## Findings

**F1, FATAL: mutable aliasing outside pools gives use-after-free.** Rule 5 locks only pools.
```
fn append_all(dst: List of Str, src: List of Str) { for s in src { dst.push(s.copy()) } }
append_all(a, a)              // dst.push reallocates a; src iterator reads freed memory
fn show(name: Str, h: Holder) { h.name = "x"; print(name) }
show(holder.name, holder)     // name borrows the freed string
for e in list { list.remove(0) }
```
Fix: a law of exclusivity (Swift/Hylo). A mutable access may not overlap any other access to the same place.
Checked statically for plain paths, dynamically for `list[i]` and pool entries. It absorbs rule 5.

**F2, SERIOUS: rule 5 traps in ordinary G11 code.**
```
if w = widgets.get(btn) { w.onTap() }   // handler: widgets.remove(dialogH) -> TRAP; widgets.add(Popup()) -> TRAP
if p = nodes.get(parent) { p.kids.push(nodes.add(Node(tok))) }   // AST builder -> TRAP
```
Moving a statement into a helper turns a compile error into a release-build trap. Fix: segmented pool storage
(entries never move, so `add` is always safe), plus deferred drop. `remove` while borrowed bumps the generation at
once and drops when the borrow ends. That is proportional to what is freed, so it passes R3.

**F3, SERIOUS: cascading deletion is manual.** Removing a node leaves its children as zombies, and closing a window
leaks its widgets. Fix: ownership cascade (an `owns` handle, or an owner recorded at `add`).

**F4, SERIOUS: a zombie is not milder than O1's leaked cycle; it is different.** A leaked cycle is unreachable and
inert. A zombie stays reachable and keeps acting:
```
logout(h): audit.log(h)   // forgot sessions.remove(h)
if s = sessions.get(cookie.h) { serve(s) }   // revoked session still authorizes
```
Fix: debug `expect_empty`, pools scoped to an owner, and F3's cascade.

**F5, SERIOUS: where pools live is untested.** The port used globals.
- Passed down, every signature carries the world, and relational methods become `table.verb(h1, h2)`.
- Global, they need a thread rule.

Fix: choose one and state it.

**F6, SERIOUS: a handle can resolve to the wrong object.**
- With the same index and generation, a handle from pool A works on pool B of the same type.
- A 32-bit generation wraps.
- An untyped handle can be used on any pool.

Fix: typed handles (`Handle of T`), retire a slot when its generation would wrap, and a pool id in the handle.

**F7, SERIOUS (P-RUST, G4): rule 2 brings back Rust's beginner errors.** Moving out of a borrow, "maybe moved" after
a branch, moving in a loop, a second closure capture. Fix: an error that suggests `.copy()` with its cost, and
immutable strings that copy cheaply. Count `.copy()` in the next example.

**F8, MINOR: threads.** Re-locking from a callback self-deadlocks, and lock order can deadlock. Data races are excluded,
because a borrow can't escape a lock block. Fix: trap when a thread re-locks a mutex it already holds; a debug
lock-order check.

**F9, MINOR:** about 12 stale branches in chatsim (the P-GO `if err` feel). Fix: `pool[h]`, which traps on a stale
handle, alongside `if u = pool.get(h)`.

**F10, MINOR:** functions can't return borrows, so getters return copies or handles. Acceptable; state it.

## Corrected scores (rubric v2)

| Option | Transp | Simp | Safety | Conc | Expr | Impl | Perf | Tool | Total |
|---|---|---|---|---|---|---|---|---|---|
| O9 as written | 4 | 3 | 4 | 4 | 2 | 3 | 4 | 4 | 70 |
| O9-S (fixes F1, F2, F3, F6) | 4 | 3 | 5 | 4 | 3 | 3 | 4 | 4 | 75 |
| O1 | 2 | 3 | 3 | 2 | 5 | 4 | 3 | 4 | 60 |
| O4 | 3 | 2 | 5 | 5 | 3 | 2 | 3 | 5 | 68 |

- **O1 Safety 3:** ARC protects lifetime, not data. A cross-thread string overwrite is a use-after-free unless a
  sendability rule is added.
- **O4 Expr and Perf 3:** names-as-references, plus a snapshot `Vec` on the hot path.

## The reviewer's acceptance conditions

1. Exclusivity rule, with the F1 programs rejected or trapped.
2. Segmented pools and deferred drop; the F2 dispatcher and AST builder run without traps.
3. Cascade ownership and zombie debug checks.
4. Typed handles, wrap retirement and a pool id.
5. Where pools live (the globals and thread rule).
6. A second example (a widget tree, callbacks that close their own dialog, subtree delete, a shared cache), in
   O9-S pseudo-syntax plus a C model, reporting the `.copy()` count, stale-branch count and trap sites.
7. A re-score with the sensitivity check.
