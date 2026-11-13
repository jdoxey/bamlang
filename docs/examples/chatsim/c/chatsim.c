// chatsim in C. Reference implementation for docs/examples/chatsim/SPEC.md.
// Build: cc -g -fsanitize=address,undefined -pthread chatsim.c -o chatsim
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct User User;
typedef struct Room Room;
typedef void (*MsgFn)(void *ctx, Room *room, const char *from, const char *text);

typedef struct { MsgFn fn; void *ctx; } Callback;      // case 17: ctx is the user
typedef struct { long fire; int user_id; char *text; } Reminder;

struct User { int id; char *name; Room *room; Callback on_message; int is_bot; };
struct Room { char *name; User **members; int nmembers; char **history; int nhist; };

typedef struct Job { char *room; char **lines; int n; struct Job *next; } Job;

static struct {
    User **users; int nusers; int next_id;
    Room **rooms; int nrooms;
    Reminder *timers; int ntimers; long now;
    int tokens;                                       // case 13: shared rate limiter
    pthread_mutex_t mu; pthread_cond_t cv;            // case 25: guards everything below
    Job *queue, *tail; int released, stop, in_flight;
    long archived_rooms, archived_msgs; char **log; int nlog;
} S = { .next_id = 1, .tokens = 3, .mu = PTHREAD_MUTEX_INITIALIZER, .cv = PTHREAD_COND_INITIALIZER };

static char *dup(const char *s) { char *r = malloc(strlen(s) + 1); strcpy(r, s); return r; }
#define PUSH(arr, n, v) do { (arr) = realloc((arr), sizeof(*(arr)) * ((n) + 1)); (arr)[(n)++] = (v); } while (0)

static User *find_user(const char *name) {
    for (int i = 0; i < S.nusers; i++) if (!strcmp(S.users[i]->name, name)) return S.users[i];
    return NULL;
}
static User *user_by_id(int id) {
    for (int i = 0; i < S.nusers; i++) if (S.users[i]->id == id) return S.users[i];
    return NULL;
}
static Room *find_room(const char *name) {
    for (int i = 0; i < S.nrooms; i++) if (!strcmp(S.rooms[i]->name, name)) return S.rooms[i];
    return NULL;
}

static int take_token(void) { if (S.tokens <= 0) { puts("  rate limited"); return 0; } S.tokens--; return 1; }

static void post(Room *r, const char *from, const char *text);

static void human_cb(void *ctx, Room *r, const char *from, const char *text) {
    User *u = ctx; printf("  [%s] %s <- %s: %s\n", r->name, u->name, from, text);
}
static void bot_cb(void *ctx, Room *r, const char *from, const char *text) {
    User *u = ctx;
    User *sender = find_user(from);
    if (sender && sender->is_bot) return;
    char buf[256]; snprintf(buf, sizeof buf, "echo: %s", text);
    post(r, u->name, buf);                            // case 20: re-enters the room mid-broadcast
}

static void post(Room *r, const char *from, const char *text) {
    PUSH(r->history, r->nhist, dup(text));
    // Case 20: members can change while we iterate (a callback could leave/join). Snapshot the ids.
    int n = r->nmembers; User **snap = malloc(sizeof(User *) * (n ? n : 1)); int *ids = malloc(sizeof(int) * (n ? n : 1));
    for (int i = 0; i < n; i++) { snap[i] = r->members[i]; ids[i] = r->members[i]->id; }
    for (int i = 0; i < n; i++) {
        User *u = user_by_id(ids[i]);                 // re-validate: may have left meanwhile
        if (!u || u->room != r || !strcmp(u->name, from)) continue;
        u->on_message.fn(u->on_message.ctx, r, from, text);
    }
    free(snap); free(ids);
}

static void remove_member(Room *r, User *u) {
    for (int i = 0; i < r->nmembers; i++) if (r->members[i] == u) { r->members[i] = r->members[--r->nmembers]; break; }
    u->room = NULL;
}

static void free_room(Room *r) {                      // case 12: last member left
    for (int i = 0; i < S.nrooms; i++) if (S.rooms[i] == r) { S.rooms[i] = S.rooms[--S.nrooms]; break; }
    Job *j = calloc(1, sizeof *j);                    // case 23: history ownership moves to the worker
    j->room = dup(r->name); j->lines = r->history; j->n = r->nhist;
    pthread_mutex_lock(&S.mu);
    if (S.tail) S.tail->next = j; else S.queue = j;
    S.tail = j; pthread_cond_broadcast(&S.cv);
    pthread_mutex_unlock(&S.mu);
    printf("  room %s closed, %d messages queued for archive\n", r->name, j->n);
    free(r->name); free(r->members); free(r);
}

static void leave_room(User *u) {
    Room *r = u->room; if (!r) return;
    remove_member(r, u);
    if (r->nmembers == 0) free_room(r);
}

static void join(const char *uname, const char *rname) {
    User *u = find_user(uname);
    if (!u) {
        u = calloc(1, sizeof *u); u->id = S.next_id++; u->name = dup(uname);
        u->is_bot = !strncmp(uname, "echobot", 7);
        u->on_message = (Callback){ u->is_bot ? bot_cb : human_cb, u };
        PUSH(S.users, S.nusers, u);
    } else leave_room(u);                             // case 4: move = leave + join
    Room *r = find_room(rname);
    if (!r) {                                         // case 26: may reuse a name still being archived
        r = calloc(1, sizeof *r); r->name = dup(rname); PUSH(S.rooms, S.nrooms, r);
    }
    PUSH(r->members, r->nmembers, u); u->room = r;
    printf("  %s joined %s (%d members)\n", uname, rname, r->nmembers);
}

