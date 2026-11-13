# D7 research: DSLs and declarative layout (Sonnet researcher, 2026-11-13; condensed)

**[unverified]** marks claims without a fetched source.

## What G11 is (closes Q15)

Every system needed the host language's control flow inside nested trees:
- Flutter keeps UI in code, not markup, so that loops and conditionals work (https://docs.flutter.dev/resources/faq).
- Compose is "just Kotlin" (https://developer.android.com/develop/ui/compose/mental-model).
- JSX exists to keep logic and markup together (https://react.dev/learn/writing-markup-with-jsx).

**Recommendation:** G11 means syntax for nested declarative data (config, UI trees, test specs, HTML). A UI framework
is a library that stress-tests it, not a language feature.

## Per system

**SwiftUI result builders.**
- **Mechanism:** `@resultBuilder` rewrites a block into `buildBlock` and `buildEither` calls
  (https://github.com/swiftlang/swift-evolution/blob/main/proposals/0289-result-builders.md).
- **Problems:** it is an annotation (fails G3); type-checking blew up exponentially; "unable to type-check this
  expression in reasonable time" hides real typos (https://developer.apple.com/forums/thread/793866); `AnyView` hurts
  diffing (https://wwdcnotes.com/notes/wwdc23/10160).
- **Kernel:** `@State` storage is owned by the framework, outside the view.

**Kotlin type-safe builders** (https://kotlinlang.org/docs/type-safe-builders.html).
- **Mechanism:** lambdas with a receiver; members are in scope unqualified; text is added with `+"text"`.
- **Problems:** it needs `@DslMarker` (an annotation) to stop `head { head { } }`; implicit scope works against R6;
  construction is imperative behind a declarative look.

**Jetpack Compose.**
- **Mechanism:** an `@Composable` compiler plugin; functions may run in any order, or be skipped
  (https://developer.android.com/develop/ui/compose/mental-model).
- **Problems:** the purity contract is unchecked; versions are coupled.

**Gradle Kotlin DSL** (https://docs.gradle.org/current/userguide/kotlin_dsl.html).
- **Benefit:** better typing than Groovy.
- **Problems:** slow first compile; string-name fallbacks; IDE dependence; painful migrations
  (https://msfjarvis.dev/posts/why-i-went-back-to-the-gradle-groovy-dsl).
- **Lesson:** config should be typed data, not an executed script.

**Flutter.**
- **Mechanism:** plain constructors with `child:` and `children: [...]`, the same shape as our `Name(field: v)`.
- **Staircase:** Flutter's own blog admits the deep nesting and recommends naming subtrees and a formatter
  (https://flutter.dev/blog/out-of-depth-with-flutter).
- **Control flow:** collection-`if` and `for` inside list literals [unverified].

**Elm** (https://guide.elm-lang.org/architecture/).
- **Mechanism:** `div attrs children`; the view is a pure function of the model; events are message values; `update`
  produces the next model.
- **Fit:** messages-as-data avoid stored closures that borrow, which fits ADR-0001 rule 3.

**QML, JSX and XAML.** A second language or grammar. QML uses braces for objects, which conflicts with ADR-0006.

**Ruby blocks and `instance_eval`.** Dynamic `self`, so the meaning of a bare name depends on context (fails R6)
(https://guides.rubyonrails.org/routing.html).

**Lua tables.** One untyped data syntax.

**Nim and Rust macros.** Excluded by G3.

**Zig and Odin.** No DSL support: "no hidden control flow" (https://ziglang.org/learn/overview/). This is the baseline
to beat.

## Cross-cutting

- **Trailing closures.** Swift forbids them in `if` and `while` conditions, because `{` could be the body
  (https://lists.swift.org/pipermail/swift-evolution/Week-of-Mon-20160321/013244.html). Its SE-0286 forward-scan rule is
  a heuristic. Our `if x = opt {` has the same collision, so any trailing block must never appear in header position.
- **Receivers versus parameters versus data.** A receiver lambda is the shortest but implicit. An explicit builder
  parameter is visible but noisy. Pure values make the tree data, at the cost of control flow inside lists.
- **Descriptions plus diffing versus retained trees.**
  - Without GC, descriptions are owned values, allocated per frame (an arena) and diffed against the framework's
    previous tree.
  - Retained trees map to pools and handles.
  - Handlers should be messages or handles, not borrowing closures.
- **State.** Framework-owned slots addressed by handles (`ui.state(key, init)`). Positional or explicit keys is open.

## Six mechanisms

1. **C1** plain constructors (Flutter/Elm).
2. **C2** C1 plus `if`/`for` clauses inside `[ ]` literals.
3. **C3** a trailing block for the last parameter, never in headers.
4. **C4** an explicit builder parameter: `build: fn(b) { b.add(…) }`.
5. **C5** a receiver lambda with nearest-receiver scope, built in.
6. **C6** data first: typed literals for config and tests; HTML and UI as libraries, with a formatter for tree layout.

## Benchmarks

1. **A todo UI.** `for` over items, an `if` placeholder, toggle and delete events as `Msg`, an input with local state by
   handle, and filter tabs from `match`.
2. **A build file.** 3 targets, shared defaults, an OS conditional, and a loop over platforms. A field typo must be a
   compile error with a suggestion.
3. **HTML and a test spec.** A page with a nav and a table from data, with escaping. A suite of 20 cases with nested
   groups and shared setup, where the runner names the failing case.
