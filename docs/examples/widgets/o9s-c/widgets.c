/* widgets under model O9-S: owned values, pools of entries, generation-checked typed handles.
   Structs store Handles, never pointers to other pool objects. A pointer from pool_borrow is a borrow:
   it lasts one call and is released with pool_release. Look for "BORROW" and "STALE" comments. */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <stdint.h>

/* ======== O9-S pool library: stands in for the built-in `Pool of T` / `Handle of T` ======== */
typedef struct { uint32_t index, gen, pool; } Handle;     /* pool 0 = the null handle (always stale) */
#define NULL_HANDLE ((Handle){ 0, 0, 0 })
#define NO_SLOT 0xFFFFFFFFu
#define SEG_SLOTS 8u                                       /* small on purpose, so tests cross segments */
enum { SL_FREE, SL_LIVE, SL_DYING, SL_RETIRED };
typedef struct {
    uint32_t gen;                                          /* bumped at remove(), so handles go stale at once */
    uint8_t state, pending;                                /* pending: drop deferred until the borrow ends */
    int borrow;                                            /* 0 free, n>0 shared borrows, -1 one mutable borrow */
    uint32_t owner, first, last, next, prev, nextfree;     /* owner cascade lists */
} Slot;
typedef struct {
    const char *name; uint32_t id; size_t elem, stride;
    uint8_t **seg; uint32_t nseg, capseg, nused, freelist;  /* segments never move: entries never move on add */
    uint32_t live, deferred, retired;
    void (*drop)(void *);                                  /* the type's drop: frees what the entry owns */
} Pool;
#define SLOT_HDR ((sizeof(Slot) + 15) & ~(size_t)15)

static uint32_t next_pool_id = 1;
static void trap(const char *fmt, ...) {                   /* a trap: message on stdout, exit 70 */
    va_list a; va_start(a, fmt);
    printf("TRAP: "); vprintf(fmt, a); printf("\n");
    va_end(a); fflush(stdout); exit(70);
}
static void *xmalloc(size_t n) { void *p = malloc(n ? n : 1); if (!p) { perror("malloc"); exit(1); } return p; }
static void *xrealloc(void *p, size_t n) { p = realloc(p, n); if (!p) { perror("realloc"); exit(1); } return p; }
static char *xstrdup(const char *s) { size_t n = strlen(s) + 1; return memcpy(xmalloc(n), s, n); }
static char *fmt(const char *f, ...) {
    va_list a, b; va_start(a, f); va_copy(b, a);
    int n = vsnprintf(NULL, 0, f, a); va_end(a);
    char *s = xmalloc((size_t)n + 1); vsnprintf(s, (size_t)n + 1, f, b); va_end(b); return s;
}

void pool_init(Pool *p, const char *name, size_t elem, void (*drop)(void *)) {
    memset(p, 0, sizeof *p);
    p->name = name; p->id = next_pool_id++; p->elem = elem; p->drop = drop;
    p->stride = SLOT_HDR + ((elem + 15) & ~(size_t)15); p->freelist = NO_SLOT;
}
static Slot *slot_at(Pool *p, uint32_t i) { return (Slot *)(p->seg[i / SEG_SLOTS] + (size_t)(i % SEG_SLOTS) * p->stride); }
static void *slot_data(Slot *s) { return (uint8_t *)s + SLOT_HDR; }
static Handle slot_handle(Pool *p, uint32_t i) { return (Handle){ i, slot_at(p, i)->gen, p->id }; }
/* NULL if the handle is stale or null. A handle from another pool traps. */
static Slot *pool_slot(Pool *p, Handle h) {
    if (h.pool == 0) return NULL;
    if (h.pool != p->id) trap("handle from pool #%u used on pool '%s' (#%u)", h.pool, p->name, p->id);
    if (h.index >= p->nused) trap("handle index %u out of range in pool '%s'", h.index, p->name);
    Slot *s = slot_at(p, h.index);
    return (s->state == SL_LIVE && s->gen == h.gen) ? s : NULL;
}
int pool_is_live(Pool *p, Handle h) { return pool_slot(p, h) != NULL; }

