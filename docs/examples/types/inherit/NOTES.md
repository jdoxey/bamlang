# Inheritance finalists H1, H2, H3: step 3 examples (ADR-0005 amendment 1, issue #5)

Run `bash run.sh` (Linux, macOS, Git Bash on Windows with clang). It parses the three corpora, runs the checker bad files,
runs the 3 am resolver and compares its table with `expected/table.txt`, builds and runs the C models and compares
transcripts. Last local result (Linux, clang 19, Python 3): `inherit examples OK`. Windows and macOS have not been run by the
author of these files; the script strips CR, adds `.exe`, and defines `_CRT_SECURE_NO_WARNINGS`.

| File | What |
|---|---|
| `parser.py` | copy of `../../syntax/p3n/parser.py` with the inheritance grammar (below) |
| `h1/types.p3`, `h2/types.p3`, `h3/types.p3` | the benchmark (shapes, widgets, `Slider`, container `Tabs`, accounts) plus (a) `SaveableButton`, (b) `LoggedNames`, (c) template method `Labelled` |
| `resolve.py` | per-finalist checker plus the 3 am resolver (`--rules h1\|h2\|h3 FILE [--detail]`, `--all DIR`) |
| `bad/` | 73 bad files: `parse_*` (parser), `h1_*`, `h2_*`, `h3_*`, `h1b_*` (checker; `# expect:` error, `# expect-warning:`, `# expect-clean:`) |
| `cmodel/h1.c h2.c h3.c h1b.c` + `.txt` | C11 dispatch models and their expected transcripts (h1b also runs under ASan/LSan on Linux) |
| `h1b/types.p3`, `h1b/api_v1.p3`, `h1b/api_v2.p3` | H1 with the review fixes (clarification pass, below); a v1/v2 pair for the API diff |

## Grammar additions (`parser.py`)
- `type Name [is X, Y, ...] { ... }`. An item starting lowercase is a built-in capability, `(is show)`; an item starting
  uppercase is a parent type, `(extends (t Widget) (t Saveable))`; the parent may be `List of Str`. The parser accepts any
  number of parents; the checker enforces one (H1, H3) or one stateful plus stateless ones (H2).
- Members of a `type`: `[pub] [override|hook] fn name(...) ...`. `(fn name [pub] [override] [hook] [abstract] [fails] ...)`.
  `override` and `hook` are contextual words (a field may still be called `hook`). Both on one method is a parse error.
- A `fn` inside a `type` with no body gets the flag `abstract` (no block child). Top-level `fn` without a body is unchanged.
- `super.m(args)` -> `(supercall m args...)`; `super(Parent).m(args)` -> `(supercall m (via Parent) args...)`. `super` is now a
  reserved word (29 reserved words).
- `dyn` takes a full type: `dyn Shape` -> `(dyn Shape)` (as before), `dyn List of Str` -> `(dyn List (t Str))`.
- `iface` and `impl` are errors ("is removed"). `pub iface` fails in `pub`'s check.
- No other AST change: `chatsim`, `widgets`, `errors`, `tricky` give byte-identical ASTs to `../../syntax/p3n/expected/`; the
  old `types.p3` is now rejected at its first `iface`.
- Also: `fn` and `type` nodes carry a `.line` attribute (not printed) for the checker's messages.

## Corpus sizes (lines, including comments and blanks)
| | total | `module core` | `module plugin` (what the plugin author writes) | main fns |
|---|---|---|---|---|
| H1 | 302 | 143 | 105 | 54 |
| H2 | 298 | 143 | 99 | 56 |
| H3 | 303 | 143 | 105 | 55 |

The old iface version (`../../syntax/p3n/corpus/types.p3`) is 236 lines without the three additions, which add about 60
lines to each corpus. `Tabs` shrank to 11 lines (it is `is Panel`, so `event` is inherited), while the closed `Widget`
enum with its `Ext` variant and the `match self` dispatchers are gone.

## The 3 am resolver (`resolve.py --all .`)
Every method call in each corpus, from the parsed AST, with a small table for List's methods. `static-up`: walk up from
the receiver's static type (steps = classes walked; 1 means it is on the class itself). `dynamic-down`: a `dyn Base`
receiver, or a self-call that is open (H1) or goes to an abstract or `hook` method (H2/H3): every body in Base and its
concrete subclasses can run. Excluded from "class calls": `Type.new` calls, calls on Str/Int/plain List, derived `show`.

