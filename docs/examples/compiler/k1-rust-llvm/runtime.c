/* K1 runtime (C11, no C++ runtime). Print and string helpers, the trap ABI, crews (OS threads).

   Trap ABI (codegen only sees these calls): p3_trap raises, p3_expect_trap and p3_cleanup_drop and the thread entry
   are the catch sites, p3_crew_* start and join threads. All trap state is thread-local.

   Linux/macOS: a trap is a *forced unwind* (_Unwind_ForcedUnwind). Generated functions keep their drops in
   `landingpad ... cleanup` blocks with personality __gcc_personality_v0 (libgcc / compiler-rt, C, cleanups only), so
   the non-trap path costs nothing: only .eh_frame / LSDA tables. The unwinder runs every cleanup up to the catcher's own
   frame, where the stop function longjmps back into the catch site. No libstdc++ / libc++, no C++ exception object.
   Windows: p3_trap is RaiseException with a private code; a catch site is __try/__except; generated cleanups are
   cleanuppad funclets with personality __C_specific_handler (plain SEH, like __try/__finally). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#ifdef _WIN32
#include <windows.h>
#include <process.h>
#define TLS __declspec(thread)
#define P3_CODE 0xE0503354UL
#else
#include <pthread.h>
#include <setjmp.h>
#include <unwind.h>
#define TLS _Thread_local
#endif

void p3_print(const char *s) { puts(s); }

const char *p3_concat(const char *a, const char *b) {
    size_t la = strlen(a), lb = strlen(b);
    char *r = (char *)malloc(la + lb + 1);
    memcpy(r, a, la);
    memcpy(r + la, b, lb + 1);
    return r;
}

const char *p3_int_to_str(long long v) {
    char *r = (char *)malloc(24);
    snprintf(r, 24, "%lld", v);
    return r;
}

/* ---- catch sites -------------------------------------------------------------------------------------------- */
typedef struct Catcher {
    struct Catcher *prev;
    const char *msg, *loc, *fn;   /* the trap that reached this catcher: message (or chain), source file:line, function */
    uintptr_t marker;
#ifndef _WIN32
    jmp_buf jb;
#endif
} Catcher;

static TLS Catcher *top;          /* innermost catch site of this thread; NULL = an uncaught trap */

static void die_uncaught(const char *msg, const char *loc, const char *fn) {
    fflush(stdout);
    fprintf(stderr, "trap: %s\n  at %s (%s)\n", msg, fn, loc);
    fflush(stderr);
    exit(101);
}

#ifdef _WIN32
__declspec(noinline) static int run_caught(void (*f)(void *), void *arg, Catcher *c) {
    volatile int trapped = 0;
    c->prev = top;
    top = c;
    __try { f(arg); }
    __except (GetExceptionCode() == P3_CODE ? EXCEPTION_EXECUTE_HANDLER : EXCEPTION_CONTINUE_SEARCH) { trapped = 1; }
    top = c->prev;
    return trapped;
}

void p3_trap(const char *msg, const char *loc, const char *fn) {
    if (!top) die_uncaught(msg, loc, fn);
    top->msg = msg; top->loc = loc; top->fn = fn;
    RaiseException(P3_CODE, EXCEPTION_NONCONTINUABLE, 0, NULL);
    abort();
}
#else
static TLS struct _Unwind_Exception exc;

/* Called by the unwinder before each frame. Frames below the catch site's frame are cleaned (their landing pads
   run, then _Unwind_Resume calls us again); at the catch site's own frame (its CFA is above its locals) we jump in. */
static _Unwind_Reason_Code stop(int version, _Unwind_Action actions, _Unwind_Exception_Class cls,
                                struct _Unwind_Exception *e, struct _Unwind_Context *ctx, void *arg) {
    (void)version; (void)cls; (void)e; (void)arg;
    if (actions & _UA_END_OF_STACK) abort();   /* unwound through a frame with no catch site (C frames cannot be cleaned) */
    if ((uintptr_t)_Unwind_GetCFA(ctx) > top->marker) longjmp(top->jb, 1);
    return _URC_NO_REASON;
}

__attribute__((noinline)) static int run_caught(void (*f)(void *), void *arg, Catcher *c) {
    volatile char marker = 0;
    c->marker = (uintptr_t)&marker;
    c->prev = top;
    top = c;
    if (setjmp(c->jb) == 0) { f(arg); top = c->prev; return 0; }
    top = c->prev;
    return 1;
}

