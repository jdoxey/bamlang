# Analysis 14: Everything Is a Path (heapfs)

Analyst verdict: **Kernel worth stealing.** Total **55 / 100**.

## 1. The idea in three sentences

Every object sits at exactly one place in an ownership tree. The tree is shaped like a filesystem: fields are entries, the parent is `..`, assigning to an owning field is `mv`, and the previous occupant is `rm -r`'d. Locals are scope-bound, counted handles that pin their object even after it is removed ("unlink while open"). Anything an object remembers but does not own is a *link*: a path that is re-resolved by name on every use, and that may find a different object or `missing`. Threads get separate namespaces and share through `mv`, frozen `ro` mounts, or `lock` mounts.

## 2. Prior art

Every piece exists, and the closest piece is in wide production use.

- **Godot's scene tree** is nearly this object model already: each node has a single parent, `NodePath` is absolute or relative (`..`), `get_node` returns null when nothing is at the path, and `queue_free` frees a whole subtree. https://docs.godotengine.org/en/4.2/classes/class_nodepath.html, https://coddy.tech/docs/gdscript/scene-tree. Godot users know the failure modes well: paths break after a reparent or rename, and nodes come back null.
- **Unreal soft object pointers.** `TSoftObjectPtr` is a path-based reference resolved lazily, so it can be null or be redirected. https://docs.unrealengine.com/4.26/en-US/API/Runtime/CoreUObject/UObject/TSoftObjectPtr/, https://dev.epicgames.com/documentation/unreal-engine/referencing-assets-in-unreal-engine?lang=en-US
- **MUMPS globals.** The language's entire data model is a hierarchical, path-subscripted tree. https://github.com/rochus-keller/MUMPS/blob/main/docs/MUMPS_Primer.adoc, https://en.wikipedia.org/wiki/Multidimensional_hierarchical_toolkit
- **Plan 9 per-process namespaces and bind/mount.** https://pdos.csail.mit.edu/6.828/2006/lec/l-plan9.html, https://members.loria.fr/EJeandel/posts/plan9/
- **Erlang registered names.** You send to a name, and a restarted process takes over that name. This is late binding with silent retargeting, and the mailing list has threads about atomically replacing a named process and about pid reuse. https://erlang.org/pipermail/erlang-questions/2014-June/079477.html, https://erlang.org/pipermail/erlang-questions/2020-July/099751.html

**Assessment.** As a memory model this is round 1's "single owner + non-owning refs" (the author says so in §9). The non-owning refs are Godot NodePaths instead of auto-cleared pointers. Rule 7 (closures go `missing`) is round 1's "callbacks become no-ops". The new parts are three: making by-name binding the *only* non-owning reference, the leaf-only-counting argument for acyclicity, and mounting the heap as a filesystem for debugging.

## 3. Soundness: counterexamples

*All code below is illustrative only — not a syntax decision.*

**C1. Deleting from a list retargets every row's callbacks (data loss).** A list of objects is an index array, so the path *is* the index.
```
for i in 0..inbox.len { rows[i].del.onTap = { inbox[i].delete() } }  // links "/app/inbox/0".."/n"
// user taps Delete on row 2 -> rm /app/inbox/2 -> old 3 becomes 2, old 4 becomes 3 ...
// user taps Delete on (old) row 3 -> link /app/inbox/3 now names old #4 -> wrong email deleted
```
Sorting is just as bad, because it is a `mv` of every element. The only fix is stable keys for all collections of objects, and then every list is a Map with user-invented keys. That is a hidden rule.

**C2. Callbacks wired in a constructor are dead on arrival.** This is the main G11 pattern.
```
class Editor { init(win) { win.toolbar.save = Button("Save", onTap: { self.save() }) } }
/app/docs/readme = Editor(win)   // during init, self lived at <caller>/~/tmp1
// The closure captured link "<caller>/~/tmp1". Placing the editor moves it; ~ is then rm'd.
// The Save button returns `missing` forever, and the dispatcher ignores it silently.
```
The same thing happens for `count = 0; Button(onTap: { count += 1 })` when `count` is a local, which is the canonical declarative-UI counter. Rule 7 needs the captured object to be placed already, at a stable path, *before* the closure is created. The language cannot check that without escape typing.

**C3. Silent no-op save.** The editor gets replaced or moved, the link goes `missing`, and the dispatcher drops the tap. The user believes the file was saved. This is the same weakness round 1 recorded for "callbacks become no-ops".

**C4. A path built from data is a traversal bug.** Scenario (d) builds `last = "/app/cache/entries/{k}"`. Suppose the cache is keyed by URL: `k = "https://x.com/a/b"` splits into four path components. Suppose `k = "../../config"`: `last` now resolves to `/app/config`, and `cache.entries[k] = fetch(k)` may overwrite it. The heap inherits the path-injection bug class. It needs either an escaping rule or typed path components (another rule).