| finalist | class calls | static-up | (super) | (closed self) | dynamic-down | (dyn receiver) | (self-call) | avg cands | avg cands, dynamic only | max cands | max up-steps | type-calls | excluded | warnings |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H1 | 44 | 21 | 2 | 0 | 23 | 12 | 11 | 1.91 | 2.74 | 5 | 3 | 13 | 12 | 0 |
| H2 | 42 | 22 | 4 | 3 | 20 | 12 | 8 | 1.79 | 2.65 | 4 | 3 | 13 | 12 | 1 |
| H3 | 44 | 24 | 2 | 3 | 20 | 12 | 8 | 1.89 | 2.95 | 5 | 3 | 13 | 12 | 1 |

Reading it:
- About 27% to 29% of class calls are `dyn` receivers (12 sites in every corpus). That part is the same for all three.
- The finalists differ only on **self-calls**. H1 makes all 11 of them dynamic (including `Button.event -> self.focus_next()`,
  which has exactly one body in the whole program, yet a reader cannot know that without searching downward). H2/H3 make 3
  of those 11 static; the 8 that stay dynamic are calls to abstract methods or to `hook text`.
- Max up-steps is 3 for all (`Button.event` -> `self.focus_next()` found in `Widget`, three classes up).
- Max candidates is 5 for H1/H3 (`dyn Widget.render` or `.close`: Panel, Labelled, Slider, Tabs, SaveableButton) and 4 for H2,
  because H2's `SaveableButton` inherits `Button`'s `render` instead of forwarding it. The forwarding methods of H1/H3
  (3 methods) add 3 candidate bodies to every `dyn Widget` render/close/event call.
- The checker warns once in H2/H3: `CountedNames.push` is bypassed by `LoggedAll.push_all` (see below).
  `--detail` lists every site.

## LoggedNames: the exact transcripts (from `cmodel/*.txt`)
Program: `a = LoggedNames` (overrides `push`: logs, then `super.push`); `LoggedAll is LoggedNames` (overrides `push_all` as a
loop over `self.push`); `CountedNames is LoggedAll` (overrides `push`: counts `n`, then `super.push`).

| step | H1 (open self-call) | H2 and H3 (closed self-call, `push` is not a hook) |
|---|---|---|
| `a.push("a")` | `log push a` | `log push a` |
| `a.push_all(["b","c"])` | no output: `List.push_all` does not call `push`; `a = [a b c]` | the same |
| `c.push_all(["x","y"])`, `c: CountedNames` | `log push x`, `log push y`; **`c.n = 2`** | `log push x`, `log push y`; **`c.n = 0`** |
| `c.push("z")` | `log push z`; `c.n = 3` | `log push z`; `c.n = 1` |
| `fill(c, ["w"])` (a `dyn List of Str`) | `log push w`; `c.n = 4` | `log push w`; `c.n = 1` |
| final list | `[x y z w]` | `[x y z w]` |

The two rules differ in exactly one place. Under H1, `LoggedAll.push_all` reaches `CountedNames.push` through the object's
vtable, so the counter is right. Under H2/H3 the call goes to `LoggedNames.push`, the counter misses 3 of 4 pushes, and the log
is still complete. The author of `CountedNames` gets no error, only the checker's warning; the cure is for `LoggedAll` to
declare a `hook fn` of its own that `push_all` calls (not possible for `List.push`, which is not ours). Under H1 the opposite
risk is the classic one: if `LoggedAll.push_all` later stops calling `self.push`, or a subclass overrides `push` and calls
`self.push_all`, the loop recurses; nothing in the source of `LoggedAll` shows that.

The built-in `List.push_all` never calls `push` under any finalist (`a.push_all` in the table), so a `LoggedNames` that only
overrides `push` silently logs fewer pushes than a reader expects. A logging subclass has to override `push_all` too. Both
rules need the List documentation to state its primitive set.