void p3_trap(const char *msg, const char *loc, const char *fn) {
    if (!top) die_uncaught(msg, loc, fn);
    top->msg = msg; top->loc = loc; top->fn = fn;
    memset(&exc, 0, sizeof exc);
    exc.exception_class = 0x5033545241500000ULL;
    _Unwind_ForcedUnwind(&exc, stop, 0);
    abort();
}
#endif

static void call_action(void *a) { ((void (*)(void))a)(); }

/* expect_trap(action:): run the action; a trap inside prints `trapped: <message chain>` and returns. */
void p3_expect_trap(void (*action)(void)) {
    Catcher c;
    c.msg = "";
    if (run_caught(call_action, (void *)action, &c)) printf("trapped: %s\n", c.msg);
}

/* Every drop called from a cleanup pad goes through here (ADR-0004 rule 8): a trap inside the drop is caught, its
   message is appended to the chain of the trap being unwound (`first; then: second`), and we return normally so the
   unwind goes on and the remaining drops run. */
typedef struct { void (*d)(void *); void *o; } DropCall;
static void call_drop(void *a) { DropCall *x = (DropCall *)a; x->d(x->o); }

void p3_cleanup_drop(void (*d)(void *), void *obj) {
    Catcher c;
    DropCall dc = { d, obj };
    c.msg = "";
    if (run_caught(call_drop, &dc, &c)) {
        Catcher *outer = c.prev;   /* the catch site whose trap is being unwound */
        const char *chain = p3_concat(outer->msg, "; then: ");
        outer->msg = p3_concat(chain, c.msg);
    }
}

/* ---- crews: one OS thread per `go`, joined at the closing brace ------------------------------------------------ */
typedef struct Task {
    void (*fn)(void);
    int trapped;
    const char *msg, *loc, *fnname;
#ifdef _WIN32
    HANDLE h;
#else
    pthread_t t;
#endif
} Task;

typedef struct Crew { Task **tasks; int n, cap; } Crew;

static void run_task(void *a) { ((Task *)a)->fn(); }

/* The child's entry is its own catch site: a trap ends the task, the chain is stored for the parent. */
static void task_main(Task *t) {
    Catcher c;
    c.msg = "";
    if (run_caught(run_task, t, &c)) { t->trapped = 1; t->msg = c.msg; t->loc = c.loc; t->fnname = c.fn; }
}

#ifdef _WIN32
static unsigned __stdcall task_entry(void *a) { task_main((Task *)a); return 0; }
#else
static void *task_entry(void *a) { task_main((Task *)a); return NULL; }
#endif

void *p3_crew_new(void) { return calloc(1, sizeof(Crew)); }

void p3_crew_go(void *crew, void (*fn)(void)) {
    Crew *c = (Crew *)crew;
    if (c->n == c->cap) { c->cap = c->cap ? c->cap * 2 : 4; c->tasks = (Task **)realloc(c->tasks, c->cap * sizeof(Task *)); }
    Task *t = (Task *)calloc(1, sizeof(Task));
    t->fn = fn;
    c->tasks[c->n++] = t;
#ifdef _WIN32
    t->h = (HANDLE)_beginthreadex(NULL, 0, task_entry, t, 0, NULL);
    if (!t->h) { fprintf(stderr, "crew: cannot start thread\n"); exit(101); }
#else
    if (pthread_create(&t->t, NULL, task_entry, t) != 0) { fprintf(stderr, "crew: cannot start thread\n"); exit(101); }
#endif
}

static Task *join_all(Crew *c) {   /* joins every task; returns the first (in `go` order) that trapped */
    Task *first = NULL;
    for (int i = 0; i < c->n; i++) {
        Task *t = c->tasks[i];
#ifdef _WIN32
        WaitForSingleObject(t->h, INFINITE);
        CloseHandle(t->h);
#else
        pthread_join(t->t, NULL);
#endif
        if (t->trapped && !first) first = t;
    }
    return first;
}

/* Normal end of `crew { }`: join all, then re-raise the first child trap here, message unchanged. */
void p3_crew_join(void *crew) {
    Crew *c = (Crew *)crew;
    Task *first = join_all(c);
    if (first) { const char *m = first->msg, *l = first->loc, *f = first->fnname; p3_trap(m, l, f); }
}

/* The crew body itself trapped (cleanup pad): join the children and drop their traps. */
void p3_crew_quiet(void *crew) { join_all((Crew *)crew); }
