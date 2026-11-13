/* C model of the merged D4 design (E1 spelling over E2 Result values). Prints ../../expected.txt.
   Model, not a product: Result-of-T structs with ONE Error type; must-consume emulated by a per-thread counter that
   is checked at exit; traps are setjmp/longjmp per crew child with a per-thread drop stack. `errors --selftest`
   runs the checks that expected.txt cannot show. Windows (MinGW): see the notes at part 2 (rename) and run_child. */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <errno.h>
#include <setjmp.h>
#include <stdatomic.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <dirent.h>
#ifdef _WIN32
#include <io.h>
#include <direct.h>
#define popen _popen
#define pclose _pclose
#define make_dir_raw(p) _mkdir(p)
#define rmdir_raw(p) _rmdir(p)
#else
#include <unistd.h>
#include <sys/wait.h>
#define make_dir_raw(p) mkdir((p), 0755)
#define rmdir_raw(p) rmdir(p)
#endif
#if defined(__GNUC__)
#pragma GCC diagnostic ignored "-Wunused-function"
#endif
#include "../../../chatsim/c/thread_compat.h"

/* ================= the one Error type ================= */
typedef enum { K_PARSE, K_IO, K_INVALID, K_STATE, K_TRAP, K_TEST } Kind;
/* bounded copy and join (silences truncation warnings honestly: truncation is the defined behaviour) */
static void scpy(char *d, size_t n, const char *s) { size_t l = strlen(s); if (l >= n) l = n - 1; memcpy(d, s, l); d[l] = 0; }
static void sjoin(char *d, size_t n, const char *a, const char *b) { scpy(d, n, a); size_t l = strlen(d); if (l + 1 < n) { d[l++] = '/'; scpy(d + l, n - l, b); } }
#define MSGN 120
#define CTXN 6
#define CTXLEN 56
#define TRN 8
typedef struct { const char *fn; int line; } Site;
typedef struct {
    Kind kind;
    char msg[MSGN];
    char ctx[CTXN][CTXLEN];   /* innermost first */
    int nctx;
    Site trace[TRN];          /* inline, no allocation (M3) */
    int ntrace;
    int more;                 /* crew: other errors besides this one */
} Error;

static Error err_new(Kind k, const char *fn, int line, const char *fmt, ...) {
    Error e; memset(&e, 0, sizeof e);
    e.kind = k;
    va_list ap; va_start(ap, fmt); vsnprintf(e.msg, MSGN, fmt, ap); va_end(ap);
    e.trace[e.ntrace].fn = fn; e.trace[e.ntrace++].line = line;
    return e;
}
static void err_ctx(Error *e, const char *fmt, ...) {
    if (e->nctx >= CTXN) return;
    va_list ap; va_start(ap, fmt); vsnprintf(e->ctx[e->nctx++], CTXLEN, fmt, ap); va_end(ap);
}
static void err_site(Error *e, const char *fn, int line) {
    if (e->ntrace < TRN) { e->trace[e->ntrace].fn = fn; e->trace[e->ntrace++].line = line; }
}
static void err_str(const Error *e, char *buf, size_t n) {
    size_t o = 0; buf[0] = 0;
    for (int i = e->nctx - 1; i >= 0 && o < n; i--) o += (size_t)snprintf(buf + o, n - o, "%s: ", e->ctx[i]);
    if (o < n) o += (size_t)snprintf(buf + o, n - o, "%s", e->msg);
    if (e->more > 0 && o < n) snprintf(buf + o, n - o, " (plus %d more)", e->more);
}

/* ================= Result of T + must-consume ================= */
static _Thread_local int tl_pending;      /* Results created and not yet consumed, per thread */
static atomic_int g_violations;           /* children that ended with unconsumed Results */
static atomic_int g_dirty_close;          /* debug exit report: Locks dropped without close() */
static inline int live_new(void) { tl_pending++; return 1; }
static inline void consume(int *live) { if (*live) { *live = 0; tl_pending--; } }

#define DEF_RESULT(N, T) typedef struct { int ok; int live; T val; Error err; } N;
#define OK(N, v) ((N){ .ok = 1, .live = live_new(), .val = (v) })
#define UNIT(N) ((N){ .ok = 1, .live = live_new() })
#define ERRV(N, e) ((N){ .ok = 0, .live = live_new(), .err = (e) })
#define FAIL(N, k, ...) ERRV(N, err_new(k, __func__, __LINE__, __VA_ARGS__))
#define IS_OK(r) (consume(&(r).live), (r).ok)   /* match / .is_ok(): the only way to look at a Result */

/* `x = try call` (outermost operation of a statement). The context text is formatted only on the error path. */
#define TRY_IMPL(RT, assign, ctxstmt, call) do { \
        __typeof__(call) try_r_ = (call); consume(&try_r_.live); \
        if (!try_r_.ok) { ctxstmt; err_site(&try_r_.err, __func__, __LINE__); return ERRV(RT, try_r_.err); } \
        assign; } while (0)
