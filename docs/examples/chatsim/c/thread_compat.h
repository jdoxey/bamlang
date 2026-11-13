/* Minimal portable threads: Win32 on Windows, pthreads elsewhere.
   C11 <threads.h> is missing on macOS and on most MinGW builds, so C needs this shim. */
#ifndef THREAD_COMPAT_H
#define THREAD_COMPAT_H
#include <stdlib.h>

typedef void (*thread_fn)(void *);
typedef struct { thread_fn fn; void *arg; } thread_start_args;

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
typedef HANDLE thread_t;
typedef SRWLOCK mutex_t;
typedef CONDITION_VARIABLE cond_t;
static DWORD WINAPI thread_tramp(LPVOID p) {
    thread_start_args s = *(thread_start_args *)p;
    free(p);
    s.fn(s.arg);
    return 0;
}
static int thread_start(thread_t *t, thread_fn fn, void *arg) {
    thread_start_args *s = malloc(sizeof *s);
    if (!s) return -1;
    s->fn = fn; s->arg = arg;
    *t = CreateThread(NULL, 0, thread_tramp, s, 0, NULL);
    if (!*t) { free(s); return -1; }
    return 0;
}
static void thread_join(thread_t *t) { WaitForSingleObject(*t, INFINITE); CloseHandle(*t); }
static void mutex_init(mutex_t *m) { InitializeSRWLock(m); }
static void mutex_destroy(mutex_t *m) { (void)m; }
static void mutex_lock(mutex_t *m) { AcquireSRWLockExclusive(m); }
static void mutex_unlock(mutex_t *m) { ReleaseSRWLockExclusive(m); }
static void cond_init(cond_t *c) { InitializeConditionVariable(c); }
static void cond_destroy(cond_t *c) { (void)c; }
static void cond_wait(cond_t *c, mutex_t *m) { SleepConditionVariableSRW(c, m, INFINITE, 0); }
static void cond_broadcast(cond_t *c) { WakeAllConditionVariable(c); }
static void sleep_ms(int ms) { Sleep((DWORD)ms); }
#else
#include <pthread.h>
#include <time.h>
typedef pthread_t thread_t;
typedef pthread_mutex_t mutex_t;
typedef pthread_cond_t cond_t;
static void *thread_tramp(void *p) {
    thread_start_args s = *(thread_start_args *)p;
    free(p);
    s.fn(s.arg);
    return NULL;
}
static int thread_start(thread_t *t, thread_fn fn, void *arg) {
    thread_start_args *s = malloc(sizeof *s);
    if (!s) return -1;
    s->fn = fn; s->arg = arg;
    if (pthread_create(t, NULL, thread_tramp, s) != 0) { free(s); return -1; }
    return 0;
}
static void thread_join(thread_t *t) { pthread_join(*t, NULL); }
static void mutex_init(mutex_t *m) { pthread_mutex_init(m, NULL); }
static void mutex_destroy(mutex_t *m) { pthread_mutex_destroy(m); }
static void mutex_lock(mutex_t *m) { pthread_mutex_lock(m); }
static void mutex_unlock(mutex_t *m) { pthread_mutex_unlock(m); }
static void cond_init(cond_t *c) { pthread_cond_init(c, NULL); }
static void cond_destroy(cond_t *c) { pthread_cond_destroy(c); }
static void cond_wait(cond_t *c, mutex_t *m) { pthread_cond_wait(c, m); }
static void cond_broadcast(cond_t *c) { pthread_cond_broadcast(c); }
static void sleep_ms(int ms) {
    struct timespec ts = { ms / 1000, (long)(ms % 1000) * 1000000L };
    nanosleep(&ts, NULL);
}
#endif
#endif