## What was awkward
1. **Two roles, H1/H3.** `SaveableButton` can be in a `List of dyn Widget` or in a `List of dyn Saveable`, not both from one
   object. I made it a `Widget` with a `Button` field and three forwarding methods (`render`, `event`, `close`) and a
   `as_saveable()` that returns a *snapshot* `ButtonSaver` (an owned copy). That is not the same thing: a later label change is
   not reflected, and `SaveableButton` is not itself `Saveable`. Returning a live borrowed `dyn Saveable` view of a field is not
   expressible under ADR-0001 without a new rule. Forwarding is also a silent trap: a new abstract method added to `Widget`
   is flagged (the class becomes abstract), but a new *defaulted* method is not forwarded, so `self.button.m()` and
   `sb.m()` can disagree.
2. **Two roles, H2.** `SaveableButton is Button, Saveable` is 8 lines, one object, two views (`cmodel/h2.c`: same pointer, two
   vtables). The cost shows up in `describe`: it exists in `Widget` and in `Saveable`, so the class is forced to override
   it and to pick with `super(Saveable)` and `super(Button)`. The reader of any class with two parents must check every
   method name against both sets; the checker does it, but a human at 3 am has to look in both chains. `super(Button).describe()`
   lands three classes up.
3. **Subclassing List.** The fact that `push_all` does not use `push` is invisible at the use site; see above. Neither rule
   helps, it is only the "primitive set" documentation. A `List` field on `LoggedNames` is also awkward (the subclass *is* the
   list), and `n` in `CountedNames` is a field of a built-in subclass, which needs the built-in layout to be extensible (C model:
   `struct { List l; int n; }`).
4. **H1's open recursion costs a hidden argument everywhere.** Every method of every class needs the dynamic vtable so
   `self.m()` can dispatch (`cmodel/h1.c`: the `vt` parameter on all methods). H2/H3 need it only in methods that contain
   a hook or abstract self-call (the C models still pass it uniformly, for simplicity).
5. **Abstract methods are implicit hooks.** Under H2/H3 a self-call to a bodyless method must be dynamic, so the rule is
   "abstract implies `hook`". The alternative (a compile error: "call to an abstract method must be declared hook") adds a
   word to every template method with no information.
6. **Forgotten `hook` is silent.** `Badge` overrides `text`; without `hook` on `Labelled.text`, `Labelled.render` would not
   call it. The checker only warns when it sees a closed self-call plus an override. Worse, `hook` must be added by the
   *base* author, who cannot know what subclasses want (the Java "design for inheritance" problem, now explicit).
7. **Panel and the closed `Widget` enum.** `collapse` (a `Panel` turning itself into a `Button` with `self = Button(...)`)
   has no analogue: a value cannot change class. I dropped it. `Panel.children` had to be `pub` for `Tabs is Panel` to
   reach it; there is no `protected`, so a field is either public or invisible to subclasses.
8. **Constructors and statics are not inherited.** `Tabs.new` is a separate function; `Tabs(children)` sets the inherited
   field by name. The checker exempts static `fn` from `override` (otherwise every `new` would need `override`).
9. **Hiding vs override.** The checker has one error for both ("already defined in Base: write `override`"). Because `override`
   is required and hiding is an error, the bad files never needed a "hides" case beyond that.
10. **Resolver blind spots.** It is syntactic: it follows declared parameter types, `let` types and return types, and it needs a
    receiver type for every call (it fails on an unresolved one, so nothing is skipped). It knows only `List` as a built-in
    class; Str, Int and others are treated as final primitives. Candidates for `dyn B` are the bodies of concrete subclasses
    in the program, so a plugin added later changes the numbers (the point of the "whole-program dyn check").

## Checker rules (resolve.py), by finalist
- All: unknown parent, cycle, field hiding, missing `override` (also hiding), `override` with no base method, override
  changing receiver mode or parameter names, `super.m()` with no parent method or an abstract one, constructing a type
  with abstract methods left, unknown method on a self or `dyn` receiver.
- H1: `hook` is an error; one parent; `super(P)` is an error.
- H3: one parent; `super(P)` is an error; warning for an override bypassed by a closed self-call.
- H2: only one parent may have fields (a built-in such as List counts as having fields); a method reachable by two different
  bodies from two parents must be overridden (an abstract plus a concrete body also counts); `super.m()` with two parents is
  ambiguous; `super(P)` must name a direct parent; the same bypass warning.