/* add(value, owner): moves value in. Never moves any existing entry. owner may be borrowed. */
Handle pool_add(Pool *p, const void *value, Handle owner) {
    Slot *os = NULL;
    if (owner.pool) { os = pool_slot(p, owner); if (!os) trap("add: owner handle is stale in pool '%s'", p->name); }
    uint32_t i;
    if (p->freelist != NO_SLOT) { i = p->freelist; p->freelist = slot_at(p, i)->nextfree; }
    else {
        if (p->nused == p->nseg * SEG_SLOTS) {
            if (p->nseg == p->capseg) { p->capseg = p->capseg ? p->capseg * 2 : 4; p->seg = xrealloc(p->seg, sizeof *p->seg * p->capseg); }
            p->seg[p->nseg] = xmalloc(p->stride * SEG_SLOTS);
            for (uint32_t k = 0; k < SEG_SLOTS; k++) {
                Slot *s = (Slot *)(p->seg[p->nseg] + k * p->stride);
                memset(s, 0, sizeof *s); s->gen = 1; s->state = SL_FREE;
            }
            p->nseg++;
        }
        i = p->nused++;
    }
    Slot *s = slot_at(p, i);
    s->state = SL_LIVE; s->pending = 0; s->borrow = 0;
    s->owner = s->first = s->last = s->next = s->prev = NO_SLOT;
    memcpy(slot_data(s), value, p->elem);
    if (os) {
        s->owner = owner.index; s->prev = os->last;
        if (os->last != NO_SLOT) slot_at(p, os->last)->next = i; else os->first = i;
        os->last = i;
    }
    p->live++;
    return slot_handle(p, i);
}
static void unlink_from_owner(Pool *p, Slot *s) {
    if (s->owner == NO_SLOT) return;
    Slot *o = slot_at(p, s->owner);
    if (s->prev != NO_SLOT) slot_at(p, s->prev)->next = s->next; else o->first = s->next;
    if (s->next != NO_SLOT) slot_at(p, s->next)->prev = s->prev; else o->last = s->prev;
    s->owner = s->prev = s->next = NO_SLOT;
}
int pool_remove(Pool *p, Handle h);
static void pool_destroy(Pool *p, uint32_t i) {            /* runs the drop, then the owner cascade */
    Slot *s = slot_at(p, i);
    p->drop(slot_data(s));
    while (s->first != NO_SLOT) pool_remove(p, slot_handle(p, s->first));
    p->live--;
    if (s->gen == UINT32_MAX) { s->state = SL_RETIRED; p->retired++; }   /* generation would wrap: retire the slot */
    else { s->state = SL_FREE; s->nextfree = p->freelist; p->freelist = i; }
}
/* remove(h): h is stale at once. If the entry is borrowed its drop runs at the last release. */
int pool_remove(Pool *p, Handle h) {
    Slot *s = pool_slot(p, h);
    if (!s) return 0;
    unlink_from_owner(p, s);
    s->gen++; s->state = SL_DYING;
    if (s->borrow != 0) { s->pending = 1; p->deferred++; return 1; }
    pool_destroy(p, h.index);
    return 1;
}
/* borrow: NULL if stale. Exclusivity: one mutable borrow, or any number of shared ones. Violation traps. */
void *pool_borrow(Pool *p, Handle h, int mut) {
    Slot *s = pool_slot(p, h);
    if (!s) return NULL;
    if (mut) {
        if (s->borrow != 0) trap("exclusivity: mutable borrow of '%s' entry %u while it is already borrowed", p->name, h.index);
        s->borrow = -1;
    } else {
        if (s->borrow < 0) trap("exclusivity: borrow of '%s' entry %u while it is mutably borrowed", p->name, h.index);
        s->borrow++;
    }
    return slot_data(s);
}
void pool_release(Pool *p, Handle h) {                     /* h may have gone stale during the borrow */
    if (h.pool != p->id) trap("release with handle from another pool");
    Slot *s = slot_at(p, h.index);
    if (s->borrow < 0) s->borrow = 0; else s->borrow--;
    if (s->borrow == 0 && s->pending) { s->pending = 0; pool_destroy(p, h.index); }
}
/* pool[h]: traps on a stale handle. A short read: traps if the entry is mutably borrowed. */
void *pool_at(Pool *p, Handle h) {
    Slot *s = pool_slot(p, h);
    if (!s) trap("pool['%s'] with a stale handle (index %u)", p->name, h.index);
    if (s->borrow < 0) trap("exclusivity: access to '%s' entry %u while it is mutably borrowed", p->name, h.index);
    return slot_data(s);
}
int pool_next(Pool *p, uint32_t *i, Handle *h) {           /* for (u32 i = 0; pool_next(p, &i, &h); ) */
    while (*i < p->nused) {
        uint32_t k = (*i)++;
        if (slot_at(p, k)->state == SL_LIVE) { *h = slot_handle(p, k); return 1; }
    }
    return 0;
}
void pool_expect_empty(Pool *p) { if (p->live) trap("pool '%s' not empty: %u live entries", p->name, p->live); }
void pool_free_storage(Pool *p) { for (uint32_t i = 0; i < p->nseg; i++) free(p->seg[i]); free(p->seg); }
/* ======== end pool library ======== */

