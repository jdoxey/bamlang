/* K2 runtime: print, string helpers, trap support, coverage dump.
   Traps: Linux/macOS use _Unwind_ForcedUnwind with a stop function (no LSDA
   parsing in our code: generated cleanups are run by libgcc's
   __gcc_personality_v0). Windows raises an SEH exception and catches it with
   __try/__except; generated code uses __CxxFrameHandler3 funclets. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#include <stdint.h>

void p3_print(const char *s) { puts(s); }

char *p3_itoa(long long v) {
  char *b = malloc(24);
  snprintf(b, 24, "%lld", v);
  return b;
}

char *p3_concat(const char *a, const char *b) {
  size_t la = strlen(a), lb = strlen(b);
  char *r = malloc(la + lb + 1);
  memcpy(r, a, la);
  memcpy(r + la, b, lb + 1);
  return r;
}

static const char *trap_msg;

#ifdef _WIN32
__declspec(dllimport) void __stdcall RaiseException(unsigned long, unsigned long, unsigned long, const void *);
#define P3_CODE 0xE0503354UL
static int depth_catch;

void p3_trap(const char *m) {
  if (!depth_catch) { fprintf(stderr, "trap: %s\n", m); fflush(stdout); exit(101); }
  trap_msg = m;
  RaiseException(P3_CODE, 1, 0, 0);
  abort();
}

void p3_expect_trap(void (*action)(void)) {
  int caught = 0;
  depth_catch++;
  __try { action(); }
  __except (_exception_code() == P3_CODE) { caught = 1; }
  depth_catch--;
  if (caught) printf("trapped: %s\n", trap_msg);
}
#else
#include <unwind.h>

static jmp_buf *cur_jb;
static uintptr_t cur_marker;
static struct _Unwind_Exception exc;

/* Called by the unwinder before each frame. Frames are cleaned (their
   landing pads run) innermost first; once we reach expect_trap's own frame
   (its CFA is above its locals) we jump back into it. */
static _Unwind_Reason_Code stop(int version, _Unwind_Action actions, _Unwind_Exception_Class cls,
                                struct _Unwind_Exception *e, struct _Unwind_Context *ctx, void *arg) {
  (void)version; (void)cls; (void)e; (void)arg;
  if (actions & _UA_END_OF_STACK) abort();
  if ((uintptr_t)_Unwind_GetCFA(ctx) > cur_marker) longjmp(*cur_jb, 1);
  return _URC_NO_REASON;
}

void p3_trap(const char *m) {
  if (!cur_jb) { fprintf(stderr, "trap: %s\n", m); fflush(stdout); exit(101); }
  trap_msg = m;
  memset(&exc, 0, sizeof exc);
  exc.exception_class = 0x5033545241500000ULL;
  _Unwind_ForcedUnwind(&exc, stop, 0);
  abort();
}

void p3_expect_trap(void (*action)(void)) {
  jmp_buf jb;
  jmp_buf *prev_jb = cur_jb;
  uintptr_t prev_marker = cur_marker;
  volatile char marker = 0;
  if (setjmp(jb) == 0) {
    cur_jb = &jb;
    cur_marker = (uintptr_t)&marker;
    action();
    cur_jb = prev_jb; cur_marker = prev_marker;
  } else {
    cur_jb = prev_jb; cur_marker = prev_marker;
    printf("trapped: %s\n", trap_msg);
  }
}
#endif

/* Per-line coverage: lcov tracefile. */
struct fnrec { const char *name; int line; int idx; };

void p3_cov_dump(const int *lines, const long long *counts, long long n,
                 const struct fnrec *fns, long long nf, const char *out, const char *src) {
  FILE *f = fopen(out, "w");
  if (!f) return;
  long long hit = 0, fnh = 0;
  fprintf(f, "TN:\nSF:%s\n", src);
  for (long long i = 0; i < nf; i++) fprintf(f, "FN:%d,%s\n", fns[i].line, fns[i].name);
  for (long long i = 0; i < nf; i++) {
    fprintf(f, "FNDA:%lld,%s\n", counts[fns[i].idx], fns[i].name);
    if (counts[fns[i].idx]) fnh++;
  }
  fprintf(f, "FNF:%lld\nFNH:%lld\n", nf, fnh);
  for (long long i = 0; i < n; i++) { fprintf(f, "DA:%d,%lld\n", lines[i], counts[i]); if (counts[i]) hit++; }
  fprintf(f, "LF:%lld\nLH:%lld\nend_of_record\n", n, hit);
  fclose(f);
}