## C models (`cmodel/`)
Objects have no vptr: a plain value is exactly its class, calls on it are direct, and slicing cannot happen. A `dyn Base`
is `{pointer, vtable}`, boxed at the store site. A class vtable has the ancestors' slots first (inherited slots point at the
ancestor's function). `super.m()` is a direct call. The List built-in uses a private `list_append` so that `push_all` never calls
the overridable `push`.
- `h1.c`: every method takes the dynamic vtable; `self.m()` is `vt->m()`.
- `h3.c`: as H1; closed self-calls are direct calls (`Widget_focus_next(...)`, `LoggedNames_push(...)`); abstract and hook
  self-calls (`kind`, `text`, `name`, `area`) stay `vt->`.
- `h2.c`: a class descriptor holds one view vtable per role (`widget`, `saveable`, `shape`, `list`); `SaveableButton` has one
  object and two views (`sw.p == sv.p`; the stateless parent needs no pointer adjustment). Self-calls to hooks are
  `dc->widget->kind(...)`; `super(Saveable).describe()` is a direct call.
- All three also print `QuietButton` (overrides `focus_next`; `Button.click` calls `self.focus_next()`): H1 prints
  `focus stays`, H2/H3 print `focus moves to next` because `focus_next` is not a hook there.

---

# H1b: the clarification pass for H1 (review `docs/adr/0005-research/inherit/review-h1.md`)

H2 and H3 are unchanged. `resolve.py --rules h1b` is H1 plus the checks below; `h1b/types.p3` (359 lines, H1 was 302) is the
benchmark rewritten under it. `bash run.sh` ends with `inherit examples OK`. `parser.py` needed no change.

## What changed, by review item
| Item | Rule (checker unless noted) | Bad files (`bad/h1b_*`) |
|---|---|---|
| F1 | A plain `Base` is exactly Base; only `dyn Base` holds subclasses. Checked at call arguments, `let`/`var` with a type, assignment, `return`, list elements, `Pool.add`, `super:`. Inside a method of `C`, `self` has type `dyn C`: it fits `dyn C` or a `dyn` ancestor only; it can't be stored (`let`, assignment, field, list element); `return self` only from a `take self` method, only as `dyn`; `self.copy()` is virtual and returns an owned `dyn C` (needs `is copy`); `dyn` values expose methods, not fields. | slice_param, slice_let, slice_assign, slice_self_arg, slice_return_self, self_store, dyn_to_plain, plain_list_param, field_through_dyn |
| F2 | `Sub(super: try Base.new(..), extra: 1)`: the base part is one value of exactly the parent type. `super:` is required when the parent chain has fields, rejected when it has none. A literal that names a base field is an error. Private fields (no `pub`) are visible in the declaring module and in subclasses in any module. No object exists until every field without a default is set. `Panel.children` and `Labelled.label` are private again; plugin `Tabs is Panel` and `Badge is Labelled` use them from another module. | super_missing, literal_base_field, literal_missing_field, super_wrong_type, private_field_other_module, private_literal_other_module |
| F3 | See the next section. | take_super_moved, take_super_after, take_super_nested, take_super_expr (+ take_super_ok, clean) |
| S3 | See "Built-ins". | value_parent, enum_parent, map_parent, list_override_sig |
| S5 | `resolve.py ... --exact` and the table below. | (no bad file) |
| S7 | Override = same receiver mode, parameter names, parameter types, parameter modes, return type, `fails`, `pub`; it may not restate a default. `super.m()` only inside `override fn m` (same name). `show/copy/equals/hash` can't be written, only declared with `is`; an `is equals` base makes every subclass field need `equals`. | override_return, override_ptype, override_fails, override_pub, override_pub_widen, override_receiver, override_default, super_other_name, super_outside_override, cap_override, cap_field |
| S2 | `--api`, `--api-diff`, cycle warning. | cycle (expect-warning) |
| S4 | `Pool of dyn Widget` in `h1b/types.p3` (`pools()`). | pool_plain |

Rule changes to keep in mind:
- **Abstract bases and `super:`.** `Labelled` is abstract (it has no `kind`), yet `Button(super: ..)` needs a `Labelled` value.
  I allow an abstract type's literal inside its own static functions only, which makes `Labelled.new` a base-part builder
  (it returns a `Labelled` that can only be handed to `super:`). This is my addition; it is the smallest rule that works,
  not a review item.
- **`super:` forbidden when the parent chain has no fields** (`Circle is Shape` is `Circle(r: r)`), required otherwise. A built-in parent (`List`) is never named: `LoggedNames()`.
- **`pub` now matters for overrides**, so `h1b/types.p3` writes `pub` on every API method (the old H1 file omitted it). Calling a
  non-`pub` method from outside is not checked yet.