#define TRY(RT, call) TRY_IMPL(RT, (void)0, (void)0, call)
#define TRYV(RT, v, call) TRY_IMPL(RT, v = try_r_.val, (void)0, call)
#define TRYC(RT, call, ...) TRY_IMPL(RT, (void)0, err_ctx(&try_r_.err, __VA_ARGS__), call)
#define TRYVC(RT, v, call, ...) TRY_IMPL(RT, v = try_r_.val, err_ctx(&try_r_.err, __VA_ARGS__), call)

DEF_RESULT(RUnit, char)
DEF_RESULT(RInt, int)

/* ================= traps: frames, drop stack, unwinding ================= */
typedef void (*drop_fn)(void *arg, int unwinding);
typedef enum { F_CHILD, F_PARENT, F_EXPECT } FrameKind;
typedef struct Frame { jmp_buf jb; FrameKind kind; size_t drop_base; Error err; struct Frame *prev; } Frame;
static _Thread_local struct {
    struct { drop_fn fn; void *arg; } drops[16];
    size_t ndrops;
    Frame *top;
    int barrier;        /* inside a callback from C */
    int unwinding;
    Error pending;
    jmp_buf unw;
} tl;

static void drop_push(drop_fn fn, void *arg) {
    if (tl.ndrops >= 16) { fputs("TRAP: drop stack overflow\n", stderr); fflush(NULL); _Exit(70); }
    tl.drops[tl.ndrops].fn = fn; tl.drops[tl.ndrops++].arg = arg;
}
static void drop_pop(drop_fn fn, void *arg) {
    if (tl.ndrops == 0 || tl.drops[tl.ndrops - 1].fn != fn || tl.drops[tl.ndrops - 1].arg != arg) {
        fputs("TRAP: drop stack mismatch\n", stderr); fflush(NULL); _Exit(70);
    }
    tl.ndrops--;
}

static void abort_trap(const Error *e, const char *why) {   /* S5: no crew child to convert to */
    fprintf(stderr, "TRAP: %s (%s)\n", e->msg, why);
    for (int i = 0; i < e->ntrace; i++) fprintf(stderr, "  at %s:%d\n", e->trace[i].fn, e->trace[i].line);
    fflush(NULL);
    _Exit(70);
}

/* Runs registered drops down to `base`. A trap inside a drop lands at tl.unw and is appended to the chain (S5). */
static void unwind_to(size_t base) {
    tl.unwinding = 1;
    (void)setjmp(tl.unw);
    while (tl.ndrops > base) {
        size_t i = --tl.ndrops;
        tl.drops[i].fn(tl.drops[i].arg, 1);
    }
    tl.unwinding = 0;
}

_Noreturn static void trap_err(Error e) {
    if (tl.unwinding) {   /* trap inside a drop during unwinding */
        char note[CTXLEN]; snprintf(note, sizeof note, "also trapped in drop: %.30s", e.msg);
        err_ctx(&tl.pending, "%s", note);
        longjmp(tl.unw, 1);
    }
    if (tl.barrier > 0) abort_trap(&e, "inside a callback from C: barrier");
    if (!tl.top) abort_trap(&e, "outside any crew");
    Frame *f = tl.top;
    tl.pending = e;
    unwind_to(f->drop_base);
    f->err = tl.pending;
    longjmp(f->jb, 1);
}
#define TRAP(...) trap_err(err_new(K_TRAP, __func__, __LINE__, __VA_ARGS__))

/* callback-from-C barrier: our comparator runs inside qsort, so a trap there aborts even inside a crew child */
typedef int (*cmp_fn)(const void *, const void *);
static _Thread_local cmp_fn tl_cb;
static int cb_shim(const void *a, const void *b) { tl.barrier++; int r = tl_cb(a, b); tl.barrier--; return r; }
static void c_qsort(void *base, size_t n, size_t sz, cmp_fn cb) { tl_cb = cb; qsort(base, n, sz, cb_shim); }

/* expect_trap { ... }: passes iff the body traps. Test-only. */
static int expect_trap(void (*fn)(void *), void *arg, Error *out) {
    Frame f; f.kind = F_EXPECT; f.drop_base = tl.ndrops; f.prev = tl.top; tl.top = &f;
    volatile int trapped = 0;
    if (setjmp(f.jb) == 0) fn(arg); else trapped = 1;
    tl.top = f.prev;
    if (trapped && out) *out = f.err;
    return trapped;
}

