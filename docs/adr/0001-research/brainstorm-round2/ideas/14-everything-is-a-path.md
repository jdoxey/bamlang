# 14. Everything Is a Path (heapfs)

## 1. Name

**Everything Is a Path.** The heap is a Unix filesystem: objects are directories, fields are entries, remembered references are symlinks, and local variables are open file descriptors.

## 2. The crazy premise

It breaks two assumptions that every design in the brief keeps.

1. **A stored reference denotes an identity.** Here a stored reference is a *name*: a path that is resolved each time it is used. If the object at that name is replaced, the reference reaches the new one. If the name is empty, the reference finds nothing.
2. **The heap is private to the program.** Here a running program's heap is mounted at `/proc/<pid>/heap` (FUSE, ProjFS or 9P). `ls`, `cat`, `du`, `find`, `rm`, `tar` and `inotifywait` are the debugger, profiler, serializer and test-fixture tool.

It borrows the one property that lets real filesystems run for decades with reference counts and no collector. **Directories cannot be hard-linked, and only leaves are counted.** The counted graph therefore has no cycles by construction. Cycles can only go through symlinks, and symlinks are not counted.

## 3. Pitch

Every object has exactly one place in a tree. Its parent is `..` and its fields are its entries. Moving an object is `mv` and deleting it is `rm -r`. Code works with **handles** (open fds). A handle pins its object, so even an object that has been `rm`'d stays alive until the handle closes. This is Unix's "unlink while open" rule, and it rules out use-after-free. Handles are scope-bound and cannot go into fields. To *remember* something it doesn't own, an object stores a **link**: a path, absolute or relative to the link's own location. Following a link either opens whatever is at that name now or yields `missing`. The result is a model with no cycles, no weak/strong/unowned zoo and no lifetime annotations. Dangling references are not a safety problem; they are a normal, inspectable condition, shown by `find -xtype l`. Some patterns come almost for free:
- A UI rebinds when its model is swapped.
- A cache treats a dangling link as a cache miss.
- A subtree moved with `mv` keeps its relative links intact.

## 4. The rules

1. **Every object lives at exactly one path.** Its fields are entries in its directory. `owner` is its nearest enclosing object; container directories such as `List` and `Dir` are transparent to it.
2. **New objects are born in your call's scratch directory `~`.** When the call returns, `~` is removed with `rm -r`. Anything you *placed* survives: assigned to an owning field, added to a container, or returned. Returning an object is `mv` into the caller's `~`.
3. **Assigning to an owning field is `mv`.** The previous occupant is removed (`rm -r`) unless it is still open somewhere.
4. **Locals and parameters are handles.** A handle keeps its object alive even after the object has been removed from the tree. It closes at the end of its scope. Handles cannot be stored in fields or in stored closures.
5. **To remember something you don't own, store a `link`.** A link is a path, absolute (`/app/cache`) or relative to where the link itself lives (`../../editor`).
6. **Following a link opens whatever is there *now*.** That may be a different object than last time, or nothing at all. `missing` must be handled with `if let … else`, or propagated with `?`. If the object at the end of a link has the wrong type, the result is also `missing`.
7. **Stored closures capture by link.** When a closure is placed, its captured handles become links to their current paths. Calling the closure opens them. If any is missing, the call returns `missing`.
8. **`mv` keeps relative links inside the moved subtree working. Absolute links that point into it break.**
9. **Values (numbers, strings, value lists) are files.** Assignment copies them. Behind the scenes, big ones are shared through hard links on immutable blocks, which is copy-on-write. The programmer never sees a counted reference.
10. **Each thread has its own tree, like a Plan 9 namespace.** Data crosses threads in one of three ways:
    - `mv` gives a subtree away. It fails with `EBUSY` if the sender still has a handle open into it.
    - `mount … ro` shares a frozen copy-on-write snapshot.
    - `mount … lock` shares live data. Every `open` on the subtree takes its lock for the handle's scope. Multi-path opens are acquired in path order.

That is ten rules. Most of them are already familiar to anyone who has used a shell.

## 5. Under the hood

- **Node header:** `{parent*, name-slot, gen, opens:u32, schema*}`. Leaf blocks also carry `nlink`.
- **Class objects are fixed-schema directories.** `self.title` compiles to a field offset, not a name lookup. `Dir`, `Map` and lists of objects are dynamic directories: a hash table or an index array.
- **Link:** an interned path (a vector of component ids) plus a relative/absolute bit plus an inline cache `(node*, gen)`.
  - Fast path: load `node->gen`, compare, and you have a hit.
  - Miss: walk the components from the root, or from the link's own node if the path is relative, then refill the cache.
  - Node memory comes from type-stable size-class pools, so the `gen` word can always be read safely. This is the same trick as Vale. The difference is that a stale generation means "re-resolve by name", not "trap".
