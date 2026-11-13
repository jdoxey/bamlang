# 08 — Terrain: the heap is a map, and things live while they can see a way home

## 1. Name

**Terrain** (the liveness mechanism is called *watershed*; its failure mode is a *landslide*).

## 2. The crazy premise

Sacred assumption broken: **"a pointer can point anywhere, and memory has no geometry."**

In Terrain the heap is a literal 3D grid of fixed-size cells. Every object with identity sits at a coordinate. A stored reference ("link") is a **1-byte relative offset** to a cell within radius 2 (a 5x5x5 neighbourhood, 124 neighbours). Longer relationships are carried by **roads**: chains of relay cells that the runtime builds for you. "Far" is slow, and the slowness is visible.

The payoff: geometry bounds every object's **in-degree**. That makes the set of "who points at me" a fixed 16-byte bitmap (one bit per neighbour position) with no per-edge allocation. With cheap, exact reverse edges, each cell can work out its own liveness from its neighbours, like a cellular automaton. Cycles are collected the instant they are cut off, with **no weak references and no tracing run over the heap**.

## 3. Pitch

You write ordinary OO code with ordinary references: parent pointers, closures capturing `self`, two components sharing a cache, all as plain links, with no weak/strong/owned kinds. The heap is a terrain. Every thing drains "downhill" through a tree of links to an anchor (a local variable, a global, a thread's stack). When you overwrite a link, only the things that drained through it check their neighbours for another way down. Things that find one stay alive. Things that don't are stranded, and they die right then, cycles included. Reachability semantics match a tracing GC, but the work is synchronous, local and proportional to what moved. Threads own territories on the map. Links can't cross borders, so data races are impossible by geometry, and cross-thread relationships become postboxes (messages). The debugger shows the heap as a map: popular objects as river deltas of roads, and still-reachable "leaks" as long roads to somewhere you forgot.

## 4. The rules (what a programmer must learn)

1. **Values and things.** Numbers, bools and strings are values: copied, immutable strings shared internally. Everything made with `class`, every `List`/`Map`, and every closure is a **thing**, and it lives at a place on the map.
2. **Links are just references.** Any field or local can refer to any thing, anywhere. There is one kind of reference. There is no weak, unowned or borrow.
3. **A thing lives exactly as long as some chain of links reaches it from an anchor** (a local, a global, a running thread). When the last chain is cut, it dies at that statement and its `drop` runs, even if it is part of a cycle.
4. **Near is fast.** `new` places a thing next to whoever created it (next to `self` in a method). `new T() near x` is an optional placement hint. Far links still work but cost a hop per road segment. This rule affects performance only, never meaning.
5. **Each thread owns a territory.** `spawn` and `send x` move things across borders. A link left pointing into another territory becomes a **postbox**: a method call through it is a message, run by the owning thread while the caller waits.

There are five rules. Rule 4 can be ignored until profiling. Nothing here involves lifetimes, annotations or ownership transfer, except `send` for threads.

## 5. Under the hood

**Cell layout (64 bytes).** 8-byte header: class id, 7-bit `parentDir` (which neighbour is my drainage parent, or ANCHORED), 24-bit height, pin count, flags. Then a 16-byte `inbits` bitmap with one bit per neighbour position that holds at least one link to me. The remaining 40 bytes hold fields. A link field is 1 byte (offset index 0..124, or none). Value fields that don't fit go to a **cellar**: a malloc'd buffer exclusively owned by the cell and freed with it. A thing with too many link fields spans an **annex**, a cluster of adjacent cells.

**The map.** A huge reserved virtual range, with pages committed on touch. Coordinate to address is arithmetic, and dereferencing a link is `cell_addr + offset_table[b]`. Links are self-relative pointers, so they cost one load and an add in LLVM.

**Roads.** Storing a link to a thing farther than radius 2 inserts relay cells (each a tiny thing with one link) along a straight path. Roads to the same target merge into a relay tree (a "delta"), so even a very popular thing has at most 124 in-neighbours. Relays are things, so they live and die by the same rule.

**Write barrier on link store `a.f = b`:**
- Set the bit for `a`'s position in `b.inbits`.
- If the old target `o` no longer receives any link from `a` (scan `a`'s ≤40 link bytes), clear `a`'s bit in `o.inbits`.
- If `o.parentDir` pointed at `a`, start a **watershed check** at `o`.
- Locals pin: a pin count with territory-local, non-atomic increments. A pinned thing is ANCHORED. When its pin count reaches zero, a watershed check starts at it.

**Watershed check (the local rule).**
1. *Fall:* mark `o` and its drainage subtree (cells whose parent chain runs through `o`) as FALLING. Children are found via `inbits` in reverse: a child is a neighbour I link to whose `parentDir` points at me.
2. *Regrip:* every FALLING cell scans its `inbits` for a neighbour that is not FALLING. If one exists, the cell re-parents onto the lowest-height such neighbour and spreads re-attachment breadth-first to the FALLING cells it links to.
3. *Strand:* cells still FALLING are unreachable. Correctness argument: any surviving path from an anchor enters the falling set at some first cell, and that cell's predecessor is not falling. Run `drop` hooks in fall order, clear their out-bits, and free the cells.

A non-falling cell always has a valid chain to an anchor, so re-parenting never creates a drainage cycle. The common case is a temporary that has been stored into a field: its pin drops, the check finds the holder in one bitmap probe, and it costs O(1).

**Territories.** Each thread owns a box of the map, with a dead zone at least 2 cells wide between boxes, so a link physically cannot reach across. A postbox is a border cell holding an atomic count and a message queue. Postboxes act as anchors on their target. Watershed work is always single-territory and never uses atomics.

**Drift (optional, v2).** When a road is traversed often, the runtime may move the far endpoint one step closer. This happens only at deterministic points, and pinned things never move. A move rewrites at most 124 in-neighbours' offsets (found via `inbits`) plus the mover's own links. This gives compaction without a compaction pass.

## 6. Scenarios (illustrative only — not a syntax decision)

**(a) Lines of a file.**
```
fn readLines(path: String) -> List of String
    lines = List of String()        // a "street": a strip of cells; strings live in cellars
    for l in File.open(path).lines { lines.add(l) }   // street grows; bends around occupied cells
    return lines                    // pin moves to caller; nothing else happens
```

**(b) Tree with parent pointers.**
```
class Node
    parent: Node?
    kids = List of Node()
    fn add(c: Node) { c.parent = self; kids.add(c) }   // plain links both ways; kids placed near self
// root = none  ->  one watershed check at root; whole tree has no other grip -> stranded, freed now
```

**(c) UI callback capturing the editor.**
```
class Editor
    text = ""
    dirty = false
    save = Button("Save", onTap: { self.save(); self.dirty = false })   // closure links Editor; Editor links Button
    fn save() { File.write(path, text) }
// app.windows.remove(w)  ->  window, editor, button, closure form a cycle; none has a non-falling
// in-neighbour -> all stranded together. No [weak self]. While the button is still on screen, the
// editor stays alive: the callback can never fire into freed memory.
```

**(d) Shared mutable cache, two components.**
```
cache = Cache()                       // a thing; entries are things on its street
search = SearchPanel(cache: cache)    // near link
preview = Preview(cache: cache)       // created far away -> road built automatically
cache.evict(k)                        // entry dies unless someone else still links it
// search closed -> if cache drained through search, it falls, regrips via preview's road (see weaknesses)
```

**(e) Mutate a big list in a function.**
```
fn normalise(xs: List of Float) { for i in 0..xs.count { xs[i] = xs[i] / xs.max } }
normalise(samples)        // passes a link; mutation is visible to caller; samples.copy() if you want one
```

**(f) Threads.**
```
stats = Stats()                                  // lives in main territory
spawn { for job in jobs { stats.record(job.run()) } }   // captured `stats` becomes a postbox:
                                                 // record() is a message run by main's thread
batch = buildBatch()
send batch to worker                             // batch + its drainage subtree emigrate;
                                                 // any links left behind turn into postboxes
```

## 7. What is new

- **Geometry bounds in-degree**, so reverse edges are a fixed 16-byte bitmap per object with no allocation. As far as I know, no listed option uses spatial placement as a *correctness* tool rather than a performance trick.
- **Watershed liveness:** cycle-correct, synchronous, deterministic death with plain references. You get ARC-style determinism with tracing-GC semantics, without weak refs (beats O1 on (b)/(c)) and without a backup cycle-collector pass (unlike O7).
- **1-byte self-relative links.** Objects are dense and pointers are tiny.
- **Data-race freedom by geography:** a link cannot physically span a territory border, and cross-thread references become actors at the border.
- **A heap you can look at:** the debugger is a map, and memory problems have shapes you can see (deltas, long roads, landslide scars).

## 8. Less crazy than it sounds, or more

*Less crazy:*
- The watershed algorithm is a cousin of the published spanning-tree and "strong/weak flip" cycle-collecting RC schemes (Brownbridge, later corrected variants), and of distance-vector routing with a feasibility condition. Those schemes struggle with the cost of finding back-edges. Geometry removes exactly that cost.
- Self-relative pointers and fixed-size cells are old, well-understood techniques.
- The programmer-facing model is *simpler* than O1: one reference kind, no `weak`, no cycle advice.

*More crazy:*
- A "pure cellular automaton" variant (each cell sets height = 1 + min of its in-neighbours' heights, and dies above an altitude ceiling) would be truly local. But it imposes a maximum hop distance from any anchor and suffers count-to-infinity on dead cycles. I rejected it in favour of fall/regrip.
- Fall/regrip is a **local mark phase over a subgraph**. That is the honest crux for G2 (below).

## 9. Known weaknesses

- **G2: needs-john.** There is never a whole-heap tracing run. But a landslide that *survives* does traversal work proportional to the size of the subtree. Example: the cache in (d) drains through `search`; `search` closes; the whole cache falls, then regrips via `preview`, so O(cache) work frees nothing. This is a pause shaped like a mini-GC, triggered by a write. Lowest-height parent choice keeps drainage trees shallow on average, but nothing bounds the worst case.
- **Cross-territory cycles leak.** A postbox A→B plus a postbox B→A, in different territories, is never reclaimed, because postboxes are counted as anchors. The rule needs a caveat, or postboxes need a cross-border protocol.
- **Every link store is a heavy barrier:** bitmap set, a scan of the old-target link bytes, and possibly a watershed check. Locals pin, which costs about the same as ARC's retain/release, though non-atomic.
- **Far links are slow, and the slowness is semantically invisible.** Performance depends on placement, which depends on creation order. Drift helps, but adds a move machinery that FFI and the debugger must respect.
- **64-byte cells waste memory** for tiny objects. Big objects need cellars or annexes, which adds indirection and runtime complexity.
- **Implementation risk is high.** A custom heap geometry, road building, annexes, the fall/regrip algorithm with `drop` ordering, territories and postboxes are all novel runtime code with subtle invariants, and hard for an AI-written compiler to get exactly right.
- **FFI:** C cannot hold links. Passing a thing to C pins it (no drift) and hands over an absolute address, and C must not store links into cells.
- **Postbox calls block.** Two territories calling each other synchronously can deadlock. Making the calls async would add a rule.
- **G3 flag:** `List of T` / `Map of K to V` are compiler-known parameterised containers (the pending question).

**Self-assessment (rough):** simplicity 4, safety 5, expressiveness 5, implementation risk 2, performance 2, concurrency 3, tooling/FFI 3, giving **~72/100**, with G2 needs-john.
