# ADR-0007 research notes (DSL and declarative layout)

URLs from memory of primary sources; not re-fetched this session.

| System | Mechanism | Lesson |
|---|---|---|
| Kotlin | Lambdas with receiver; `@DslMarker` stops outer receivers leaking inward. https://kotlinlang.org/docs/type-safe-builders.html | Proven, small, no macros. The leak problem needs a rule. Gradle Kotlin DSL and kotlinx.html use it. |
| Swift / SwiftUI | `@resultBuilder` annotation, `some View`, property wrappers | Powerful but annotation-based (G3) and notorious for type-checker blowups and opaque errors (P-SWIFT). https://docs.swift.org/swift-book/documentation/the-swift-programming-language/attributes/ |
| Flutter / Dart | Plain constructors with named arguments and list literals | No special feature; deep nesting and trailing commas; formatter-dependent. https://docs.flutter.dev/ui/widgets-intro |
| Ruby | Blocks and `instance_eval` | Very flexible, no static checking. |
| Lisp / Clojure | Macros | G3 forbids. |
| QML / Jetpack Compose | QML is a separate declarative language; Compose uses annotations (`@Composable`) | Separate language doubles learning (G1); annotation again G3. |
| Zig / Odin | Plain structs and calls | No DSL support. |
| Gradle Groovy | Closures with delegate | Same idea as receivers, dynamic. |

Lessons: (1) named arguments, field defaults and trailing closures cover Flutter-style trees for free; (2) lambdas with receiver is the smallest feature that gives nested block DSLs, and needs the innermost-only scope rule; (3) annotation and macro routes are out by G3.
