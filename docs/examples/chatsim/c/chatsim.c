/* chatsim, reference version in plain C with manual memory.
   Behaviour is defined by ../SPEC.md and ../expected.txt. Every lifetime rule is the programmer's job:
   look for "MANUAL:" comments, which mark each place C makes you clean up by hand. */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include "thread_compat.h"

#define RATE_LIMIT 3

static long users_alive, rooms_alive; /* main thread only */

typedef struct Room Room;
typedef struct User User;
typedef void (*OnMessage)(void *ctx, Room *room, User *from, const char *text);

typedef struct { User *user; OnMessage cb; void *ctx; } Member;

struct User {
    char *name;
    Room *room;
    User *last_from;  /* non-owning; MANUAL: nulled when that user is freed */
    int had_contact;
    int is_bot;
};

struct Room {
    char *name;
    Member *members; int nmembers, capmembers;
    char **history; int nhistory, caphistory;
};

typedef struct Timer {
    int due; User *user; /* non-owning; MANUAL: nulled when the user is freed */
    char *user_name; char *text;
    struct Timer *next;
} Timer;

typedef struct { char *name; int tick; int count; } RateEntry;

typedef struct Job {
    char *room_name; char **history; int n;  /* owned by the job once queued */
    struct Job *next;
} Job;

typedef struct {
    mutex_t lock; cond_t changed;
    Job *head, *tail; int pending; int stop;
    long messages, archived_rooms, archived_messages;
    char **archive; int narchive, caparchive;
} Shared; /* everything the worker thread touches */

static User **users; static int nusers, capusers;
static Room **rooms; static int nrooms, caprooms;
static Timer *timers;
static RateEntry *rates; static int nrates, caprates;
static int clock_now;
static Shared sh;

static void *xmalloc(size_t n) { void *p = malloc(n); if (!p) { perror("malloc"); exit(1); } return p; }
static void *xrealloc(void *p, size_t n) { p = realloc(p, n); if (!p) { perror("realloc"); exit(1); } return p; }
static char *xstrdup(const char *s) { size_t n = strlen(s) + 1; return memcpy(xmalloc(n), s, n); }
static char *fmt(const char *f, ...) {
    va_list a, b; va_start(a, f); va_copy(b, a);
    int n = vsnprintf(NULL, 0, f, a); va_end(a);
    char *s = xmalloc((size_t)n + 1); vsnprintf(s, (size_t)n + 1, f, b); va_end(b);
    return s;
}
#define PUSH(arr, n, cap, v) do { if ((n) == (cap)) { (cap) = (cap) ? (cap) * 2 : 4; \
    (arr) = xrealloc((arr), sizeof *(arr) * (size_t)(cap)); } (arr)[(n)++] = (v); } while (0)