## F3: `take self` and drops (`cmodel/h1b.c`)
Each class descriptor has `parent`, `drop_own` (the fields that class declares) and a `tail_drop(obj, dyn, from)` function that
runs the `drop_own` of the dynamic class and its ancestors up to, not including, `from`, **subclass first**.
- `take self` method of class `X`: do its work, then `tail_drop(obj, dyn, X)` (everything below `X`), then drop `X`'s own fields
  that were not moved out. The compiler knows `X`'s moved fields statically (drop flags), so a method that returns `self.label`
  (`into_label`) skips the label and still drops the tail: no double free.
- Plain drop of a `dyn` is `tail_drop(obj, dyn, NULL)`: whole chain, subclass first.
- `take self` override that calls `super.close()`: checker rules: the call is a whole statement (`super.m(..)`, `return super.m(..)`
  or `let x = super.m(..)`) at the top level of the method body, with no `self` in the arguments; no earlier statement moves a
  non-`Int/Float/Bool` field out (`let i = self.icon`, `x = self.icon`); no later statement mentions `self`. `Badge.close` prints
  and then returns `super.close()`; `Labelled.close` drops `Badge.icon`, then `Labelled.label`. `Tag` inherits `close` and
  its `icon` is still dropped (transcript lines 10-13 of `cmodel/h1b.txt`).
- **Contradiction in the brief:** it said "drop my unmoved fields, then the tail" and also "subclass fields first". I followed the
  review's order (subclass fields first), so a `take self` method runs the tail before its own fields.
- ASan + LSan + UBSan on Linux (clang 19): no leaks, no double frees, stderr empty; `run.sh` repeats this and checks the stdout.
  LSan was confirmed live with a deliberate-leak test program.
- Not checked: the checker's move detection is syntactic (a `let`/assignment whose value is exactly `self.f`); moves through a
  call argument are not seen.

## Built-ins (S3)
- **Classes (may be a parent):** the containers (`List`, `Map`, `SortedMap`, `Lru`, `Pool`) and `Str`. Only `List` has a defined primitive
  set so far; subclassing the others is an error ("primitive set is not defined yet") until each gets one.
- **Values, not classes:** `Int`, `Float`, `Bool`, user enums, `Optional`, tuples, `Handle`. `type X is Int` is an error.
- **`List` primitives:** `push(x)`, `insert(at, x)`, `remove_at(at) -> T`, `get(at) -> Optional of T` (also behind `get_mut`), `set(at, value)`, `len()`.
  Every other method (`push_all`, `pop`, `retain`, `is_empty`, `take_out`, `map`, `join`, ...) is *derived*: for an exact `List` it
  takes the direct path; for an instance of a subclass it calls the primitives through the object's vtable. A subclass may also
  override a derived method (`LoggedAll.push_all` does in H1; H1b no longer needs it).
- **Syntax:** `xs[i]` is `get`, `xs[i] = v` is `set`, `for x in xs` is `len` once and `get(i)` for each `i`, a list pattern
  `[a, ..rest]` is `len` plus `get`, `xs += ys` is `push_all`. So a subclass that overrides `get` changes indexing, loops and patterns,
  and one that overrides `push` changes `+=` and `push_all`.
- **C model transcript:** `a.push_all([b, c])` on `LoggedNames` now prints `log push b`, `log push c`. An exact `List.push_all` makes
  0 primitive-slot calls, a `LoggedNames` makes 2. `SortedNames` overrides `push` and `insert`:
  `push_all([pear, apple, fig])` gives `[apple fig pear]`, `insert(at: 0, zebra)` gives `[apple fig pear zebra]`, `retain` and `pop`
  keep it sorted.

## S5, S1 numbers (`resolve.py --all .`; `expected/table.txt`)
| | class calls | dynamic-down | (dyn recv) | (self-call) | static self-calls |
|---|---|---|---|---|---|
| H1 (old corpus) | 44 | 23 (52%) | 12 | 11 | 0 |
| H1b | 58 | 30 (52%) | 16 | 14 | 0 |
| H1b `--exact` | 58 | 25 (43%) | 16 | 9 | 5 |
| T3+ iface/impl (old accepted design) | 25 | 10 (40%) | 7 | 3 | 1 |

