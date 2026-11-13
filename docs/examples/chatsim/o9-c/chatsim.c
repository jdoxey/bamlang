/* chatsim under model O9: owned values plus generation-checked handles into pools.
   No struct stores a pointer to another pool object; only Handles. A pointer from a pool lookup
   is a borrow: look for "BORROW:" comments where it must not outlive a call that may mutate the pool. */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <stdint.h>
#include "../c/thread_compat.h"

#define RATE_LIMIT 3

/* ======== generic pool (slot map); in the real language this would be built in ======== */
typedef struct { uint32_t index, gen; } Handle;           /* gen 0 is never issued: {0,0} is "none" */
typedef struct {
    size_t elem; uint32_t cap, count;
    uint8_t *data; uint32_t *gen; uint8_t *live;
    void (*drop)(void *);                                 /* frees what the entry owns */
} Pool;

static void *xmalloc(size_t n) { void *p = malloc(n); if (!p) { perror("malloc"); exit(1); } return p; }
static void *xrealloc(void *p, size_t n) { p = realloc(p, n); if (!p) { perror("realloc"); exit(1); } return p; }
static char *xstrdup(const char *s) { size_t n = strlen(s) + 1; return memcpy(xmalloc(n), s, n); }

static void pool_init(Pool *p, size_t elem, void (*drop)(void *)) { memset(p, 0, sizeof *p); p->elem = elem; p->drop = drop; }
static void *pool_get(Pool *p, Handle h) {                /* NULL if stale or none */
    if (h.index >= p->cap || !p->live[h.index] || p->gen[h.index] != h.gen) return NULL;
    return p->data + (size_t)h.index * p->elem;
}
static Handle pool_add(Pool *p, const void *value) {      /* moves value in; may move every entry */
    uint32_t i = 0;
    while (i < p->cap && p->live[i]) i++;
    if (i == p->cap) {
        uint32_t nc = p->cap ? p->cap * 2 : 2;
        p->data = xrealloc(p->data, p->elem * nc); p->gen = xrealloc(p->gen, sizeof *p->gen * nc);
        p->live = xrealloc(p->live, nc);
        for (uint32_t k = p->cap; k < nc; k++) { p->gen[k] = 1; p->live[k] = 0; }
        p->cap = nc;
    }
    memcpy(p->data + (size_t)i * p->elem, value, p->elem);
    p->live[i] = 1; p->count++;
    return (Handle){ i, p->gen[i] };
}
static void pool_remove(Pool *p, Handle h) {              /* drops the entry and invalidates every handle to it */
    void *e = pool_get(p, h);
    if (!e) return;
    p->drop(e);
    p->live[h.index] = 0; p->gen[h.index]++; p->count--;
}
static void pool_free(Pool *p) {
    for (uint32_t i = 0; i < p->cap; i++) if (p->live[i]) p->drop(p->data + (size_t)i * p->elem);
    free(p->data); free(p->gen); free(p->live);
}
#define POOL_EACH(p, h) for (Handle h = { 0, 0 }; h.index < (p)->cap; h.index++) if (((p)->live[h.index]) && ((h.gen = (p)->gen[h.index]), 1))
/* ======== end generic pool ======== */

#define NONE ((Handle){ 0, 0 })
static char *fmt(const char *f, ...) {
    va_list a, b; va_start(a, f); va_copy(b, a);
    int n = vsnprintf(NULL, 0, f, a); va_end(a);
    char *s = xmalloc((size_t)n + 1); vsnprintf(s, (size_t)n + 1, f, b); va_end(b);
    return s;
}
#define PUSH(arr, n, cap, v) do { if ((n) == (cap)) { (cap) = (cap) ? (cap) * 2 : 4; \
    (arr) = xrealloc((arr), sizeof *(arr) * (size_t)(cap)); } (arr)[(n)++] = (v); } while (0)

static long users_alive, rooms_alive; /* main thread only */

typedef void (*OnMessage)(Handle self, Handle room, Handle from, const char *text);
typedef struct { OnMessage fn; Handle self; } Callback;   /* closure capturing a handle: a plain value */
typedef struct { Handle user; Callback cb; } Member;

typedef struct {
    char *name;
    Handle room, last_from;
    int had_contact, is_bot;
    int rate_tick, rate_count;    /* rate limiter state is owned by the user: dies with it */
} User;

typedef struct {
    char *name;
    Member *members; int nmembers, capmembers;
    char **history; int nhistory, caphistory;
} Room;

typedef struct { int due; Handle user; char *user_name; char *text; } Timer;

typedef struct Job { char *room_name; char **history; int n; struct Job *next; } Job;
typedef struct {
    mutex_t lock; cond_t changed;
    Job *head, *tail; int pending; int stop;
    long messages, archived_rooms, archived_messages;
    char **archive; int narchive, caparchive;
} Shared;

