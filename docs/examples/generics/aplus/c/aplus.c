/* generics benchmark under option A+ (D2, loop 2), modelled in C honouring ADR-0001.
   Rules in force: one owner; `=` moves (memcpy, then the source is dead); copies are explicit (look for COPY);
   borrows last one statement/call (look for BORROW); drops are explicit (look for DROP).
   Section 1 stands in for the compiler's built-ins (List and Map with run-time borrow counts, Pool, Handle, Id). Section 2 is the program, a transcription of ../aplus.txt. */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <stdint.h>
#pragma GCC diagnostic ignored "-Wunused-function"
#include "../../../chatsim/c/thread_compat.h"

/* ====================================================================================================
   SECTION 1: BUILT-INS (stand-ins for the compiler's List, Map, Str, Pool, Handle, Id, Channel).
   Nothing in section 2 reaches into these structs except through the functions.
   ==================================================================================================== */
#if defined(__GNUC__)
#define NORETURN __attribute__((noreturn))
#else
#define NORETURN
#endif
static NORETURN void trap(const char *f, ...) {   /* no signals: print to stdout, then exit(70) */
    va_list a; va_start(a, f);
    printf("TRAP: "); vprintf(f, a); printf("\n"); fflush(stdout);
    va_end(a); exit(70);
}
static void *xmalloc(size_t n) { void *p = malloc(n ? n : 1); if (!p) trap("out of memory"); return p; }
static void *xrealloc(void *p, size_t n) { p = realloc(p, n ? n : 1); if (!p) trap("out of memory"); return p; }

/* ---- Str: an owned heap string. str_copy is `.copy()`; str_drop is the drop. ---- */
typedef char *Str;
static Str str_copy(const char *s) { size_t n = strlen(s) + 1; return memcpy(xmalloc(n), s, n); }
static void str_drop(void *p) { free(*(Str *)p); *(Str *)p = NULL; }
#if defined(__GNUC__)
__attribute__((format(printf, 1, 2)))
#endif
static Str str_fmt(const char *f, ...) {
    char buf[256]; va_list a; va_start(a, f);
    int n = vsnprintf(buf, sizeof buf, f, a); va_end(a);
    if (n < 0 || (size_t)n >= sizeof buf) trap("str_fmt: result too long for the model");
    return str_copy(buf);
}

/* ---- List of T: elements are owned; push moves in; remove_at moves out (or drops when out == NULL). ---- */
typedef void (*DropFn)(void *);
typedef void (*CopyFn)(const void *src, void *dst);   /* deep copy of one element */
typedef struct { uint8_t *data; size_t len, cap, esz; DropFn drop; int borrow; } List;   /* borrow: live block borrows (S1) */
static void list_init(List *l, size_t esz, DropFn drop) { memset(l, 0, sizeof *l); l->esz = esz; l->drop = drop; }
static void list_borrow(List *l) { l->borrow++; }
static void list_release(List *l) { l->borrow--; }
static void list_check_mut(const List *l, const char *op) {
    if (l->borrow) trap("%s on a List while %d block borrow(s) of it are live", op, l->borrow);
}
static void list_push(List *l, void *v) {                  /* MOVE: *v is dead afterwards */
    list_check_mut(l, "push");
    if (l->len == l->cap) { l->cap = l->cap ? l->cap * 2 : 4; l->data = xrealloc(l->data, l->cap * l->esz); }
    memcpy(l->data + l->len * l->esz, v, l->esz); l->len++;
}
static void *list_at(const List *l, size_t i) {            /* BORROW: valid until the list is next written */
    if (i >= l->len) trap("index %zu out of range (len %zu)", i, l->len);
    return l->data + i * l->esz;
}
static void list_remove_at(List *l, size_t i, void *out) {
    list_check_mut(l, "remove_at");
    void *p = list_at(l, i);
    if (out) memcpy(out, p, l->esz); else if (l->drop) l->drop(p);
    memmove(l->data + i * l->esz, l->data + (i + 1) * l->esz, (l->len - i - 1) * l->esz); l->len--;
}
static void list_drop(void *p) {                           /* DROP: drops every element, frees the buffer */
    List *l = p;
    if (l->drop) for (size_t i = 0; i < l->len; i++) l->drop(l->data + i * l->esz);
    free(l->data); memset(l, 0, sizeof *l);
}
static void list_copy(const void *src, void *dst) {        /* COPY: deep, element by element (needs elem copier) */
    (void)src; (void)dst; trap("list_copy needs a copier; use list_copy_with");
}
static List list_copy_with(const List *s, CopyFn cp) {
    List d; list_init(&d, s->esz, s->drop);
    for (size_t i = 0; i < s->len; i++) {
        uint8_t tmp[64]; if (s->esz > sizeof tmp) trap("element too large for the model");
        cp(s->data + i * s->esz, tmp); list_push(&d, tmp);
    }
    return d;
}
static void list_sort(List *l, int (*cmp)(const void *, const void *)) { qsort(l->data, l->len, l->esz, cmp); }
static size_t list_min_index_by(const List *l, long (*key)(const void *)) {    /* first minimum */
    size_t b = 0; for (size_t i = 1; i < l->len; i++) if (key(l->data + i * l->esz) < key(l->data + b * l->esz)) b = i;
    return b;
}
static size_t list_max_index_by(const List *l, long (*key)(const void *)) {    /* first maximum */
    size_t b = 0; for (size_t i = 1; i < l->len; i++) if (key(l->data + i * l->esz) > key(l->data + b * l->esz)) b = i;
    return b;
}
static List list_filter(const List *s, int (*pred)(const void *), CopyFn cp) { /* value form: COPIES the kept ones */
    List d; list_init(&d, s->esz, s->drop);
    for (size_t i = 0; i < s->len; i++) if (pred(s->data + i * s->esz)) {
        uint8_t tmp[64]; cp(s->data + i * s->esz, tmp); list_push(&d, tmp);
    }
    return d;
}
static List list_map(const List *s, size_t oesz, DropFn odrop, void (*f)(const void *in, void *out)) {
    List d; list_init(&d, oesz, odrop);
    for (size_t i = 0; i < s->len; i++) { uint8_t tmp[64]; f(s->data + i * s->esz, tmp); list_push(&d, tmp); }
    return d;
}

