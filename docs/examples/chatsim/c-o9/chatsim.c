// O9 model: owned values + generation-checked handles into pools.
// No pointer to a User or Room is ever stored. Everything refers to others by Handle; get() returns NULL if stale.
// Build: cc -g -fsanitize=address,undefined -pthread chatsim.c -o chatsim
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { unsigned idx, gen; } H;               // gen 0 never valid
#define NOH ((H){0, 0})
#define POOL(T, N) struct { T v[N]; unsigned gen[N]; char used[N]; }
#define CAP 32
#define ALLOC(p, out) ({ H h_ = NOH; for (unsigned i_ = 0; i_ < CAP; i_++) if (!(p).used[i_]) { (p).used[i_] = 1; \
    (p).gen[i_]++; memset(&(p).v[i_], 0, sizeof((p).v[i_])); h_ = (H){ i_, (p).gen[i_] }; break; } *(out) = h_; h_.gen != 0; })
#define GET(p, h) ((h).gen && (p).used[(h).idx] && (p).gen[(h).idx] == (h).gen ? &(p).v[(h).idx] : NULL)
#define FREE(p, h) do { (p).used[(h).idx] = 0; } while (0)   // gen bumps on next alloc; stale handles now fail used-check

typedef struct Room Room;
typedef struct { void (*fn)(H self, H room, const char *from, const char *text); H self; } Callback; // case 17: handle, no cycle
typedef struct { char name[32]; H room; Callback cb; int is_bot; } User;
struct Room { char name[32]; H members[16]; int nmembers; char **history; int nhist; };
typedef struct { long fire; H user; char *text; } Reminder;
typedef struct Job { char *room; char **lines; int n; struct Job *next; } Job;

static struct {
    POOL(User, CAP) users; POOL(Room, CAP) rooms; Reminder timers[64]; int ntimers; long now; int tokens;
    pthread_mutex_t mu; pthread_cond_t cv; Job *queue, *tail; int released, stop, in_flight;
    long archived_rooms, archived_msgs; char *log[16]; int nlog;
} S = { .tokens = 3, .mu = PTHREAD_MUTEX_INITIALIZER, .cv = PTHREAD_COND_INITIALIZER };

static char *dup(const char *s) { char *r = malloc(strlen(s) + 1); strcpy(r, s); return r; }
static H find_user(const char *n) { for (unsigned i = 0; i < CAP; i++) if (S.users.used[i] && !strcmp(S.users.v[i].name, n)) return (H){ i, S.users.gen[i] }; return NOH; }
static H find_room(const char *n) { for (unsigned i = 0; i < CAP; i++) if (S.rooms.used[i] && !strcmp(S.rooms.v[i].name, n)) return (H){ i, S.rooms.gen[i] }; return NOH; }
static int same(H a, H b) { return a.idx == b.idx && a.gen == b.gen; }
static int take_token(void) { if (S.tokens <= 0) { puts("  rate limited"); return 0; } S.tokens--; return 1; }

static void post(H rh, const char *from, const char *text);
static void human_cb(H self, H rh, const char *from, const char *text) {
    User *u = GET(S.users, self); Room *r = GET(S.rooms, rh); if (!u || !r) return;
    printf("  [%s] %s <- %s: %s\n", r->name, u->name, from, text);
}
static void bot_cb(H self, H rh, const char *from, const char *text) {
    User *u = GET(S.users, self); if (!u) return;
    User *snd = GET(S.users, find_user(from)); if (snd && snd->is_bot) return;
    char buf[256]; snprintf(buf, sizeof buf, "echo: %s", text);
    char name[32]; strcpy(name, u->name);              // copy: post() may invalidate pointers (case 20)
    post(rh, name, buf);
}

