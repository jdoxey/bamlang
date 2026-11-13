// K1 runtime. Compiled as C++ (`clang -x c++`) because a trap is a real C++ exception:
// the same code works with __gxx_personality_v0 (Linux/macOS) and __CxxFrameHandler3 (Windows MSVC).
// It stays within the C subset plus `throw`; no C++ headers are used.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern "C" {

void p3_print(const char *s) { fputs(s, stdout); fputc('\n', stdout); }

// Strings are NUL-terminated and never freed (spike simplification; see NOTES.md).
const char *p3_concat(const char *a, const char *b) {
    size_t la = strlen(a), lb = strlen(b);
    char *r = (char *)malloc(la + lb + 1);
    memcpy(r, a, la); memcpy(r + la, b, lb + 1);
    return r;
}

const char *p3_int_to_str(long long v) {
    char *r = (char *)malloc(24);
    snprintf(r, 24, "%lld", v);
    return r;
}

static const char *g_msg = "";
const char *p3_trap_message(void) { return g_msg; }

// Raise the trap. The generated code's cleanups/landing pads run drops while this unwinds.
void p3_trap(const char *msg) { g_msg = msg; throw 1; }

// Coverage fallback: dump the per-line counter table written by `--coverage` builds.
void p3_cov_dump(long long *c, long long n) {
    const char *path = getenv("P3_COV_OUT");
    FILE *f = fopen(path ? path : "p3.cov", "w");
    if (!f) return;
    for (long long i = 0; i < n; i++) if (c[i]) fprintf(f, "%lld %lld\n", i, c[i]);
    fclose(f);
}

}