/* ======== the widgets program ======== */
typedef enum { K_WINDOW, K_PANEL, K_BUTTON, K_LABEL, K_IMAGE } Kind;
static const char *kind_name[] = { "window", "panel", "button", "label", "image" };

typedef struct { Handle *v; size_t n, cap; } HList;        /* List of Handle */
static int h_eq(Handle a, Handle b) { return a.index == b.index && a.gen == b.gen && a.pool == b.pool; }
static void hl_push(HList *l, Handle h) {
    if (l->n == l->cap) { l->cap = l->cap ? l->cap * 2 : 4; l->v = xrealloc(l->v, sizeof(Handle) * l->cap); }
    l->v[l->n++] = h;
}
static void hl_erase(HList *l, Handle h) {
    for (size_t i = 0; i < l->n; i++) if (h_eq(l->v[i], h)) { memmove(l->v + i, l->v + i + 1, (l->n - i - 1) * sizeof(Handle)); l->n--; return; }
}
static HList hl_copy(const HList *l) {
    HList c = { xmalloc(sizeof(Handle) * l->n), l->n, l->n };
    if (l->n) memcpy(c.v, l->v, sizeof(Handle) * l->n);
    return c;
}
static void hl_free(HList *l) { free(l->v); *l = (HList){ 0 }; }

typedef struct Callback {                                  /* a closure: code + captured values */
    void (*fn)(struct Callback *, Handle self);
    const char *action; Handle target; char *arg;          /* captured: a handle and an owned string */
} Callback;
typedef struct {
    Kind kind; char *name, *text; Handle parent; HList kids;
    Callback on; Handle img; Handle sub;                   /* img: Handle of CacheEntry, sub: Handle of Sub */
} Widget;
typedef struct { char *file, *bytes; int users; } CacheEntry;
typedef struct { void (*fn)(Handle cap, Handle self); Handle cap; } Sub;   /* subscriber: {fn, captured handle} */

static Pool widgets, subs, cache;
static HList windows, sub_order;
static int count;

/* ---- image cache: a hand-written user count ---- */
void cache_drop(void *e) { CacheEntry *c = e; printf("  cache: drop %s\n", c->file); free(c->file); free(c->bytes); }
Handle cache_acquire(const char *file) {
    Handle h;
    for (uint32_t i = 0; pool_next(&cache, &i, &h); ) {
        CacheEntry *e = pool_borrow(&cache, h, 1);
        if (strcmp(e->file, file) == 0) {
            e->users++; printf("  cache: share %s users=%d\n", file, e->users);
            pool_release(&cache, h); return h;
        }
        pool_release(&cache, h);
    }
    size_t n = strlen(file);
    CacheEntry e = { xstrdup(file), xmalloc(n * 100 + 1), 1 };
    for (int k = 0; k < 100; k++) memcpy(e.bytes + n * (size_t)k, file, n);
    e.bytes[n * 100] = 0;
    printf("  cache: new %s (%zu bytes)\n", file, n * 100);
    return pool_add(&cache, &e, NULL_HANDLE);
}
void cache_release(Handle h) {
    CacheEntry *e = pool_borrow(&cache, h, 1);
    if (!e) return;                                        /* STALE: nothing to release */
    e->users--; printf("  cache: release %s users=%d\n", e->file, e->users);
    int last = e->users == 0;
    pool_release(&cache, h);
    if (last) pool_remove(&cache, h);
}

