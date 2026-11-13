# Analysis 13 — Slow Match

Analyst: independent. Inputs read: brief.md, round2.md, CHARTER.md, ideas/13-slow-match.md only.

## 1. The idea in three sentences

References never keep anything alive. Instead, every heap object hangs off exactly one parent in a "fuse forest", and the root of each tree is a trigger: a scope exit, an idle timeout, a use count, or an event such as `win.closed`. Objects are attached to a parent implicitly the first time a scope-fused object is stored somewhere, or explicitly with `keep x <fuse>`. Burning a node burns its subtree at the turn boundary, and touching a burnt object raises a catchable `Burnt` through a generation check.

## 2. Prior art

It is a synthesis of known parts. The new parts are the composition and the implicit "first store anchors" rule.

| Slow Match part | Prior art |
|---|---|
| Idle fuse, renewed by use | **Short-term memory** (Kirsch et al., ISMM 2011): "objects in short-term memory expire after a finite amount of time, which makes deallocation unnecessary", and the program must refresh objects to keep them. https://research.google/pubs/short-term-memory-for-self-collecting-mutators , https://tiptoe.cs.uni-salzburg.at/short-term-memory/ |
| Renewal-based lifetime | Jini/River leases: "When the time for the lease has expired, the service ends or the resource is freed". Also .NET Remoting `ILease`. https://river.apache.org/release-doc/3.0.0/specs/html/lease-spec.html |
| Anchor tree with cascade, `keep x while y` | **talloc**: "frees a piece of talloc memory, and all its children"; `talloc_steal` "changes the parent context" (this is `keep while`). https://www.samba.org/~tridge/etest/lib/talloc/talloc.3.html . Qt QObject trees: https://doc.qt.io/qt-5.15/objecttrees.html . APR pools. |
| Pressure eviction | NSCache and purgeable memory: https://developer.apple.com/documentation/foundation/nscache.md |
| Fizzle via `(addr, gen)` | Vale generational references. Already covered as **O6**. |

**Honest classification.** Take the anchor tree, which is a single-owner tree. Add generation-checked non-owning references and you have O6, or the round-1 "single owner + auto-cleared refs" family. Slow Match adds two things on top: time, use and event roots, and implicit owner selection. The inventor admits this in §9.1, and the analysis below confirms it.

## 3. Soundness counterexamples (illustrative only — not a syntax decision)

**C1. The idea's own scenario (b) leaks, so "leaks impossible by construction" is false.**
```
root = Node(); k = Node()
root.add(k)
  // inside add: k.parent = self   -> self (root) is still scope-fused -> root anchored to k
  //             kids.append(k)    -> k scope-fused -> k anchored to kids, kids anchored to root
```
- The fuse chain is now root → k → kids → root. That is a cycle with no trigger.
- It never burns. The §5 claim "trees, never DAGs" only holds if anchoring checks ancestry. That check costs a walk up the parent chain, O(depth), on every anchoring store.
- When the check fails, the spec defines no outcome: refuse, error, or keep the scope fuse.

**C2. Scenario (c) also forms a fuse cycle when the editor keeps its own button. This is very common.**
```
ed = Editor()
ed.build(win)                 // closure captures self -> ed anchored to closure
                              // self.saveBtn = b      -> b anchored to ed
                              // Button(onTap: clo)    -> closure anchored to b   => ed→clo→b→ed
keep ed while win             // if written first, fine; if after, or forgotten -> leak/cycle
```
Correctness depends on the *order of statements*, and nothing in the code shows that.

**C3. A pure-looking helper kills its argument.** This is non-local.
```
fn maxBy(a: Item, b: Item) -> Item
  tmp = List(); tmp.append(a); tmp.append(b)   // a, b were caller's scope-fused temps -> anchored to tmp
  return tmp.sortBy(score).first
item = Item(); best = maxBy(item, other)       // tmp burns at callee exit -> item burns mid-turn
item.name                                       // caller's check was elided ("scope-fused local")
```
- Rule 8 only protects *non-scope* burns. Scope exits burn mid-turn and cascade (rule 7).
- §5 elides checks on scope-fused locals. Here the caller's local was re-anchored by the callee, so the elision is unsound. The caller silently reads a burnt object, whose destructor has already run.
- The same pattern appears in worklist and visited-set code: `json.encode`, graph walks, parsers with a stack (see C4).
- Fixing this needs either interprocedural escape inference, which is the fragile approach the brief warns about, or a rule that parameters never anchor. That rule breaks (b), where `add(k)` relies on anchoring a parameter.