/* ---- Map of K to V (model: linear search; the real one hashes). Owns its keys and values. ---- */
typedef struct {
    int (*eq)(const void *, const void *);
    CopyFn kcopy; DropFn kdrop, vdrop;
    size_t ksz, vsz;
} MapOps;
typedef struct { const MapOps *o; List keys, vals; int borrow; } Map;
static void map_borrow(Map *m) { m->borrow++; }       /* with x = m[k] { ... } borrows the WHOLE Map (S7) */
static void map_release(Map *m) { m->borrow--; }
static void map_init(Map *m, const MapOps *o) { m->borrow = 0; m->o = o; list_init(&m->keys, o->ksz, o->kdrop); list_init(&m->vals, o->vsz, o->vdrop); }
static long map_find(const Map *m, const void *k) {
    for (size_t i = 0; i < m->keys.len; i++) if (m->o->eq(m->keys.data + i * m->o->ksz, k)) return (long)i;
    return -1;
}
static int map_has(const Map *m, const void *k) { return map_find(m, k) >= 0; }
static void *map_get(const Map *m, const void *k) {        /* BORROW of the value, or NULL */
    long i = map_find(m, k); return i < 0 ? NULL : m->vals.data + (size_t)i * m->o->vsz;
}
static void *map_at(const Map *m, const void *k) {         /* m[k]: traps if missing */
    void *p = map_get(m, k); if (!p) trap("map key missing"); return p;
}
static void map_insert(Map *m, void *k, void *v) {         /* MOVES k and v in; an existing entry's value is dropped */
    long i = map_find(m, k);
    if (i < 0 && m->borrow) trap("insert of a new key into a Map while %d block borrow(s) of it are live", m->borrow);
    if (i >= 0) {
        if (m->o->kdrop) m->o->kdrop(k);
        void *slot = m->vals.data + (size_t)i * m->o->vsz;
        if (m->o->vdrop) m->o->vdrop(slot);
        memcpy(slot, v, m->o->vsz);
    } else { list_push(&m->keys, k); list_push(&m->vals, v); }
}
static int map_remove(Map *m, const void *k, void *out) {  /* 1 if removed; value moved to out (or dropped) */
    long i = map_find(m, k); if (i < 0) return 0;
    if (m->borrow) trap("remove from a Map while %d block borrow(s) of it are live", m->borrow);
    list_remove_at(&m->keys, (size_t)i, NULL); list_remove_at(&m->vals, (size_t)i, out); return 1;
}
static List map_keys(const Map *m) { return list_copy_with(&m->keys, m->o->kcopy); }   /* COPY: new List of K */
static void map_drop(Map *m) { list_drop(&m->keys); list_drop(&m->vals); }

/* ---- Id, Handle and Pool. A Handle of T is (index, generation, 64-bit pool id); an Id is the same triple with the
   type erased (pool.id(h)). Pool ids come from a counter that is never reused (atomic in the real thing).
   Staleness (generation mismatch) is a normal outcome: get/handle report it and the caller takes `else`.
   A FOREIGN handle (another pool's id) is a bug, never an `else`: it always traps (S5). ---- */
typedef struct { uint32_t index, gen; uint64_t pool; } Id;        /* pool 0 = none */
typedef struct { uint32_t index, gen; uint64_t pool; } Handle;    /* "of T" is a compile-time fact the C model drops */
static uint64_t next_pool_id = 1;
typedef struct {
    uint64_t pool_id; size_t esz, cap, live; DropFn drop;
    void **slot; uint32_t *gen; uint8_t *occupied;     /* each entry is its own allocation: add never moves entries */
    uint32_t *freel; size_t nfree;                     /* free slots, LIFO; a slot whose generation would wrap is retired */
} Pool;
static void pool_init(Pool *p, size_t esz, DropFn drop) { memset(p, 0, sizeof *p); p->pool_id = next_pool_id++; p->esz = esz; p->drop = drop; }
static int id_eq(Id a, Id b) { return a.index == b.index && a.gen == b.gen && a.pool == b.pool; }
static void pool_check(const Pool *p, uint64_t pool, const char *what) {
    if (pool != p->pool_id) trap("foreign %s: issued by pool #%llu, used on pool #%llu", what, (unsigned long long)pool, (unsigned long long)p->pool_id);
}
static Handle pool_add(Pool *p, void *v) {                  /* MOVES *v in */
    uint32_t i;
    if (p->nfree) i = p->freel[--p->nfree];
    else {
        if (p->cap == (size_t)UINT32_MAX) trap("pool full");
        i = (uint32_t)p->cap; p->cap++;
        p->slot = xrealloc(p->slot, p->cap * sizeof *p->slot); p->gen = xrealloc(p->gen, p->cap * sizeof *p->gen);
        p->occupied = xrealloc(p->occupied, p->cap); p->slot[i] = NULL; p->gen[i] = 1; p->occupied[i] = 0;
    }
    p->slot[i] = xmalloc(p->esz); memcpy(p->slot[i], v, p->esz); p->occupied[i] = 1; p->live++;
    return (Handle){ i, p->gen[i], p->pool_id };
}
static void *pool_get(const Pool *p, Handle h) {            /* BORROW, or NULL when stale (the `else` branch); traps if foreign */
    pool_check(p, h.pool, "Handle");
    if (h.index >= p->cap || !p->occupied[h.index] || p->gen[h.index] != h.gen) return NULL;
    return p->slot[h.index];
}
static void *pool_at(const Pool *p, Handle h) {             /* pool[h]: traps on stale and on foreign */
    void *e = pool_get(p, h);
    if (!e) trap("stale Handle (index %u, generation %u) used on pool #%llu", h.index, h.gen, (unsigned long long)p->pool_id);
    return e;
}
static int pool_remove(Pool *p, Handle h, void *out) {      /* 1 if removed: entry MOVED to out, or DROPPED if out == NULL */
    void *e = pool_get(p, h); if (!e) return 0;
    if (out) memcpy(out, e, p->esz); else if (p->drop) p->drop(e);
    free(e); p->slot[h.index] = NULL; p->occupied[h.index] = 0; p->live--;
    if (p->gen[h.index] == UINT32_MAX) return 1;            /* generation would wrap: retire the slot */
    p->gen[h.index]++;
    p->freel = xrealloc(p->freel, (p->nfree + 1) * sizeof *p->freel); p->freel[p->nfree++] = h.index;
    return 1;
}
static Id pool_id(const Pool *p, Handle h) { pool_check(p, h.pool, "Handle"); return (Id){ h.index, h.gen, h.pool }; }  /* pool.id(h) */
static int pool_handle(const Pool *p, Id id, Handle *out) { /* pool.handle(id): 1 if live; 0 if stale; traps if foreign */
    pool_check(p, id.pool, "Id");
    Handle h = { id.index, id.gen, id.pool };
    if (!pool_get(p, h)) return 0;
    *out = h; return 1;
}
static void pool_drop(Pool *p) {
    for (size_t i = 0; i < p->cap; i++) if (p->occupied[i]) { if (p->drop) p->drop(p->slot[i]); free(p->slot[i]); }
    free(p->slot); free(p->gen); free(p->occupied); free(p->freel); memset(p, 0, sizeof *p);
}

