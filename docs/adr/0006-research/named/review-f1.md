# Adversarial review of F1 (Fable 5.2 reviewer, 2026-11-14; condensed)

**Verdict:** accept F1 only with fixes 1-6 (the result is F1b). As written F1 scores 67, behind F3 at 70. F1b scores 75.

1. **FATAL.** Forced lambda names break the no-shadowing rule (`map(each: fn(item) => item.cells.filter(keep: fn(item) => …))`).
   - **Fix:** lambda parameters are free names bound by position. The type's names label only calls through the value.
2. **SERIOUS.** Positional patterns versus labelled construction give the swap bug (`Rect(h, w) => …` binds h to the
   w field).
   - **Fix:** a binder that equals a *different* field's name is an error. Add a multi-field variant to the corpus.
3. **SERIOUS.** The pun accepted `f(Red)`, `f(self)` and `f((x))`.
   - **Fix:** a pun is one lowercase identifier token, and not `self`.
4. **SERIOUS (readers).** `draw(y)` with `fn draw(x = 0, y = 0)` looks positional. No silent mis-binding was found.
   - **Fix:** state that `f(x)` never means "first parameter"; the error suggests `count: n`.
5. **SERIOUS.** F1 silently decides D7: no positional items, so D2 "variadic" dies. `print(text: 3)` has the wrong
   name, and the print-concat allowance turned `print(1, 2)` into `1 + 2`.
   - **Fix:** no variadics; `print` takes one `Str`; say so in D7.
6. **SERIOUS.**
   - **Interfaces.** An impl's parameter names must equal the iface's.
   - **Identity.** Function-type identity by names costs a wrapper lambda, recorded as traded away.
7. **MINOR.** Declaration order costs DSL writers and evolution. Keep it; the error prints the corrected call; revisit
   in D7.
8. **MINOR.** List every unlabelled form: the receiver, key arguments, patterns, the pun, `try … context`. Reject
   duplicate keys.
9. **MINOR.** Stutters (`print(text:)` 83 of 462 labels).
   - **Library rule:** the natural operand is the receiver (`x.clamp(low:, high:)`, `a.max(other: b)`).
   - **D9:** FFI declarations name every parameter.
10. **SERIOUS (evidence).** +6% is over whole files: code only is +8.0%, and without strings +9.5%. Lines over 100
    columns go from 23 to 32. The punned corpus was never written.
11. **SERIOUS (evidence).** `same_meaning.py` accepted capturing, non-injective and field-leaking renames, `+`
    concatenation as addition, and wrong or reordered labels.
    - **Fix:** repair it, and add a label-versus-declaration check.
12. **MINOR.** Interpolation works; add `"{pad(text: a, width: 3):>5}"` to the corpus.

## Corrected scores (applied to `scores.py`)

| Option | Owner | Simple | Read | Brevity | Evolve | Impl | Total | Owner 10 / brevity 30 |
|---|---|---|---|---|---|---|---|---|
| **F1b** | 4 | 4 | 4 | 3 | 3 | 4 | **75** | 72 |
| F3 | 3 | 4 | 4 | 3 | 3 | 4 | 70 | 70 |
| F1 as written | 4 | 3 | 4 | 3 | 2 | 3 | 67 | 64 |
| F2 | 2 | 3 | 4 | 5 | 2 | 4 | 65 | 74 |