static Pool users, rooms;
static Timer *timers; static int ntimers, captimers;
static int clock_now;
static Shared sh;

static void drop_user(void *p) { User *u = p; free(u->name); users_alive--; }
static void drop_room(void *p) {
    Room *r = p;
    for (int i = 0; i < r->nhistory; i++) free(r->history[i]);
    free(r->history); free(r->members); free(r->name); rooms_alive--;
}
static User *user_get(Handle h) { return pool_get(&users, h); }
static Room *room_get(Handle h) { return pool_get(&rooms, h); }

/* ---------- worker thread ---------- */
static void worker(void *unused) {
    (void)unused;
    mutex_lock(&sh.lock);
    for (;;) {
        while (!sh.head && !sh.stop) cond_wait(&sh.changed, &sh.lock);
        if (!sh.head) break;
        Job *j = sh.head; sh.head = j->next; if (!sh.head) sh.tail = NULL;
        mutex_unlock(&sh.lock);
        sleep_ms(20);
        long bytes = 0;
        for (int i = 0; i < j->n; i++) bytes += (long)strlen(j->history[i]);
        char *entry = fmt("%s: %d messages, %ld bytes", j->room_name, j->n, bytes);
        int n = j->n;
        for (int i = 0; i < j->n; i++) free(j->history[i]);
        free(j->history); free(j->room_name); free(j);
        mutex_lock(&sh.lock);
        sh.archived_rooms++; sh.archived_messages += n;
        PUSH(sh.archive, sh.narchive, sh.caparchive, entry);
        sh.pending--;
        cond_broadcast(&sh.changed);
    }
    mutex_unlock(&sh.lock);
}
static void archive_room(char *room_name, char **history, int n) { /* takes ownership of both */
    Job *j = xmalloc(sizeof *j);
    j->room_name = room_name; j->history = history; j->n = n; j->next = NULL;
    mutex_lock(&sh.lock);
    if (sh.tail) sh.tail->next = j; else sh.head = j;
    sh.tail = j; sh.pending++;
    cond_broadcast(&sh.changed);
    mutex_unlock(&sh.lock);
}

/* ---------- lookup by name ---------- */
static Handle find_user(const char *name) {
    POOL_EACH(&users, h) if (strcmp(((User *)pool_get(&users, h))->name, name) == 0) return h;
    return NONE;
}
static Handle find_room(const char *name) {
    POOL_EACH(&rooms, h) if (strcmp(((Room *)pool_get(&rooms, h))->name, name) == 0) return h;
    return NONE;
}

/* ---------- rate limiter ---------- */
static int rate_ok(User *u) {
    if (u->rate_tick != clock_now) { u->rate_tick = clock_now; u->rate_count = 0; }
    if (u->rate_count >= RATE_LIMIT) { printf("rate limited: %s\n", u->name); return 0; }
    u->rate_count++;
    return 1;
}

/* ---------- rooms and messages ---------- */
static void post(Handle rh, Handle fh, const char *text) {
    {   /* BORROW: r and from end at the closing brace; the callbacks below may call post() again. */
        Room *r = room_get(rh); User *from = user_get(fh);
        if (!r || !from) { printf("post dropped: room or sender is gone\n"); return; }
        PUSH(r->history, r->nhistory, r->caphistory, fmt("%s: %s", from->name, text));
        mutex_lock(&sh.lock); sh.messages++; mutex_unlock(&sh.lock);
        printf("#%s %s: %s\n", r->name, from->name, text);
    }
    for (int i = 0; ; i++) {
        Room *r = room_get(rh);            /* re-look-up every iteration: a callback ran in between */
        if (!r) break;                      /* room vanished under us */
        if (i >= r->nmembers) break;
        Member m = r->members[i];           /* copy by value */
        if (m.user.index != fh.index || m.user.gen != fh.gen) m.cb.fn(m.cb.self, rh, fh, text);
    }
}

static void on_message_person(Handle selfh, Handle roomh, Handle fromh, const char *text) {
    (void)roomh;
    User *self = user_get(selfh); User *from = user_get(fromh);
    if (!self) return;                      /* stale captured handle: member is gone */
    printf("  %s sees %s: %s\n", self->name, from ? from->name : "?", text);
}
static void on_message_bot(Handle selfh, Handle roomh, Handle fromh, const char *text) {
    char *reply;
    {   /* BORROW: self/from end here, before post() below */
        User *self = user_get(selfh); User *from = user_get(fromh);
        if (!self || !from) return;
        printf("  %s sees %s: %s\n", self->name, from->name, text);
        if (from->is_bot) return;
        reply = fmt("echo: %s", text);
    }
    post(roomh, selfh, reply);
    free(reply);
}