/* ---- Channel of T: owned values move through; close ends the stream. ---- */
typedef struct { mutex_t m; cond_t c; List q; int closed; } Chan;
static void chan_init(Chan *c, size_t esz, DropFn drop) { mutex_init(&c->m); cond_init(&c->c); list_init(&c->q, esz, drop); c->closed = 0; }
static void chan_send(Chan *c, void *v) { mutex_lock(&c->m); list_push(&c->q, v); cond_broadcast(&c->c); mutex_unlock(&c->m); }
static void chan_close(Chan *c) { mutex_lock(&c->m); c->closed = 1; cond_broadcast(&c->c); mutex_unlock(&c->m); }
static int chan_recv(Chan *c, void *out) {                 /* 1 and a MOVED value, or 0 when closed and empty */
    mutex_lock(&c->m);
    while (c->q.len == 0 && !c->closed) cond_wait(&c->c, &c->m);
    int got = c->q.len > 0; if (got) list_remove_at(&c->q, 0, out);
    mutex_unlock(&c->m); return got;
}
static void chan_drop(Chan *c) { list_drop(&c->q); mutex_destroy(&c->m); cond_destroy(&c->c); }
/* ======== end of built-ins ======== */

/* ====================================================================================================
   SECTION 2: THE PROGRAM
   ==================================================================================================== */

/* ---------------------------------------------------------------- Part 1 */
typedef struct { Str name, dept; long salary; } Employee;
static void employee_drop(void *p) { Employee *e = p; str_drop(&e->name); str_drop(&e->dept); }
static void employee_copy(const void *s, void *d) {        /* Employee.copy(): two Str copies */
    const Employee *e = s; *(Employee *)d = (Employee){ str_copy(e->name), str_copy(e->dept), e->salary };
}
static int employee_cmp(const void *pa, const void *pb) {  /* sort_by(.dept, .salary desc, .name) */
    const Employee *a = pa, *b = pb; int c;
    if ((c = strcmp(a->dept, b->dept))) return c;
    if (a->salary != b->salary) return a->salary > b->salary ? -1 : 1;
    return strcmp(a->name, b->name);
}
static long employee_salary(const void *p) { return ((const Employee *)p)->salary; }
static int employee_rich(const void *p) { return ((const Employee *)p)->salary > 50000; }
static void employee_name_copy(const void *p, void *out) { *(Str *)out = str_copy(((const Employee *)p)->name); }

static int str_eq(const void *a, const void *b) { return strcmp(*(Str *)a, *(Str *)b) == 0; }
static void str_kcopy(const void *s, void *d) { *(Str *)d = str_copy(*(Str *)s); }
static int str_cmp_qsort(const void *a, const void *b) { return strcmp(*(Str *)a, *(Str *)b); }
static const MapOps STR_TO_EMPLOYEES = { str_eq, str_kcopy, str_drop, list_drop, sizeof(Str), sizeof(List) };

static void print_str_list(const List *l) {
    printf("[");
    for (size_t i = 0; i < l->len; i++) printf("%s%s", i ? " " : "", *(Str *)list_at(l, i));
    printf("]");
}

static List employees_fixture(void) {
    static const struct { const char *n, *d; long s; } raw[] = {
        {"Grace", "sales", 60000}, {"Bob", "eng", 70000}, {"Dave", "ops", 45000}, {"Carol", "eng", 90000},
        {"Heidi", "sales", 40000}, {"Alice", "eng", 70000}, {"Erin", "ops", 55000}, {"Frank", "sales", 40000} };
    List l; list_init(&l, sizeof(Employee), employee_drop);
    for (size_t i = 0; i < sizeof raw / sizeof *raw; i++) {
        Employee e = { str_copy(raw[i].n), str_copy(raw[i].d), raw[i].s };   /* literals create owned Strs */
        list_push(&l, &e);                                                  /* MOVE */
    }
    return l;
}