/* ---- poisoned mutex (S7) ---- */
typedef struct { mutex_t m; atomic_int poisoned; } PMutex;
static void pm_init(PMutex *p) { mutex_init(&p->m); atomic_init(&p->poisoned, 0); }
static void pm_drop(void *a, int unwinding) {
    PMutex *p = a;
    if (unwinding) atomic_store(&p->poisoned, 1);
    mutex_unlock(&p->m);                       /* the lock is released while unwinding */
}
static void pm_lock(PMutex *p) {
    if (atomic_load(&p->poisoned)) TRAP("lock on a poisoned mutex");
    mutex_lock(&p->m);
    drop_push(pm_drop, p);
}
static void pm_unlock(PMutex *p) { drop_pop(pm_drop, p); mutex_unlock(&p->m); }
static int pm_is_poisoned(PMutex *p) { return atomic_load(&p->poisoned); }
static void pm_clear_poison(PMutex *p) { atomic_store(&p->poisoned, 0); }

/* ---- F1: a variable a child borrowed mutably dies if the child traps ----
   Real language: compile error through the move checker. Model: a run-time `dead` flag; use of a dead Cell traps. */
typedef struct { int v; int dead; } Cell;
static void cell_drop(void *a, int unwinding) { if (unwinding) ((Cell *)a)->dead = 1; }
static void cell_borrow_mut(Cell *c) { drop_push(cell_drop, c); }
static void cell_release(Cell *c) { drop_pop(cell_drop, c); }
static int cell_get(Cell *c) { if (c->dead) TRAP("use of a variable dead after a trapped crew child"); return c->v; }

/* ================= crews ================= */
typedef struct Crew Crew;
typedef RInt (*child_fn)(Crew *, int id, void *arg);
typedef struct { Crew *c; int id; child_fn fn; void *arg; RInt res; thread_t th; } Child;
struct Crew { Child ch[8]; int n; atomic_int cancel; };

static void child_main(void *p) {
    Child *ch = p;
    Frame f; f.kind = F_CHILD; f.drop_base = 0; f.prev = NULL; tl.top = &f; tl.ndrops = 0;
    tl_pending = 0;
    volatile int trapped = 0;
    if (setjmp(f.jb) == 0) ch->res = ch->fn(ch->c, ch->id, ch->arg); else trapped = 1;
    tl.top = NULL;
    if (trapped) {   /* conversion at the brace: Error of kind trap, a worker context, a site */
        Error e = f.err; err_ctx(&e, "worker %d", ch->id + 1); err_site(&e, "crew brace", 0);
        ch->res = ERRV(RInt, e);
        tl_pending = 1;   /* only the result we just made; whatever the dead frames held is gone */
    }
    (void)IS_OK(ch->res);                         /* handed over to the crew: consumed here */
    if (tl_pending != 0) atomic_fetch_add(&g_violations, 1);
    if (!ch->res.ok) atomic_store(&ch->c->cancel, 1);
}
static void crew_go(Crew *c, child_fn fn, void *arg) {
    Child *ch = &c->ch[c->n];
    ch->c = c; ch->id = c->n; ch->fn = fn; ch->arg = arg;
    c->n++;
    if (thread_start(&ch->th, child_main, ch) != 0) { fputs("thread_start failed\n", stderr); exit(2); }
}
typedef void (*crew_body)(Crew *, void *);

/* `crew c { body }` (try_mode 0) or `try crew c { body }` (try_mode 1).
   F2: only a child's trap is converted, and only in try mode. A trap in the body cancels, joins, and continues. */
static RUnit crew_run(int try_mode, crew_body body, void *arg) {
    Crew c; memset(&c, 0, sizeof c); atomic_init(&c.cancel, 0);
    Frame f; f.kind = F_PARENT; f.drop_base = tl.ndrops; f.prev = tl.top; tl.top = &f;
    volatile int trapped = 0;
    if (setjmp(f.jb) == 0) body(&c, arg); else trapped = 1;
    tl.top = f.prev;
    if (trapped) atomic_store(&c.cancel, 1);
    for (int i = 0; i < c.n; i++) thread_join(&c.ch[i].th);
    if (trapped) trap_err(f.err);                 /* not converted: the trap goes on */
    int cnt = 0, first = -1;                      /* "first" = lowest worker number */
    for (int i = 0; i < c.n; i++) if (!c.ch[i].res.ok) { if (first < 0) first = i; cnt++; }
    if (first >= 0 && !try_mode && c.ch[first].res.err.kind == K_TRAP) {
        for (int i = 0; i < c.n; i++) if (!c.ch[i].res.ok && c.ch[i].res.err.kind == K_TRAP) trap_err(c.ch[i].res.err);
    }
    if (first < 0) return UNIT(RUnit);
    Error e = c.ch[first].res.err;
    e.more = cnt - 1;
    return ERRV(RUnit, e);
}

/* ================= part 1 ================= */
typedef struct { char section[24], key[24], value[48]; } Entry;
typedef struct { Entry e[16]; int n; } Config;
DEF_RESULT(RConfig, Config)
typedef struct { Config cfg; char section[24]; } Parser;