**C5. The inline cache is unsound for name semantics.** §5 describes the fast path as "one `gen` compare". But `gen` is only bumped on `rm`, and only on the root of the removed subtree.
```
link L = "/app/docs/readme"       // cache = (readme*, g)
mv /app/docs /app/archive         // no node under docs is rm'd, so no gen bumps
L.open()                          // cache hit returns the object now at /app/archive/readme
                                  // rule 6 says it should be missing (or whatever /app/docs/readme is now)
```
The same happens when an ancestor is replaced while a handle pins the old one: its children are never unlinked, so their `gen`s never change. A correct check has two options:
- Validate every ancestor on each lookup: O(depth) per follow.
- Use a namespace-wide epoch: every `mv` or `rm` in a busy UI invalidates every link cache.

The claim that it costs the same as O6 is therefore false. Memory safety still holds, because the pools are type-stable. Rule 6 or the performance claim has to give.

**C6. `ro` mounts race and break the no-cycles argument.** A worker opening a frozen node does `opens++`, while the owner thread opens the same shared node. Only `lock` mounts are specified as atomic, so this is a non-atomic race on the counter, which leads to an early free and then a use-after-free. Btrfs-style copy-on-write also shares unchanged *interior* nodes between the live tree and the snapshot. That amounts to hard-linking directories:
- `..` and `owner` become ambiguous.
- Shared directory nodes need reference counts.

The "only leaves are counted" property fails exactly where threads share. The result is still acyclic, because it is immutable, so this can be fixed. The fix: atomic counts on frozen nodes, and handles that carry the path they were opened through, like a Plan 9 chan.

**C7. Lock mounts deadlock implicitly.**
```
T1: open /stats as s { notify(s) }        // notify follows link "/config" internally
T2: open /config as c { log(c.stats) }    // log follows link "/stats" internally
```
Each thread holds one lock and implicitly follows a link into the other's mount, so neither can proceed. Following a link takes the lock invisibly, so path ordering cannot be enforced. A lock is also held for as long as the handle lives, which includes blocking channel receives inside that scope.

**C8. Assigning a field steals the object.** Rule 3 makes `self.selected = model.items[i]` a `mv`. The item leaves the list, the indices shift (C1 again), and every link to it breaks. The programmer has to declare `selected: link`, and then has to know which fields own and which link. That is Rust's owner-vs-borrow distinction moved to field declarations and checked at run time. The return rule is ambiguous in the same way. Does `fn current() { return self.doc }` move the doc out of `self` ("returning is mv"), or return a handle? Either answer is an extra rule.

**C9. Writes to orphans are silently lost.** A callback removes the editor while `save()` higher up the stack still holds a handle to it. That handle keeps editing the unlinked orphan, and those edits are freed at scope exit. Nothing goes wrong with memory, but the data is gone.

**C10. Leaks.** Nothing leaks structurally, because handles follow a stack discipline and links are not counted. But everything long-lived has to be *named*, so programs drift toward `/app/...` globals, registries that never get cleaned up, and logical leaks. `du` makes these visible, which helps.

## 4. Scenarios

| | Verdict | Note |
|---|---|---|
| (a) growing list | **works** | Value list plus move-on-return. |
| (b) parent pointers | **works** | `..`/`owner` is structural and free. The best answer to (b) seen so far. |
| (c) UI callback | **partial** | Works only when `self` is already placed at a stable path. Constructor wiring dies (C2), list rows retarget (C1), failures are silent no-ops (C3). |
| (d) shared cache | **partial** | Treating a dangling link as a miss is nice. Path injection (C4) and string-built paths are not. |
| (e) mutate big list | **works** | Handle parameter, in place. |
| (f) threads | **partial** | `mv` is fine. `ro` races as specified (C6). `lock` deadlocks implicitly (C7). The `EBUSY` check is O(subtree). |

## 5. Gates and charter

- **G2: pass.** Nothing is traced. `rm -r` costs time proportional to what is deleted, at a known point. The reaper thread frees memory already known to be garbage; it is not a collection run.
- **G3: pass, flagged needs-john.** `link` is a keyword. But "wrong type → missing" means links are typed (`link Cache`), and `Dir`/`List` hold typed elements. These are built-in parameterised types, which is the brief's pending question, now with one more member (`link T`).
- **G1: strained.** There are 10 stated rules plus about 5 hidden ones:
  - owning vs link field
  - return as move vs return as handle
  - value list vs object list semantics
  - escaping path keys
  - place before you capture
  - stable keys rather than indices

  On top of that, every object needs a design answer to "where does it live?".