static void part1(void) {
    printf("== Part 1: algorithms over Employee ==\n");
    List emps = employees_fixture();
    List sorted = list_copy_with(&emps, employee_copy);                     /* COPY (deep) */
    list_sort(&sorted, employee_cmp);
    printf("sorted by dept, salary desc, name:\n");
    for (size_t i = 0; i < sorted.len; i++) {
        Employee *e = list_at(&sorted, i);                                  /* BORROW for the loop body */
        printf("  %-5s %-6s %ld\n", e->dept, e->name, e->salary);
    }
    size_t lo = list_min_index_by(&emps, employee_salary), hi = list_max_index_by(&emps, employee_salary);
    printf("min_by salary: %s %ld\n", ((Employee *)list_at(&emps, lo))->name, ((Employee *)list_at(&emps, lo))->salary);
    printf("max_by salary: %s %ld\n", ((Employee *)list_at(&emps, hi))->name, ((Employee *)list_at(&emps, hi))->salary);

    Map groups; map_init(&groups, &STR_TO_EMPLOYEES);
    list_borrow(&emps);                                                     /* for e in emps: BORROW the list */
    for (size_t i = 0; i < emps.len; i++) {
        Employee *e = list_at(&emps, i);                                    /* BORROW */
        if (!map_has(&groups, &e->dept)) {
            Str k = str_copy(e->dept); List empty; list_init(&empty, sizeof(Employee), employee_drop);   /* COPY key */
            map_insert(&groups, &k, &empty);                                /* MOVE both */
        }
        Employee c; employee_copy(e, &c);                                   /* COPY */
        list_push(map_at(&groups, &e->dept), &c);                           /* groups[e.dept].push(...): place, one statement */
    }
    list_release(&emps);
    List depts = map_keys(&groups);                                         /* COPY: List of Str */
    list_sort(&depts, str_cmp_qsort);
    printf("group_by dept:\n");
    for (size_t i = 0; i < depts.len; i++) {
        Str *d = list_at(&depts, i);
        map_borrow(&groups);                                                /* with g = groups[d] { ... }: borrows the whole Map */
        List *g = map_at(&groups, d);
        long total = 0; for (size_t j = 0; j < g->len; j++) total += ((Employee *)list_at(g, j))->salary;
        printf("  %-5s count=%zu total=%ld\n", *d, g->len, total);
        map_release(&groups);
    }
    List rich = list_filter(&emps, employee_rich, employee_copy);           /* COPY of each kept Employee */
    List names = list_map(&rich, sizeof(Str), str_drop, employee_name_copy);/* COPY of each name */
    printf("salary > 50000: "); print_str_list(&names); printf("\n");
    list_drop(&names); list_drop(&rich); list_drop(&depts); map_drop(&groups); list_drop(&sorted); list_drop(&emps);  /* DROP: scope end, reverse order */
}

/* ---------------------------------------------------------------- Part 2 */
static int inject_forget_slot_removal = 0;   /* test hook for the F3 check (--f3, --f3-put); never set in normal runs */

/* ===== the LRU logic, written ONCE, over Id (no key type, no value type, no pool) ===== */
typedef struct { size_t cap; List order; } Lru;                          /* order: List of Id, least recent first */
static void lru_init(Lru *l, size_t cap) { l->cap = cap; list_init(&l->order, sizeof(Id), NULL); }
static void lru_drop(Lru *l) { list_drop(&l->order); }
static void lru_touch(Lru *l, Id id) {
    for (size_t i = 0; i < l->order.len; i++)
        if (id_eq(*(Id *)list_at(&l->order, i), id)) { list_remove_at(&l->order, i, NULL); break; }
    list_push(&l->order, &id);
}
static int lru_full(const Lru *l) { return l->order.len >= l->cap; }
static Id lru_pop_victim(Lru *l) { Id v; list_remove_at(&l->order, 0, &v); return v; }
/* ===== end of generic LRU ===== */

/* ===== per-use glue: UserKey -> Profile ===== */
typedef struct { long tenant, id; } UserKey;
typedef struct { Str name, email; } Profile;
typedef struct { UserKey key; Profile val; } PEntry;
static void profile_drop(void *p) { Profile *q = p; str_drop(&q->name); str_drop(&q->email); }
static void pentry_drop(void *p) { profile_drop(&((PEntry *)p)->val); }
static void profile_copy(const void *s, void *d) { const Profile *p = s; *(Profile *)d = (Profile){ str_copy(p->name), str_copy(p->email) }; }
static int userkey_eq(const void *a, const void *b) { return memcmp(a, b, sizeof(UserKey)) == 0; }
static void userkey_copy(const void *s, void *d) { memcpy(d, s, sizeof(UserKey)); }
static const MapOps USERKEY_TO_HANDLE = { userkey_eq, userkey_copy, NULL, NULL, sizeof(UserKey), sizeof(Handle) };

typedef struct { Lru lru; Map slots; Pool pool; } ProfileCache;
static void pc_init(ProfileCache *c, size_t cap) { lru_init(&c->lru, cap); map_init(&c->slots, &USERKEY_TO_HANDLE); pool_init(&c->pool, sizeof(PEntry), pentry_drop); }
static void pc_drop(ProfileCache *c) { lru_drop(&c->lru); map_drop(&c->slots); pool_drop(&c->pool); }
static int pc_get(ProfileCache *c, UserKey k, Profile *out) {              /* 1 and a COPY in *out on a hit */
    Handle *hp = map_get(&c->slots, &k);
    if (!hp) return 0;
    Handle h = *hp;                                                        /* Handle is Copy: the Map borrow ends here (S7) */
    PEntry *e = pool_get(&c->pool, h);                                     /* BORROW */
    if (!e) return 0;                                                      /* STALE: the entry was evicted */
    lru_touch(&c->lru, pool_id(&c->pool, h));                              /* disjoint field: no conflict with e */
    profile_copy(&e->val, out); return 1;                                  /* COPY */
}
static int pc_put(ProfileCache *c, UserKey k, Profile v, UserKey *evicted) {   /* v is MOVED in */
    Handle *known = map_get(&c->slots, &k);
    if (known) {                                                           /* self.pool[h].val = v: traps if stale */
        Handle h = *known; PEntry *e = pool_at(&c->pool, h);
        profile_drop(&e->val); e->val = v; lru_touch(&c->lru, pool_id(&c->pool, h)); return 0;
    }
    int ev = 0;
    if (lru_full(&c->lru)) {
        Handle vh;
        if (pool_handle(&c->pool, lru_pop_victim(&c->lru), &vh)) {
            PEntry old; pool_remove(&c->pool, vh, &old);                   /* MOVE the whole entry out */
            if (!inject_forget_slot_removal) map_remove(&c->slots, &old.key, NULL);
            *evicted = old.key; ev = 1;                                    /* partial move; old.val DROPs below */
            profile_drop(&old.val);
        } else trap("lru victim is not in the pool");                      /* STALE: unreachable */
    }
    PEntry ne = { k, v };
    Handle h = pool_add(&c->pool, &ne);
    map_insert(&c->slots, &k, &h);
    lru_touch(&c->lru, pool_id(&c->pool, h));
    return ev;
}