/* ---- model and subscribers ---- */
void sub_drop(void *e) { (void)e; printf("  drop subscriber\n"); }
Handle model_subscribe(void (*fn)(Handle, Handle), Handle cap) {
    Sub s = { fn, cap };
    Handle h = pool_add(&subs, &s, NULL_HANDLE);
    hl_push(&sub_order, h);
    return h;
}
void model_unsub(Handle h) { hl_erase(&sub_order, h); pool_remove(&subs, h); }
void notify(void) {
    HList snap = hl_copy(&sub_order);                      /* callbacks may unsubscribe: iterate a copy */
    for (size_t i = 0; i < snap.n; i++) {
        Sub *s = pool_borrow(&subs, snap.v[i], 0);         /* BORROW: held across the callback */
        if (s) { s->fn(s->cap, snap.v[i]); pool_release(&subs, snap.v[i]); }
        /* else STALE: unsubscribed earlier in this same notify; skip */
    }
    hl_free(&snap);
}
void label_notify(Handle cap, Handle self) {
    (void)self;
    Widget *w = pool_borrow(&widgets, cap, 1);
    if (w) { free(w->text); w->text = fmt("count=%d", count); printf("  notify %s: %s\n", w->name, w->text); pool_release(&widgets, cap); }
    else printf("  notify: label gone\n");                /* STALE (cannot happen: widget drop unsubscribes) */
}
void label_notify_once(Handle cap, Handle self) {
    Widget *w = pool_borrow(&widgets, cap, 1);
    if (w) {
        free(w->text); w->text = fmt("count=%d", count); printf("  notify %s: %s\n", w->name, w->text);
        printf("  once: %s unsubscribes itself\n", w->name);
        w->sub = NULL_HANDLE; model_unsub(self);           /* self is borrowed by notify: its drop is deferred */
        pool_release(&widgets, cap);
    } else printf("  notify: label gone\n");                /* STALE (cannot happen) */
}

/* ---- widgets ---- */
void widget_drop(void *e) {                                /* cross-pool ownership is written in drop */
    Widget *w = e;
    printf("  drop %s %s\n", kind_name[w->kind], w->name);
    if (pool_is_live(&cache, w->img)) cache_release(w->img);
    if (pool_is_live(&subs, w->sub)) model_unsub(w->sub);
    free(w->name); free(w->text); free(w->on.arg); hl_free(&w->kids);
}
Handle find_widget(const char *name) {
    Handle h;
    for (uint32_t i = 0; pool_next(&widgets, &i, &h); )
        if (strcmp(((Widget *)pool_at(&widgets, h))->name, name) == 0) return h;
    return NULL_HANDLE;
}
Handle new_widget(Handle parent, Kind kind, const char *name, const char *arg) {
    Widget w = { kind, xstrdup(name), xstrdup(arg ? arg : ""), parent, { 0 }, { 0 }, NULL_HANDLE, NULL_HANDLE };
    int sub_mode = 0;                                      /* 1 = count, 2 = count-once */
    if (kind == K_IMAGE) w.img = cache_acquire(arg);
    if (kind == K_LABEL && arg && (!strcmp(arg, "count") || !strcmp(arg, "count-once"))) {
        sub_mode = arg[5] ? 2 : 1; free(w.text); w.text = fmt("count=%d", count);
    }
    Handle h = pool_add(&widgets, &w, parent);             /* owner = parent; the parent may be borrowed */
    if (parent.pool) { Widget *p = pool_at(&widgets, parent); hl_push(&p->kids, h); }
    else hl_push(&windows, h);
    if (sub_mode) {
        Handle s = model_subscribe(sub_mode == 2 ? label_notify_once : label_notify, h);
        ((Widget *)pool_at(&widgets, h))->sub = s;
        printf("  subscribed %s\n", name);
    }
    return h;
}
void remove_widget(Handle h) {
    Widget *w = pool_at(&widgets, h);
    if (w->kind == K_WINDOW) hl_erase(&windows, h);
    else if (pool_is_live(&widgets, w->parent)) hl_erase(&((Widget *)pool_at(&widgets, w->parent))->kids, h);
    pool_remove(&widgets, h);                              /* cascades to the whole subtree */
}
Handle enclosing_window(Handle h) {
    for (Handle cur = h; cur.pool; cur = ((Widget *)pool_at(&widgets, cur))->parent)
        if (((Widget *)pool_at(&widgets, cur))->kind == K_WINDOW) return cur;
    return NULL_HANDLE;
}

