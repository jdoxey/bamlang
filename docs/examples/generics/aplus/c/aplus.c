/* generics benchmark under option A+ (D2, loop 2), modelled in C honouring ADR-0001.
   Rules in force: one owner; `=` moves (memcpy, then the source is dead); copies are explicit (look for COPY);
   borrows last one statement/call (look for BORROW); drops are explicit (look for DROP).
   Section 1 stands in for the compiler's built-ins. Section 2 is the program, a transcription of ../aplus.txt. */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <stdint.h>
#pragma GCC diagnostic ignored "-Wunused-function"
#include "../../../chatsim/c/thread_compat.h"

/* ====================================================================================================
   SECTION 1: BUILT-INS (stand-ins for the compiler's List, Map, Str, Ids, Id, Table, Channel).
   Nothing in section 2 reaches into these structs except through the functions.
   ==================================================================================================== */
#if defined(__GNUC__)
#define NORETURN __attribute__((noreturn))
#else
#define NORETURN
#endif
static NORETURN void trap(const char *f, ...) {
    va_list a; va_start(a, f);
    fprintf(stderr, "trap: "); vfprintf(stderr, f, a); fprintf(stderr, "\n");
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
typedef struct { uint8_t *data; size_t len, cap, esz; DropFn drop; } List;
static void list_init(List *l, size_t esz, DropFn drop) { memset(l, 0, sizeof *l); l->esz = esz; l->drop = drop; }
static void list_push(List *l, void *v) {                  /* MOVE: *v is dead afterwards */
    if (l->len == l->cap) { l->cap = l->cap ? l->cap * 2 : 4; l->data = xrealloc(l->data, l->cap * l->esz); }
    memcpy(l->data + l->len * l->esz, v, l->esz); l->len++;
}
static void *list_at(const List *l, size_t i) {            /* BORROW: valid until the list is next written */
    if (i >= l->len) trap("index %zu out of range (len %zu)", i, l->len);
    return l->data + i * l->esz;
}
static void list_remove_at(List *l, size_t i, void *out) {
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
typedef struct { const MapOps *o; List keys, vals; } Map;
static void map_init(Map *m, const MapOps *o) { m->o = o; list_init(&m->keys, o->ksz, o->kdrop); list_init(&m->vals, o->vsz, o->vdrop); }
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
    if (i >= 0) {
        if (m->o->kdrop) m->o->kdrop(k);
        void *slot = m->vals.data + (size_t)i * m->o->vsz;
        if (m->o->vdrop) m->o->vdrop(slot);
        memcpy(slot, v, m->o->vsz);
    } else { list_push(&m->keys, k); list_push(&m->vals, v); }
}
static int map_remove(Map *m, const void *k, void *out) {  /* 1 if removed; value moved to out (or dropped) */
    long i = map_find(m, k); if (i < 0) return 0;
    list_remove_at(&m->keys, (size_t)i, NULL); list_remove_at(&m->vals, (size_t)i, out); return 1;
}
static List map_keys(const Map *m) { return list_copy_with(&m->keys, m->o->kcopy); }   /* COPY: new List of K */
static void map_drop(Map *m) { list_drop(&m->keys); list_drop(&m->vals); }

/* ---- Id and Ids: untyped, generation-checked. An Id is (index, generation, issuer); it copies implicitly. ---- */
typedef struct { uint32_t index, gen, issuer; } Id;        /* issuer 0 = no Id */
typedef struct { uint32_t issuer; List gens; } Ids;       /* gens: List of uint32 */
static uint32_t next_issuer = 1;
static void ids_init(Ids *s) { s->issuer = next_issuer++; list_init(&s->gens, sizeof(uint32_t), NULL); }
static Id ids_issue(Ids *s) { uint32_t g = 1; list_push(&s->gens, &g); return (Id){ (uint32_t)s->gens.len - 1, 1, s->issuer }; }
static size_t ids_count(const Ids *s) { return s->gens.len; }
static Id ids_reissue(Ids *s, Id old) {                    /* same slot, next generation: `old` is stale from now on */
    if (old.issuer != s->issuer) trap("Id from issuer #%u used on issuer #%u", old.issuer, s->issuer);
    uint32_t *g = list_at(&s->gens, old.index);
    if (*g != old.gen) trap("reissue of a stale Id");
    (*g)++; return (Id){ old.index, *g, s->issuer };
}
static int id_eq(Id a, Id b) { return a.index == b.index && a.gen == b.gen && a.issuer == b.issuer; }
static void ids_drop(Ids *s) { list_drop(&s->gens); }

/* ---- Table of T: values keyed by Id. A slot holds the generation of the Id that wrote it; 0 = empty.
   Staleness is relative to the Table's own slot (see NOTES.md, "unclear"). ---- */
typedef struct { uint32_t issuer; size_t esz, cap; uint8_t *data; uint32_t *gen; DropFn drop; } Table;
static void table_init(Table *t, size_t esz, DropFn drop) { memset(t, 0, sizeof *t); t->esz = esz; t->drop = drop; }
static void table_check(Table *t, Id id) {
    if (id.issuer == 0) trap("none Id used on a Table");
    if (t->issuer == 0) t->issuer = id.issuer;
    else if (t->issuer != id.issuer) trap("Id from issuer #%u used on a Table of issuer #%u", id.issuer, t->issuer);
}
static void table_insert(Table *t, Id id, void *v) {       /* MOVES *v in; the slot must be empty */
    table_check(t, id);
    if (id.index >= t->cap) {
        size_t nc = t->cap ? t->cap : 4; while (nc <= id.index) nc *= 2;
        t->data = xrealloc(t->data, nc * t->esz); t->gen = xrealloc(t->gen, nc * sizeof *t->gen);
        for (size_t i = t->cap; i < nc; i++) t->gen[i] = 0;
        t->cap = nc;
    }
    if (t->gen[id.index]) trap("insert into an occupied Table slot");
    memcpy(t->data + id.index * t->esz, v, t->esz); t->gen[id.index] = id.gen;
}
static void *table_get(Table *t, Id id) {                  /* BORROW, or NULL when the Id is stale (the `else` branch) */
    table_check(t, id);
    if (id.index >= t->cap || t->gen[id.index] != id.gen) return NULL;
    return t->data + id.index * t->esz;
}
static void *table_at(Table *t, Id id) {                   /* t[id]: traps on a stale Id */
    void *p = table_get(t, id); if (!p) trap("stale Id (index %u, generation %u) used on a Table", id.index, id.gen); return p;
}
static void table_set(Table *t, Id id, void *v) {          /* t[id] = v: DROPS the old value, MOVES v in; traps if stale */
    void *p = table_at(t, id); if (t->drop) t->drop(p); memcpy(p, v, t->esz);
}
static int table_remove(Table *t, Id id, void *out) {      /* 1 if removed: value MOVED to out, or DROPPED if out == NULL */
    void *p = table_get(t, id); if (!p) return 0;
    if (out) memcpy(out, p, t->esz); else if (t->drop) t->drop(p);
    t->gen[id.index] = 0; return 1;
}
static void table_drop(Table *t) {
    for (size_t i = 0; i < t->cap; i++) if (t->gen[i] && t->drop) t->drop(t->data + i * t->esz);
    free(t->data); free(t->gen); memset(t, 0, sizeof *t);
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
    for (size_t i = 0; i < emps.len; i++) {
        Employee *e = list_at(&emps, i);                                    /* BORROW */
        if (!map_has(&groups, &e->dept)) {
            Str k = str_copy(e->dept); List empty; list_init(&empty, sizeof(Employee), employee_drop);   /* COPY key */
            map_insert(&groups, &k, &empty);                                /* MOVE both */
        }
        Employee c; employee_copy(e, &c);                                   /* COPY */
        list_push(map_at(&groups, &e->dept), &c);                           /* groups[e.dept].push(...): place, one statement */
    }
    List depts = map_keys(&groups);                                         /* COPY: List of Str */
    list_sort(&depts, str_cmp_qsort);
    printf("group_by dept:\n");
    for (size_t i = 0; i < depts.len; i++) {
        Str *d = list_at(&depts, i);
        List *g = map_at(&groups, d);                                       /* with g = groups[d] { ... } */
        long total = 0; for (size_t j = 0; j < g->len; j++) total += ((Employee *)list_at(g, j))->salary;
        printf("  %-5s count=%zu total=%ld\n", *d, g->len, total);
    }
    List rich = list_filter(&emps, employee_rich, employee_copy);           /* COPY of each kept Employee */
    List names = list_map(&rich, sizeof(Str), str_drop, employee_name_copy);/* COPY of each name */
    printf("salary > 50000: "); print_str_list(&names); printf("\n");
    list_drop(&names); list_drop(&rich); list_drop(&depts); map_drop(&groups); list_drop(&sorted); list_drop(&emps);  /* DROP: scope end, reverse order */
}

/* ---------------------------------------------------------------- Part 2 */
static int inject_forget_slot_removal = 0;   /* test hook for the F3 check (--f3, --f3-put); never set in normal runs */

/* ===== the LRU logic, written ONCE, over Id (no key type, no value type) ===== */
typedef struct { size_t cap; Ids ids; List order; } Lru;                  /* order: List of Id, least recent first */
static void lru_init(Lru *l, size_t cap) { l->cap = cap; ids_init(&l->ids); list_init(&l->order, sizeof(Id), NULL); }
static void lru_drop(Lru *l) { ids_drop(&l->ids); list_drop(&l->order); }
static void lru_touch(Lru *l, Id id) {
    for (size_t i = 0; i < l->order.len; i++)
        if (id_eq(*(Id *)list_at(&l->order, i), id)) { list_remove_at(&l->order, i, NULL); break; }
    list_push(&l->order, &id);
}
typedef struct { Id id; int has_victim; Id victim; } Acquired;
static Acquired lru_acquire(Lru *l) {
    if (ids_count(&l->ids) < l->cap) { Id id = ids_issue(&l->ids); lru_touch(l, id); return (Acquired){ id, 0, { 0, 0, 0 } }; }
    Id victim = *(Id *)list_at(&l->order, 0);
    Id id = ids_reissue(&l->ids, victim);                                  /* victim is stale in Ids from here on */
    list_remove_at(&l->order, 0, NULL);
    lru_touch(l, id);
    return (Acquired){ id, 1, victim };
}
/* ===== end of generic LRU ===== */

/* ===== per-use glue: UserKey -> Profile ===== */
typedef struct { long tenant, id; } UserKey;
typedef struct { Str name, email; } Profile;
static void profile_drop(void *p) { Profile *q = p; str_drop(&q->name); str_drop(&q->email); }
static void profile_copy(const void *s, void *d) { const Profile *p = s; *(Profile *)d = (Profile){ str_copy(p->name), str_copy(p->email) }; }
static int userkey_eq(const void *a, const void *b) { return memcmp(a, b, sizeof(UserKey)) == 0; }
static void userkey_copy(const void *s, void *d) { memcpy(d, s, sizeof(UserKey)); }
static const MapOps USERKEY_TO_ID = { userkey_eq, userkey_copy, NULL, NULL, sizeof(UserKey), sizeof(Id) };

typedef struct { Lru lru; Map slots; Table keys, vals; } ProfileCache;
static void pc_init(ProfileCache *c, size_t cap) {
    lru_init(&c->lru, cap); map_init(&c->slots, &USERKEY_TO_ID);
    table_init(&c->keys, sizeof(UserKey), NULL); table_init(&c->vals, sizeof(Profile), profile_drop);
}
static void pc_drop(ProfileCache *c) { lru_drop(&c->lru); map_drop(&c->slots); table_drop(&c->keys); table_drop(&c->vals); }
static int pc_get(ProfileCache *c, UserKey k, Profile *out) {              /* 1 and a COPY in *out on a hit */
    Id *id = map_get(&c->slots, &k);                                       /* BORROW; Id copies implicitly */
    if (!id) return 0;
    Profile *p = table_get(&c->vals, *id);                                 /* BORROW */
    if (!p) return 0;                                                      /* STALE: the entry was evicted */
    lru_touch(&c->lru, *id);                                               /* disjoint field: no conflict with p */
    profile_copy(p, out); return 1;                                        /* COPY */
}
static int pc_put(ProfileCache *c, UserKey k, Profile v, UserKey *evicted) {   /* v is MOVED in */
    Id *known = map_get(&c->slots, &k);
    if (known) { Id id = *known; table_set(&c->vals, id, &v); lru_touch(&c->lru, id); return 0; }   /* t[id] = v: traps if stale */
    Acquired a = lru_acquire(&c->lru);
    int ev = 0;
    if (a.has_victim) {
        UserKey old;
        if (table_remove(&c->keys, a.victim, &old)) {
            if (!inject_forget_slot_removal) map_remove(&c->slots, &old, NULL);
            *evicted = old; ev = 1;
        } else trap("lru victim has no key");                              /* STALE: unreachable */
        table_remove(&c->vals, a.victim, NULL);                            /* DROP the old Profile */
    }
    table_insert(&c->keys, a.id, &k); table_insert(&c->vals, a.id, &v);
    map_insert(&c->slots, &k, &a.id);
    return ev;
}

/* ===== per-use glue: String -> List of Int ===== */
static int str_key_eq(const void *a, const void *b) { return strcmp(*(Str *)a, *(Str *)b) == 0; }
static const MapOps STR_TO_ID = { str_key_eq, str_kcopy, str_drop, NULL, sizeof(Str), sizeof(Id) };
static void int_copy(const void *s, void *d) { memcpy(d, s, sizeof(long)); }

typedef struct { Lru lru; Map slots; Table keys, vals; } QueryCache;
static void qc_init(QueryCache *c, size_t cap) {
    lru_init(&c->lru, cap); map_init(&c->slots, &STR_TO_ID);
    table_init(&c->keys, sizeof(Str), str_drop); table_init(&c->vals, sizeof(List), list_drop);
}
static void qc_drop(QueryCache *c) { lru_drop(&c->lru); map_drop(&c->slots); table_drop(&c->keys); table_drop(&c->vals); }
static int qc_get(QueryCache *c, const Str *k, List *out) {                /* 1 and a COPY on a hit */
    Id *id = map_get(&c->slots, k);
    if (!id) return 0;
    List *l = table_get(&c->vals, *id);
    if (!l) return 0;                                                      /* STALE */
    lru_touch(&c->lru, *id);
    *out = list_copy_with(l, int_copy); return 1;                          /* COPY */
}
static int qc_put(QueryCache *c, const Str *k, List v, Str *evicted) {     /* k is borrowed; v is MOVED in */
    Id *known = map_get(&c->slots, k);
    if (known) { Id id = *known; table_set(&c->vals, id, &v); lru_touch(&c->lru, id); return 0; }
    Acquired a = lru_acquire(&c->lru);
    int ev = 0;
    if (a.has_victim) {
        Str old;
        if (table_remove(&c->keys, a.victim, &old)) {
            if (!inject_forget_slot_removal) map_remove(&c->slots, &old, NULL);
            *evicted = old; ev = 1;                                        /* the key moves out to the caller */
        } else trap("lru victim has no key");                              /* STALE: unreachable */
        table_remove(&c->vals, a.victim, NULL);
    }
    Str k1 = str_copy(*k), k2 = str_copy(*k);                              /* COPY x2: the Table and the Map each own a key */
    table_insert(&c->keys, a.id, &k1); table_insert(&c->vals, a.id, &v);
    map_insert(&c->slots, &k2, &a.id);
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
    Str key = str_copy(k), ev;
    if (qc_put(c, &key, v, &ev)) { printf("queries evict %s\n", ev); str_drop(&ev); }
    str_drop(&key);
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
   In Go option A that returned another entry's value. Here the dangling Id is stale, so get takes `else`
   (--f3), and a later put of the same key traps on `vals[id] = v` (--f3-put). */
static void f3_check(int then_put) {
    inject_forget_slot_removal = 1;
    ProfileCache pc; pc_init(&pc, 2);
    putP(&pc, 1, 1, "Ann", "ann@example.com"); putP(&pc, 1, 2, "Ben", "ben@example.com");
    putP(&pc, 2, 1, "Cy", "cy@example.com");              /* evicts 1/1 but leaves 1/1 -> Id in slots */
    printf("f3: lookup through the dangling Id:\n"); getP(&pc, 1, 1);
    if (then_put) { printf("f3: put through the dangling Id:\n"); putP(&pc, 1, 1, "Ann2", "ann2@example.com"); }
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

typedef struct { Ids ids; Table counts; } Stats;            /* the context passed to every subscriber */
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
/* subscriber 2: captures an Id (copied in) naming a counter in Stats.counts */
typedef struct { Id counter; } CounterEnv;
static void counter_call(void *env, const Event *e, Stats *st) {
    CounterEnv *c = env;
    switch (e->tag) {
    case EV_MESSAGE: *(long *)table_at(&st->counts, c->counter) += 1; break;   /* stats.counts[counter] += 1 */
    case EV_JOINED: case EV_LEFT: break;
    }
}
/* subscriber 3: owns its state outright (a prefix Str moved in, an Int copied in and mutated) */
typedef struct { Str prefix; long n; } WelcomeEnv;
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
    Stats stats; ids_init(&stats.ids); table_init(&stats.counts, sizeof(long), NULL);
    Id counter = ids_issue(&stats.ids); long zero = 0; table_insert(&stats.counts, counter, &zero);
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
    printf("messages seen: %ld\n", *(long *)table_at(&stats.counts, counter));
    list_drop(&bus.subs); table_drop(&stats.counts); ids_drop(&stats.ids);
}

/* ---------------------------------------------------------------- Part 4b: mixed widget kinds */
typedef struct { Str label; long clicks; } Button;
typedef struct { long value, max; } Slider;
typedef struct { Str text; } LabelW;
static void button_drop(void *p) { str_drop(&((Button *)p)->label); }
static void labelw_drop(void *p) { str_drop(&((LabelW *)p)->text); }

/* module-level state (main thread): one Ids for widget identity, one Table per kind */
static Ids widget_ids;
static Table buttons, sliders, labels;

static Str render_button(Id id) { Button *b = table_at(&buttons, id); return str_fmt("[%s] clicks=%ld", b->label, b->clicks); }
static Str render_slider(Id id) {
    Slider *s = table_at(&sliders, id); Str bar = xmalloc((size_t)s->max + 1);
    for (long i = 0; i < s->max; i++) bar[i] = i < s->value ? '#' : '.';
    bar[s->max] = 0; Str out = str_fmt("[%s] %ld/%ld", bar, s->value, s->max); free(bar); return out;
}
static Str render_label(Id id) { return str_copy(((LabelW *)table_at(&labels, id))->text); }   /* COPY: render returns an owned Str */

typedef struct { Str name; Str (*render)(Id); } WidgetKind; /* a record of functions */
static void kind_drop(void *p) { str_drop(&((WidgetKind *)p)->name); }
typedef struct { size_t kind; Id id; } Item;                /* plain data: kind index + Id */

static Id add_button(List *items, const char *label) {
    Id id = ids_issue(&widget_ids); Button b = { str_copy(label), 0 };
    table_insert(&buttons, id, &b); Item it = { 0, id }; list_push(items, &it); return id;
}
static Id add_slider(List *items, long value, long max) {
    Id id = ids_issue(&widget_ids); Slider s = { value, max };
    table_insert(&sliders, id, &s); Item it = { 1, id }; list_push(items, &it); return id;
}
static Id add_label(List *items, const char *text) {
    Id id = ids_issue(&widget_ids); LabelW l = { str_copy(text) };
    table_insert(&labels, id, &l); Item it = { 2, id }; list_push(items, &it); return id;
}

static void part4_widgets(void) {
    printf("-- widgets --\n");
    ids_init(&widget_ids);
    table_init(&buttons, sizeof(Button), button_drop); table_init(&sliders, sizeof(Slider), NULL); table_init(&labels, sizeof(LabelW), labelw_drop);
    List kinds; list_init(&kinds, sizeof(WidgetKind), kind_drop);
    WidgetKind k0 = { str_copy("button"), render_button }, k1 = { str_copy("slider"), render_slider }, k2 = { str_copy("label"), render_label };
    list_push(&kinds, &k0); list_push(&kinds, &k1); list_push(&kinds, &k2);
    List items; list_init(&items, sizeof(Item), NULL);
    Id ok = add_button(&items, "OK"); add_slider(&items, 0, 8); add_label(&items, "Hello");
    add_button(&items, "Cancel"); Id vol = add_slider(&items, 4, 8);
    ((Button *)table_at(&buttons, ok))->clicks += 1; ((Button *)table_at(&buttons, ok))->clicks += 1;   /* buttons[ok].clicks += 1, twice */
    ((Slider *)table_at(&sliders, vol))->value = 8;                       /* sliders[vol].value = 8 */
    /* the first slider is set to 4 through its own Id: items[1] */
    ((Slider *)table_at(&sliders, ((Item *)list_at(&items, 1))->id))->value = 4;
    for (size_t i = 0; i < items.len; i++) {
        Item *it = list_at(&items, i);                                    /* BORROW */
        WidgetKind *k = list_at(&kinds, it->kind);                        /* BORROW */
        Str s = k->render(it->id);                                        /* owned result */
        printf("%s: %s\n", k->name, s);
        str_drop(&s);                                                     /* DROP */
    }
    list_drop(&items); list_drop(&kinds); table_drop(&buttons); table_drop(&sliders); table_drop(&labels); ids_drop(&widget_ids);
}

static void part4(void) {
    printf("== Part 4 (A+ only): outside the stdlib ==\n");
    part4_bus();
    part4_widgets();
}

int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "--f3") == 0) { f3_check(0); return 0; }
    if (argc > 1 && strcmp(argv[1], "--f3-put") == 0) { f3_check(1); return 0; }
    part1(); part2(); part3(); part4();
    return 0;
}