/* ===== per-use glue: String -> List of Int ===== */
typedef struct { Str key; List val; } QEntry;
static int str_key_eq(const void *a, const void *b) { return strcmp(*(Str *)a, *(Str *)b) == 0; }
static const MapOps STR_TO_HANDLE = { str_key_eq, str_kcopy, str_drop, NULL, sizeof(Str), sizeof(Handle) };
static void int_copy(const void *s, void *d) { memcpy(d, s, sizeof(long)); }
static void qentry_drop(void *p) { QEntry *q = p; str_drop(&q->key); list_drop(&q->val); }

typedef struct { Lru lru; Map slots; Pool pool; } QueryCache;
static void qc_init(QueryCache *c, size_t cap) { lru_init(&c->lru, cap); map_init(&c->slots, &STR_TO_HANDLE); pool_init(&c->pool, sizeof(QEntry), qentry_drop); }
static void qc_drop(QueryCache *c) { lru_drop(&c->lru); map_drop(&c->slots); pool_drop(&c->pool); }
static int qc_get(QueryCache *c, const Str *k, List *out) {                /* 1 and a COPY on a hit */
    Handle *hp = map_get(&c->slots, k);
    if (!hp) return 0;
    Handle h = *hp;
    QEntry *e = pool_get(&c->pool, h);
    if (!e) return 0;                                                      /* STALE */
    lru_touch(&c->lru, pool_id(&c->pool, h));
    *out = list_copy_with(&e->val, int_copy); return 1;                    /* COPY */
}
static int qc_put(QueryCache *c, Str k, List v, Str *evicted) {            /* k and v are MOVED in */
    Handle *known = map_get(&c->slots, &k);
    if (known) {
        Handle h = *known; QEntry *e = pool_at(&c->pool, h);
        list_drop(&e->val); e->val = v; lru_touch(&c->lru, pool_id(&c->pool, h)); str_drop(&k); return 0;
    }
    int ev = 0;
    if (lru_full(&c->lru)) {
        Handle vh;
        if (pool_handle(&c->pool, lru_pop_victim(&c->lru), &vh)) {
            QEntry old; pool_remove(&c->pool, vh, &old);
            if (!inject_forget_slot_removal) map_remove(&c->slots, &old.key, NULL);
            *evicted = old.key; ev = 1;                                    /* MOVE the key out to the caller */
            list_drop(&old.val);
        } else trap("lru victim is not in the pool");
    }
    QEntry ne = { str_copy(k), v };                                        /* COPY: the entry owns one key ... */
    Handle h = pool_add(&c->pool, &ne);
    map_insert(&c->slots, &k, &h);                                         /* ... and the Map owns the moved-in one */
    lru_touch(&c->lru, pool_id(&c->pool, h));
    return ev;
}
/* ===== end of LRU ===== */

static void putP(ProfileCache *c, long t, long i, const char *n, const char *e) {
    printf("profiles put %ld/%ld\n", t, i);
    UserKey ev;
    if (pc_put(c, (UserKey){ t, i }, (Profile){ str_copy(n), str_copy(e) }, &ev)) printf("profiles evict %ld/%ld\n", ev.tenant, ev.id);
}
static void getP(ProfileCache *c, long t, long i) {
    Profile p;
    if (pc_get(c, (UserKey){ t, i }, &p)) { printf("profiles get %ld/%ld hit %s <%s>\n", t, i, p.name, p.email); profile_drop(&p); }
    else printf("profiles get %ld/%ld miss\n", t, i);
}
static void putQ(QueryCache *c, const char *k, size_t n, const long *vs) {
    printf("queries put %s\n", k);
    List v; list_init(&v, sizeof(long), NULL); for (size_t i = 0; i < n; i++) list_push(&v, (void *)&vs[i]);
    Str ev;
    if (qc_put(c, str_copy(k), v, &ev)) { printf("queries evict %s\n", ev); str_drop(&ev); }
}
static void getQ(QueryCache *c, const char *k) {
    Str key = str_copy(k); List v;
    if (qc_get(c, &key, &v)) {
        printf("queries get %s hit [", k);
        for (size_t i = 0; i < v.len; i++) printf("%s%ld", i ? " " : "", *(long *)list_at(&v, i));
        printf("]\n"); list_drop(&v);
    } else printf("queries get %s miss\n", k);
    str_drop(&key);
}

static void part2(void) {
    printf("== Part 2: LRU cache reused for two key/value pairs ==\n");
    ProfileCache pc; pc_init(&pc, 2);
    QueryCache qc; qc_init(&qc, 3);
    putP(&pc, 1, 1, "Ann", "ann@example.com");
    putP(&pc, 1, 2, "Ben", "ben@example.com");
    getP(&pc, 1, 1);
    putP(&pc, 2, 1, "Cy", "cy@example.com");
    getP(&pc, 1, 2);
    putP(&pc, 1, 3, "Di", "di@example.com");
    getP(&pc, 2, 1);
    getP(&pc, 1, 1);
    putQ(&qc, "a", 1, (long[]){ 1 });
    putQ(&qc, "b", 2, (long[]){ 2, 2 });
    putQ(&qc, "c", 1, (long[]){ 3 });
    getQ(&qc, "a");
    putQ(&qc, "d", 1, (long[]){ 4 });
    getQ(&qc, "b");
    putQ(&qc, "a", 2, (long[]){ 1, 1 });
    putQ(&qc, "e", 1, (long[]){ 5 });
    getQ(&qc, "c");
    getQ(&qc, "a");
    pc_drop(&pc); qc_drop(&qc);
}

/* F3 check (review-a.md): a cache whose put forgets to remove the evicted key from `slots`.
   In Go option A that returned another entry's value. Here the dangling Handle is stale (the slot is reused with the
   next generation), so get takes `else` (--f3), and a later put of the same key traps on `pool[h].val = v` (--f3-put). */
