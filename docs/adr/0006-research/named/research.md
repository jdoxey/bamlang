# Amendment 1 research: always-labelled arguments (Sonnet researcher, 2026-11-14; condensed)

[unverified] marks claims without a fetched source. The Swift Book pages rendered empty, so the notes cite proposals.

## Per language

- **Swift.**
  - Guidelines (https://www.swift.org/documentation/api-design-guidelines/):
    - omit labels when arguments can't be told apart (`min(a, b)`, `zip`);
    - defaulted arguments always get labels;
    - "clarity is more important than brevity".
  - SE-0046 (https://github.com/swiftlang/swift-evolution/blob/main/proposals/0046-first-label.md) made the first label
    uniform. "First parameter is special" was an accident that needed a migration to remove.
  - SE-0111 (https://github.com/swiftlang/swift-evolution/blob/main/proposals/0111-remove-arg-label-type-significance.md)
    removed labels from function types:
    - a value typed `(ofHits:forRuns:)` could hold a function whose parameters meant something else;
    - labels belong to declarations, not types;
    - calls through function values are positional.
  - A request for `f(foo, bar)` to mean `f(foo: foo, bar: bar)`
    (https://forums.swift.org/t/omitting-argument-labels-in-function-calls-with-matching-argument-names/64427) was
    rejected, because an unlabelled overload could change its meaning.
- **Objective-C and Smalltalk** (https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/DefiningClasses/DefiningClasses.html):
  - labels are part of the selector, and the order is fixed;
  - the method name must read as a phrase (`at:put:`).
- **OCaml** (https://ocaml.org/manual/5.2/lablexamples.html):
  - `~x` puns `~x:x`, and labelled arguments commute;
  - free order plus partial application forces labels into types: a higher-order function that applies arguments in
    another order fails, and optional arguments need annotations and a trailing non-optional argument.
- **C# and Kotlin**
  (https://learn.microsoft.com/en-us/dotnet/csharp/programming-guide/classes-and-structs/named-and-optional-arguments,
  https://kotlinlang.org/docs/functions.html):
  - names are optional, any order, evaluated in call-site order;
  - parameter names become an unplanned public API;
  - Kotlin can't name Java (FFI) arguments.
- **Python:**
  - PEP 3102 (https://peps.python.org/pep-3102/) added keyword-only parameters;
  - PEP 570 (https://peps.python.org/pep-0570/) added positional-only `/`, because renaming a parameter broke keyword
    callers and builtins like `pow` never took keywords.
- **Dart** (https://dart.dev/language/functions): named parameters are opt-in (`{required x}`), in any order.
- **Punning precedent:**
  - Rust `User { username, email }` (https://doc.rust-lang.org/book/ch05-01-defining-structs.html);
  - JS `{a, b}`;
  - OCaml `~x`.

## Lessons for "every argument labelled, one name per parameter"

1. **No language labels every call with zero exemptions;** the nearest is Smalltalk/ObjC, where the name is a phrase.
   Verbosity on `print`, `max(a, b)` and one-argument calls is the known cost. No study measures it, so our corpus
   rewrite is the evidence.
2. **Renaming a parameter breaks every caller.** That is accepted, and it must be a compile error, never a silent
   change.
3. **Labels in function types (pre-SE-0111) were abandoned by Swift.** Labels on function values are the design fork.
4. **Swift's objection to punning was ambiguity with unlabelled calls.** With no positional form at all, `f(x)` has only
   one reading, so the objection does not apply.
5. **Free order** brings OCaml's and C#'s evaluation-order and inference problems. Fixed order has none of them.
6. **FFI functions** need declared names (D9/M-phase).