static void post(H rh, const char *from, const char *text) {
    Room *r = GET(S.rooms, rh); if (!r) return;
    r->history = realloc(r->history, sizeof(char *) * (r->nhist + 1)); r->history[r->nhist++] = dup(text);
    H snap[16]; int n = r->nmembers; memcpy(snap, r->members, sizeof(H) * n);   // snapshot handles
    for (int i = 0; i < n; i++) {
        User *u = GET(S.users, snap[i]);               // re-validate each time: may have left or died
        if (!u || !same(u->room, rh) || !strcmp(u->name, from)) continue;
        u->cb.fn(u->cb.self, rh, from, text);
    }
}

static void leave_room(H uh) {
    User *u = GET(S.users, uh); if (!u) return;
    Room *r = GET(S.rooms, u->room); H rh = u->room; u->room = NOH; if (!r) return;
    for (int i = 0; i < r->nmembers; i++) if (same(r->members[i], uh)) { r->members[i] = r->members[--r->nmembers]; break; }
    if (r->nmembers == 0) {                            // case 12
        Job *j = calloc(1, sizeof *j); j->room = dup(r->name); j->lines = r->history; j->n = r->nhist;   // case 23: move
        printf("  room %s closed, %d messages queued for archive\n", r->name, j->n);
        FREE(S.rooms, rh);
        pthread_mutex_lock(&S.mu); if (S.tail) S.tail->next = j; else S.queue = j; S.tail = j;
        pthread_cond_broadcast(&S.cv); pthread_mutex_unlock(&S.mu);
    }
}

static void join(const char *name, const char *rname) {
    H uh = find_user(name);
    if (uh.gen) leave_room(uh);                        // case 4
    else {
        if (!ALLOC(S.users, &uh)) { puts("  full"); return; }
        User *u = GET(S.users, uh); snprintf(u->name, 32, "%s", name); u->is_bot = !strncmp(name, "echobot", 7);
        u->cb = (Callback){ u->is_bot ? bot_cb : human_cb, uh };
    }
    H rh = find_room(rname);
    if (!rh.gen) { ALLOC(S.rooms, &rh); snprintf(GET(S.rooms, rh)->name, 32, "%s", rname); }   // case 26: new slot, new gen
    Room *r = GET(S.rooms, rh); r->members[r->nmembers++] = uh; GET(S.users, uh)->room = rh;
    printf("  %s joined %s (%d members)\n", name, rname, r->nmembers);
}

static void tick(long n) {
    for (long t = 0; t < n; t++) {
        S.now++; if (S.tokens < 3) S.tokens++;
        for (int i = 0; i < S.ntimers;) {
            if (S.timers[i].fire <= S.now) {
                Reminder rm = S.timers[i]; S.timers[i] = S.timers[--S.ntimers];
                User *u = GET(S.users, rm.user);       // case 15: stale handle -> NULL
                if (u) printf("  reminder for %s: %s\n", u->name, rm.text); else printf("  reminder dropped (user gone)\n");
                free(rm.text);
            } else i++;
        }
    }
    printf("  now=%ld\n", S.now);
}