static const char *config_get(const Config *c, const char *sec, const char *key) {   /* Optional: NULL = absent */
    for (int i = 0; i < c->n; i++) if (!strcmp(c->e[i].section, sec) && !strcmp(c->e[i].key, key)) return c->e[i].value;
    return NULL;
}
static void trim(char *s) {
    size_t n = strlen(s);
    while (n && (s[n - 1] == ' ' || s[n - 1] == '\t' || s[n - 1] == '\r')) s[--n] = 0;
    size_t k = 0; while (s[k] == ' ' || s[k] == '\t') k++;
    memmove(s, s + k, strlen(s + k) + 1);
}
static const char *key_at(const Config *c, int i) {
    if (i < 0 || i >= c->n) TRAP("index %d out of range (len %d)", i, c->n);
    return c->e[i].key;
}
static RUnit parse_line(Parser *p, int no, const char *raw) {
    char line[160]; snprintf(line, sizeof line, "%s", raw); trim(line);
    size_t n = strlen(line);
    if (n == 0 || line[0] == '#') return UNIT(RUnit);
    if (line[0] == '[' && line[n - 1] == ']') { line[n - 1] = 0; scpy(p->section, sizeof p->section, line + 1); return UNIT(RUnit); }
    char *eq = strchr(line, '=');
    if (!eq) return FAIL(RUnit, K_PARSE, "config.ini:%d: missing '='", no);
    *eq = 0;
    char key[24]; scpy(key, sizeof key, line); trim(key);
    if (!key[0]) return FAIL(RUnit, K_PARSE, "config.ini:%d: empty key", no);
    if (config_get(&p->cfg, p->section, key)) return FAIL(RUnit, K_PARSE, "config.ini:%d: duplicate key '%s' in [%s]", no, key, p->section);
    Entry *e = &p->cfg.e[p->cfg.n++];
    snprintf(e->section, sizeof e->section, "%s", p->section);
    snprintf(e->key, sizeof e->key, "%s", key);
    char val[48]; snprintf(val, sizeof val, "%s", eq + 1); trim(val);
    snprintf(e->value, sizeof e->value, "%s", val);
    return UNIT(RUnit);
}
static int next_line(const char **cur, char *buf, size_t n) {
    if (!**cur) return 0;
    const char *nl = strchr(*cur, '\n');
    size_t len = nl ? (size_t)(nl - *cur) : strlen(*cur);
    if (len >= n) len = n - 1;
    memcpy(buf, *cur, len); buf[len] = 0;
    *cur = nl ? nl + 1 : *cur + strlen(*cur);
    return 1;
}
static RConfig parse_fail_fast(const char *text) {
    Parser p; memset(&p, 0, sizeof p);
    char l[160]; int no = 0;
    while (next_line(&text, l, sizeof l)) { no++; TRY(RConfig, parse_line(&p, no, l)); }
    return OK(RConfig, p.cfg);
}
typedef struct { Error errs[8]; int n; } Report;
static void report_add_if_err(Report *r, RUnit res) {     /* consumes the Result */
    if (!IS_OK(res) && r->n < 8) r->errs[r->n++] = res.err;
}
static Config parse_all(const char *text, Report *rep) {
    Parser p; memset(&p, 0, sizeof p);
    char l[160]; int no = 0;
    while (next_line(&text, l, sizeof l)) { no++; report_add_if_err(rep, parse_line(&p, no, l)); }
    return p.cfg;
}
static RInt parse_int(const char *s) {
    char *end; long v = strtol(s, &end, 10);
    if (end == s || *end) return FAIL(RInt, K_PARSE, "not an integer: %s", s);
    return OK(RInt, (int)v);
}
static const char *bad_text = "# sample config\n[server]\nport = 8080\nhost\n= nokey\nport = 9090\n[db]\nname = x\n";
static const char *good_text = "# sample config\n[server]\nport = 8080\nhost = localhost\n[db]\nname = x\n";

static RUnit part1(void) {
    char buf[256];
    puts("== part 1: config parser");
    RConfig ff = parse_fail_fast(bad_text);
    if (!IS_OK(ff)) { err_str(&ff.err, buf, sizeof buf); printf("fail-fast: %s\n", buf); }
    Report rep; memset(&rep, 0, sizeof rep);
    (void)parse_all(bad_text, &rep);
    puts("collect-all:");
    for (int i = 0; i < rep.n; i++) { err_str(&rep.errs[i], buf, sizeof buf); printf("  %s\n", buf); }
    printf("%d errors\n", rep.n);

    Config cfg;
    TRYV(RUnit, cfg, parse_fail_fast(good_text));
    const char *s = config_get(&cfg, "server", "port");
    if (s) { int port; TRYVC(RUnit, port, parse_int(s), "server.port"); printf("server.port = %d\n", port); }
    s = config_get(&cfg, "server", "timeout");
    if (s) printf("server.timeout = %s\n", s); else puts("timeout not set, using 30");
    return UNIT(RUnit);
}

