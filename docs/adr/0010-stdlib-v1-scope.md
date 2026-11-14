# ADR-0010: Standard library v1 scope

- **Status:** Accepted
- **Date:** 2026-11-14
- **Tier:** Light (see `docs/PROCESS.md`)
- **Decided by:** Claude (ruling R7). John may veto by opening an issue.

## Context

G6 asks for "a good standard library with Lists, Arrays, Time, Calendar, etc." Earlier ADRs passed on the container
quality bar (0002), `Error` kinds and helpers (0004), the DSL libraries (0007) and subclassing primitive sets (0005
amendment 1). This scope is cheap to grow later, so the decision is Light.

## Decision

1. **Built-in classes and their primitive sets.** For subclass instances, every other method goes through these.
   - **List:** `push`, `insert`, `remove_at`, `get`, `set`, `len`.
   - **Array** (fixed length): `get`, `set`, `len`.
   - **Deque:** `push_back`, `push_front`, `pop_back`, `pop_front`, `get`, `set`, `len`.
   - **Map, SortedMap and Lru:** `get`, `set`, `remove`, `len`, `entries`. Lru adds `capacity`.
   - **Set:** `add`, `remove`, `contains`, `len`, `items`.
   - **Heap:** `push`, `pop`, `peek`, `len`.
   - **Str** is UTF-8 and immutable. Its primitives are `bytes` and `len_bytes`. Chars, graphemes and lines are
     derived methods, and their names say what they count.
2. **Quality bar** (M6 exit). Every container ships with documentation stating each method's complexity, conformance
   tests, and a CI benchmark against C++ `std::` and Rust `std` equivalents. The target is within 1.5× at `-O2` on all
   three OSes for push/get, insert/lookup and sort, with any miss reported in CI.
3. **`std` modules in v1:**
   - **Core:** `core` (numbers, `Str`, `Optional`, `Result`, `Error`, `Report`, `Txn`), `text`, `math`, `random`.
   - **System:** `fs`, `path`, `io` (buffered), `process` (arguments, environment, exit, child processes).
   - **Time:** monotonic `Instant`/`Duration`; UTC `DateTime` with the OS local offset; calendar `Date` (weekday,
     ISO 8601, month and day arithmetic).
   - **Other:** `sync` (Mutex, Channel, Atomic, crews), `net` (TCP, UDP, DNS), `json`, `test` (D11), `ffi`.
4. **`Error.kind`** has 12 values: `not_found`, `exists`, `permission`, `invalid`, `parse`, `io`, `timeout`,
   `closed`, `unsupported`, `no_memory`, `trap`, `other`.
   - `try_alloc` returns `no_memory`.
   - `fs.replace(path, bytes)` writes atomically: a temporary file, then a rename.
5. **`extras` in v1** (generic dialect, ADR-0002):
   - `html`: escapes by default (`Text` escapes, `Raw` doesn't);
   - `ui`: retained `Node of M` trees, slots and keys (ADR-0007), with a **terminal renderer only**;
   - `tz`: IANA time zones;
   - `SmallList`, `BTreeMap`, `RingBuffer`.

   ADR-0009's TOML manifest replaces the build DSL library from ADR-0007's examples.
6. **Not in v1:** a native GUI, TLS and HTTP (wait for `extras`), regular expressions, database drivers, and
   serialisation beyond JSON.
7. **Debugger formatters** (M7, ADR-0008 rule 6). gdb, lldb and natvis show List, Array, Map, Set, Str, Handle
   (target or "stale"), enums (the active variant only) and `dyn` (the concrete class).

## Consequences

Every G6 item is covered, and subclassing (issue #5) is defined for every container. v1 can't serve HTTPS or a
desktop GUI. The benchmark bar is the riskiest M6 commitment. Add modules by a later Light ADR when two real programs
need them (ADR-0002's "add a shape" rule).
