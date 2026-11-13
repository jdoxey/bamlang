#include "p3rt.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>

typedef struct p3_trapframe {
    struct p3_trapframe *prev;
    p3_cleanup *mark;      /* cleanup stack height when expect_trap was entered */
    p3_Str msg;
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

/* Run drops innermost first down to the catching frame's mark, then jump to it. */
_Noreturn void p3_trap(p3_Str msg) {
    p3_cleanup *stop = frame ? frame->mark : NULL;
    while (p3_top != stop) {
        p3_cleanup *c = p3_top;
        p3_top = c->prev;   /* pop before running: a trap inside a drop cannot re-run it */
        c->fn(c->obj);
    }
    if (!frame) {
        fflush(stdout);
        fprintf(stderr, "trap: %s\n", msg);
        exit(101);
    }
    frame->msg = msg;
    longjmp(frame->jb, 1);
}

void p3_expect_trap(void (*action)(void)) {
    p3_trapframe f;
    f.prev = frame; f.mark = p3_top; f.msg = NULL;
    frame = &f;
    if (setjmp(f.jb) == 0) {
        action();
        frame = f.prev;
        return;
    }
    frame = f.prev;
    printf("trapped: %s\n", f.msg);
}