static void f3_check(int then_put) {
    inject_forget_slot_removal = 1;
    ProfileCache pc; pc_init(&pc, 2);
    putP(&pc, 1, 1, "Ann", "ann@example.com"); putP(&pc, 1, 2, "Ben", "ben@example.com");
    putP(&pc, 2, 1, "Cy", "cy@example.com");              /* evicts 1/1 but leaves its Handle in slots */
    printf("f3: lookup through the dangling Handle:\n"); getP(&pc, 1, 1);
    if (then_put) { printf("f3: put through the dangling Handle:\n"); putP(&pc, 1, 1, "Ann2", "ann2@example.com"); }
    pc_drop(&pc);
}

/* ---------------------------------------------------------------- Part 3 */
typedef struct { Str street, city; } Address;
typedef struct { int some; Address v; } OptAddress;
typedef struct { long id; Str name; OptAddress addr; } User;
typedef struct { int some; User v; } OptUser;
typedef struct { long id; OptAddress addr; } Reply;
static void address_drop(Address *a) { str_drop(&a->street); str_drop(&a->city); }
static void optaddr_drop(OptAddress *o) { if (o->some) address_drop(&o->v); o->some = 0; }
static void user_drop(void *p) { User *u = p; str_drop(&u->name); optaddr_drop(&u->addr); }
static void reply_drop(void *p) { optaddr_drop(&((Reply *)p)->addr); }
static void long_copy(const void *s, void *d) { memcpy(d, s, sizeof(long)); }
static int long_eq(const void *a, const void *b) { return *(const long *)a == *(const long *)b; }
static const MapOps INT_TO_USER = { long_eq, long_copy, NULL, user_drop, sizeof(long), sizeof(User) };
static Map users;                                           /* module-level: main-thread state */

static OptAddress address_copy(const Address *a) { return (OptAddress){ 1, { str_copy(a->street), str_copy(a->city) } }; }
static void users_init(void) {
    map_init(&users, &INT_TO_USER);
    long k1 = 1, k2 = 2;
    User u1 = { 1, str_copy("Ann"), { 1, { str_copy("10 Main St"), str_copy("Springfield") } } };
    User u2 = { 2, str_copy("Ben"), { 0, { NULL, NULL } } };
    map_insert(&users, &k1, &u1); map_insert(&users, &k2, &u2);
}
static OptUser find_user(long id) {
    User *u = map_get(&users, &id);                         /* BORROW inside the if */
    if (!u) return (OptUser){ 0, { 0, NULL, { 0, { NULL, NULL } } } };
    OptAddress a = u->addr.some ? address_copy(&u->addr.v) : (OptAddress){ 0, { NULL, NULL } };   /* COPY */
    return (OptUser){ 1, { u->id, str_copy(u->name), a } };                                      /* COPY */
}
static OptAddress user_addr(OptUser u) {                    /* and_then(fn u -> u.addr): consumes u */
    if (!u.some) return (OptAddress){ 0, { NULL, NULL } };
    OptAddress a = u.v.addr; u.v.addr.some = 0;             /* MOVE the field out; the rest of u is dropped */
    str_drop(&u.v.name); return a;
}
static void worker(void *arg) {                             /* the only printer while Part 3 runs */
    Chan *rx = arg; Reply r;
    while (chan_recv(rx, &r)) {
        if (r.addr.some) printf("addr for %ld: %s, %s\n", r.id, r.addr.v.street, r.addr.v.city);
        else printf("addr for %ld: none\n", r.id);
        reply_drop(&r);                                     /* DROP */
    }
}
static void part3(void) {
    printf("== Part 3: Optional pipeline across a thread ==\n");
    users_init();
    Chan ch; chan_init(&ch, sizeof(Reply), reply_drop);
    thread_t th; if (thread_start(&th, worker, &ch) != 0) trap("thread_start");
    for (long id = 1; id <= 3; id++) {
        Reply r = { id, user_addr(find_user(id)) };
        chan_send(&ch, &r);                                 /* MOVE */
    }
    chan_close(&ch); thread_join(&th);
    chan_drop(&ch); map_drop(&users);
}

/* ---------------------------------------------------------------- Part 4a: event bus */
typedef enum { EV_JOINED, EV_LEFT, EV_MESSAGE } EvTag;
typedef struct { EvTag tag; Str name, text; } Event;        /* name: who joined/left, or the sender */
static Event ev_joined(const char *n) { return (Event){ EV_JOINED, str_copy(n), NULL }; }
static Event ev_left(const char *n) { return (Event){ EV_LEFT, str_copy(n), NULL }; }
static Event ev_message(const char *f, const char *t) { return (Event){ EV_MESSAGE, str_copy(f), str_copy(t) }; }
static void event_drop(Event *e) { if (e->name) str_drop(&e->name); if (e->text) str_drop(&e->text); }

typedef struct { Pool counts; } Stats;                      /* the context passed to every subscriber (Pool of Int) */
/* A stored closure: code plus an owned, heap-allocated environment (F11: a hidden allocation). */
typedef struct { void (*call)(void *env, const Event *e, Stats *st); void *env; void (*drop_env)(void *env); } Sub;
static void sub_drop(void *p) { Sub *s = p; if (s->drop_env) s->drop_env(s->env); free(s->env); }

/* subscriber 1: no captures */
static void logger_call(void *env, const Event *e, Stats *st) {
    (void)env; (void)st;
    switch (e->tag) {                                       /* exhaustive: -Wswitch -Werror rejects a missing case */
    case EV_JOINED: printf("log: %s joined\n", e->name); break;
    case EV_LEFT: printf("log: %s left\n", e->name); break;
    case EV_MESSAGE: printf("log: %s says %s\n", e->name, e->text); break;
    }
}
/* subscriber 2: captures a Handle (copied in) naming a counter in Stats.counts */
typedef struct { Handle counter; } CounterEnv;
static void counter_call(void *env, const Event *e, Stats *st) {
    CounterEnv *c = env;
    switch (e->tag) {
    case EV_MESSAGE: *(long *)pool_at(&st->counts, c->counter) += 1; break;   /* stats.counts[counter] += 1 */
    case EV_JOINED: case EV_LEFT: break;
    }
}
/* subscriber 3: owns its state outright (a prefix Str moved in, an Int copied in and mutated) */
typedef struct { Str prefix; long n; } WelcomeEnv;     /* `seen` is mutated, so it is MOVED into the closure (S4) */
static void welcome_call(void *env, const Event *e, Stats *st) {
    WelcomeEnv *w = env; (void)st;
    switch (e->tag) {
    case EV_JOINED: w->n += 1; printf("%s #%ld %s\n", w->prefix, w->n, e->name); break;
    case EV_LEFT: case EV_MESSAGE: break;
    }
}
static void welcome_drop(void *env) { str_drop(&((WelcomeEnv *)env)->prefix); }