static Handle open_room(const char *name) {
    Room r; memset(&r, 0, sizeof r);
    r.name = xstrdup(name);
    Handle h = pool_add(&rooms, &r);
    rooms_alive++;
    printf("#%s opened\n", name);
    return h;
}

static void enter_room(Handle uh, const char *room_name) {
    Handle rh = find_room(room_name);
    if (!rh.gen) rh = open_room(room_name);   /* BORROW: any earlier Room or User pointer is invalid after this */
    User *u = user_get(uh); Room *r = room_get(rh);
    if (!u || !r) { printf("enter failed\n"); return; }
    Member m = { uh, { u->is_bot ? on_message_bot : on_message_person, uh } };
    PUSH(r->members, r->nmembers, r->capmembers, m);
    u->room = rh;
    printf("%s joined #%s\n", u->name, r->name);
}

/* Removes the user from its room; closes and archives the room if empty. */
static void exit_room(Handle uh) {
    User *u = user_get(uh);
    if (!u) return;
    Handle rh = u->room;
    Room *r = room_get(rh);
    if (!r) { printf("exit: %s has no room\n", u->name); u->room = NONE; return; }
    for (int i = 0; i < r->nmembers; i++) if (r->members[i].user.index == uh.index && r->members[i].user.gen == uh.gen) {
        memmove(&r->members[i], &r->members[i + 1], sizeof *r->members * (size_t)(r->nmembers - i - 1));
        r->nmembers--; break;
    }
    u->room = NONE;
    printf("%s left #%s\n", u->name, r->name);
    if (r->nmembers == 0) {
        printf("#%s closed, %d messages sent to archive\n", r->name, r->nhistory);
        char *name = xstrdup(r->name); char **hist = r->history; int n = r->nhistory;
        r->history = NULL; r->nhistory = 0;                   /* ownership moves to the job */
        pool_remove(&rooms, rh);                              /* drops members array and name */
        archive_room(name, hist, n);
    }
}

/* ---------- commands ---------- */
static void cmd_join(const char *name, const char *room) {
    if (find_user(name).gen) { printf("join failed: %s is already here\n", name); return; }
    User u; memset(&u, 0, sizeof u);
    u.name = xstrdup(name); u.is_bot = strcmp(name, "echobot") == 0;
    Handle uh = pool_add(&users, &u);
    users_alive++;
    enter_room(uh, room);
}

static void cmd_say(const char *name, const char *text) {
    Handle uh = find_user(name);
    User *u = user_get(uh);
    if (!u) { printf("say failed: %s is not here\n", name); return; }
    if (!rate_ok(u)) return;
    Handle rh = u->room;   /* copy the handle out; u must not live across post() */
    post(rh, uh, text);
}

static void deliver_dm(Handle fh, Handle th, const char *text) {
    User *from = user_get(fh); User *to = user_get(th);
    if (!from || !to) { printf("dm dropped\n"); return; }
    printf("dm %s -> %s: %s\n", from->name, to->name, text);
    printf("  %s sees dm from %s: %s\n", to->name, from->name, text);
    to->last_from = fh; to->had_contact = 1;
    mutex_lock(&sh.lock); sh.messages++; mutex_unlock(&sh.lock);
}

static void cmd_dm(const char *from_name, const char *to_name, const char *text) {
    Handle fh = find_user(from_name);
    User *from = user_get(fh);
    if (!from) { printf("dm failed: %s is not here\n", from_name); return; }
    if (!rate_ok(from)) return;
    Handle th = find_user(to_name);
    if (!user_get(th)) { printf("dm failed: %s is not here\n", to_name); return; }
    deliver_dm(fh, th, text);
}

static void cmd_reply(const char *name, const char *text) {
    Handle uh = find_user(name);
    User *u = user_get(uh);
    if (!u) { printf("reply failed: %s is not here\n", name); return; }
    if (!rate_ok(u)) return;
    Handle lf = u->last_from;
    if (!user_get(lf)) {                    /* none, or stale: the contact left */
        if (u->had_contact) printf("reply failed: %s's last contact has left\n", name);
        else printf("reply failed: %s has no one to reply to\n", name);
        return;
    }
    deliver_dm(uh, lf, text);
}

static void cmd_remind(const char *name, int delay, const char *text) {
    Handle uh = find_user(name);
    if (!user_get(uh)) { printf("remind failed: %s is not here\n", name); return; }
    Timer t = { clock_now + delay, uh, xstrdup(name), xstrdup(text) };
    PUSH(timers, ntimers, captimers, t);
    int i = ntimers - 1;                    /* stable insert after all timers due at or before */
    while (i > 0 && timers[i - 1].due > t.due) { timers[i] = timers[i - 1]; i--; }
    timers[i] = t;
    printf("reminder for %s set for tick %d\n", name, t.due);
}

