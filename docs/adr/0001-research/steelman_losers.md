# Steelman review of ADR-0001 (memory management): the options that lost

- **Reviewer role:** adversarial. I make the strongest honest case for O1, O4, O2 and O6, and against the scores that put O3 first.
- **Inputs read:** `lang-charter/docs/CHARTER.md` and `reports/Memory management model ADR.md` only. I did not read `research_notes/`. Where I mention "the notes", I mean what the ADR itself says the notes contain.
- **Evidence labels:** **[source]** means checked on the web for this review (URL given). **[ADR-internal]** means the argument rests on the ADR's own text. **[reasoning]** means my own argument, with no external evidence.
- **Date:** 2026-11-07

---

## 1. Verdict

**The recommendation should change.** The ADR scores some machinery as costly in the losing options, but the same machinery is free or harmless when it appears in O3. Fixing three of those inconsistencies changes the totals to:

- **O4: 79**
- **O1: 77**
- **O3: 70**

Each fix moves one cell by one step. Any one of the three, applied alone, already takes the lead away from O3. O3 keeps first place only if all three are rejected.

The three load-bearing changes:

| ID | Cell | Old → New | Core reason | Confidence |
|---|---|---|---|---|
| **C** | O4 Expressiveness | 3 → **4** | O4's built-in `shared` kind is the same thing as O3's identity type. O3's main G11 mitigation (framework store plus handles) doesn't depend on the memory model and works under O4 too. O3 has the same limit on escaping-closure captures. | High |
| **B** | O3 Implementation risk | 4 → **3** | The ADR's own tractability ranking puts MVS+CoW below Inko-style ownership, yet O6 scores 3 and O3 scores 4. O3 needs most of O2's machinery, and O2 scores 3. O3's exclusivity enforcement is critical to soundness and can't be switched off, which is the reason O4 was marked down. | Medium-high |
| **A** | O3 Simplicity | 4 → **3** | O3 contains everything in O1, including `weak` and silent cycles, and adds values, `inout`, exclusivity errors and hidden copies. The ADR gives O1 a 4 for one silent exception, so O3 can't also be a 4. O3 also has two of the three faults the ADR uses to mark O4 down to 3. | Medium (a genuine judgement call) |

Secondary changes that raise losers' scores without changing the winner: **O2 Expressiveness 2 → 3**, and for **O6 (scored as its Inko variant)** Implementation risk 3 → 4, Concurrency 2 → 4 and Performance 4 → 3.

Fair as scored: O1's individual cells (some justifications are wrong; see §3.3), O4 Simplicity 3, O7 (it depends on the gate), O8 and O5.

---

## 2. Arithmetic check of the draft

I recomputed every total and all ten sensitivity rows with a script, using the ADR's formula (total = Σ w·s / 5, or for re-weighted variants Σ w·s × 20 / Σ w). **Every figure in the draft is correct.** Examples:

- O3: 25·4 + 15·4 + 15·4 + 15·4 + 10·4 + 10·3 + 10·4 = 390, so 78.0
- O1: 25·4 + 15·4 + 15·4 + 15·5 + 10·3 + 10·2 + 10·4 = 385, so 77.0
- O4: 25·3 + 15·4 + 15·3 + 15·4 + 10·5 + 10·4 + 10·5 = 380, so 76.0

The problem is in the score cells, not the sums.

---

## 3. Option by option

### 3.1 O4 (simplified ownership): Expressiveness is understated (3 → 4)

**Draft justification:** "(a), (e) and (f) are free. (b), (c) and (d) always go through RC (ownership notes). Escaping closures move owned captures out of the enclosing scope."

**Why that is unfair.**

1. **O3 and O4 solve (b), (c) and (d) with the same tool. [ADR-internal]**
   - O3's 4 says: "The identity type covers graphs, caches and stateful view models."
   - O4's 3 says these "always go through RC". O4's RC kind is "a built-in shared (RC/weak) kind".
   - O3's identity type is also an RC object with `weak` fields.
   - So the same mechanism is a strength in O3 (4) and a weakness in O4 (3).
   - If anything, O4's `shared Document()` decides sharing per instance, while O3 decides it per type declaration. Per instance is the more flexible of the two. [reasoning]