static void *worker(void *arg) {
    (void)arg; pthread_mutex_lock(&S.mu);
    for (;;) {
        while (!S.stop && !(S.released && S.queue)) pthread_cond_wait(&S.cv, &S.mu);
        if (!S.queue) { if (S.stop) break; continue; }
        Job *j = S.queue; S.queue = j->next; if (!S.queue) S.tail = NULL; S.in_flight = 1;
        pthread_mutex_unlock(&S.mu);
        size_t bytes = 0; for (int i = 0; i < j->n; i++) bytes += strlen(j->lines[i]);
        char line[160]; snprintf(line, sizeof line, "archived %s: %d msgs, %zu bytes", j->room, j->n, bytes);
        pthread_mutex_lock(&S.mu);
        S.archived_rooms++; S.archived_msgs += j->n; S.log[S.nlog++] = dup(line); S.in_flight = 0; pthread_cond_broadcast(&S.cv);
        for (int i = 0; i < j->n; i++) free(j->lines[i]);
        free(j->lines); free(j->room); free(j);
    }
    pthread_mutex_unlock(&S.mu); return NULL;
}
static void flush(void) {
    pthread_mutex_lock(&S.mu); S.released = 1; pthread_cond_broadcast(&S.cv);
    while (S.queue || S.in_flight) pthread_cond_wait(&S.cv, &S.mu);
    S.released = 0; for (int i = 0; i < S.nlog; i++) { printf("  %s\n", S.log[i]); free(S.log[i]); } S.nlog = 0;
    pthread_mutex_unlock(&S.mu);
}
static void stats(void) {
    int nu = 0, nr = 0, pending = 0; for (int i = 0; i < CAP; i++) { nu += S.users.used[i]; nr += S.rooms.used[i]; }
    pthread_mutex_lock(&S.mu); for (Job *j = S.queue; j; j = j->next) pending++;
    printf("  users=%d rooms=%d timers=%d archived_rooms=%ld archived_msgs=%ld pending=%d\n", nu, nr, S.ntimers, S.archived_rooms, S.archived_msgs, pending);
    pthread_mutex_unlock(&S.mu);
}
static int split(char *line, char **w, int max) {
    int n = 0;
    while (*line && n < max) {
        while (*line == ' ') line++; if (!*line) break;
        if (*line == '"') { w[n++] = ++line; while (*line && *line != '"') line++; } else { w[n++] = line; while (*line && *line != ' ') line++; }
        if (*line) *line++ = 0;
    }
    return n;
}
int main(void) {
    pthread_t th; pthread_create(&th, NULL, worker, NULL); char line[512];
    while (fgets(line, sizeof line, stdin)) {
        line[strcspn(line, "\r\n")] = 0; char *hash = strstr(line, "  #"); if (hash) *hash = 0;
        if (!line[0] || line[0] == '#') continue;
        printf("> %s\n", line); char *w[5]; int n = split(line, w, 5);
        if ((!strcmp(w[0], "join") || !strcmp(w[0], "move")) && n == 3) join(w[1], w[2]);
        else if (!strcmp(w[0], "leave") && n == 2) {
            H uh = find_user(w[1]); User *u = GET(S.users, uh);
            if (u) { leave_room(uh); printf("  %s left\n", u->name); FREE(S.users, uh); } else puts("  no such user");
        } else if (!strcmp(w[0], "say") && n == 3) {
            User *u = GET(S.users, find_user(w[1]));
            if (!u || !u->room.gen) puts("  not in a room"); else if (take_token()) post(u->room, u->name, w[2]);
        } else if (!strcmp(w[0], "dm") && n == 4) {
            User *from = GET(S.users, find_user(w[1])), *to = GET(S.users, find_user(w[2]));
            if (!from) puts("  no such user"); else if (!to) printf("  dm failed: %s is not here\n", w[2]);
            else if (take_token()) { char f[32]; strcpy(f, from->name); to->cb.fn(to->cb.self, to->room, f, w[3]); }
        } else if (!strcmp(w[0], "remind") && n == 4) {
            H uh = find_user(w[1]);
            if (uh.gen) { S.timers[S.ntimers++] = (Reminder){ S.now + atol(w[2]), uh, dup(w[3]) }; puts("  reminder set"); } else puts("  no such user");
        } else if (!strcmp(w[0], "tick") && n == 2) tick(atol(w[1]));
        else if (!strcmp(w[0], "flush")) flush(); else if (!strcmp(w[0], "stats")) stats(); else puts("  bad command");
    }
    for (unsigned i = 0; i < CAP; i++) if (S.users.used[i]) { H h = { i, S.users.gen[i] }; leave_room(h); printf("  %s left\n", S.users.v[i].name); FREE(S.users, h); }
    flush();
    for (int i = 0; i < S.ntimers; i++) free(S.timers[i].text);
    pthread_mutex_lock(&S.mu); S.stop = 1; pthread_cond_broadcast(&S.cv); pthread_mutex_unlock(&S.mu); pthread_join(th, NULL);
    return 0;
}
