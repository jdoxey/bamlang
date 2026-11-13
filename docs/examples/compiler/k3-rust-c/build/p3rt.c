#include "p3rt.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#ifdef _WIN32
#include <windows.h>
#include <process.h>
#else
#include <pthread.h>
#endif

/* macOS setjmp saves the signal mask (a syscall); _setjmp does not. glibc's setjmp does not either. */
#ifdef __APPLE__
#define P3_SETJMP(b) _setjmp(b)
#define P3_LONGJMP(b, v) _longjmp(b, v)
#else
#define P3_SETJMP(b) setjmp(b)
#define P3_LONGJMP(b, v) longjmp(b, v)
#endif

typedef struct p3_site { p3_Str file, fn; int line; } p3_site;

typedef struct p3_trapframe {
    struct p3_trapframe *prev;
    p3_cleanup *mark;      /* cleanup stack height when this frame was entered */
    char **chain;          /* drop frames only: message chain of the trap being unwound */
    int is_drop;
    char *msg;             /* catcher frames: the message that arrived */
    p3_site site;
    jmp_buf jb;
} p3_trapframe;

_Thread_local p3_cleanup *p3_top = NULL;
static _Thread_local p3_trapframe *frame = NULL;

void p3_print(p3_Str s) { puts(s); }

p3_Str p3_fmt(const char *fmt, ...) {
    va_list a, b;
    va_start(a, fmt);
    va_copy(b, a);
    int n = vsnprintf(NULL, 0, fmt, a);
    va_end(a);
    char *buf = malloc((size_t)n + 1); /* spike: strings are never freed */
    vsnprintf(buf, (size_t)n + 1, fmt, b);
    va_end(b);
    return buf;
}

static char *dup(const char *s) { size_t n = strlen(s) + 1; char *d = malloc(n); memcpy(d, s, n); return d; }

static char *append_then(char *chain, const char *msg) {
    size_t a = strlen(chain), b = strlen(msg);
    char *r = malloc(a + b + 9);
    memcpy(r, chain, a); memcpy(r + a, "; then: ", 8); memcpy(r + a + 8, msg, b + 1);
    return r;
}

/* Run one already-popped drop under a drop frame. A trap inside it appends to *chain, unwinds the
   drops registered since, and longjmps back here; the caller then carries on with the next drop.
   setjmp lives only in runtime functions: no generated-code local is live across a longjmp. */
static void run_drop(p3_cleanup *c, char **chain) {
    p3_trapframe df;
    df.prev = frame; df.mark = p3_top; df.chain = chain; df.is_drop = 1;
    frame = &df;
    if (P3_SETJMP(df.jb) == 0) c->fn(c->obj);
    frame = df.prev;
}

static void unwind_to(p3_cleanup *stop, char **chain) {
    while (p3_top != stop) {
        p3_cleanup *c = p3_top;
        p3_top = c->prev;   /* pop before running: a trap inside a drop cannot re-run it */
        run_drop(c, chain);
    }
}

_Noreturn void p3_trap(p3_Str msg, p3_Str file, int line, p3_Str fn) {
    p3_trapframe *f = frame;
    if (f && f->is_drop) {
        /* trap inside a drop while unwinding an earlier trap: chain it, abandon this drop only */
        *f->chain = append_then(*f->chain, msg);
        unwind_to(f->mark, f->chain);
        P3_LONGJMP(f->jb, 1);
    }
    char *m = dup(msg);
    unwind_to(f ? f->mark : NULL, &m);
    if (!f) {
        fflush(stdout);
        fprintf(stderr, "trap: %s\n  at %s (%s:%d)\n", m, fn, file, line);
        fflush(stderr);
        exit(101);
    }
    f->msg = m;
    f->site = (p3_site){file, fn, line};
    P3_LONGJMP(f->jb, 1);
}

void p3_expect_trap(void (*action)(void)) {
    p3_trapframe f;
    f.prev = frame; f.mark = p3_top; f.msg = NULL; f.is_drop = 0; f.chain = NULL;
    frame = &f;
    if (P3_SETJMP(f.jb) == 0) {
        action();
        frame = f.prev;
        return;
    }
    frame = f.prev;
    printf("trapped: %s\n", f.msg);
}

/* ---- crews: one OS thread per go(), joined at the brace ---- */

#ifdef _WIN32
typedef HANDLE p3_thread;
#define P3_THREAD_RET unsigned __stdcall
#define P3_THREAD_OK 0
#else
typedef pthread_t p3_thread;
#define P3_THREAD_RET void *
#define P3_THREAD_OK NULL
#endif

typedef struct p3_task {
    void (*fn)(void);
    p3_thread th;
    int started, trapped;
    char *msg;
    p3_site site;
} p3_task;

/* Child entry: the trap is caught here and stored; it never crosses the thread boundary. */
static P3_THREAD_RET task_entry(void *arg) {
    p3_task *t = arg;
    p3_trapframe f;
    f.prev = NULL; f.mark = p3_top; f.msg = NULL; f.is_drop = 0; f.chain = NULL;
    frame = &f;
    if (P3_SETJMP(f.jb) == 0) {
        t->fn();
    } else {
        t->trapped = 1; t->msg = f.msg; t->site = f.site;
    }
    frame = NULL;
    return P3_THREAD_OK;
}

static void crew_end(void *o) {
    p3_crew *c = o;
    for (size_t i = 0; i < c->n; i++) {
        p3_task *t = c->tasks[i];
        if (!t->started) continue;
#ifdef _WIN32
        WaitForSingleObject(t->th, INFINITE);
        CloseHandle(t->th);
#else
        pthread_join(t->th, NULL);
#endif
    }
    /* the first trap in go() order wins; the join above made the stored fields visible */
    p3_task *first = NULL;
    for (size_t i = 0; i < c->n && !first; i++) if (c->tasks[i]->trapped) first = c->tasks[i];
    char *msg = NULL; p3_site site = {c->file, c->fn, c->line};
    if (first) { msg = first->msg; site = first->site; }
    for (size_t i = 0; i < c->n; i++) free(c->tasks[i]);
    free(c->tasks);
    c->tasks = NULL; c->n = 0;
    if (msg) p3_trap(msg, site.file, site.line, site.fn);   /* re-raise in the parent */
}

void p3_crew_begin(p3_crew *c, p3_Str file, int line, p3_Str fn) {
    c->tasks = NULL; c->n = c->cap = 0; c->file = file; c->line = line; c->fn = fn;
    p3_push(&c->node, crew_end, c);
}

void p3_crew_go(p3_crew *c, void (*task)(void)) {
    if (c->n == c->cap) {
        c->cap = c->cap ? c->cap * 2 : 4;
        c->tasks = realloc(c->tasks, c->cap * sizeof *c->tasks);
    }
    p3_task *t = calloc(1, sizeof *t);
    t->fn = task;
    c->tasks[c->n++] = t;
    int ok;
#ifdef _WIN32
    uintptr_t h = _beginthreadex(NULL, 0, task_entry, t, 0, NULL);
    ok = h != 0; t->th = (HANDLE)h;
#else
    ok = pthread_create(&t->th, NULL, task_entry, t) == 0;
#endif
    t->started = ok;
    if (!ok) p3_trap("cannot start thread", c->file, c->line, c->fn);
}