typedef struct { List subs; } Bus;                          /* List of Sub */
static void bus_init(Bus *b) { list_init(&b->subs, sizeof(Sub), sub_drop); }
static void bus_subscribe(Bus *b, Sub s) { list_push(&b->subs, &s); }          /* MOVE: the closure is stored */
static void bus_publish(Bus *b, Event ev, Stats *st) {                         /* ev is MOVED in, dropped at the end */
    for (size_t i = 0; i < b->subs.len; i++) {
        Sub *s = list_at(&b->subs, i);                                         /* BORROW (mutable: the closure may change its state) */
        s->call(s->env, &ev, st);                                              /* ev lent to the subscriber for the call */
    }
    event_drop(&ev);                                                           /* DROP */
}

static void part4_bus(void) {
    printf("-- event bus --\n");
    Stats stats; pool_init(&stats.counts, sizeof(long), NULL);
    long zero = 0; Handle counter = pool_add(&stats.counts, &zero);
    Bus bus; bus_init(&bus);
    bus_subscribe(&bus, (Sub){ logger_call, NULL, NULL });
    CounterEnv *ce = xmalloc(sizeof *ce); ce->counter = counter;
    bus_subscribe(&bus, (Sub){ counter_call, ce, NULL });
    WelcomeEnv *we = xmalloc(sizeof *we); we->prefix = str_copy("welcome"); we->n = 0;
    bus_subscribe(&bus, (Sub){ welcome_call, we, welcome_drop });
    bus_publish(&bus, ev_joined("ann"), &stats);
    bus_publish(&bus, ev_joined("ben"), &stats);
    bus_publish(&bus, ev_message("ann", "hi"), &stats);
    bus_publish(&bus, ev_message("ben", "hello"), &stats);
    bus_publish(&bus, ev_left("ann"), &stats);
    bus_publish(&bus, ev_message("ben", "anyone?"), &stats);
    printf("messages seen: %ld\n", *(long *)pool_at(&stats.counts, counter));
    list_drop(&bus.subs); pool_drop(&stats.counts);
}

/* ---------------------------------------------------------------- Part 4b: mixed widget kinds (sum type of typed handles) */
typedef struct { Str label; long clicks; } Button;
typedef struct { long value, max; } Slider;
typedef struct { Str text; } LabelW;
static void button_drop(void *p) { str_drop(&((Button *)p)->label); }
static void labelw_drop(void *p) { str_drop(&((LabelW *)p)->text); }

typedef enum { W_BUTTON, W_SLIDER, W_LABEL } WTag;
typedef struct { WTag tag; Handle h; } Widget;              /* enum Widget { Button(Handle of Button), ... }: plain data, copies */
typedef struct { Pool buttons, sliders, labels; } Ui;

static Handle ui_add_button(Ui *ui, List *items, const char *label) {
    Button b = { str_copy(label), 0 }; Handle h = pool_add(&ui->buttons, &b);
    Widget w = { W_BUTTON, h }; list_push(items, &w); return h;
}
static Handle ui_add_slider(Ui *ui, List *items, long value, long max) {
    Slider s = { value, max }; Handle h = pool_add(&ui->sliders, &s);
    Widget w = { W_SLIDER, h }; list_push(items, &w); return h;
}
static Handle ui_add_label(Ui *ui, List *items, const char *text) {
    LabelW l = { str_copy(text) }; Handle h = pool_add(&ui->labels, &l);
    Widget w = { W_LABEL, h }; list_push(items, &w); return h;
}
static const char *ui_name(const Ui *ui, Widget w) {
    (void)ui;
    switch (w.tag) { case W_BUTTON: return "button"; case W_SLIDER: return "slider"; case W_LABEL: return "label"; }   /* -Wswitch: exhaustive */
    return "";
}
static Str ui_render(const Ui *ui, Widget w) {
    switch (w.tag) {                                        /* a new kind is a compile error here under -Wswitch -Werror */
    case W_BUTTON: { Button *b = pool_at(&ui->buttons, w.h); return str_fmt("[%s] clicks=%ld", b->label, b->clicks); }
    case W_SLIDER: {
        Slider *s = pool_at(&ui->sliders, w.h); Str bar = xmalloc((size_t)s->max + 1);
        for (long i = 0; i < s->max; i++) bar[i] = i < s->value ? '#' : '.';
        bar[s->max] = 0; Str out = str_fmt("[%s] %ld/%ld", bar, s->value, s->max); free(bar); return out;
    }
    case W_LABEL: return str_copy(((LabelW *)pool_at(&ui->labels, w.h))->text);   /* COPY: render returns an owned Str */
    }
    return NULL;
}

static void part4_widgets(void) {
    printf("-- widgets --\n");
    Ui ui; pool_init(&ui.buttons, sizeof(Button), button_drop); pool_init(&ui.sliders, sizeof(Slider), NULL); pool_init(&ui.labels, sizeof(LabelW), labelw_drop);
    List items; list_init(&items, sizeof(Widget), NULL);
    Handle ok = ui_add_button(&ui, &items, "OK"); Handle s0 = ui_add_slider(&ui, &items, 0, 8); ui_add_label(&ui, &items, "Hello");
    ui_add_button(&ui, &items, "Cancel"); Handle vol = ui_add_slider(&ui, &items, 4, 8);
    ((Button *)pool_at(&ui.buttons, ok))->clicks += 1; ((Button *)pool_at(&ui.buttons, ok))->clicks += 1;   /* buttons[ok].clicks += 1, twice */
    ((Slider *)pool_at(&ui.sliders, vol))->value = 8;
    ((Slider *)pool_at(&ui.sliders, s0))->value = 4;
    list_borrow(&items);                                                  /* for w in items: BORROW */
    for (size_t i = 0; i < items.len; i++) {
        Widget *w = list_at(&items, i);
        Str s = ui_render(&ui, *w);                                       /* owned result */
        printf("%s: %s\n", ui_name(&ui, *w), s);
        str_drop(&s);                                                     /* DROP */
    }
    list_release(&items);
    list_drop(&items); pool_drop(&ui.buttons); pool_drop(&ui.sliders); pool_drop(&ui.labels);
}