static void cmd_tick(int n) {
    for (int i = 0; i < n; i++) {
        clock_now++;
        while (ntimers > 0 && timers[0].due <= clock_now) {
            Timer t = timers[0];
            memmove(&timers[0], &timers[1], sizeof *timers * (size_t)(ntimers - 1)); ntimers--;
            User *u = user_get(t.user);
            if (u) printf("reminder for %s: %s\n", u->name, t.text);
            else printf("reminder for %s dropped: user has left\n", t.user_name);
            free(t.user_name); free(t.text);
        }
    }
    printf("clock is %d\n", clock_now);
}

static void cmd_move(const char *name, const char *room) {
    Handle uh = find_user(name);
    if (!user_get(uh)) { printf("move failed: %s is not here\n", name); return; }
    exit_room(uh);
    enter_room(uh, room);
}

static void cmd_leave(const char *name) {
    Handle uh = find_user(name);
    if (!user_get(uh)) { printf("leave failed: %s is not here\n", name); return; }
    exit_room(uh);
    pool_remove(&users, uh);   /* no cleanup walk: every handle to uh is now stale */
}

static void cmd_stats(void) {
    mutex_lock(&sh.lock);
    while (sh.pending > 0) cond_wait(&sh.changed, &sh.lock);
    printf("stats: users=%u rooms=%u messages=%ld archived_rooms=%ld archived_messages=%ld\n",
           users.count, rooms.count, sh.messages, sh.archived_rooms, sh.archived_messages);
    for (int i = 0; i < sh.narchive; i++) printf("  archive %s\n", sh.archive[i]);
    mutex_unlock(&sh.lock);
    printf("  alive: users=%ld rooms=%ld\n", users_alive, rooms_alive);
}

/* ---------- input ---------- */
static char *next_word(char **s) {
    while (**s == ' ') (*s)++;
    if (!**s) return NULL;
    char *w = *s;
    while (**s && **s != ' ') (*s)++;
    if (**s) *(*s)++ = '\0';
    return w;
}
static char *rest(char *s) { while (*s == ' ') s++; return s; }

int main(void) {
    pool_init(&users, sizeof(User), drop_user); pool_init(&rooms, sizeof(Room), drop_room);
    mutex_init(&sh.lock); cond_init(&sh.changed);
    thread_t th;
    if (thread_start(&th, worker, NULL) != 0) { fprintf(stderr, "cannot start worker\n"); return 1; }

    char line[1024];
    while (fgets(line, sizeof line, stdin)) {
        line[strcspn(line, "\r\n")] = '\0';
        if (line[0] == '\0' || line[0] == '#') continue;
        printf("> %s\n", line);
        char *s = line;
        char *cmd = next_word(&s);
        if (!cmd) continue;
        char *a = NULL, *b = NULL;
        if (!strcmp(cmd, "join") && (a = next_word(&s)) && (b = next_word(&s))) cmd_join(a, b);
        else if (!strcmp(cmd, "say") && (a = next_word(&s))) cmd_say(a, rest(s));
        else if (!strcmp(cmd, "dm") && (a = next_word(&s)) && (b = next_word(&s))) cmd_dm(a, b, rest(s));
        else if (!strcmp(cmd, "reply") && (a = next_word(&s))) cmd_reply(a, rest(s));
        else if (!strcmp(cmd, "remind") && (a = next_word(&s)) && (b = next_word(&s))) cmd_remind(a, atoi(b), rest(s));
        else if (!strcmp(cmd, "tick") && (a = next_word(&s))) cmd_tick(atoi(a));
        else if (!strcmp(cmd, "move") && (a = next_word(&s)) && (b = next_word(&s))) cmd_move(a, b);
        else if (!strcmp(cmd, "leave") && (a = next_word(&s))) cmd_leave(a);
        else if (!strcmp(cmd, "stats")) cmd_stats();
        else printf("bad command: %s\n", cmd);
    }

    mutex_lock(&sh.lock); sh.stop = 1; cond_broadcast(&sh.changed); mutex_unlock(&sh.lock);
    thread_join(&th);
    pool_free(&rooms); pool_free(&users);
    for (int i = 0; i < sh.narchive; i++) free(sh.archive[i]);
    free(sh.archive);
    for (int i = 0; i < ntimers; i++) { free(timers[i].user_name); free(timers[i].text); }
    free(timers);
    mutex_destroy(&sh.lock); cond_destroy(&sh.changed);
    printf("exit: alive users=%ld rooms=%ld\n", users_alive, rooms_alive);
    return 0;
}