static void drop_user(User *u) {
    leave_room(u);
    // case 15: timers are keyed by user id, so they outlive the user and are checked when they fire
    for (int i = 0; i < S.nusers; i++) if (S.users[i] == u) { S.users[i] = S.users[--S.nusers]; break; }
    printf("  %s left\n", u->name); free(u->name); free(u);
}

static void tick(long n) {
    for (long t = 0; t < n; t++) {
        S.now++; if (S.tokens < 3) S.tokens++;
        for (int i = 0; i < S.ntimers;) {
            if (S.timers[i].fire <= S.now) {
                Reminder rm = S.timers[i]; S.timers[i] = S.timers[--S.ntimers];
                User *u = user_by_id(rm.user_id);      // look up by id, never hold User*
                if (u) printf("  reminder for %s: %s\n", u->name, rm.text);
                else printf("  reminder dropped (user gone)\n");
                free(rm.text);
            } else i++;
        }
    }
    printf("  now=%ld\n", S.now);
}

static void *worker(void *arg) {
    (void)arg;
    pthread_mutex_lock(&S.mu);
    for (;;) {
        while (!S.stop && !(S.released && S.queue)) pthread_cond_wait(&S.cv, &S.mu);
        if (!S.queue) { if (S.stop) break; continue; }
        Job *j = S.queue; S.queue = j->next; if (!S.queue) S.tail = NULL;
        S.in_flight = 1;
        pthread_mutex_unlock(&S.mu);
        size_t bytes = 0; for (int i = 0; i < j->n; i++) bytes += strlen(j->lines[i]);   // "write" it
        char line[160]; snprintf(line, sizeof line, "archived %s: %d msgs, %zu bytes", j->room, j->n, bytes);
        pthread_mutex_lock(&S.mu);
        S.archived_rooms++; S.archived_msgs += j->n; PUSH(S.log, S.nlog, dup(line));
        S.in_flight = 0; pthread_cond_broadcast(&S.cv);
        for (int i = 0; i < j->n; i++) free(j->lines[i]);
        free(j->lines); free(j->room); free(j);
    }
    pthread_mutex_unlock(&S.mu);
    return NULL;
}

static void flush(void) {
    pthread_mutex_lock(&S.mu);
    S.released = 1; pthread_cond_broadcast(&S.cv);
    while (S.queue || S.in_flight) pthread_cond_wait(&S.cv, &S.mu);
    S.released = 0;
    for (int i = 0; i < S.nlog; i++) { printf("  %s\n", S.log[i]); free(S.log[i]); }
    S.nlog = 0; free(S.log); S.log = NULL;
    pthread_mutex_unlock(&S.mu);
}

static void stats(void) {
    pthread_mutex_lock(&S.mu);
    int pending = 0; for (Job *j = S.queue; j; j = j->next) pending++;
    printf("  users=%d rooms=%d timers=%d archived_rooms=%ld archived_msgs=%ld pending=%d\n",
           S.nusers, S.nrooms, S.ntimers, S.archived_rooms, S.archived_msgs, pending);
    pthread_mutex_unlock(&S.mu);
}

// Parse: words separated by spaces; a "quoted" word may contain spaces.
static int split(char *line, char **w, int max) {
    int n = 0;
    while (*line && n < max) {
        while (*line == ' ') line++;
        if (!*line) break;
        if (*line == '"') { w[n++] = ++line; while (*line && *line != '"') line++; }
        else { w[n++] = line; while (*line && *line != ' ') line++; }
        if (*line) *line++ = 0;
    }
    return n;
}

int main(void) {
    pthread_t th; pthread_create(&th, NULL, worker, NULL);
    char line[512];
    while (fgets(line, sizeof line, stdin)) {
        line[strcspn(line, "\r\n")] = 0;
        char *hash = strstr(line, "  #"); if (hash) *hash = 0;
        if (!line[0] || line[0] == '#') continue;
        printf("> %s\n", line);
        char *w[5]; int n = split(line, w, 5);
        if (!strcmp(w[0], "join") && n == 3) join(w[1], w[2]);
        else if (!strcmp(w[0], "move") && n == 3) join(w[1], w[2]);
        else if (!strcmp(w[0], "leave") && n == 2) { User *u = find_user(w[1]); if (u) drop_user(u); else puts("  no such user"); }
        else if (!strcmp(w[0], "say") && n == 3) {
            User *u = find_user(w[1]);
            if (!u || !u->room) puts("  not in a room"); else if (take_token()) post(u->room, u->name, w[2]);
        } else if (!strcmp(w[0], "dm") && n == 4) {   // case 14: target may be gone
            User *from = find_user(w[1]), *to = find_user(w[2]);
            if (!from) puts("  no such user");
            else if (!to) printf("  dm failed: %s is not here\n", w[2]);
            else if (take_token()) to->on_message.fn(to->on_message.ctx, to->room, from->name, w[3]);
        } else if (!strcmp(w[0], "remind") && n == 4) {
            User *u = find_user(w[1]);
            if (u) { Reminder r = { S.now + atol(w[2]), u->id, dup(w[3]) }; PUSH(S.timers, S.ntimers, r); puts("  reminder set"); }
            else puts("  no such user");
        } else if (!strcmp(w[0], "tick") && n == 2) tick(atol(w[1]));
        else if (!strcmp(w[0], "flush")) flush();
        else if (!strcmp(w[0], "stats")) stats();
        else puts("  bad command");
    }
    // shutdown: free everything still alive
    while (S.nusers) drop_user(S.users[0]);
    flush();
    pthread_mutex_lock(&S.mu); S.stop = 1; pthread_cond_broadcast(&S.cv); pthread_mutex_unlock(&S.mu);
    pthread_join(th, NULL);
    free(S.users); free(S.rooms); free(S.timers);
    return 0;
}
