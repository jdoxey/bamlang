# Amendment 1 step 3 lessons and pre-review scores (Opus)

Examples are in `docs/examples/types/inherit/`. The ADR-0005 benchmark is rewritten under each finalist, plus three
additions: a widget that is also saveable, a `List of Str` subclass that logs, and a template method. A 3 am resolver
classifies every method call, a checker has 36 bad files, and a C model of each option's dispatch is included.

## The resolver (every call on a class type)

| | Calls | Static-up | Dynamic-down (`dyn` / self) | Average candidates | Max candidates | Max steps up |
|---|---|---|---|---|---|---|
| H1 | 44 | 21 | 23 (12 / 11) | 1.91 | 5 | 3 |
| H2 | 42 | 22 | 20 (12 / 8) | 1.79 | 4 | 3 |
| H3 | 44 | 24 | 20 (12 / 8) | 1.89 | 5 | 3 |

The 12 `dyn` sites are identical in all three. The finalists differ only in how self-calls dispatch.

## What the code taught

- **Closed recursion (H2, H3) fails silently, which is the opposite of the 3 am goal.** `CountedNames` overrides
  `push`, and `LoggedAll.push_all` calls `self.push`. Under closed recursion three of four pushes went uncounted. A
  reader of `CountedNames` sees `override fn push` and reasonably expects every push to be counted. A forgotten
  `hook` gives no error; the checker can only warn when it spots the pattern.
- **Open recursion (H1) behaves as the reader expects** (every push counted). The cost: 3 more dynamic self-call
  sites, and the classic fragile-base risk. That is mitigated by the required `override`, by no hiding, and by
  built-ins that never call their own overridable methods.
- **The two-roles case is the real cost of single inheritance.** `SaveableButton` needs a field, three forwarding
  methods and a snapshot `as_saveable()`, because a live borrowed view of a second role can't be expressed under
  ADR-0001. H2 handles it as one object, but a name present in both parents must be overridden and disambiguated
  with `super(P)`, and the reader must search two chains.
- **Built-in subclassing works under every option.** It depends on a documented primitive set: the built-in
  `push_all` never calls `push`, so a logging subclass must override both.
- **Gaps found:**
  - there is no `protected` (`Panel.children` had to become `pub`);
  - statics aren't inherited;
  - "a value changes its own kind" (`collapse`) has no analogue.

## Scores (`scores.py`)

| Option | 3 am | Owner | Safety | Simple | Ext | Fit | Impl | Total |
|---|---|---|---|---|---|---|---|---|
| **H1 single, open** | 3.5 | 5 | 3.5 | 4.5 | 3.5 | 4 | 4 | **80.5** |
| H3 single, closed | 4 | 4.5 | 3 | 3.5 | 3.5 | 4 | 4 | 76.5 |
| H2 stateless parents, closed | 3.5 | 4 | 3 | 3 | 4.5 | 3.5 | 3 | 70.5 |

- **H1 and H3 tie** (a gap of 4). H1 still leads with the 3 am test weighted 35 (77.5 against 75.5), corrected per review m1.
- **The examples break the tie for H1:** the silent miscount under closed recursion is a 3 am failure in behaviour,
  not in lookup.
- **The reviewer attacks H1.**