/* ---- callbacks ---- */
void cb_inc(Callback *c, Handle self) { (void)c; (void)self; count++; printf("  count=%d\n", count); notify(); }
void cb_close(Callback *c, Handle self) {
    (void)c;
    Handle win = enclosing_window(self);
    if (!win.pool) { printf("  close: no enclosing window\n"); return; }
    printf("  close: removing window %s\n", ((Widget *)pool_at(&widgets, win))->name);
    remove_widget(win);                                    /* removes the button running this callback */
}
void cb_open(Callback *c, Handle self) {
    (void)self;
    if (find_widget(c->arg).pool) { printf("  open: %s already exists\n", c->arg); return; }
    Handle win = new_widget(NULL_HANDLE, K_WINDOW, c->arg, NULL);           /* adds while a button is borrowed */
    char *ln = fmt("%s-label", c->arg), *bn = fmt("%s-close", c->arg);
    new_widget(win, K_LABEL, ln, "opened");
    Handle b = new_widget(win, K_BUTTON, bn, NULL);
    Widget *bw = pool_at(&widgets, b);
    bw->on = (Callback){ cb_close, "close", NULL_HANDLE, NULL };
    free(ln); free(bn);
    printf("  open: created window %s\n", c->arg);       /* c->arg is still valid: add never moved the clicked button */
}
void cb_unsub(Callback *c, Handle self) {
    (void)self;
    Widget *l = pool_borrow(&widgets, c->target, 1);
    if (!l) { printf("  unsub: label no longer exists (stale handle)\n"); return; }
    if (pool_is_live(&subs, l->sub)) { printf("  unsub: %s unsubscribed\n", l->name); model_unsub(l->sub); l->sub = NULL_HANDLE; }
    else printf("  unsub: %s is not subscribed\n", l->name);
    pool_release(&widgets, c->target);
}

/* ---- commands ---- */
void print_tree(Handle h, int depth) {
    Widget *w = pool_borrow(&widgets, h, 0);
    if (!w) { printf("%*s(stale child)\n", depth * 2, ""); return; }   /* STALE (cannot happen) */
    printf("%*s%s %s", depth * 2, "", kind_name[w->kind], w->name);
    if (w->kind == K_LABEL) printf(" \"%s\"%s", w->text, pool_is_live(&subs, w->sub) ? " [subscribed]" : "");
    if (w->kind == K_IMAGE) printf(" %s", w->text);
    if (w->on.fn) printf(" [on:%s%s%s]", w->on.action, w->on.arg ? " " : "", w->on.arg ? w->on.arg : "");
    printf("\n");
    for (size_t i = 0; i < w->kids.n; i++) print_tree(w->kids.v[i], depth + 1);
    pool_release(&widgets, h);
}
void print_stats(void) {
    printf("stats: widgets=%u subscribers=%u cache=%u count=%d\n", widgets.live, subs.live, cache.live, count);
}
static void err(const char *f, const char *a) { printf("error: "); printf(f, a); printf("\n"); }