static void part4(void) {
    printf("== Part 4 (A+ only): outside the stdlib ==\n");
    part4_bus();
    part4_widgets();
}

/* ---------------------------------------------------------------- Trap tests (run.sh): each prints "TRAP: ..." and exits 70 */
static List g_log;                                          /* module-level List of Str, as in the review's S1 example */
static void note(const char *s) { Str x = str_copy(s); list_push(&g_log, &x); }   /* structural mutation from another function */
static void s1_run(int release_first) {                    /* with first = log[0] { note("b") } */
    list_init(&g_log, sizeof(Str), str_drop); note("a");
    list_borrow(&g_log); Str *first = list_at(&g_log, 0);   /* the block borrow is taken here ... */
    if (release_first) { printf("s1: first=%s\n", *first); list_release(&g_log); }
    note("b");                                              /* ... and the push happens in another function */
    printf("s1: pushed after the borrow ended, len=%zu\n", g_log.len);
    list_drop(&g_log);
}
static void s7_run(void) {                                  /* with x = m[k] { m.remove(k) } : the whole Map is borrowed */
    Map m; map_init(&m, &STR_TO_EMPLOYEES);
    Str k = str_copy("eng"); List l; list_init(&l, sizeof(Employee), employee_drop); map_insert(&m, &k, &l);
    Str q = str_copy("eng");
    map_borrow(&m); (void)map_at(&m, &q);
    printf("s7: removing the key while its value is borrowed\n");
    map_remove(&m, &q, NULL);
    printf("s7: not reached\n");
}
static void s5_run(int via_at) {                            /* a Handle/Id from pool A used on pool B */
    Pool a, b; pool_init(&a, sizeof(long), NULL); pool_init(&b, sizeof(long), NULL);
    long v = 7; Handle ha = pool_add(&a, &v); pool_add(&b, &v);
    Id ida = pool_id(&a, ha); Handle out;
    printf("s5: own pool: handle(id) -> %d\n", pool_handle(&a, ida, &out));
    pool_remove(&a, ha, NULL);
    printf("s5: stale id on its own pool takes else: handle(id) -> %d\n", pool_handle(&a, ida, &out));
    if (via_at) pool_at(&b, ha); else pool_handle(&b, ida, &out);
    printf("s5: not reached\n");
}
/* S6: m[k].push(m[j].pop()) and m[k].push(grow(m)): arguments are evaluated BEFORE the receiver place (two-phase).
   The naive order takes the place first, holds the Map borrowed, and the argument's insert then traps (S1). */
static const MapOps STR_TO_LIST_OF_STR = { str_eq, str_kcopy, str_drop, list_drop, sizeof(Str), sizeof(List) };
static void m_add_list(Map *m, const char *k, size_t n, const char *const *xs) {
    Str key = str_copy(k); List l; list_init(&l, sizeof(Str), str_drop);
    for (size_t i = 0; i < n; i++) { Str x = str_copy(xs[i]); list_push(&l, &x); }
    map_insert(m, &key, &l);
}
static Str m_pop(Map *m, const char *k) {                   /* m[k].pop(): the place is borrowed for this operation only */
    Str key = str_copy(k); List *l = map_at(m, &key); str_drop(&key);
    Str out; list_remove_at(l, l->len - 1, &out); return out;
}
static Str grow(Map *m) {                                   /* an argument that structurally mutates the Map */
    m_add_list(m, "z", 0, NULL); return str_copy("from-grow");
}
static void print_m(Map *m, const char *k) {
    Str key = str_copy(k); List *l = map_at(m, &key); printf("s6: %s=", k); print_str_list(l); printf("\n"); str_drop(&key);
}
static void s6_run(int naive) {
    Map m; map_init(&m, &STR_TO_LIST_OF_STR);
    m_add_list(&m, "a", 1, (const char *const[]){ "x" }); m_add_list(&m, "b", 2, (const char *const[]){ "y", "w" });
    /* m["a"].push(m["b"].pop()) */
    { Str v = m_pop(&m, "b");                                              /* phase 1: the argument, fully evaluated */
      Str key = str_copy("a"); list_push(map_at(&m, &key), &v); str_drop(&key); }   /* phase 2: the place, used at once */
    print_m(&m, "a"); print_m(&m, "b");
    /* m["a"].push(grow(m)) */
    if (naive) {
        Str key = str_copy("a"); map_borrow(&m); List *place = map_at(&m, &key);   /* place first, borrowed ... */
        Str v = grow(&m);                                                          /* ... then the argument inserts: S1 trap */
        list_push(place, &v);
    } else {
        Str v = grow(&m);                                                          /* phase 1 */
        Str key = str_copy("a"); map_borrow(&m); List *place = map_at(&m, &key);   /* phase 2: borrow only for the push */
        list_push(place, &v); map_release(&m); str_drop(&key);
    }
    print_m(&m, "a");
    map_drop(&m);
}

int main(int argc, char **argv) {
    const char *a = argc > 1 ? argv[1] : "";
    if (!strcmp(a, "--f3")) { f3_check(0); return 0; }
    if (!strcmp(a, "--f3-put")) { f3_check(1); return 0; }
    if (!strcmp(a, "--s1")) { s1_run(0); return 0; }
    if (!strcmp(a, "--s1-ok")) { s1_run(1); return 0; }
    if (!strcmp(a, "--s7")) { s7_run(); return 0; }
    if (!strcmp(a, "--s5")) { s5_run(0); return 0; }
    if (!strcmp(a, "--s5-at")) { s5_run(1); return 0; }
    if (!strcmp(a, "--s6")) { s6_run(0); return 0; }
    if (!strcmp(a, "--s6-naive")) { s6_run(1); return 0; }
    part1(); part2(); part3(); part4();
    return 0;
}
