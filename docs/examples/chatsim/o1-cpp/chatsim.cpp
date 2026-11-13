// chatsim under model O1: pure ARC (std::shared_ptr everywhere, std::weak_ptr for back-references).
// Build with -DNAIVE to get the first, leaking version (strong captures, strong user->room).
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

using std::shared_ptr;
using std::string;
using std::weak_ptr;

static const int RATE_LIMIT = 3;
static long users_alive = 0, rooms_alive = 0;  // main thread only

static void out(const string& s) { std::fputs(s.c_str(), stdout); std::fputc('\n', stdout); }

struct Room;

struct User {
    string name;
#ifdef NAIVE
    shared_ptr<Room> room;  // strong: User -> Room -> callback -> User is a cycle
#else
    weak_ptr<Room> room;    // the server owns rooms; a user only observes its room
#endif
    weak_ptr<User> last_from;  // non-owning: a departed contact must not be kept alive
    bool had_contact = false;
    bool is_bot = false;
    explicit User(string n) : name(std::move(n)) { ++users_alive; }
    ~User() { --users_alive; }
    User(const User&) = delete;
    User& operator=(const User&) = delete;
};

// Everything the worker thread touches.
struct Shared {
    std::mutex lock;
    std::condition_variable changed;
    struct Job { string room_name; std::vector<string> history; };
    std::deque<shared_ptr<Job>> queue;
    int pending = 0;
    bool stop = false;
    long messages = 0, archived_rooms = 0, archived_messages = 0;
    std::vector<string> archive;
};

struct RateLimiter {
    struct Entry { int tick = 0; int count = 0; };
    std::map<string, Entry> entries;
    bool ok(const string& name, int now) {
        auto it = entries.find(name);
        if (it == entries.end()) it = entries.emplace(name, Entry{now, 0}).first;
        Entry& e = it->second;
        if (e.tick != now) { e.tick = now; e.count = 0; }
        if (e.count >= RATE_LIMIT) { out("rate limited: " + name); return false; }
        e.count++;
        return true;
    }
    void forget(const string& name) { entries.erase(name); }
};

using OnMessage = std::function<void(Room&, const shared_ptr<User>& from, const string& text)>;
struct Member { weak_ptr<User> user; OnMessage cb; };

struct Room {
    string name;
    std::vector<Member> members;
    std::vector<string> history;
    shared_ptr<Shared> sh;
    Room(string n, shared_ptr<Shared> s) : name(std::move(n)), sh(std::move(s)) { ++rooms_alive; }
    ~Room() { --rooms_alive; }
    Room(const Room&) = delete;
    Room& operator=(const Room&) = delete;
};

struct Timer {
    int due;
    weak_ptr<User> user;  // the reminder must not keep its user alive
    string user_name, text;
};

static void count_message(Shared& sh) { std::lock_guard<std::mutex> g(sh.lock); sh.messages++; }

// Re-entrancy (case 20): a callback may call post() again. Index loop, and the callback is
// copied out of the vector first, so a nested push_back/realloc cannot invalidate what runs.
static void post(Room& room, const shared_ptr<User>& from, const string& text) {
    room.history.push_back(from->name + ": " + text);
    count_message(*room.sh);
    out("#" + room.name + " " + from->name + ": " + text);
    for (size_t i = 0; i < room.members.size(); i++) {
        OnMessage cb = room.members[i].cb;  // atomic refcount traffic on the closure state
        if (room.members[i].user.lock() != from) cb(room, from, text);
    }
}