void cmd_window(char **t, int n) {
    if (n < 2) { err("usage: %s NAME", "window"); return; }
    if (find_widget(t[1]).pool) { err("name %s already exists", t[1]); return; }
    new_widget(NULL_HANDLE, K_WINDOW, t[1], NULL);
    printf("created window %s\n", t[1]);
}
void cmd_add(char **t, int n) {
    if (n < 4) { err("usage: %s PARENT KIND NAME [ARG]", "add"); return; }
    Handle p = find_widget(t[1]);
    if (!p.pool) { err("no such widget %s", t[1]); return; }
    Kind pk = ((Widget *)pool_at(&widgets, p))->kind;
    if (pk != K_WINDOW && pk != K_PANEL) { err("%s cannot have children", t[1]); return; }
    Kind k = K_PANEL; int ok = 0;
    for (int i = K_PANEL; i <= K_IMAGE; i++) if (!strcmp(t[2], kind_name[i])) { k = (Kind)i; ok = 1; }
    if (!ok) { err("unknown kind %s", t[2]); return; }
    if (find_widget(t[3]).pool) { err("name %s already exists", t[3]); return; }
    const char *arg = n > 4 ? t[4] : NULL;
    if (k == K_IMAGE && !arg) { err("image %s needs a file name", t[3]); return; }
    new_widget(p, k, t[3], arg);
    printf("added %s %s to %s\n", t[2], t[3], t[1]);
}
void cmd_on(char **t, int n) {
    if (n < 3) { err("usage: %s NAME ACTION [ARG]", "on"); return; }
    Handle b = find_widget(t[1]);
    if (!b.pool) { err("no such widget %s", t[1]); return; }
    Widget *w = pool_at(&widgets, b);
    if (w->kind != K_BUTTON) { err("%s is not a button", t[1]); return; }
    Callback c = { NULL, NULL, NULL_HANDLE, NULL };
    if (!strcmp(t[2], "inc")) { c.fn = cb_inc; c.action = "inc"; }
    else if (!strcmp(t[2], "close")) { c.fn = cb_close; c.action = "close"; }
    else if (!strcmp(t[2], "open") || !strcmp(t[2], "unsub")) {
        if (n < 4) { err("%s needs an argument", t[2]); return; }
        if (!strcmp(t[2], "open")) { c.fn = cb_open; c.action = "open"; }
        else {
            Handle l = find_widget(t[3]);
            if (!l.pool) { err("no such widget %s", t[3]); return; }
            if (((Widget *)pool_at(&widgets, l))->kind != K_LABEL) { err("%s is not a label", t[3]); return; }
            c.fn = cb_unsub; c.action = "unsub"; c.target = l;   /* captures a handle */
        }
        c.arg = xstrdup(t[3]);
    } else { err("unknown action %s", t[2]); return; }
    if (w->on.fn) { printf("  replaced callback '%s'\n", w->on.action); free(w->on.arg); }
    w->on = c;
    printf("%s.onClick = %s\n", t[1], t[2]);
}
void cmd_click(char **t, int n) {
    if (n < 2) { err("usage: %s NAME", "click"); return; }
    Handle h = find_widget(t[1]);
    if (!h.pool) { err("no such widget %s", t[1]); return; }
    Widget *w = pool_borrow(&widgets, h, 0);               /* BORROW: held across the callback */
    if (w->kind != K_BUTTON) err("%s is not a button", t[1]);
    else if (!w->on.fn) printf("click %s: no callback\n", w->name);
    else {
        w->on.fn(&w->on, h);                               /* may remove this very button */
        printf("click %s done%s\n", w->name, pool_is_live(&widgets, h) ? "" : " (button removed itself)");
    }
    pool_release(&widgets, h);                             /* a deferred drop runs here */
}
void cmd_remove(char **t, int n) {
    if (n < 2) { err("usage: %s NAME", "remove"); return; }
    Handle h = find_widget(t[1]);
    if (!h.pool) { err("no such widget %s", t[1]); return; }
    remove_widget(h);
    printf("removed %s\n", t[1]);
}
void cmd_tree(void) {
    if (!windows.n) printf("(no windows)\n");
    for (size_t i = 0; i < windows.n; i++) print_tree(windows.v[i], 0);
}

void widgets_init(void) {
    pool_init(&widgets, "widgets", sizeof(Widget), widget_drop);
    pool_init(&subs, "subscribers", sizeof(Sub), sub_drop);
    pool_init(&cache, "image-cache", sizeof(CacheEntry), cache_drop);
}
int widgets_finish(void) {
    printf("exit report: widgets=%u subscribers=%u cache=%u\n", widgets.live, subs.live, cache.live);
    printf("deferred drops: widgets=%u subscribers=%u cache=%u\n", widgets.deferred, subs.deferred, cache.deferred);
    pool_expect_empty(&widgets); pool_expect_empty(&subs); pool_expect_empty(&cache);
    hl_free(&windows); hl_free(&sub_order);
    pool_free_storage(&widgets); pool_free_storage(&subs); pool_free_storage(&cache);
    return 0;
}

#ifndef WIDGETS_AS_LIB
int main(void) {
    widgets_init();
    char line[512];
    while (fgets(line, sizeof line, stdin)) {
        line[strcspn(line, "\r\n")] = 0;
        char *p = line; while (*p == ' ' || *p == '\t') p++;
        if (!*p || *p == '#') continue;
        printf("> %s\n", p);
        char *t[6] = { 0 }; int n = 0;
        for (char *tok = strtok(p, " \t"); tok && n < 6; tok = strtok(NULL, " \t")) t[n++] = tok;
        if (!strcmp(t[0], "window")) cmd_window(t, n);
        else if (!strcmp(t[0], "add")) cmd_add(t, n);
        else if (!strcmp(t[0], "on")) cmd_on(t, n);
        else if (!strcmp(t[0], "click")) cmd_click(t, n);
        else if (!strcmp(t[0], "remove")) cmd_remove(t, n);
        else if (!strcmp(t[0], "tree")) cmd_tree();
        else if (!strcmp(t[0], "stats")) print_stats();
        else err("unknown command %s", t[0]);
    }
    return widgets_finish();
}
#endif