2. **O3's answer to the G11 crux isn't specific to O3. [ADR-internal + reasoning]**
   - O3's Pro (c) works because the DSL keeps state in a framework store and the callback captures a handle, a small plain value.
   - That needs only two things: views are values, and handles are copyable.
   - O4 has both. Owned values are values, and O4 is described as working "as with Mojo".
   - In Mojo, small types are copied implicitly. Values "are copied if they are implicitly copyable", and only non-implicitly-copyable types need `.copy()` or the `^` transfer sigil ([InfoWorld, Mojo 1.0](https://www.infoworld.com/article/4173158/first-look-at-mojo-1-0.html); [Mojo manual, ownership](https://mojolang.org/docs/manual/values/ownership/): trivial types are "always passed by copy").
   - A handle captured in an O4 closure is therefore copied, not moved, and the `Counter` example works the same under O4.
   - Decision Q4(a) commits the DSL to this architecture whichever memory model wins.
   - O4 does need one design rule: implicit copyability must be inferred from structure, not declared, to satisfy G3. That is a rule, not a reason to score O4 down.

3. **O3 has the same limit on escaping closures, and fails more quietly. [ADR-internal + source]**
   - Decision #5 says O3's escaping closures "capture values by copy".
   - Take the O4 con snippet (`button.onTap = { doc.save() }; print(doc.saved)`) with a value-type `Document` under O3. One of two things happens. The compiler rejects `doc.save()` as a mutation of an immutable capture, or the closure mutates a private copy and `print(doc.saved)` never changes, silently.
   - Swift has exactly this pitfall: an escaping closure that captures a struct sees a stale copy ("It outputs 1, not 2"), and the compiler refuses to let a `mutating` method capture `self` ([Swift Forums, "A pitfall with value type + escaping closure"](https://forums.swift.org/t/a-pitfall-with-value-type-escaping-closure/50161)).
   - The fix is the same in both models: make `Document` identity or shared.
   - So "escaping closures move owned captures" is not a gap in expressiveness relative to O3. It is a difference in failure mode, and O4's failure is the louder one.

4. **Don't count the friction of moving twice. [reasoning]**
   - Everything O3 can express, O4 can express with an explicit `.copy()`.
   - The cost of writing `.copy()` and seeing use-after-move errors is already charged in O4 Simplicity (3).
   - Charging it again in Expressiveness double-counts.

**Revised: O4 Expressiveness 3 → 4.** This puts it level with O3 and O1. I don't argue for 5, because the shared kind still brings O1's cycle rules (see the con under Option O4 in the ADR).

**O4 Simplicity 3 is fair. I don't change it.** Use-after-move errors are a real hurdle that O3 doesn't have. The O3-vs-O4 snippet (`b = a; a.append(4)`) shows O4 as specified fairly, though it uses the worst case (a heap container). A plain-data struct under O4 would copy implicitly.

**O4's other cells (Safety 4, Impl 4, Perf 5, Concurrency 4, Tooling 5) are fair.** One mild caution: Perf 5 assumes users won't scatter `.copy()` calls to silence move errors, the "clone everywhere" habit. [reasoning; no change]

### 3.2 O3 (the recommendation): two cells are overstated

#### O3 Implementation risk: 4 → 3

The ADR already calls this "the most disputed score". I think the dispute should be settled against O3.

1. **The ADR breaks its own cited ranking. [ADR-internal]**
   - The sensitivity section says "the notes' own tractability ranking puts 'MVS + CoW' third, behind plain RC and Inko-style owned values."
   - The ADR scores Inko-style ownership (folded into O6) at **3** and MVS+CoW (O3) at **4**.
   - Either O6 is too low or O3 is too high. The ADR doesn't explain the inversion.

2. **O3 contains most of O2's machinery, but scores lower risk than O2. [ADR-internal]**
   - O2 scores 3 for "init/move dataflow, exclusivity checking and `yield`-projection lowering", with Swiftlet's slowness and Hylo's late 1.0 as evidence.
   - O3 needs exclusivity checking, CoW uniqueness, and init/move dataflow (for move-at-last-use, which Decision #1 makes the default optimisation). It then adds O1's whole runtime on top: RC headers, zeroing weak references, cycle reporting, and the identity kind.
   - Dropping user-facing projections and `sink` saves some work, but not enough for a superset to be *lower* risk.

3. **"Optimisations can be switched off" doesn't cover exclusivity, the same objection that cost O4 a point. [source + ADR-internal]**
   - O4's justification marks it down because "the use-after-move check is critical to soundness and can't be switched off".
   - O3 has an equivalent check. Swift's compiler team describes exclusivity enforcement as something that "legalizes performance optimization while protecting memory safety". Swift enforces it at run time for class properties, globals and escaping captures, and trapping with "overlapping accesses" ([Swift Forums, run-time exclusivity checking in release mode](https://forums.swift.org/t/enabling-run-time-exclusivity-checking-in-release-mode/17626); [SE-0176](https://github.com/apple/swift-evolution/blob/master/proposals/0176-enforce-exclusive-access-to-memory.md): "Class properties and global variables will have to enforce the rule dynamically").
   - The ADR admits O3 needs this for `inout` access to identity-object fields, but marks it "(inferred from the notes; to be confirmed in implementation)". **An unconfirmed component that soundness depends on is not a 4.**

4. **A correct baseline is not a shippable baseline. [ADR-internal]**
   - The ADR itself cites Swiftlet, which lacked uniqueness optimisations, as "significantly slower than Swift".
   - So the uniqueness and move passes are effectively required for O3 to be usable, and they are exactly the risky part.
   - The Judgement then uses the same staging argument a second time to wear down O1's lead ("removes much of O1's implementation-risk advantage"). The argument is already priced into O3's 4, so this counts it twice.

**Revised: O3 Implementation risk 4 → 3.** That puts O3 level with O2 and O6, below O4 (4) and O1 (5).

#### O3 Simplicity: 4 → 3

1. **O3 contains O1's whole model, and O1 scores 4 for having one silent exception. [ADR-internal]**
   - O1's 4 says: "One rule … plus one exception (weak back-references). The exception fails silently."
   - O3 keeps that rule and that silent exception for its identity subset. It then adds a second type kind, two meanings of `a = b`, `inout` with call-site marking, exclusivity errors ("`swap(&a[i], &a[j])` is rejected", in Consequences), and hidden O(n) copies.
   - The identity subset is not rare. The ADR lists "resources, caches, view models, graph nodes", and every G11 UI app has view models.
   - Learners therefore need both models. Something strictly larger than a 4 with one exception can't also be a 4.

2. **O3 has two of the three faults used to mark O4 down to 3. [ADR-internal]**
   - O4's 3 cites "use-after-move errors, aliasing-XOR-mutation errors and a second, RC-based world".
   - O3 has aliasing-XOR-mutation errors (`inout` exclusivity) and a second RC-based world (the identity type).
   - The O3 charter row ("no lifetimes, no borrow checker, no move errors and no capture lists") leaves out the exclusivity errors that the Consequences section admits.

3. **Choosing between the two type kinds is a known learnability cost, and it is P-SWIFT. [source]**
   - Apple publishes a dedicated guide because "their similarities can make it difficult to choose one over the other" ([Apple, Choosing Between Structures and Classes](https://developer.apple.com/documentation/swift/choosing-between-structures-and-classes.md)).
   - The charter names Swift's "too many features" as a problem to avoid.

**The case for keeping 4, stated honestly.** The same Apple page argues that value types make it "easier to reason about a portion of your code without needing to consider the whole state of your app", which is a genuine learnability benefit O1 lacks. That benefit is real, but it doesn't cancel a strictly larger set of concepts. My fallback is 3.5. **Revised: O3 Simplicity 4 → 3**, ranking O1 (4) > O3 (3, the stronger 3) ≥ O4 (3).

#### O3 cells I examined and left alone

- **Performance 4.** This is generous. Hidden O(n) copies hurt the *predictability* half of the criterion. Swift's run-time exclusivity checks cost a run-time call on each class-property access, and microbenchmark regressions of up to +840% (ClassArrayGetter2) were seen when the checks were first enabled in release builds ([Swift Forums](https://forums.swift.org/t/enabling-run-time-exclusivity-checking-in-release-mode/17626)). Those were microbenchmarks that were later optimised, so I keep 4.
- **Tooling 4.** This is equal to O1 although O3 has more compiler-inserted code (CoW copy paths, exclusivity calls) to attribute in coverage. It is a marginal difference, so I keep 4.

### 3.3 O1 (pure ARC): the scores are fair; the case against it has errors

I tried to raise O1's Performance (3) and Concurrency (2) and couldn't do it honestly.

- Every user object lives on the heap with pointer indirection, and Java is retrofitting value objects for exactly this reason: "heap flattening" and "scalarization, which avoids memory allocation" ([OpenJDK Valhalla, Value Classes and Objects](https://openjdk.org/projects/valhalla/value-objects)). So Performance 3 stands.
- Making every type shareable does need a Sendable-style layer, so Concurrency 2 stands.

But the case the draft makes against O1 has three defects:

1. **The performance evidence is about O3's model, not O1's. [source]**
   - The "about 32% of execution time on RC" figure comes from *Swift*, which is the value/class hybrid the ADR calls "O3 is Swift's core model". The Swift runtime it measured "implements RC with lock-free atomic operations".
   - The paper's 32% is an average over client programs (42%) and server programs (15%). The paper also finds that "not using atomic operations reduces the average execution time of the programs by 25%" ([Choi, Shull & Torrellas, BRC, PACT 2018](https://docs.rs/crate/biasedrc/latest/source/paper.pdf)).
   - So the figure mostly measures the cost of *atomic* counts in an O3-shaped language. It doesn't separate O1 from O3. The score survives, but on the heap-allocation argument, not this one.

2. **The O1 callback example is a strawman (see §4, item 1).** The O1 text says cycles leak "with nothing to warn you". But O1's own Tooling row credits "An exit-time cycle report works on every OS". Decision #4's lint ("flags an escaping closure that is stored into an identity object and captures that same object") is independent of the memory model.

3. **The irreversibility tie-breaker doesn't separate O3 from O1 as cleanly as claimed. [source + reasoning]**
   - The Judgement says "O3 is the only top-scoring option that keeps [List/Map] as values without making move errors part of everyday code", and "O1 makes them references, as Java and Python do."
   - But reference user types and value-semantic built-in containers can be combined. PHP has shipped that model for decades: arrays are shared and separated on write ("If the refcount is one, `SEPARATE_ZVAL()` won't do anything"), while "an object value is just an ID" ([PHP Internals Book, memory management](https://www.phpinternalsbook.com/php5/zvals/memory_management.html)). PHP also has a cycle collector, so it is a precedent for the semantics, not for G2.
   - The ADR itself says "the RC notes' own staging plan already assumes value types with CoW over refcounted buffers in stage 1". I can't check the notes, but if that's right, the notes' own O1 plan already had value containers.
   - Call this variant **O1+**: ARC user types plus CoW `List`/`Map`/`String`, and therefore `inout`.
   - Rough score: Simplicity 4 (3 if you accept my O3 argument), Safety 4, Expressiveness 4, Impl 4, Perf 3, Concurrency 2, Tooling 4. That gives raw 100+60+60+60+30+20+40 = 370, so **74**, or 69 with Simplicity 3. It doesn't win. **Its value is that it removes the irreversibility argument as a reason to prefer O3 over O1**, and it makes the documented fallback ("List becomes a reference type") unnecessary.

**Revised O1 cells: none.** O1 still totals 77. What O1 gains in this review is relative, from O3's corrections.

### 3.4 O2 (strict MVS): Expressiveness is understated (2 → 3)

1. **The ADR is committing the DSL to O2's UI architecture anyway. [ADR-internal]**
   - Q4(a) commits the DSL to "views as values, with state in a framework-owned store addressed by handles".
   - O2's "con (c)" is a message or update loop over value views: the same family of design, in the Elm/SwiftUI style.
   - The remaining O2-specific question is whether a closure can call `count.set(...)` on a store the runtime owns. In O2 that needs a framework intrinsic, such as enqueuing an update the runtime applies between frames, because user code can't hold the store's mutable reference. That costs something, but it doesn't put UI out of reach. [reasoning]

2. **The parent-pointer example uses raw `Int` indices, but the ADR's own stdlib ships something safer (see §4, item 4).**
   - Decision #8 ships a generational handle store in which "a stale handle returns 'missing', which is memory-safe" ([slotmap docs](https://docs.rs/slotmap/)). It is a stdlib facility and works the same under O2.
   - That takes most of the force out of "stale indices turn into logic bugs the compiler can't see".

3. **What still really costs O2 something:**
   - shared caches threaded down as `inout`
   - whole-graph access at each traversal step ([Racordon et al.](https://daveabrahams.com/wp-content/uploads/2022/02/implementation_strategies_for_mutable_value_semantics-preprint.pdf))
   - no identity at all

   On the ADR's own scale, "3 means workable at a clear cost" fits this. A 2 is close to the disqualification anchor.

**Revised: O2 Expressiveness 2 → 3.** I checked whether O2 Simplicity 3 double-counts the same "hits a wall" cost. It doesn't, because O5's Simplicity 1 also counts fighting the borrow checker, so walls are counted under simplicity consistently. Other O2 cells are fair. **O2: 350, so 70.**

### 3.5 O6 (single ownership with checked references): scored on the wrong variant

The ADR folds the Inko variant (owned values with run-time-counted borrows) into O6. It then scores O6 entirely on Vale's record: Vale's benchmark, Vale's unshipped isolates, Vale's stalled optimisations and the Golden Spike announcement. Yet the variant the notes rank **second most tractable** is Inko's. Scoring an option on its weaker variant is unfair, but picking the best cell from each variant would be cherry-picking. So I score the **Inko variant as a whole, consistently**:

| Criterion | Old → New | Reason |
|---|---|---|
| Implementation risk | 3 → **4** | Ranked ahead of MVS+CoW in the ADR's cited ranking. A precedent exists: Inko replaced its interpreter with "a native code compiler using LLVM as its backend", built by a small self-funded team ("working on Inko full-time and using our savings") ([Inko 0.11.0 release](https://inko-lang.org/news/inko-0-11-0-released)). [source] |
| Concurrency | 2 → **4** | "No precedent to copy" is wrong for this variant. Inko ships lightweight processes that "don't share memory, instead values are moved between processes", and a value is sendable only if it is a value type or a unique (`uni`) value, so "no data race conditions can occur" ([Inko manual, concurrency](https://docs.inko-lang.org/manual/main/getting-started/concurrency)). It has the same limit as O2, no shared mutable state across threads, and O2 scores 4. `uni` is a type modifier, so it passes G3 under the ADR's rule. [source] |
| Performance | 4 → **3** | For consistency. The +10.84% figure is Vale's. Inko counts every borrow at run time (the ADR says it "counts borrows"; Inko panics with "can't drop a value … as it still has 1 reference(s)", [Inko manual, memory](https://docs.inko-lang.org/manual/latest/getting-started/memory-management)). That is RC-like traffic, though non-atomic. [reasoning] |
| Simplicity, Safety, Expressiveness, Tooling | unchanged (3, 4, 4, 3) | Inko detects use-after-drop deterministically at the drop site rather than probabilistically on dereference. That is better for debugging but doesn't move a whole step. |

**O6 (Inko variant): 25·3 + 15·4 + 15·4 + 15·4 + 10·3 + 10·4 + 10·3 = 355, so 71** (up from 66). It is underrated, but it doesn't win.

### 3.6 Options I judged fairly scored

- **O7.** Its fate rests on the G2 ruling (Q2b), not on its cells. Performance 2 and Concurrency 1 look harsh next to O1 but are defensible given an adaptive collection threshold and tracing during mutation. One point for John: an *optional* collector that can be switched off (the CPython model) makes O7 a strict superset of O1. If Q2b is answered "no", O7 at Simplicity 35 reaches 78.2 under my revised scores and beats both O1 and O4 (77.3).
- **O8.** The low scores follow from P-C. Fair.
- **O5.** It fails the G3 gate. The scores are irrelevant.

---

## 4. Code examples that misrepresent an option

| # | Location | Problem | Fair version |
|---|---|---|---|
| 1 | O1, Con (c), "our language" block | `// compiles, runs, leaks Editor forever`, plus the prose "cycles leak with nothing to warn you". This contradicts O1's own Tooling row (an exit-time cycle report on every OS). It also denies O1 the Decision #4 lint, which is independent of the memory model. O3's *identical* snippet is captioned "needs a weak capture or a compiler lint". | Give O1 the same caption as O3's identity case: `// cycle: lint warns; debug build reports the leak at exit`. The real difference is only that O3's DSL can avoid identity `self` for views. |
| 2 | O1, Performance justification | Swift's 32% RC figure is cited against O1. It was measured on Swift (O3's model) with atomic RC ([BRC](https://docs.rs/crate/biasedrc/latest/source/paper.pdf)). | Justify Perf 3 with heap allocation and lack of flattening (see [Valhalla](https://openjdk.org/projects/valhalla/value-objects)), and apply any atomic-RC penalty equally to O3. |
| 3 | O4, Con (c) | The compile error is shown for O4. O3's behaviour on the same code is never shown: with a value `Document` and capture by copy (Decision #5), O3 either rejects `doc.save()` or mutates a stale copy without telling you ([Swift Forums pitfall](https://forums.swift.org/t/a-pitfall-with-value-type-escaping-closure/50161)). | Show both. The fix (make it identity or shared) is the same, and O4's error is the more honest failure. |
| 4 | O2, Con (b) | `parent: Optional<Int>` raw indices, captioned "unchecked indices". The ADR's own Decision #8 ships a generational handle store that is equally available to O2. | Use `parent: Optional<Handle>`, where a stale handle yields "missing". |
| 5 | O3, Pro (c), `view Counter` | Presented as an O3 strength. It is a DSL technique that works under O4 (copyable handle) and, through a runtime intrinsic, under O2. | Present it as model-independent, or show it under each option. |
| 6 | O4 Safety vs O3 Safety text | O4 is tied to a `RefCell` "already borrowed" panic. O3's equivalent run-time exclusivity trap (Swift: "overlapping accesses") appears only in Consequences, marked "to be confirmed". The scores are equal (4 and 4), but the text is lopsided. | State the run-time trap in O3's Safety row too. |
| 7 | Charter table, O3 G1 row | "no move errors and no capture lists" leaves out the `inout` exclusivity errors that the Consequences section admits. | Add "exclusivity errors on `inout` (e.g. `swap(&a[i], &a[j])`)". |

The O3-vs-O4 `b = a; a.append(4)` snippet is **fair** to O4 as specified. Its O3 comment ("fine; the buffer is copied here") understates that the copy is a hidden O(n) operation, but the text elsewhere says so.

---

## 5. Revised scores and totals

Revised cells are in **bold**. Formula: total = Σ weight × score / 5.

| Option | Simp (25) | Safety (15) | Expr (15) | Impl (15) | Perf (10) | Conc (10) | Tool (10) | Raw | **Total** | Draft |
|---|---|---|---|---|---|---|---|---|---|---|
| **O4** | 3 | 4 | **4** | 4 | 5 | 4 | 5 | 395 | **79.0** | 76 |
| O1 | 4 | 4 | 4 | 5 | 3 | 2 | 4 | 385 | **77.0** | 77 |
| O7 (gated) | 5 | 5 | 5 | 3 | 2 | 1 | 3 | 380 | 76.0 | 76 |
| O6 (Inko variant) | 3 | 4 | 4 | **4** | **3** | **4** | 3 | 355 | **71.0** | 66 |
| O3 | **3** | 4 | 4 | **3** | 4 | 3 | 4 | 350 | **70.0** | 78 |
| O2 | 3 | 5 | **3** | 3 | 4 | 4 | 3 | 350 | **70.0** | 67 |
| O5 (G3 fail) | 1 | 5 | 2 | 1 | 5 | 5 | 5 | 295 | 59.0 | 59 |
| O8 | 2 | 2 | 2 | 4 | 5 | 2 | 3 | 270 | 54.0 | 54 |

Arithmetic:

- **O4:** 25·3 + 15·4 + 15·4 + 15·4 + 10·5 + 10·4 + 10·5 = 75+60+60+60+50+40+50 = 395, and 395/5 = **79.0**
- **O1:** 25·4 + 15·4 + 15·4 + 15·5 + 10·3 + 10·2 + 10·4 = 100+60+60+75+30+20+40 = 385, so **77.0**
- **O6:** 75+60+60+60+30+40+30 = 355, so **71.0**
- **O3:** 25·3 + 15·4 + 15·4 + 15·3 + 10·4 + 10·3 + 10·4 = 75+60+60+45+40+30+40 = 350, so **70.0**
- **O2:** 25·3 + 15·5 + 15·3 + 15·3 + 10·4 + 10·4 + 10·3 = 75+75+45+45+40+40+30 = 350, so **70.0**

**Moderate (half-step) version**, for readers who think the integer scale is too coarse. Use O3 Simplicity 3.5, O3 Impl 3.5 and O4 Expressiveness 3.5:

- O3: 87.5+60+60+52.5+40+30+40 = 370, so **74.0**
- O4: 75+60+52.5+60+50+40+50 = 387.5, so **77.5**
- O1: **77.0**

O4 still leads narrowly, and O3 is third.

### Which changes carry the result (applied to the draft's scores one at a time)

| Changes accepted | O1 | O3 | O4 | Winner |
|---|---|---|---|---|
| none (draft) | 77 | **78** | 76 | O3 |
| A only (O3 Simp → 3) | **77** | 73 | 76 | O1 |
| B only (O3 Impl → 3) | **77** | 75 | 76 | O1 |
| C only (O4 Expr → 4) | 77 | 78 | **79** | O4 |
| A + B | **77** | 70 | 76 | O1 |
| A + C, B + C, A + B + C | 77 | 70–75 | **79** | O4 |

O3 stays first only if **all three** are rejected.

### Weight sensitivity under the revised scores (eligible options; O7 shown separately)

| Variant | O1 | O3 | O4 | O2 | O6 | O7 (gated) | Eligible winner |
|---|---|---|---|---|---|---|---|
| Base | 77.0 | 70.0 | **79.0** | 70.0 | 71.0 | 76.0 | O4 |
| Simplicity 35 | **77.3** | 69.1 | **77.3** | 69.1 | 70.0 | 78.2 | O1 = O4 |
| Impl risk 25 | **79.1** | 69.1 | **79.1** | 69.1 | 71.8 | 74.5 | O1 = O4 |
| Simp 35 + Impl 25 | **79.2** | 68.3 | 77.5 | 68.3 | 70.8 | 76.7 | O1 |
| Safety 25 | 77.3 | 70.9 | **79.1** | 72.7 | 71.8 | 78.2 | O4 |
| Expressiveness 25 | 77.3 | 70.9 | **79.1** | 69.1 | 71.8 | 78.2 | O4 |
| Performance 20 | 75.5 | 70.9 | **80.9** | 70.9 | 70.0 | 72.7 | O4 |
| Concurrency 20 | 73.6 | 69.1 | **79.1** | 70.9 | 71.8 | 70.9 | O4 |
| Tooling 20 | 77.3 | 70.9 | **80.9** | 69.1 | 70.0 | 74.5 | O4 |
| All equal | 74.3 | 71.4 | **82.9** | 71.4 | 71.4 | 68.6 | O4 |

Under the revised scores, **O3 wins no weighting variant.** The real contest is O4 against O1. O1 wins only when both simplicity and implementation risk are weighted up.

---

## 6. The Judgement section, steelmanned from the other side (labelled opinion)

1. **Irreversibility.** This is a real reason to choose value-semantic containers in v1. But it argues *for* O4 just as much, and it argues against O1-as-specified, not O1+ (§3.3). It doesn't single out O3.
2. **Staging.** This is already the stated basis for O3's Impl 4, so using it again to discount O1's lead counts it twice. And a staged O3 at stage 1 is Swiftlet: correct but "significantly slower".
3. **"Silent slowdown beats a teaching compile error."** This reverses the ADR's own principle in Context: "any analysis whose bugs fail silently … is high-risk." The project prefers loud failures for compiler bugs. Preferring silent failures for user performance bugs needs its own justification, especially since the charter lists slowness as a problem (P-PY). A compile error is caught on every build. A hidden O(n) copy is caught only if a profiler runs on representative data. Reasonable people can still prefer O3's trade under G1, but it is a preference, and the scores no longer back it.

---

## 7. Does the recommendation change?

**Yes.** Under the revised scores, **O4 should be the recommendation (79), with O1 (77) the documented alternative.** O3 falls to 70, level with O2 and below O6's Inko variant.

If John rejects change C (O4 Expressiveness) but accepts either A or B, **O1 wins**. In every case the draft's claim that "the coordinator's O3 hypothesis survives" no longer holds. At most the ADR can say the rubric can't separate O1 and O4 and that O3 trails both.

**What could honestly restore O3:**

1. A stage-1 prototype showing that exclusivity checking (static plus dynamic for identity fields) and CoW uniqueness are cheap for the agent to build. That would reverse B.
2. Learnability evidence that value-default semantics reduce novice errors enough to outweigh having two type kinds. That would reverse A.
3. A concrete G11 scenario that O3's identity type handles and O4's `shared` kind cannot. I couldn't construct one. That would reverse C.

**Process note for the ADR author.** The draft's sensitivity analysis is good, but it only tests changes the author considered. All three changes in this review come from *cross-option consistency*: the same mechanism must get the same score wherever it appears. A one-paragraph consistency check per criterion would have caught them.

---

## Sources checked for this review

- Choi, Shull, Torrellas, *Biased Reference Counting*, PACT 2018: https://docs.rs/crate/biasedrc/latest/source/paper.pdf
- SE-0176, *Enforce Exclusive Access to Memory*: https://github.com/apple/swift-evolution/blob/master/proposals/0176-enforce-exclusive-access-to-memory.md
- Swift Forums, *Enabling run-time exclusivity checking in release mode*: https://forums.swift.org/t/enabling-run-time-exclusivity-checking-in-release-mode/17626
- Swift Forums, *A pitfall with value type + escaping closure*: https://forums.swift.org/t/a-pitfall-with-value-type-escaping-closure/50161
- Apple, *Choosing Between Structures and Classes*: https://developer.apple.com/documentation/swift/choosing-between-structures-and-classes.md
- InfoWorld, *First look at Mojo 1.0*: https://www.infoworld.com/article/4173158/first-look-at-mojo-1-0.html
- Mojo manual, *Ownership*: https://mojolang.org/docs/manual/values/ownership/
- Inko manual, *Memory management*: https://docs.inko-lang.org/manual/latest/getting-started/memory-management
- Inko manual, *Concurrency*: https://docs.inko-lang.org/manual/main/getting-started/concurrency
- Inko 0.11.0 release notes: https://inko-lang.org/news/inko-0-11-0-released
- PHP Internals Book, *Memory management*: https://www.phpinternalsbook.com/php5/zvals/memory_management.html
- OpenJDK Project Valhalla, *Value Classes and Objects*: https://openjdk.org/projects/valhalla/value-objects

Not independently checked: the Shahriyar et al. "16% cyclic" figure, the Bronze trial counts, and the notes' tractability ranking (taken from the ADR's own text). None of my revisions depends on the first two.