static OnMessage make_callback(const shared_ptr<User>& u) {
#ifdef NAIVE
    shared_ptr<User> self = u;  // strong capture: the room's closure now owns the user
    return [self](Room& room, const shared_ptr<User>& from, const string& text) {
#else
    weak_ptr<User> weak = u;
    return [weak](Room& room, const shared_ptr<User>& from, const string& text) {
        shared_ptr<User> self = weak.lock();
        if (!self) return;
#endif
        out("  " + self->name + " sees " + from->name + ": " + text);
        if (self->is_bot && !from->is_bot) post(room, self, "echo: " + text);
    };
}

struct Server {
    std::map<string, shared_ptr<User>> users;
    std::map<string, shared_ptr<Room>> rooms;
    std::multimap<int, shared_ptr<Timer>> timers;  // equal keys keep insertion order
    shared_ptr<RateLimiter> rate = std::make_shared<RateLimiter>();
    shared_ptr<Shared> sh = std::make_shared<Shared>();
    int clock_now = 0;
    std::thread th;

    Server() { th = std::thread(&Server::worker, sh); }
    ~Server() {
        { std::lock_guard<std::mutex> g(sh->lock); sh->stop = true; }
        sh->changed.notify_all();
        th.join();
    }

    static void worker(shared_ptr<Shared> sh) {
        std::unique_lock<std::mutex> lk(sh->lock);
        for (;;) {
            sh->changed.wait(lk, [&] { return !sh->queue.empty() || sh->stop; });
            if (sh->queue.empty()) break;
            shared_ptr<Shared::Job> j = sh->queue.front();
            sh->queue.pop_front();
            lk.unlock();
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
            long bytes = 0;
            for (const string& m : j->history) bytes += (long)m.size();
            string entry = j->room_name + ": " + std::to_string(j->history.size()) + " messages, " +
                           std::to_string(bytes) + " bytes";
            long n = (long)j->history.size();
            j.reset();  // history freed here, on the worker thread
            lk.lock();
            sh->archived_rooms++; sh->archived_messages += n;
            sh->archive.push_back(entry);
            sh->pending--;
            sh->changed.notify_all();
        }
    }

    shared_ptr<User> find_user(const string& n) {
        auto it = users.find(n);
        return it == users.end() ? nullptr : it->second;
    }

    shared_ptr<Room> open_room(const string& name) {
        auto r = std::make_shared<Room>(name, sh);
        rooms[name] = r;
        out("#" + name + " opened");
        return r;
    }

    void enter_room(const shared_ptr<User>& u, const string& room_name) {
        auto it = rooms.find(room_name);
        shared_ptr<Room> r = it != rooms.end() ? it->second : open_room(room_name);
        r->members.push_back(Member{u, make_callback(u)});
        u->room = r;
        out(u->name + " joined #" + r->name);
    }

    void exit_room(const shared_ptr<User>& u) {
#ifdef NAIVE
        shared_ptr<Room> r = std::move(u->room);
#else
        shared_ptr<Room> r = u->room.lock();
#endif
        for (size_t i = 0; i < r->members.size(); i++)
            if (r->members[i].user.lock() == u) { r->members.erase(r->members.begin() + (long)i); break; }
        out(u->name + " left #" + r->name);
        if (r->members.empty()) {
            rooms.erase(r->name);
            size_t n = r->history.size();
            out("#" + r->name + " closed, " + std::to_string(n) + " messages sent to archive");
            auto job = std::make_shared<Shared::Job>();
            job->room_name = r->name;
            job->history = std::move(r->history);  // ownership of the history moves to the job
            {
                std::lock_guard<std::mutex> g(sh->lock);
                sh->queue.push_back(job);
                sh->pending++;
            }
            sh->changed.notify_all();
        }
    }  // last shared_ptr<Room> dies here -> ~Room

    void deliver_dm(const shared_ptr<User>& from, const shared_ptr<User>& to, const string& text) {
        out("dm " + from->name + " -> " + to->name + ": " + text);
        out("  " + to->name + " sees dm from " + from->name + ": " + text);
        to->last_from = from; to->had_contact = true;
        count_message(*sh);
    }

    void join(const string& name, const string& room) {
        if (find_user(name)) { out("join failed: " + name + " is already here"); return; }
        auto u = std::make_shared<User>(name);
        u->is_bot = name == "echobot";
        users[name] = u;
        enter_room(u, room);
    }
    void say(const string& name, const string& text) {
        auto u = find_user(name);
        if (!u) { out("say failed: " + name + " is not here"); return; }
        if (!rate->ok(name, clock_now)) return;
#ifdef NAIVE
        shared_ptr<Room> r = u->room;
#else
        shared_ptr<Room> r = u->room.lock();
#endif
        post(*r, u, text);
    }
    void dm(const string& from_name, const string& to_name, const string& text) {
        auto from = find_user(from_name);
        if (!from) { out("dm failed: " + from_name + " is not here"); return; }
        if (!rate->ok(from_name, clock_now)) return;
        auto to = find_user(to_name);
        if (!to) { out("dm failed: " + to_name + " is not here"); return; }
        deliver_dm(from, to, text);
    }
    void reply(const string& name, const string& text) {
        auto u = find_user(name);
        if (!u) { out("reply failed: " + name + " is not here"); return; }
        if (!rate->ok(name, clock_now)) return;
        auto to = u->last_from.lock();  // liveness comes from a failed lock
        if (!to) {
            out(u->had_contact ? "reply failed: " + name + "'s last contact has left"
                               : "reply failed: " + name + " has no one to reply to");
            return;
        }
        deliver_dm(u, to, text);
    }
    void remind(const string& name, int delay, const string& text) {
        auto u = find_user(name);
        if (!u) { out("remind failed: " + name + " is not here"); return; }
        auto t = std::make_shared<Timer>(Timer{clock_now + delay, u, name, text});
        timers.emplace(t->due, t);
        out("reminder for " + name + " set for tick " + std::to_string(t->due));
    }
    void tick(int n) {
        for (int i = 0; i < n; i++) {
            clock_now++;
            while (!timers.empty() && timers.begin()->first <= clock_now) {
                shared_ptr<Timer> t = timers.begin()->second;
                timers.erase(timers.begin());
                if (auto u = t->user.lock()) out("reminder for " + u->name + ": " + t->text);
                else out("reminder for " + t->user_name + " dropped: user has left");
            }
        }
        out("clock is " + std::to_string(clock_now));
    }
    void move(const string& name, const string& room) {
        auto u = find_user(name);
        if (!u) { out("move failed: " + name + " is not here"); return; }
        exit_room(u);
        enter_room(u, room);
    }
    void leave(const string& name) {
        auto u = find_user(name);
        if (!u) { out("leave failed: " + name + " is not here"); return; }
        exit_room(u);
        users.erase(name);
        rate->forget(name);
    }  // u dies here -> ~User (unless something else still holds it)
    void stats() {
        std::unique_lock<std::mutex> lk(sh->lock);
        sh->changed.wait(lk, [&] { return sh->pending == 0; });
        out("stats: users=" + std::to_string(users.size()) + " rooms=" + std::to_string(rooms.size()) +
            " messages=" + std::to_string(sh->messages) + " archived_rooms=" + std::to_string(sh->archived_rooms) +
            " archived_messages=" + std::to_string(sh->archived_messages));
        for (const string& e : sh->archive) out("  archive " + e);
        lk.unlock();
        out("  alive: users=" + std::to_string(users_alive) + " rooms=" + std::to_string(rooms_alive));
    }
};

static bool next_word(const string& s, size_t& p, string& w) {
    while (p < s.size() && s[p] == ' ') p++;
    if (p >= s.size()) return false;
    size_t b = p;
    while (p < s.size() && s[p] != ' ') p++;
    w = s.substr(b, p - b);
    return true;
}
static string rest(const string& s, size_t p) {
    while (p < s.size() && s[p] == ' ') p++;
    return s.substr(p);
}

int main() {
    {
        Server srv;
        char buf[1024];
        while (std::fgets(buf, sizeof buf, stdin)) {
            string line(buf);
            while (!line.empty() && (line.back() == '\n' || line.back() == '\r')) line.pop_back();
            if (line.empty() || line[0] == '#') continue;
            out("> " + line);
            size_t p = 0;
            string cmd, a, b;
            if (!next_word(line, p, cmd)) continue;
            if (cmd == "join" && next_word(line, p, a) && next_word(line, p, b)) srv.join(a, b);
            else if (cmd == "say" && next_word(line, p, a)) srv.say(a, rest(line, p));
            else if (cmd == "dm" && next_word(line, p, a) && next_word(line, p, b)) srv.dm(a, b, rest(line, p));
            else if (cmd == "reply" && next_word(line, p, a)) srv.reply(a, rest(line, p));
            else if (cmd == "remind" && next_word(line, p, a) && next_word(line, p, b)) srv.remind(a, std::atoi(b.c_str()), rest(line, p));
            else if (cmd == "tick" && next_word(line, p, a)) srv.tick(std::atoi(a.c_str()));
            else if (cmd == "move" && next_word(line, p, a) && next_word(line, p, b)) srv.move(a, b);
            else if (cmd == "leave" && next_word(line, p, a)) srv.leave(a);
            else if (cmd == "stats") srv.stats();
            else out("bad command: " + cmd);
        }
    }  // Server destroyed: worker joined, then maps, timers, rooms, users released
    out("exit: alive users=" + std::to_string(users_alive) + " rooms=" + std::to_string(rooms_alive));
    return 0;
}