/* ================= part 2 ================= */
typedef struct { void (*undo)(void *); void *arg; int committed; } Txn;
static void txn_drop(void *a, int unwinding) { (void)unwinding; Txn *t = a; if (!t->committed) t->undo(t->arg); }
static void txn_begin(Txn *t, void (*undo)(void *), void *arg) { t->undo = undo; t->arg = arg; t->committed = 0; drop_push(txn_drop, t); }
static void txn_commit(Txn *t) { t->committed = 1; }
static void txn_end(Txn *t) { drop_pop(txn_drop, t); if (!t->committed) t->undo(t->arg); }   /* scope exit */

typedef struct { char path[256]; int open; } Lock;
static RUnit inject(int fail_at, int step) { if (fail_at == step) return FAIL(RUnit, K_TEST, "injected failure"); return UNIT(RUnit); }
static RUnit lock_create(Lock *l, const char *path) {
#ifdef _WIN32
    int fd = _open(path, _O_CREAT | _O_EXCL | _O_WRONLY, _S_IREAD | _S_IWRITE);
#else
    int fd = open(path, O_CREAT | O_EXCL | O_WRONLY, 0644);
#endif
    if (fd < 0) return FAIL(RUnit, K_IO, "%s", strerror(errno));
#ifdef _WIN32
    _close(fd);
#else
    close(fd);
#endif
    snprintf(l->path, sizeof l->path, "%s", path); l->open = 1;
    return UNIT(RUnit);
}
static RUnit lock_close(Lock *l) {     /* try lock.close(): consuming, fallible */
    if (remove(l->path) != 0) return FAIL(RUnit, K_IO, "%s", strerror(errno));
    l->open = 0;
    return UNIT(RUnit);
}
static RUnit write_file(const char *path, const char *s) {   /* File.create + write + try f.close() */
    FILE *f = fopen(path, "wb");
    if (!f) return FAIL(RUnit, K_IO, "%s", strerror(errno));
    size_t w = fwrite(s, 1, strlen(s), f);
    int cl = fclose(f);
    if (w != strlen(s) || cl != 0) return FAIL(RUnit, K_IO, "%s", strerror(errno));
    return UNIT(RUnit);
}
static RUnit read_file(const char *path, char *out, size_t n) {
    FILE *f = fopen(path, "rb");
    if (!f) return FAIL(RUnit, K_IO, "%s", strerror(errno));
    size_t r = fread(out, 1, n - 1, f); out[r] = 0; fclose(f);
    return UNIT(RUnit);
}
static RUnit rename_over(const char *from, const char *to) {
#ifdef _WIN32
    remove(to);     /* Windows: rename() will not replace. remove-then-rename is NOT atomic; the model accepts that */
#endif
    if (rename(from, to) != 0) return FAIL(RUnit, K_IO, "%s", strerror(errno));
    return UNIT(RUnit);
}
static RUnit make_dir(const char *d) { if (make_dir_raw(d) != 0) return FAIL(RUnit, K_IO, "%s", strerror(errno)); return UNIT(RUnit); }
static int cmp_str(const void *a, const void *b) { return strcmp(a, b); }
static void list_dir(const char *dir, char *out, size_t n) {
    char names[32][64]; int cnt = 0;
    DIR *d = opendir(dir);
    out[0] = 0;
    if (!d) return;
    struct dirent *e;
    while ((e = readdir(d)) && cnt < 32) {
        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
        scpy(names[cnt++], 64, e->d_name);
    }
    closedir(d);
    qsort(names, (size_t)cnt, 64, cmp_str);
    size_t o = 0;
    for (int i = 0; i < cnt; i++) o += (size_t)snprintf(out + o, n - o, "%s%s", i ? " " : "", names[i]);
}
static void rm_tree(const char *dir) {      /* best effort, cannot fail: used from drops */
    char names[32][64]; int cnt = 0;
    DIR *d = opendir(dir);
    if (!d) return;
    struct dirent *e;
    while ((e = readdir(d)) && cnt < 32) {
        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
        scpy(names[cnt++], 64, e->d_name);
    }
    closedir(d);
    for (int i = 0; i < cnt; i++) { char p[256]; sjoin(p, sizeof p, dir, names[i]); remove(p); }
    rmdir_raw(dir);
}

