# ADR-0005: Types and object orientation

- **Status:** Accepted
- **Date:** 2026-11-13
- **Tier:** Full (research in `0005-research/notes.md`)
- **Decided by:** Claude (ruling R7). John may veto by opening an issue.

## Context

P-PY: passing `self` makes OO weird. P-C: no native OO. ADR-0001: values have one owner; borrows cannot be stored; identity lives in pools. ADR-0002: no user generics, so polymorphism is by interface. ADR-0004: `Optional`/`Result`. Decide what kinds of user type exist, how methods and `self` work, and whether inheritance exists.

## Charter

| Goal / problem | Effect | Why |
|---|---|---|
| G1, R6 | serves | Two kinds of user type (`type` and `enum`) plus `interface`. A method's effect on the receiver is visible in its signature. |
| G3 | neutral | No generic types; interfaces are not templates. |
| G4 | serves | Methods live in the type body; no receiver parameter. |
| G11 | neutral | Builders and layout need constructors with named fields (D6, D7). |
| P-PY | avoids | No explicit `self` parameter. |
| P-C | avoids | Native methods and interfaces. |
| P-SWIFT | avoids | One struct-like kind, no classes vs structs split, no extensions, no protocols with associated types. |
| P-JAVA | avoids | No inheritance hierarchies. |
| P-RUST | avoids | No traits with generics, no lifetimes. |

## Criteria

R6 (what a method can do to the receiver is readable); fewest kinds of type (G1); answers P-PY and P-C; fits ADR-0001 ownership; reuse without hierarchy; implementation risk.

## Options considered

1. **A. One struct-like `type` with methods inside, structural `interface`, tagged `enum` + `match`, no inheritance (chosen).**
2. **B. Classes with single inheritance + interfaces** (Java/Kotlin). Hierarchies, virtual dispatch, `super`; classic OO.
3. **C. Rust-style `struct` + `impl` + nominal traits.** Methods outside the type; `impl Trait for Type` ceremony.
4. **D. Go-style receivers + structural interfaces + embedding.** Receiver clause is Python's `self` in disguise.
5. **E. Swift-style class/struct/enum/protocol/extension.** Too many kinds (P-SWIFT).
6. **F. Data-only types and free functions** (Odin/C). Fails P-C.
7. **Crazy G. Prototype objects** (JS/Self): objects are maps cloned from others. Dynamic; fails P-C safety.
8. **Crazy H. Everything is an enum with methods.** Unifies shapes but makes plain records awkward.

| | Simplicity 25 | P-PY/P-C 25 | Ownership fit 20 | Reuse 15 | Impl 15 | Total |
|---|---|---|---|---|---|---|
| A | 5 | 5 | 5 | 3 | 4 | 90 |
| B | 2 | 5 | 3 | 5 | 3 | 71 |
| C | 3 | 3 | 5 | 4 | 3 | 70 |
| D | 4 | 4 | 5 | 4 | 4 | 82 |
| E | 1 | 4 | 3 | 5 | 2 | 59 |

A beats D by 8, more than the 5-point tie band.

## What the real examples taught

The chatsim models (`docs/examples/chatsim/`) all had the same shape: a `User` with a name, a room handle, a callback; a `Room` with a member list of handles and a history. In every model the callback was a free function taking `(world, self-handle, from, text)`; the only thing "method-like" was `post(room, ...)`. The Rust O4 model's callback had to be moved out of the user before being called (case 20), which shows that **a stored behaviour should be an interface value or function value, called with the world as an argument**, not a method on the object that stores it.

Illustrative syntax, superseded by ADR-0006 (methods are written with `fn`/`mut fn`):

```text
interface MessageHandler { receive(world mut World, room Handle of Room, from String, text String) }

type Room {
    name String
    members List of Handle of User
    history List of String

    post(from String, text String) {      // `self` implicit; fields visible by bare name
        history.add(text)
    }
}
```

## Decision

Adopt **A**.

1. **`type Name { fields; methods }`** is the one record kind. Fields are values owned by the record (ADR-0001). Methods are declared inside the body. `self` is implicit: fields and other methods are visible by bare name; the keyword `self` names the whole value when needed. A local or parameter may not shadow a field (compile error).
2. **Receiver mode is visible in the signature.** A method that changes the receiver is marked `mut` (as parameters are at call sites, ADR-0001 rule 2). Methods without `mut` cannot change the receiver. Methods borrow the receiver for the call; they can consume it with `take`.
3. **`enum Name { A, B(x Int), C(name String) }`** is the tagged union. `match` is exhaustive. Variants hold owned values. `Optional` and `Result` follow this shape but are built-in (ADR-0002).
4. **`interface Name { method signatures }`** is structural: any type with matching methods satisfies it. A variable or field of interface type owns a value of some satisfying type (boxed by the compiler); parameters of interface type borrow. Allocation happens where a concrete value is first converted to the interface type, and is spelled in the source as that conversion.
5. **No inheritance.** Reuse is by composition: a type may *embed* another by listing it as an unnamed field, which forwards its methods. Embedding is the only reuse feature; if D6 examples can avoid it, it is deferred.
6. **No constructors or destructors.** A value is built by naming its fields (`Room(name: "x")`); defaults come from field initialisers. A user type has no finalizer (ADR-0001, ADR-0004).
7. **No user generics** (ADR-0002); interfaces and the built-in containers carry polymorphism.
8. **Visibility** is decided with modules in D9. Until then everything is public.
9. **Operators on user types** (`==`, `<`, `+`): not overloadable in v1. `==` is structural for built-in-comparable fields only.

## Consequences

- Easier: classic method-call syntax with no `self` noise; closed `enum` + `match` for variants; one record kind.
- Harder: no implementation inheritance, so frameworks that rely on it need composition; embedding forwarding rules must be specified precisely (D6); boxed interface values cost an allocation.
- Rules out: classes, subtype polymorphism by hierarchy, `extension`, operator overloading, generics.

## Syntax budget impact

Keywords: `type`, `enum`, `interface`, `match`, `mut`, `self`, `take`. No annotations. Constructors by field names, `X of T` from ADR-0002.