**C4. The canonical parser returns a dead tree.**
```
fn parse(src) -> Node
  stack = List(); root = Node()
  stack.append(root)            // root anchored to stack (first store)
  ...build children under stack.last...
  return root                   // return moves only *scope-fused* objects; root's fuse is stack
                                // stack burns at scope exit -> whole AST burns -> caller fizzles
```

**C5. Overwriting a field or removing an element retains the old value. Memory is unbounded while the parent lives.**
```
class Editor
  fn open(p) self.doc = Doc.load(p)      // each old Doc stays anchored to self
server.queue.pop()                        // popped Request stays anchored to queue (cf. idea's (b) moveTo note)
```
- "Finite trigger" is not "bounded memory". Anything anchored under the app root, or under a long-lived object, accumulates until that ancestor dies.
- The only remedy is `snuff`, which is a manual, deferred `free`.
- This is the "Scope-bound regions… leaks long-lived objects" failure from the covered list, moved down to per-object granularity.

**C6. Session data is lost even while the session is in use.**
```
s = Session(); keep s for 30m; s.cart = Cart()    // cart anchored to s
handler: c = s.cart ... (holds c across many requests, touches c, never s)  // s's fuse is never relit
```
- After 30 minutes the session burns and takes the cart with it, even though the cart is being used.
- Rule 10 can also burn `s` *early* under memory pressure. So the idea's own motivating example, session idle timeout, cannot safely hold user data.
- An idle fuse is only safe for data you can recompute.

**C7. Aborting a turn leaves state half-applied.** For a banking engineer, this one matters most.
```
from.balance -= amt
ledger.entry(amt)             // ledger anchored to an evicted cache entry -> Burnt -> turn aborted
                              // debit applied, entry not written; no rollback
```

**C8. Threads.**
- `send job to worker` moves the subtree, but the sender's copies of the reference stay valid. Generations are only atomic for "shared" objects, so the sender's reads race with the worker's writes.
- Rule 11 says objects "reachable from several threads" burn at the global epoch. Knowing reachability needs either a trace, which is a GC run, or a flag. A flag misses aliases left behind by `send`.
- Idle relight writes the header on *every use*, so reads become writes. Read-mostly data shared across threads then ping-pongs cache lines.

**C9. Stale slots grow without bound.**
- In scenario (d) the `cache` Map keeps a slot per URL forever, unless user code sweeps it.
- That is a leak in a long-running server.

**C10. Smaller ambiguities.**
- What counts as a "use" for `for 3 uses`: each deref, or each external call?
- 32-bit generations wrap around.
- `keep a while b; keep b while a` builds an explicit cycle.
- Returning a struct value that holds object references: does each referenced object's fuse move to the caller? The spec doesn't say.

## 4. Scenarios

- **(a) works.** Return moves the fuse, and strings are values.
- **(b) fails as written.** The parent pointer creates a fuse cycle (C1). Re-parenting is manual, and removal keeps the old anchor.
- **(c) partial.** When it is set up right, the window cascade is elegant and the closure cycle doesn't matter. It is order-sensitive, though, and a forgotten or late `keep` leaks (C2).
- **(d) partial.** TTL and eviction come for free, but neither component can keep an entry alive while it uses it. Every use must handle `Burnt`, and dead slots accumulate (C9).
- **(e) works.** It is a plain reference with no fuse effect.
- **(f) hand-wave.** `send` leaves aliases behind, "reachable from several threads" is undefined without a trace, and there is no race safety (C8).

## 5. Gates

- **G2: pass, with a caveat.** The timer wheel, cascade frees and epochs are not a GC run. The caveat is C8: if rule 11 is implemented by finding cross-thread reachability, that is a trace, and the gate fails.
- **G3: pass.** `keep` is an executable statement, not a type-level annotation. It is, however, a lifetime declaration in disguise. Flag: `Shared(List())` is a built-in parameterised wrapper, so it falls under the pending List/Map question.

**Other charter strains:**
- **G1:** 11 stated rules, plus at least 4 implicit ones: store order matters, removal retains, fuse cycles, and what a "use" is.
- **P-C:** the check elision is unsound (C3), and there are thread races (C8).
- **P-GO/P-JAVA spirit:** pressure eviction reintroduces nondeterminism caused by the runtime, the "GC pain" in another form.