typedef struct { char lock[256], tmp[256], dst[256]; Lock lk; const char *content; int fail_at; } Rep;
static void rep_undo(void *a) {      /* Txn undo: infallible. A Lock still open here is a dirty drop (R4 report). */
    Rep *r = a;
    remove(r->tmp);
    if (r->lk.open) { atomic_fetch_add(&g_dirty_close, 1); remove(r->lk.path); r->lk.open = 0; }
}
static RUnit rf_body(Rep *r, Txn *t) {
    TRYC(RUnit, lock_create(&r->lk, r->lock), "step 1: create lock");
    TRYC(RUnit, inject(r->fail_at, 1), "step 1: create lock");
    TRYC(RUnit, write_file(r->tmp, r->content), "step 2: write temp");
    TRYC(RUnit, inject(r->fail_at, 2), "step 2: write temp");
    TRYC(RUnit, inject(r->fail_at, 3), "step 3: rename temp");
    TRYC(RUnit, rename_over(r->tmp, r->dst), "step 3: rename temp");
    TRYC(RUnit, inject(r->fail_at, 4), "step 4: remove lock");
    TRYC(RUnit, lock_close(&r->lk), "step 4: remove lock");
    txn_commit(t);
    return UNIT(RUnit);
}
static RUnit replace_file(const char *dir, const char *name, const char *content, int fail_at) {
    Rep r; memset(&r, 0, sizeof r);
    { char n2[128]; snprintf(n2, sizeof n2, "%.100s.lock", name); sjoin(r.lock, sizeof r.lock, dir, n2); }
    { char n2[128]; snprintf(n2, sizeof n2, "%.100s.tmp", name); sjoin(r.tmp, sizeof r.tmp, dir, n2); }
    sjoin(r.dst, sizeof r.dst, dir, name);
    r.content = content; r.fail_at = fail_at;
    Txn t; txn_begin(&t, rep_undo, &r);
    RUnit res = rf_body(&r, &t);
    txn_end(&t);                           /* scope exit: undo unless committed */
    return res;
}
static void dir_undo(void *a) { rm_tree(a); }
static RUnit part2_body(const char *dir) {
    char path[256], files[256], content[64], buf[200];
    sjoin(path, sizeof path, dir, "data.txt");
    TRYC(RUnit, write_file(path, "old"), "seed data.txt");
    puts("start: content old");
    static const char *const labels[] = { "no failure", "fail at step 1", "fail at step 2", "fail at step 3", "fail at step 4" };
    for (int run = 0; run < 5; run++) {
        char v[16], res[300];
        snprintf(v, sizeof v, "v%d", run + 1);
        RUnit r = replace_file(dir, "data.txt", v, run);
        if (IS_OK(r)) snprintf(res, sizeof res, "ok");
        else { err_str(&r.err, buf, sizeof buf); snprintf(res, sizeof res, "error: %s", buf); }
        printf("run %d, %s: %s\n", run + 1, labels[run], res);
        list_dir(dir, files, sizeof files);
        TRYC(RUnit, read_file(path, content, sizeof content), "read data.txt");
        printf("  files: %s\n  content: %s\n", files, content);
    }
    return UNIT(RUnit);
}
static RUnit part2(void) {
    const char *dir = "errors-tmp.d";      /* under the current directory (build/): no tmpnam, same on all OSes */
    rm_tree(dir);                          /* stale leftover from a crashed run */
    puts("== part 2: replace_file");
    TRYC(RUnit, make_dir(dir), "make temp dir");
    Txn t; txn_begin(&t, dir_undo, (void *)dir);   /* never committed: acts as defer */
    RUnit r = part2_body(dir);
    txn_end(&t);
    return r;
}

/* ================= part 3 ================= */
static const char *const texts[4] = { "[a]\nx = 1\n", "[b]\nname = w2\nbroken line\n", "[c]\nz = 3\n", "[d]\nk = 4\n" };
typedef struct { PMutex *m; Cell *tally; } W3;
static RInt worker(Crew *c, int id, void *arg) {
    (void)c; (void)arg;
    Config cfg;
    TRYVC(RInt, cfg, parse_fail_fast(texts[id]), "worker %d", id + 1);
    return OK(RInt, cfg.n);
}
static RInt worker3(Crew *c, int id, void *arg) {
    (void)c; (void)id;
    W3 *w = arg;
    Config cfg;
    TRYVC(RInt, cfg, parse_fail_fast(texts[2]), "worker 3");
    pm_lock(w->m);                          /* lock m { */
    cell_borrow_mut(w->tally);              /* F1: &mut tally */
    w->tally->v += 10;                      /* half-done update */
    printf("%s", key_at(&cfg, cfg.n + 5));  /* trap: index out of range */
    cell_release(w->tally);
    pm_unlock(w->m);
    return OK(RInt, cfg.n);
}
typedef struct { W3 w3; } P3;
static void p3_body(Crew *c, void *a) {
    P3 *p = a;
    crew_go(c, worker, NULL); crew_go(c, worker, NULL); crew_go(c, worker3, &p->w3); crew_go(c, worker, NULL);
}
static void w3_direct(void *a) { RInt r = worker3(NULL, 2, a); (void)IS_OK(r); }
static RUnit part3(void) {
    puts("== part 3: crew");
    PMutex m; pm_init(&m);
    Cell tally = { 100, 0 };
    P3 p = { { &m, &tally } };
    RUnit r = crew_run(1, p3_body, &p);      /* _ = try crew c { ... } or e { print } */
    if (!IS_OK(r)) { char buf[256]; err_str(&r.err, buf, sizeof buf); printf("error: %s\n", buf); }
    /* print(tally)  <- compile error in the real language (F1); in the model cell_get(&tally) would trap */
    printf("mutex poisoned: %s\n", pm_is_poisoned(&m) ? "yes" : "no");

    PMutex scratch; pm_init(&scratch); Cell t = { 0, 0 }; W3 w = { &scratch, &t };
    Error e;
    if (!expect_trap(w3_direct, &w, &e) || e.kind != K_TRAP || !pm_is_poisoned(&scratch)) {
        puts("expect_trap FAILED"); return FAIL(RUnit, K_TEST, "worker 3 did not trap");
    }
    puts("expect_trap ok");
    return UNIT(RUnit);
}