- `--exact`: a self-call site stays dynamic only if its method body can be reached with a `dyn` receiver (through a `dyn` call,
  or through open self-calls and `super` calls from such a body). Only 5 of 14 self-call sites became static (`Saveable.describe`,
  `SortedNames.insert`, `SortedNames.push`). The big ones (`Shape.describe`, `Labelled.render/close`, `Button.event`) are reached
  through `dyn Shape`/`dyn Widget`, so they stay dynamic. Exact receivers help classes that are not used through `dyn`; they do not
  change the picture for the base classes that exist to be used through `dyn`.
- **Does not match the review:** the review says 8 of 25 for T3+; this resolver gets 10 of 25: 7 `dyn` receivers plus the 3 self-calls
  inside the provided `Shape.describe` and `Shape.intersects` (the only open self-calls in that design). H1's 63% in the review is for a
  portion of the corpus I did not reproduce; over whole corpora the gap is 40% against 52% (43% with `--exact`).
- `H1b`'s 16 `dyn` receivers (H1: 12) come from the added `show_widget`, `any_widget` and `pools()`. Their candidate counts are
  5 or 6 bodies per `dyn Widget` call, as before.
- Static self-sites in `--exact` rows count as one candidate, so the "avg cand dyn" column rises (3.00 to 3.40) only because the cheap
  sites left it.

## S2: fragile base tooling
`resolve.py --api FILE` lists each `pub` method with the `self.` calls its body makes (open ones; `copy` shows as derived).
`--api-diff OLD NEW` flags every changed self-call set, added method and removed method as BREAKING (exit 1). For `api_v1.p3` ->
`api_v2.p3` (the review's `Labelled.close` change plus an added `title`):

    BREAKING: Labelled.close self-call set changed: -{text} +{}: a subclass that overrides text no longer sees this method call it
    BREAKING: Labelled.title added: a subclass that already declares `title` now fails to compile (`override` missing)

A cycle through overrides (a base `push_all` calls `self.push`; a subclass `push` calls `self.push_all`) is a warning
(`bad/h1b_cycle.p3`). The diff works on the method list of each file; it says nothing about which subclass is hurt (that needs
the whole program).

## S4: pools
`Pool of Button` holds exactly `Button` (`add(value: badge)` is rejected: "write `Pool of dyn Button`"); `with b = buttons[h]` gives
a plain `Button` and static calls. `Pool of dyn Widget` holds a `Button`, a `Slider` and a `Badge`; `with w = widgets[h]` gives a `dyn Widget`
and dynamic calls. Likewise a `LoggedNames` can't be passed as a plain `List of Str` (`h1b_plain_list_param`); a `pub` function that
wants to accept subclasses must say `dyn`. The lint for class-typed `pub` parameters is not written.

## S6: two roles
Unchanged: `SaveableButton` is a `Widget` with a `Button` field plus three forwarding methods and a snapshot `as_saveable()`.
If John answers yes to issue #6 (extra parents that are abstract only: no fields, no bodies), it would read:

    type Saveable { pub fn save(self) -> Str }                          # abstract only: no fields, no bodies, no provided methods
    type SaveableButton is Button, Saveable {                           # one stateful chain (Button), plus abstract parents
      pub override fn save(self) -> Str { return "button:{self.title()}" }
    }

`Saveable.describe` (a provided function) would have to go, or move out as `fn describe(s: dyn Saveable)`; every body still sits
on the `Button` chain, the object has one vtable per abstract parent (as in `cmodel/h2.c`), and a `dyn Saveable` of a `SaveableButton`
is one object, so the "live view" problem disappears. Not implemented in the checker.

## Still awkward
- A literal is checked by class name only: generic arguments (`List of dyn Widget` against `List of Button`) are not compared,
  except for list-literal elements. Casts, `match` on `dyn` and downcasts are not modelled at all.
- Abstract-base construction (above) is an invented rule; a reader meets `Labelled.new` returning an abstract type.
- `dyn` values can't expose fields, so any data a subclass needs from a base must go through a method (`title()`).
- Six primitives mean overriding `get` changes the cost of every loop; there is no way to say "I only want `push`".
- Fragile base risk remains by design; the tooling reports it but cannot prevent it.
- Windows and macOS have not been run by the author of these files (the sanitizer step is Linux only).