**Positives:** G8 (burn provenance) and G10 (virtual clock).

## 6. Score

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 2 | Too many rules, and correctness is non-local: a callee or the order of stores decides lifetime (C2, C3). |
| Memory safety | 15 | 3 | Generation checks make most failures defined, but the check elision is unsound (C3) and threads race (C8). |
| Expressiveness (b),(c),(d), implicit self | 15 | 3 | The (c) cascade and cache TTLs are real wins. (b) is broken and (d) has no shared lifetime. Implicit self is fine. |
| Implementation risk (AI-written, LLVM) | 15 | 3 | The parts are mundane (talloc tree, timing wheel, generations). The risk is in the anchoring rule: a dynamic check on every store, cycle detection, fuse transfer through returned structs, proofs for check elision. |
| Performance & predictability | 10 | 2 | No RC traffic, but there is a branch on every store, writes on reads for idle fuses, retention growth (C5) and nondeterministic eviction. |
| Concurrency fit | 10 | 2 | No race safety, aliases survive `send`, and relight writes break read-sharing. |
| Tooling, debuggability, FFI | 10 | 4 | Burn provenance, the forest debugger and the virtual clock are excellent, and the `pin` FFI is sensible. Pressure eviction makes heisenbugs in production. |

Each term is weight × score / 5:
- Simplicity: 25×2/5 = 10
- Memory safety: 15×3/5 = 9
- Expressiveness: 15×3/5 = 9
- Implementation risk: 15×3/5 = 9
- Performance: 10×2/5 = 4
- Concurrency: 10×2/5 = 4
- Tooling: 10×4/5 = 8

**Total = 10 + 9 + 9 + 9 + 4 + 4 + 8 = 53 / 100.**

That is 30 below O1 (83), 29 below O4 (82) and 15 below round 1's best (68). It lands in round 1's single-owner band (47–68), as the inventor predicted.

## 7. What the premise teaches, and the kernel

**What the premise teaches:**
- **Separating the lifetime graph from the pointer graph really does make cycles irrelevant.** That is the one genuinely good insight. The cost is that you now need a second graph, and someone has to say where each node goes in it.
- **Implicit owner selection is the worst point in the design space.** If "first store anchors" decides ownership, then ownership is inferred, which is fragile, and also invisible. Either make ownership explicit (O4 move semantics) or make it shared and counted (O1). Don't guess.
- **"Every object has a finite trigger" does not give bounded memory.** Leak-freedom has to be measured against the *useful* lifetime, not the "eventual" one. Regions, talloc and Slow Match all fail this for long-lived parents.
- **Programmers do think in events and time, but only for a few objects:** windows, sessions, timers and caches. That is a library-scale need, not a reason to put every object on a fuse.
- **A caught "use after death" error is only better than a leak when the turn is transactional.** Without rollback, safe failure becomes data corruption (C7).

**Kernel worth stealing (for O1, or for O4's `shared` kind):**
1. **Event-owned subscriptions.** Closures registered as callbacks (`onTap`, timers, observers) are *owned by an event scope*, such as `win.closed`. When the event fires, the runtime drops those closures' strong references.
   - In O1 this breaks the self → button → closure → self cycle deterministically, with no `weak` in user code. The pattern is Qt object trees, or a DisposeBag, built into the language.
   - It adds one rule: "callbacks live until their owner's close event".
2. **Lifetime assertions as a debug mode.** `expect x dies with win`: when `win` closes, any tagged object that is still alive is reported with its retaining path, in the style of LeakCanary.
   - This is Slow Match's provenance aimed at O1's real failure mode, which is leaks from cycles.
   - Mirror image: a weak reference that reads nil in debug builds reports *why* and *where* the last strong release happened. That is "fizzle with history".
3. **A stdlib `Cache` with TTL and memory-pressure eviction.** It sits on O1's weak and strong references, NSCache-style, rather than being a memory model.
4. **A virtual clock in the test harness** (G10), so time-based behaviour becomes deterministic in tests.

## 8. Verdict

**Kernel worth stealing.** As a memory model it is a dead end: implicit anchoring reintroduces single ownership, makes lifetime non-local, and breaks its own scenarios (b) and (c). The event-scoped callback ownership and the debug provenance are worth porting into O1.