- **G8 / G10: strongly positive.** You get a heap browser, `du` profiling, dangling-link audits and `tar` fixtures.
- **Determinism:** kept.
- **Security:** the live-patchable debug mount must be impossible to enable in release builds.

## 6. Score

| Criterion | W | S | Justification |
|---|---|---|---|
| Simplicity & learnability | 25 | 2 | The shell metaphor is familiar. Against that, about 15 rules, and the worst failures are silent run-time retargets rather than compile errors. |
| Memory safety | 15 | 4 | No use-after-free thanks to pins and type-stable pools. The `ro` counter race (C6) is a spec hole that can be fixed. |
| Expressiveness (b)(c)(d), implicit self | 15 | 3 | (b) is excellent, (d) good, (c) fragile (C1–C3). Implicit `self` works. |
| Implementation risk (AI-written, LLVM) | 15 | 2 | Path resolver, ancestor-valid caches, scratch tracking, capture conversion at placement, CoW with shared interior nodes, namespaces, and FUSE/ProjFS/9P on three OSes. The semantic subtleties are hard to test. |
| Performance & predictability | 10 | 2 | Link follows cost O(depth) or a global epoch (C5). String or hashed dynamic paths, counted handles, O(n) `rm -r` and `EBUSY` checks. |
| Concurrency fit | 10 | 3 | Isolated namespaces by default are good. `ro` races, implicit lock order deadlocks, and locks are coarse. |
| Tooling, debuggability, C FFI | 10 | 4 | The heap browser is best-in-class. FFI pointers last only for a handle's scope, so C libraries that keep user-data pointers need wrapper nodes plus links. |

Total = (25×2 + 15×4 + 15×3 + 15×2 + 10×2 + 10×3 + 10×4) / 5
      = (50 + 60 + 45 + 30 + 20 + 30 + 40) / 5 = 275 / 5 = **55**.

That is 28 below O1 (83), 27 below O4 (82), and 13 below round 1's best (68). The author predicted the mid-60s. The extra loss comes from C1/C2 (crux scenario (c)) and C5 (the fast-path claim does not hold).

## 7. What the premise teaches, and the kernel

**What the crazy premise teaches:**
1. **There are two kinds of reference, and every sane design merges them.** One is "this exact object" (identity). The other is "whatever fills this role now" (a slot or name). Hot reload, swapping the document model and cache entries all want the second. Making the slot kind the *only* non-owning reference is wrong, as C1 and C2 show. Offering it as a separate, explicit kind is right, and it is a library concern, not a memory model. Godot, Unreal and Erlang all keep it next to identity references, never in place of them.
2. **Filesystems have no cycles because they forbid shared ownership of containers, not because they count cleverly.** For O1 or O4: if the `shared`/RC kind may only hold immutable values, or types that cannot reach back to their owner, then RC cycles are impossible by construction. That is a checkable rule, not an annotation.
3. **A single owner makes "parent" free.** In an ownership tree the runtime always knows the owner slot, so (b) needs no weak reference at all.
4. **Ownership trees give every object a canonical name.** That is valuable for debugging, even if it is useless for binding.

**Salvageable kernel:**
- **For O4: an intrinsic `x.owner`.** Every uniquely owned object carries a hidden back-pointer to its owning object. A move updates it, at one word per object. `x.owner` returns an optional borrow. This solves (b) without weak references or a new rule beyond "objects know their owner".
- **For O1 or O4: a debug-build heap browser** over a socket CLI. Skip FUSE in v1. It names objects by their ownership or root path; for O1 that is the shortest strong path from a root. It would provide:
  - `ls` with refcounts and types
  - `du` showing retained size
  - `find --dangling-weak`
  - `find --cycles`: a debug-only cycle report run on demand. This is not a collection run, so G2 is unaffected.
  - `lsof` for live borrows
  - `tar` snapshot/restore for test fixtures (G10)

  This serves G8 directly.
- **For the stdlib: an explicit `Slot`/registry type** for late-bound "current editor/model" wiring. It is opt-in and fails loudly by default, and it is never the implicit capture mode.
- **Rule for O4's `shared` kind:** it may hold only immutable data or acyclic-by-type data. This removes the need for weak references in most programs.

## 8. Verdict

**Kernel worth stealing.** As a memory model this is single-owner-plus-NodePath. Its by-name binding breaks the crux scenario: index retargeting (C1), dead constructor callbacks (C2) and silent no-ops (C3). Its claimed fast path is wrong (C5). Its by-products are worth taking: a structural `owner` intrinsic, an ownership-path heap browser for debug builds, and the "share only immutable containers" rule that rules out cycles.