- **Handle:** a pointer plus `opens++`, then `opens--` at scope exit. The count is non-atomic inside a thread's namespace. The compiler removes the inc/dec pair when no call or `rm` can happen inside the scope. Handles never enter the heap, so the counts follow a stack discipline and cannot form cycles.
- **`rm`:** unlink the node from its parent and bump its `gen`.
  - If `opens == 0`, free the subtree depth-first.
  - Child nodes that are still open become "unlinked-open" orphans and are freed when their last handle closes.
  - Large subtrees can be handed to a reaper thread, because they are already unreachable by name. Nothing is traced; work is proportional to the bytes deleted, and only when they are deleted.
- **Scratch `~`:** each call keeps a list of the nodes it owns. At return, nodes that were not moved out are freed. Escape analysis allocates never-placed objects on the stack.
- **Threads:**
  - `mv` across namespaces is a pointer handoff, after checking that every `opens` in the subtree is 0.
  - `ro` mounts freeze the subtree. Owner writes then copy the path being written, btrfs-style.
  - `lock` mounts attach a mutex to the mount root and switch that subtree's `opens` to atomic counts.
- **Tooling:** in debug builds the runtime serves the namespace:
  - `ls -l` shows type, `opens` and size; `du -sh /proc/1234/heap/*` is a memory profiler.
  - `find -xtype l` lists dangling links; an `lsof` equivalent lists live handles.
  - `cat`/`echo >` read and patch fields live.
  - `tar` takes a heap snapshot; restoring one is a test fixture or a hot-reload checkpoint.
  - inotify on a path doubles as the observer mechanism.
- **C FFI:** `open x as raw` gives a C pointer that is valid for the handle's scope, because the handle pins the object. C may not keep it. Any C object that has to live longer is wrapped in a leaf node whose destructor runs on `rm`.

## 6. Scenarios

*All code below is illustrative only — not a syntax decision.*

**(a) Read lines into a growing list**
```
fn readLines(p) {
  lines = List()                    // born in ~/lines; a value list = one growable file
  for l in File.open(p).lines { lines.append(l) }   // realloc under the hood, like >>
  return lines                      // mv ~/lines -> caller's ~
}
self.lines = readLines("a.txt")     // mv into /app/editor/lines; old lines rm -r'd
```

**(b) Tree with parent pointers.** The parent pointer is `..`, which is free and uncounted.
```
class Node { name: String; kids: Dir }
/app/tree = Node("root")
/app/tree.kids.a = Node("a")        // lives at /app/tree/kids/a
fn depth(n) { d = 0; while let p = n.owner { d += 1; n = p }; return d }
rm /app/tree/kids/a                 // detaches and frees "a" and its subtree
```

**(c) UI callback capturing `self`.** This is the crux.
```
class Editor {
  text: String; dirty: Bool
  fn save() { … }
  fn attach(win) {                  // win is a handle to a window owned elsewhere
    win.toolbar.save = Button("Save", onTap: { self.save(); self.dirty = false })
    // closure placed at /app/windows/main/toolbar/save/onTap
    // captured self -> link "/app/docs/readme" (its path at capture time)
  }
}
// tap: runtime opens the link -> handle pins the editor for the duration of the call
// rm /app/docs/readme   -> next tap returns missing; dispatcher ignores it;
//                          `find -xtype l` shows exactly which buttons dangle
// /app/docs/readme = Editor(load("readme"))  -> every button, menu item and
//                          shortcut now drives the NEW editor without rewiring
```
There are no cycles even if the editor also links to the window, because links are not counted. Neither object has to outlive the other.

**(d) Shared mutable cache used by two components**
```
/app/cache = Cache()
class Search  { cache: link = "/app/cache" }
class Preview { cache: link = "/app/cache"; last: link
  fn show(k) {
    if let e = cache.entries[k] { render(e) } else { cache.entries[k] = fetch(k) }
    last = "/app/cache/entries/{k}" // remembered by name
  }
}
// eviction = rm entries/k  -> a later `last` lookup is a miss, not a crash
// a refresh replaces entries/k -> both components see the fresh entry through their links
```

