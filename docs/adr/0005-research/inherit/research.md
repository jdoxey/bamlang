# Amendment 1 research: inheritance and "find where it is implemented" (Sonnet researcher, 2026-11-14; condensed)

[unverified] marks claims without a fetched source.

## Single or multiple inheritance

- **C++:** a diamond gives two base subobjects unless the base is `virtual`; members are qualified to disambiguate
  (https://en.wikipedia.org/wiki/Multiple_inheritance).
- **Python's C3 MRO:** an order conflict is an error, and the reader has to compute the MRO to know where `super()`
  goes (https://docs.python.org/3/howto/mro.html).
- **Eiffel:** clashes are resolved in the heir (`rename`, `redefine`, `select`), and `Precursor {P}` calls the
  parent's version (https://www.eiffel.org/doc/eiffel/ET-_Inheritance).
- **Mixins and traits** (Scala, Ruby, Dart, https://dart.dev/language/mixins) add a second, linearised axis.
- **Single inheritance gives a linear chain:** "this class or an ancestor" is literally true. Every multiple scheme
  needs a rule saying which method wins.

## Overriding

- **The fragile base class** (https://en.wikipedia.org/wiki/Fragile_base_class) comes from open recursion through
  `this`. The listed mitigations: a required `override`, `final`/`sealed`, and static self-calls unless requested.
  Bloch: "design and document for inheritance or else prohibit it".
- **Kotlin** is final by default, needs `open`, and requires `override`. It warns against calling open members in
  constructors (https://kotlinlang.org/docs/inheritance.html).
- **The C# `new` trap:** hiding compiles with only a warning, so one name resolves by static type
  (https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/keywords/new-modifier).
- **Java's `@Override` is optional,** so a base rename silently orphans an override [unverified].

## Subclassing built-ins

- **Java `InstrumentedHashSet`:** `addAll` calls `add`, so overriding both double-counts (Effective Java item 18, via
  search).
- **CPython's built-in methods skip overridden `__getitem__`,** hence `UserDict`/`UserList`. The fast paths are
  inconsistent (https://docs.python.org/3/library/collections.html,
  https://discuss.python.org/t/dict-copy-optimization-causes-surprising-behavior-for-subclasses/7201).
- **Either way, the reader can't predict which overrides run.** The way out is a documented primitive set, or no
  self-dispatch inside the built-ins.

## Value semantics

- **Slicing:** a derived object copied into a base variable loses its derived part
  (https://en.wikipedia.org/wiki/Object_slicing).
- **For owned values:** a plain `Base` value means exactly that class. Only a boxed `dyn Base` holds a subclass, so
  slicing can't happen, and `dyn` marks where a reader must look *down*.

## Comprehension evidence

The evidence is mixed. Daly et al. 1996: 3 levels were faster to maintain than flat code, and 5 levels slower but not
significantly (https://strathprints.strath.ac.uk/id/eprint/2677). The Harrison et al. 2000 replication reportedly
favoured flat code (https://researchr.org/publication/HarrisonCN00/bibtex). The Prechelt replications found effort
hardly correlated with depth (https://ps.ipd.kit.edu/838.php). This supports a soft depth lint at most.

## Two roles

A widget that is also serialisable needs one of:
- multiple inheritance of abstract classes (Eiffel, C++, Python ABCs);
- mixins;
- a forwarding field under single inheritance (Bloch's composition).

## Choices ranked for the 3 am test

1. single inheritance;
2. a mandatory `override`;
3. no hiding;
4. closed recursion by default, or no self-use in the built-ins;
5. `dyn` at every dynamic site;
6. explicit `super.m()`;
7. a tool listing the overrides and resolution of each class;
8. a soft depth lint;
9. built-ins that can be subclassed, with a documented primitive set.