/* ================= exit report, main ================= */
static const char *g_argv0;
static void at_exit_report(void) {
    if (tl_pending != 0) { fprintf(stderr, "error: %d unconsumed Result(s) at exit\n", tl_pending); fflush(NULL); _Exit(99); }
    int d = atomic_load(&g_dirty_close);
    if (d) fprintf(stderr, "exit report (R4): %d Lock(s) dropped without close()\n", d);
}

/* ================= selftest ================= */
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } else printf("ok   %s\n", #c); } while (0)

static int run_child(const char *mode, char *out, size_t n) {   /* re-exec self; Windows: _popen via cmd.exe */
    char cmd[600];
#ifdef _WIN32
    snprintf(cmd, sizeof cmd, "\"\"%s\" %s 2>&1\"", g_argv0, mode);
#else
    snprintf(cmd, sizeof cmd, "\"%s\" %s 2>&1", g_argv0, mode);
#endif
    FILE *p = popen(cmd, "r");
    size_t o = 0;
    if (!p) return -1;
    int ch;
    while ((ch = fgetc(p)) != EOF) if (o + 1 < n) out[o++] = (char)ch;
    out[o] = 0;
    int st = pclose(p);
#ifdef _WIN32
    return st;
#else
    return WIFEXITED(st) ? WEXITSTATUS(st) : 128;
#endif
}
static atomic_int inner_joined, inner_returned, drop_a_ran;
static RInt slow_worker(Crew *c, int id, void *arg) { (void)c; (void)id; (void)arg; sleep_ms(30); atomic_store(&inner_joined, 1); return OK(RInt, 0); }
static void inner_body_traps(Crew *c, void *arg) { (void)arg; crew_go(c, slow_worker, NULL); TRAP("parent body trap"); }
static RInt child_parent_trap(Crew *c, int id, void *arg) {
    (void)c; (void)id; (void)arg;
    RUnit r = crew_run(1, inner_body_traps, NULL);   /* try crew whose BODY traps: not converted */
    atomic_store(&inner_returned, 1); (void)IS_OK(r);
    return OK(RInt, 0);
}
static RInt trapping_worker(Crew *c, int id, void *arg) { (void)c; (void)id; (void)arg; TRAP("child trap"); }
static void inner_body_child_trap(Crew *c, void *arg) { (void)arg; crew_go(c, trapping_worker, NULL); }
static RInt child_plain_crew(Crew *c, int id, void *arg) {
    (void)c; (void)id; (void)arg;
    RUnit r = crew_run(0, inner_body_child_trap, NULL);   /* plain crew re-traps a child's trap */
    atomic_store(&inner_returned, 1); (void)IS_OK(r);
    return OK(RInt, 0);
}
static void body_one(Crew *c, void *arg) { crew_go(c, (child_fn)arg, NULL); }
static void drop_traps(void *a, int u) { (void)a; (void)u; TRAP("drop trap"); }
static void drop_a(void *a, int u) { (void)a; (void)u; atomic_store(&drop_a_ran, 1); }
static RInt child_drop_trap(Crew *c, int id, void *arg) {
    (void)c; (void)id; (void)arg;
    drop_push(drop_a, NULL); drop_push(drop_traps, NULL);
    TRAP("body trap");
}
static void use_dead(void *a) { (void)cell_get(a); }
static void lock_poisoned(void *a) { pm_lock(a); }
static int cmp_traps(const void *a, const void *b) { (void)a; (void)b; TRAP("trap in comparator"); }
static RInt qsort_worker(Crew *c, int id, void *arg) { (void)c; (void)id; (void)arg; int v[3] = { 3, 1, 2 }; c_qsort(v, 3, sizeof v[0], cmp_traps); return OK(RInt, 0); }
static void body_qsort(Crew *c, void *arg) { (void)arg; crew_go(c, qsort_worker, NULL); }

static int selftest(void) {
    char out[2048]; Error e;
    /* F2: trap in the parent body is not converted; it propagates to the outer child, after joining the inner child */
    {
        RUnit r = crew_run(1, body_one, (void *)child_parent_trap);
        int ok = IS_OK(r);
        CHECK(!ok && r.err.kind == K_TRAP && strstr(r.err.msg, "parent body trap"));
        CHECK(atomic_load(&inner_returned) == 0);   /* inner `try crew` never returned a Result */
        CHECK(atomic_load(&inner_joined) == 1);     /* children joined before the trap continued */
    }
    /* F2: plain crew re-traps a child's trap */
    {
        atomic_store(&inner_returned, 0);
        RUnit r = crew_run(1, body_one, (void *)child_plain_crew);
        int ok = IS_OK(r);
        CHECK(!ok && r.err.kind == K_TRAP && strstr(r.err.msg, "child trap"));
        CHECK(atomic_load(&inner_returned) == 0);
    }
    /* S5: trap in drop during unwinding is appended to the chain; later drops still run */
    {
        RUnit r = crew_run(1, body_one, (void *)child_drop_trap);
        int ok = IS_OK(r);
        char buf[512]; if (!ok) err_str(&r.err, buf, sizeof buf); else buf[0] = 0;
        CHECK(!ok && strstr(buf, "also trapped in drop: drop trap") && strstr(buf, "body trap"));
        CHECK(atomic_load(&drop_a_ran) == 1);
    }
    /* S7: poison; lock on poisoned traps; clear_poison repairs */
    {
        PMutex m; pm_init(&m); Cell t = { 1, 0 }; W3 w = { &m, &t };
        CHECK(expect_trap(w3_direct, &w, &e));
        CHECK(pm_is_poisoned(&m));
        CHECK(expect_trap(lock_poisoned, &m, &e) && strstr(e.msg, "poisoned"));
        pm_clear_poison(&m);
        pm_lock(&m); pm_unlock(&m);
        CHECK(!pm_is_poisoned(&m));
        /* F1: t was mutably borrowed by the trapping child: dead; using it traps (compile error in the real language) */
        CHECK(t.dead == 1 && t.v == 11);
        CHECK(expect_trap(use_dead, &t, &e) && strstr(e.msg, "dead"));
    }
    /* S1: Result must be consumed: re-exec a child that leaks one */
    CHECK(run_child("--leak-result", out, sizeof out) != 0 && strstr(out, "unconsumed"));
    /* S5: trap outside any crew aborts with the trace */
    CHECK(run_child("--trap-bare", out, sizeof out) != 0 && strstr(out, "TRAP"));
    /* S5: callback-from-C barrier: a trap inside a qsort comparator aborts even inside a crew child */
    CHECK(run_child("--trap-qsort", out, sizeof out) != 0 && strstr(out, "TRAP") && strstr(out, "barrier"));
    /* S6: dirty Lock drop is counted and the file is removed (replace_file failing at step 3 in a scratch dir) */
    {
        const char *dir = "errors-self.d"; rm_tree(dir);
        RUnit mk = make_dir(dir); (void)IS_OK(mk);
        int before = atomic_load(&g_dirty_close);
        RUnit r = replace_file(dir, "x", "new", 3); int ok = IS_OK(r);
        char files[128]; list_dir(dir, files, sizeof files);
        CHECK(!ok && atomic_load(&g_dirty_close) == before + 1 && files[0] == 0);
        r = replace_file(dir, "x", "new", -1); ok = IS_OK(r);
        list_dir(dir, files, sizeof files);
        CHECK(ok && !strcmp(files, "x") && atomic_load(&g_dirty_close) == before + 1);   /* clean path: committed */
        rm_tree(dir);
    }
    CHECK(tl_pending == 0 && atomic_load(&g_violations) == 0);
    printf(fails ? "selftest FAILED (%d)\n" : "selftest passed\n", fails);
    return fails != 0;
}

static int run_part(RUnit r) {   /* main: fn main() -> Unit fails; an Err prints "fatal" and exits 1 */
    if (IS_OK(r)) return 0;
    char buf[256]; err_str(&r.err, buf, sizeof buf); printf("fatal: %s\n", buf);
    return 1;
}

int main(int argc, char **argv) {
    g_argv0 = argv[0];
    atexit(at_exit_report);
    if (argc > 1) {
        if (!strcmp(argv[1], "--selftest")) return selftest();
        if (!strcmp(argv[1], "--leak-result")) { RInt r = parse_int("5"); (void)r; return 0; }   /* never consumed */
        if (!strcmp(argv[1], "--trap-bare")) { Config c; memset(&c, 0, sizeof c); (void)key_at(&c, 3); return 0; }
        if (!strcmp(argv[1], "--trap-qsort")) { RUnit r = crew_run(1, body_qsort, NULL); (void)IS_OK(r); return 0; }
        fprintf(stderr, "unknown option %s\n", argv[1]);
        return 2;
    }
    if (run_part(part1()) || run_part(part2()) || run_part(part3())) return 1;
    return 0;
}