**(e) Pass a large list to a mutating function**
```
fn normalize(xs) { for i in 0..xs.len { xs[i] = xs[i] / xs.max } }   // param = handle
normalize(/app/data/samples)        // in place, no copy; pinned even if rm'd meanwhile
```

**(f) Sharing between threads**
```
w = spawn worker
mv ~/batch  w:/inbox/batch          // give away; EBUSY if I still have it open
mount /app/config w:/config ro      // frozen CoW snapshot
mount /app/stats  w:/stats  lock    // live and shared
// in worker:
open /stats as s { s.count += 1 }   // lock held for the handle's scope
```

## 7. What is new

- **References by name, not by identity.** Late binding makes three things the model's default behaviour:
  - Swapping a model rebinds the UI.
  - A dangling link reads as a cache miss.
  - A subtree moved with `mv` keeps its relative links.

  Round 1's "auto-cleared non-owning refs" and O1's weak refs go dead when their target dies. A link here keeps working when anything new appears at the name.
- **Leaf-only counting.** Hard links are allowed only on leaf blocks, so the counted graph has no cycles by construction. This is the real reason filesystems never needed a collector, adopted as a language rule.
- **Unlink-while-open.** Handles pin objects, so `rm` is always safe. Deleting is a namespace operation; freeing happens later and deterministically.
- **Per-thread namespaces with mount modes** (`mv`, `ro`, `lock`) as the entire concurrency-sharing story.
- **The OS shell is the debugger.** This covers memory profiling, leak hunting (`du`), dangling-reference audits, live patching, snapshotting (`tar`) and observing (inotify). G8 and G10 come mostly for free, and declarative UI (G11) is literally a tree literal plus path watches.

## 8. Less crazy than it sounds, or more

**Less crazy:**
- Unix has run this exact model for 50 years: tree ownership, uncounted symlinks, counted leaves and fds that pin unlinked inodes, with no collector.
- Plan 9 showed that per-process namespaces and mounts are a workable concurrency and sharing model.
- Smalltalk images, the browser DOM (`querySelector` is late binding by path) and REST URLs all show that by-name references are how people already wire up long-lived, non-nesting things.
- The fast path costs one generation compare, the same price as O6.

**More crazy:**
- Every remembered reference is fallible and may silently retarget, which is a new kind of logic bug.
- Exposing the heap through FUSE on three operating systems is a serious engineering project, although it is debug-only and can fall back to a built-in `heap` CLI over a socket.

**Gates.** G2 passes: frees are explicit or structural, and nothing is traced. G3 passes, except that `List`/`Dir`/`Map` are built-in containers, which is the brief's pending question. `link` is a type keyword, not an annotation. Determinism is kept.

**Self-assessment, generous:** simplicity 3.5, safety 4, expressiveness 4, implementation risk 3, performance 3, concurrency 4, tooling 5, for a total of about 74. An analyst will probably land in the mid-60s.

## 9. Known weaknesses

- **Typo'd or stale paths fail at run time as `missing`.** The compiler can check relative links against schemas only when the ancestor types are known statically, which they usually aren't, because a node can be placed anywhere.
- **Silent retargeting.** A callback may act on a *different* editor than the one it was created for. That is a feature for reload and a bug for "close tab A, open tab B at the same name". A possible mitigation is links that pin a generation (`link! …` = missing on replace), but that is an 11th rule.
- **`mv` breaks absolute links.** Programmers will learn to fear renaming, as sysadmins do. Relative links help only within one subtree.
- **Everything must be named and placed.** This pushes designs toward a global namespace, which is effectively globals with slashes, and it adds a "where does this live?" question that ARC never asks.
- **`missing` handling spreads to every use of a link,** much as `Optional` does with weak refs in Swift, only more often.
- **Performance:**
  - Dynamic-path lookups hash strings, and a cache miss walks the path.
  - Handles still cost an inc/dec where the optimizer can't prove them away.
  - `rm -r` of a huge subtree is O(n), so it either pauses or needs the reaper.
- **Lock-on-open is coarse.** Path ordering prevents deadlock only for opens made in one statement; nested opens can still deadlock.
- **Handles cannot be stored.** Any long-lived traversal state, such as iterators kept in objects, has to be re-expressed as links or indices.
- **Shell tools can mutate the live heap,** so the debug mount needs permissions (`chmod`/uid checks) and must be off in release builds.
- **Structurally, this is "single owner + non-owning refs" with by-name semantics on top.** An analyst may judge that the novelty is in the binding semantics and the tooling, not in the memory model itself.
