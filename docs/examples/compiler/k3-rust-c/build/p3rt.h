/* k3 runtime. Traps use a per-thread cleanup stack plus setjmp/longjmp. All trap state is _Thread_local. */
#ifndef P3RT_H
#define P3RT_H
#include <stdint.h>
#include <stddef.h>
#include <setjmp.h>

typedef const char *p3_Str;

/* One node per live droppable local (or live crew); lives in the owner's own stack frame. */
typedef struct p3_cleanup {
    struct p3_cleanup *prev;
    void (*fn)(void *);
    void *obj;
} p3_cleanup;

extern _Thread_local p3_cleanup *p3_top;

#define P3_INLINE static inline __attribute__((always_inline))
P3_INLINE void p3_push(p3_cleanup *c, void (*fn)(void *), void *obj) {
    c->prev = p3_top; c->fn = fn; c->obj = obj; p3_top = c;
}
P3_INLINE void p3_pop_run(p3_cleanup *c) {
    p3_top = c->prev;
    c->fn(c->obj);
}

/* A crew lives in the opening function's frame. Its cleanup node joins the children, so a trap in the
   crew body also joins them (innermost-first order) before it continues. */
typedef struct p3_crew {
    p3_cleanup node;
    struct p3_task **tasks;
    size_t n, cap;
    p3_Str file, fn;
    int line;
} p3_crew;

void p3_print(p3_Str s);
p3_Str p3_fmt(const char *fmt, ...);
_Noreturn void p3_trap(p3_Str msg, p3_Str file, int line, p3_Str fn);
void p3_expect_trap(void (*action)(void));
void p3_crew_begin(p3_crew *c, p3_Str file, int line, p3_Str fn);
void p3_crew_go(p3_crew *c, void (*task)(void));
#endif