/* ---------- worker thread (case 23, 25, 26) ---------- */
static void worker(void *unused) {
    (void)unused;
    mutex_lock(&sh.lock);
    for (;;) {
        while (!sh.head && !sh.stop) cond_wait(&sh.changed, &sh.lock);
        if (!sh.head) break;
        Job *j = sh.head; sh.head = j->next; if (!sh.head) sh.tail = NULL;
        mutex_unlock(&sh.lock);
        sleep_ms(20); /* slow "disk write", so a room can reopen meanwhile */
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

static void archive_room(char *room_name, char **history, int n) { /* takes ownership */
    Job *j = xmalloc(sizeof *j);
    j->room_name = room_name; j->history = history; j->n = n; j->next = NULL;
    mutex_lock(&sh.lock);
    if (sh.tail) sh.tail->next = j; else sh.head = j;
    sh.tail = j; sh.pending++;
    cond_broadcast(&sh.changed);
    mutex_unlock(&sh.lock);
}

/* ---------- lookup ---------- */
static User *find_user(const char *name) {
    for (int i = 0; i < nusers; i++) if (strcmp(users[i]->name, name) == 0) return users[i];
    return NULL;
}
static Room *find_room(const char *name) {
    for (int i = 0; i < nrooms; i++) if (strcmp(rooms[i]->name, name) == 0) return rooms[i];
    return NULL;
}

/* ---------- rate limiter (case 13) ---------- */
static int rate_ok(const char *name) {
    RateEntry *e = NULL;
    for (int i = 0; i < nrates; i++) if (strcmp(rates[i].name, name) == 0) e = &rates[i];
    if (!e) { RateEntry n = { xstrdup(name), clock_now, 0 }; PUSH(rates, nrates, caprates, n); e = &rates[nrates - 1]; }
    if (e->tick != clock_now) { e->tick = clock_now; e->count = 0; }
    if (e->count >= RATE_LIMIT) { printf("rate limited: %s\n", name); return 0; }
    e->count++;
    return 1;
}
static void rate_forget(const char *name) {
    for (int i = 0; i < nrates; i++) if (strcmp(rates[i].name, name) == 0) {
        free(rates[i].name); rates[i] = rates[--nrates]; return;
    }
}

/* ---------- rooms and messages ---------- */
static void post(Room *room, User *from, const char *text) {
    PUSH(room->history, room->nhistory, room->caphistory, fmt("%s: %s", from->name, text));
    mutex_lock(&sh.lock); sh.messages++; mutex_unlock(&sh.lock);
    printf("#%s %s: %s\n", room->name, from->name, text);
    /* Re-entrancy (case 20): a callback may post again, which may grow history but not members.
       Index, not pointer, because a nested call could realloc the array. */
    for (int i = 0; i < room->nmembers; i++) {
        Member m = room->members[i];
        if (m.user != from) m.cb(m.ctx, room, from, text);
    }
}

static void on_message_person(void *ctx, Room *room, User *from, const char *text) {
    (void)room;
    User *self = ctx; /* the "closure" captures its user as a raw pointer */
    printf("  %s sees %s: %s\n", self->name, from->name, text);
}
static void on_message_bot(void *ctx, Room *room, User *from, const char *text) {
    User *self = ctx;
    printf("  %s sees %s: %s\n", self->name, from->name, text);
    if (!from->is_bot) {
        char *reply = fmt("echo: %s", text);
        post(room, self, reply);
        free(reply);
    }
}

static Room *open_room(const char *name) {
    Room *r = xmalloc(sizeof *r);
    memset(r, 0, sizeof *r);
    r->name = xstrdup(name);
    PUSH(rooms, nrooms, caprooms, r);
    rooms_alive++;
    printf("#%s opened\n", name);
    return r;
}

static void enter_room(User *u, const char *room_name) {
    Room *r = find_room(room_name);
    if (!r) r = open_room(room_name);
    Member m = { u, u->is_bot ? on_message_bot : on_message_person, u };
    PUSH(r->members, r->nmembers, r->capmembers, m);
    u->room = r;
    printf("%s joined #%s\n", u->name, r->name);
}

static void free_room(Room *r) {
    for (int i = 0; i < r->nhistory; i++) free(r->history[i]);
    free(r->history); free(r->members); free(r->name); free(r);
    rooms_alive--;
}

/* Removes u from its room; closes and archives the room if it is now empty (case 12). */
static void exit_room(User *u) {
    Room *r = u->room;
    for (int i = 0; i < r->nmembers; i++) if (r->members[i].user == u) {
        memmove(&r->members[i], &r->members[i + 1], sizeof *r->members * (size_t)(r->nmembers - i - 1));
        r->nmembers--; break;
    }
    u->room = NULL;
    printf("%s left #%s\n", u->name, r->name);
    if (r->nmembers == 0) {
        for (int i = 0; i < nrooms; i++) if (rooms[i] == r) { rooms[i] = rooms[--nrooms]; break; }
        printf("#%s closed, %d messages sent to archive\n", r->name, r->nhistory);
        archive_room(xstrdup(r->name), r->history, r->nhistory); /* ownership of history moves */
        r->history = NULL; r->nhistory = 0;
        free_room(r);
    }
}

static void free_user(User *u) {
    for (int i = 0; i < nusers; i++) if (users[i] == u) { users[i] = users[--nusers]; break; }
    /* MANUAL: every non-owning pointer to u must be found and cleared, or it dangles. */
    for (int i = 0; i < nusers; i++) if (users[i]->last_from == u) users[i]->last_from = NULL;
    for (Timer *t = timers; t; t = t->next) if (t->user == u) t->user = NULL;
    rate_forget(u->name);
    free(u->name); free(u);
    users_alive--;
}

/* ---------- commands ---------- */
static void cmd_join(const char *name, const char *room) {
    if (find_user(name)) { printf("join failed: %s is already here\n", name); return; }
    User *u = xmalloc(sizeof *u);
    memset(u, 0, sizeof *u);
    u->name = xstrdup(name);
    u->is_bot = strcmp(name, "echobot") == 0;
    PUSH(users, nusers, capusers, u);
    users_alive++;
    enter_room(u, room);
}

static void cmd_say(const char *name, const char *text) {
    User *u = find_user(name);
    if (!u) { printf("say failed: %s is not here\n", name); return; }
    if (!rate_ok(name)) return;
    post(u->room, u, text);
}

static void deliver_dm(User *from, User *to, const char *text) {
    printf("dm %s -> %s: %s\n", from->name, to->name, text);
    printf("  %s sees dm from %s: %s\n", to->name, from->name, text);
    to->last_from = from; to->had_contact = 1;
    mutex_lock(&sh.lock); sh.messages++; mutex_unlock(&sh.lock);
}

static void cmd_dm(const char *from_name, const char *to_name, const char *text) {
    User *from = find_user(from_name);
    if (!from) { printf("dm failed: %s is not here\n", from_name); return; }
    if (!rate_ok(from_name)) return;
    User *to = find_user(to_name);
    if (!to) { printf("dm failed: %s is not here\n", to_name); return; }
    deliver_dm(from, to, text);
}

static void cmd_reply(const char *name, const char *text) {
    User *u = find_user(name);
    if (!u) { printf("reply failed: %s is not here\n", name); return; }
    if (!rate_ok(name)) return;
    if (!u->last_from) {
        if (u->had_contact) printf("reply failed: %s's last contact has left\n", name);
        else printf("reply failed: %s has no one to reply to\n", name);
        return;
    }
    deliver_dm(u, u->last_from, text);
}

static void cmd_remind(const char *name, int delay, const char *text) {
    User *u = find_user(name);
    if (!u) { printf("remind failed: %s is not here\n", name); return; }
    Timer *t = xmalloc(sizeof *t);
    t->due = clock_now + delay; t->user = u; t->user_name = xstrdup(name); t->text = xstrdup(text); t->next = NULL;
    Timer **p = &timers; /* stable order: after every timer due at or before this one */
    while (*p && (*p)->due <= t->due) p = &(*p)->next;
    t->next = *p; *p = t;
    printf("reminder for %s set for tick %d\n", name, t->due);
}

static void cmd_tick(int n) {
    for (int i = 0; i < n; i++) {
        clock_now++;
        while (timers && timers->due <= clock_now) {
            Timer *t = timers; timers = t->next;
            if (t->user) printf("reminder for %s: %s\n", t->user->name, t->text);
            else printf("reminder for %s dropped: user has left\n", t->user_name);
            free(t->user_name); free(t->text); free(t);
        }
    }
    printf("clock is %d\n", clock_now);
}

static void cmd_move(const char *name, const char *room) {
    User *u = find_user(name);
    if (!u) { printf("move failed: %s is not here\n", name); return; }
    exit_room(u);
    enter_room(u, room);
}

static void cmd_leave(const char *name) {
    User *u = find_user(name);
    if (!u) { printf("leave failed: %s is not here\n", name); return; }
    exit_room(u);
    free_user(u);
}

static void cmd_stats(void) {
    mutex_lock(&sh.lock);
    while (sh.pending > 0) cond_wait(&sh.changed, &sh.lock);
    printf("stats: users=%d rooms=%d messages=%ld archived_rooms=%ld archived_messages=%ld\n",
           nusers, nrooms, sh.messages, sh.archived_rooms, sh.archived_messages);
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

    /* Shutdown: stop the worker, then free what is left without archiving it. */
    mutex_lock(&sh.lock); sh.stop = 1; cond_broadcast(&sh.changed); mutex_unlock(&sh.lock);
    thread_join(&th);
    while (nrooms > 0) free_room(rooms[--nrooms]);
    while (nusers > 0) free_user(users[0]);
    for (int i = 0; i < sh.narchive; i++) free(sh.archive[i]);
    free(sh.archive); free(users); free(rooms); free(rates);
    while (timers) { Timer *t = timers; timers = t->next; free(t->user_name); free(t->text); free(t); }
    mutex_destroy(&sh.lock); cond_destroy(&sh.changed);
    printf("exit: alive users=%ld rooms=%ld\n", users_alive, rooms_alive);
    return 0;
}
