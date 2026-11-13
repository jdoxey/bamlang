/* k3 runtime. Traps use a per-thread cleanup stack plus setjmp/longjmp. */
#ifndef P3RT_H
#define P3RT_H
#include <stdint.h>
#include <setjmp.h>

typedef const char *p3_Str;

/* One node per live droppable local; lives in the local's own stack frame. */
typedef struct p3_cleanup {
    struct p3_cleanup *prev;
    void (*fn)(void *);
    void *obj;
} p3_cleanup;

extern _Thread_local p3_cleanup *p3_top;

static inline void p3_push(p3_cleanup *c, void (*fn)(void *), void *obj) {
    c->prev = p3_top; c->fn = fn; c->obj = obj; p3_top = c;
}
static inline void p3_pop_run(p3_cleanup *c) {
    p3_top = c->prev;
    c->fn(c->obj);
}

void p3_print(p3_Str s);
p3_Str p3_fmt(const char *fmt, ...);
_Noreturn void p3_trap(p3_Str msg);
void p3_expect_trap(void (*action)(void));
#endif
