// chatsim under model O4 (simplified ownership): one owner, assignment moves, no references stored in structs.
// "SHARED:" marks each place the model forced Rc/Weak/clone/ids; see NOTES.md.
use std::cell::{Cell, RefCell};
use std::collections::VecDeque;
use std::io::{self, BufRead};
use std::rc::{Rc, Weak};
use std::sync::atomic::{AtomicI64, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::thread;
use std::time::Duration;

const RATE_LIMIT: i32 = 3;
static USERS_ALIVE: AtomicI64 = AtomicI64::new(0);
static ROOMS_ALIVE: AtomicI64 = AtomicI64::new(0);

// SHARED: the room's callback captures the user, and the server also owns the user, so User is Rc.
// Its mutable fields need Cell/RefCell because Rc only gives &User. room is a NAME (id), not a pointer.
struct User {
    name: String,
    room: RefCell<Option<String>>,
    last_from: RefCell<Weak<User>>, // SHARED: non-owning back-reference; Weak goes dead by itself
    had_contact: Cell<bool>,
    is_bot: bool,
}
impl User {
    fn new(name: &str) -> Rc<User> {
        USERS_ALIVE.fetch_add(1, Ordering::SeqCst);
        Rc::new(User {
            name: name.to_string(),
            room: RefCell::new(None),
            last_from: RefCell::new(Weak::new()),
            had_contact: Cell::new(false),
            is_bot: name == "echobot",
        })
    }
}
impl Drop for User {
    fn drop(&mut self) {
        USERS_ALIVE.fetch_sub(1, Ordering::SeqCst);
    }
}

// SHARED: Rc, not Box, because post() must copy the callback list out so a callback can re-enter post().
type OnMessage = Rc<dyn Fn(&mut Server, &str, &Rc<User>, &str)>;
struct Member {
    user: Rc<User>,
    cb: OnMessage,
}
struct Room {
    name: String,
    members: Vec<Member>,
    history: Vec<String>,
}
impl Room {
    fn new(name: &str) -> Room {
        ROOMS_ALIVE.fetch_add(1, Ordering::SeqCst);
        Room { name: name.to_string(), members: Vec::new(), history: Vec::new() }
    }
}
impl Drop for Room {
    fn drop(&mut self) {
        ROOMS_ALIVE.fetch_sub(1, Ordering::SeqCst);
    }
}

struct Timer {
    due: i32,
    user: Weak<User>, // SHARED: dead automatically when the user is freed
    user_name: String,
    text: String,
}
struct RateEntry {
    name: String,
    tick: i32,
    count: i32,
}
struct Job {
    room_name: String,
    history: Vec<String>, // moved in; the worker owns it
}
#[derive(Default)]
struct Shared {
    queue: VecDeque<Job>,
    pending: i32,
    stop: bool,
    messages: i64,
    archived_rooms: i64,
    archived_messages: i64,
    archive: Vec<String>,
}
type SharedRef = Arc<(Mutex<Shared>, Condvar)>;

fn worker(sh: SharedRef) {
    let (lock, cv) = &*sh;
    let mut g = lock.lock().unwrap();
    loop {
        while g.queue.is_empty() && !g.stop {
            g = cv.wait(g).unwrap();
        }
        let Some(job) = g.queue.pop_front() else { break };
        drop(g);
        thread::sleep(Duration::from_millis(20)); // slow "disk write"
        let bytes: usize = job.history.iter().map(|h| h.len()).sum();
        let n = job.history.len();
        let entry = format!("{}: {} messages, {} bytes", job.room_name, n, bytes);
        drop(job);
        g = lock.lock().unwrap();
        g.archived_rooms += 1;
        g.archived_messages += n as i64;
        g.archive.push(entry);
        g.pending -= 1;
        cv.notify_all();
    }
}

struct Server {
    users: Vec<Rc<User>>,
    rooms: Vec<Room>,
    timers: Vec<Timer>,
    rates: Vec<RateEntry>,
    clock: i32,
    sh: SharedRef,
}

impl Server {
    fn bump_messages(&self) {
        self.sh.0.lock().unwrap().messages += 1;
    }
    // SHARED: returns a cloned Rc; a borrow into self.users would block every &mut self call after it.
    fn find_user(&self, name: &str) -> Option<Rc<User>> {
        self.users.iter().find(|u| u.name == name).cloned()
    }
    fn room_idx(&self, name: &str) -> Option<usize> {
        self.rooms.iter().position(|r| r.name == name)
    }

    fn rate_ok(&mut self, name: &str) -> bool {
        let clock = self.clock;
        let i = match self.rates.iter().position(|e| e.name == name) {
            Some(i) => i,
            None => {
                self.rates.push(RateEntry { name: name.to_string(), tick: clock, count: 0 });
                self.rates.len() - 1
            }
        };
        let e = &mut self.rates[i];
        if e.tick != clock {
            e.tick = clock;
            e.count = 0;
        }
        if e.count >= RATE_LIMIT {
            println!("rate limited: {}", name);
            return false;
        }
        e.count += 1;
        true
    }
    fn rate_forget(&mut self, name: &str) {
        if let Some(i) = self.rates.iter().position(|e| e.name == name) {
            self.rates.swap_remove(i);
        }
    }

    fn post(&mut self, room: &str, from: &Rc<User>, text: &str) {
        let idx = self.room_idx(room).unwrap();
        self.rooms[idx].history.push(format!("{}: {}", from.name, text));
        self.bump_messages();
        println!("#{} {}: {}", room, from.name, text);
        // Re-entrancy (case 20): a callback may call post() again. Walking self.rooms[idx].members
        // while passing &mut self to the callback is a borrow error, so copy the list first.
        let snapshot: Vec<(Rc<User>, OnMessage)> =
            self.rooms[idx].members.iter().map(|m| (m.user.clone(), m.cb.clone())).collect();
        for (u, cb) in snapshot {
            if !Rc::ptr_eq(&u, from) {
                cb(self, room, from, text);
            }
        }
    }

    fn open_room(&mut self, name: &str) -> usize {
        self.rooms.push(Room::new(name));
        println!("#{} opened", name);
        self.rooms.len() - 1
    }

    fn enter_room(&mut self, u: &Rc<User>, room_name: &str) {
        let idx = match self.room_idx(room_name) {
            Some(i) => i,
            None => self.open_room(room_name),
        };
        let me = u.clone(); // SHARED: the closure's capture of the user (case 17)
        let cb: OnMessage = if u.is_bot {
            Rc::new(move |srv: &mut Server, room: &str, from: &Rc<User>, text: &str| {
                println!("  {} sees {}: {}", me.name, from.name, text);
                if !from.is_bot {
                    srv.post(room, &me, &format!("echo: {}", text));
                }
            })
        } else {
            Rc::new(move |_srv: &mut Server, _room: &str, from: &Rc<User>, text: &str| {
                println!("  {} sees {}: {}", me.name, from.name, text);
            })
        };
        self.rooms[idx].members.push(Member { user: u.clone(), cb });
        *u.room.borrow_mut() = Some(room_name.to_string());
        println!("{} joined #{}", u.name, room_name);
    }

    fn exit_room(&mut self, u: &Rc<User>) {
        let room_name = u.room.borrow_mut().take().unwrap();
        let idx = self.room_idx(&room_name).unwrap();
        let r = &mut self.rooms[idx];
        if let Some(i) = r.members.iter().position(|m| Rc::ptr_eq(&m.user, u)) {
            r.members.remove(i); // drops the closure, and with it the captured Rc
        }
        println!("{} left #{}", u.name, room_name);
        if self.rooms[idx].members.is_empty() {
            let mut room = self.rooms.swap_remove(idx);
            println!("#{} closed, {} messages sent to archive", room.name, room.history.len());
            // Room implements Drop, so fields cannot be moved out; take them instead.
            let history = std::mem::take(&mut room.history);
            let name = std::mem::take(&mut room.name);
            self.archive_room(name, history);
        }
    }

    fn archive_room(&mut self, room_name: String, history: Vec<String>) {
        let (lock, cv) = &*self.sh;
        let mut g = lock.lock().unwrap();
        g.queue.push_back(Job { room_name, history });
        g.pending += 1;
        cv.notify_all();
    }

    fn free_user(&mut self, u: &Rc<User>) {
        if let Some(i) = self.users.iter().position(|x| Rc::ptr_eq(x, u)) {
            self.users.swap_remove(i);
        }
        // Nothing to hunt for: last_from and timers hold Weak, which go dead on their own.
        self.rate_forget(&u.name);
    }

    fn cmd_join(&mut self, name: &str, room: &str) {
        if self.find_user(name).is_some() {
            println!("join failed: {} is already here", name);
            return;
        }
        let u = User::new(name);
        self.users.push(u.clone());
        self.enter_room(&u, room);
    }

    fn cmd_say(&mut self, name: &str, text: &str) {
        let Some(u) = self.find_user(name) else {
            println!("say failed: {} is not here", name);
            return;
        };
        if !self.rate_ok(name) {
            return;
        }
        let room = u.room.borrow().clone().unwrap(); // SHARED: clone of the room id
        self.post(&room, &u, text);
    }

    fn deliver_dm(&self, from: &Rc<User>, to: &Rc<User>, text: &str) {
        println!("dm {} -> {}: {}", from.name, to.name, text);
        println!("  {} sees dm from {}: {}", to.name, from.name, text);
        *to.last_from.borrow_mut() = Rc::downgrade(from);
        to.had_contact.set(true);
        self.bump_messages();
    }

    fn cmd_dm(&mut self, from_name: &str, to_name: &str, text: &str) {
        let Some(from) = self.find_user(from_name) else {
            println!("dm failed: {} is not here", from_name);
            return;
        };
        if !self.rate_ok(from_name) {
            return;
        }
        let Some(to) = self.find_user(to_name) else {
            println!("dm failed: {} is not here", to_name);
            return;
        };
        self.deliver_dm(&from, &to, text);
    }

    fn cmd_reply(&mut self, name: &str, text: &str) {
        let Some(u) = self.find_user(name) else {
            println!("reply failed: {} is not here", name);
            return;
        };
        if !self.rate_ok(name) {
            return;
        }
        let last = u.last_from.borrow().upgrade();
        match last {
            None => {
                if u.had_contact.get() {
                    println!("reply failed: {}'s last contact has left", name);
                } else {
                    println!("reply failed: {} has no one to reply to", name);
                }
            }
            Some(to) => self.deliver_dm(&u, &to, text),
        }
    }

    fn cmd_remind(&mut self, name: &str, delay: i32, text: &str) {
        let Some(u) = self.find_user(name) else {
            println!("remind failed: {} is not here", name);
            return;
        };
        let due = self.clock + delay;
        let t = Timer { due, user: Rc::downgrade(&u), user_name: name.to_string(), text: text.to_string() };
        let pos = self.timers.partition_point(|x| x.due <= due);
        self.timers.insert(pos, t);
        println!("reminder for {} set for tick {}", name, due);
    }

    fn cmd_tick(&mut self, n: i32) {
        for _ in 0..n {
            self.clock += 1;
            while !self.timers.is_empty() && self.timers[0].due <= self.clock {
                let t = self.timers.remove(0);
                match t.user.upgrade() {
                    Some(u) => println!("reminder for {}: {}", u.name, t.text),
                    None => println!("reminder for {} dropped: user has left", t.user_name),
                }
            }
        }
        println!("clock is {}", self.clock);
    }

    fn cmd_move(&mut self, name: &str, room: &str) {
        let Some(u) = self.find_user(name) else {
            println!("move failed: {} is not here", name);
            return;
        };
        self.exit_room(&u);
        self.enter_room(&u, room);
    }

    fn cmd_leave(&mut self, name: &str) {
        let Some(u) = self.find_user(name) else {
            println!("leave failed: {} is not here", name);
            return;
        };
        self.exit_room(&u);
        self.free_user(&u);
    }

    fn cmd_stats(&self) {
        let (lock, cv) = &*self.sh;
        let g = cv.wait_while(lock.lock().unwrap(), |s| s.pending > 0).unwrap();
        println!(
            "stats: users={} rooms={} messages={} archived_rooms={} archived_messages={}",
            self.users.len(),
            self.rooms.len(),
            g.messages,
            g.archived_rooms,
            g.archived_messages
        );
        for a in &g.archive {
            println!("  archive {}", a);
        }
        drop(g);
        println!(
            "  alive: users={} rooms={}",
            USERS_ALIVE.load(Ordering::SeqCst),
            ROOMS_ALIVE.load(Ordering::SeqCst)
        );
    }
}

fn next_word<'a>(s: &mut &'a str) -> Option<&'a str> {
    *s = s.trim_start_matches(' ');
    if s.is_empty() {
        return None;
    }
    let end = s.find(' ').unwrap_or(s.len());
    let w = &s[..end];
    *s = if end < s.len() { &s[end + 1..] } else { &s[end..] };
    Some(w)
}
fn rest(s: &str) -> &str {
    s.trim_start_matches(' ')
}
fn atoi(s: &str) -> i32 {
    let s = s.trim_start();
    let (neg, body) = match s.strip_prefix('-') {
        Some(b) => (true, b),
        None => (false, s.strip_prefix('+').unwrap_or(s)),
    };
    let digits: String = body.chars().take_while(|c| c.is_ascii_digit()).collect();
    let v: i32 = digits.parse().unwrap_or(0);
    if neg { -v } else { v }
}

fn main() {
    let sh: SharedRef = Arc::new((Mutex::new(Shared::default()), Condvar::new()));
    let wsh = sh.clone();
    let handle = thread::spawn(move || worker(wsh));
    let mut srv = Server {
        users: Vec::new(),
        rooms: Vec::new(),
        timers: Vec::new(),
        rates: Vec::new(),
        clock: 0,
        sh: sh.clone(),
    };

    let stdin = io::stdin();
    let mut input = stdin.lock();
    let mut buf: Vec<u8> = Vec::new();
    loop {
        buf.clear();
        if input.read_until(b'\n', &mut buf).unwrap_or(0) == 0 {
            break;
        }
        let end = buf.iter().position(|&b| b == b'\r' || b == b'\n').unwrap_or(buf.len());
        let line = String::from_utf8_lossy(&buf[..end]).into_owned();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        println!("> {}", line);
        let mut s: &str = &line;
        let Some(cmd) = next_word(&mut s) else { continue };
        let a = next_word(&mut s);
        match (cmd, a) {
            ("join", Some(a)) => match next_word(&mut s) {
                Some(b) => srv.cmd_join(a, b),
                None => println!("bad command: {}", cmd),
            },
            ("say", Some(a)) => srv.cmd_say(a, rest(s)),
            ("dm", Some(a)) => match next_word(&mut s) {
                Some(b) => srv.cmd_dm(a, b, rest(s)),
                None => println!("bad command: {}", cmd),
            },
            ("reply", Some(a)) => srv.cmd_reply(a, rest(s)),
            ("remind", Some(a)) => match next_word(&mut s) {
                Some(b) => srv.cmd_remind(a, atoi(b), rest(s)),
                None => println!("bad command: {}", cmd),
            },
            ("tick", Some(a)) => srv.cmd_tick(atoi(a)),
            ("move", Some(a)) => match next_word(&mut s) {
                Some(b) => srv.cmd_move(a, b),
                None => println!("bad command: {}", cmd),
            },
            ("leave", Some(a)) => srv.cmd_leave(a),
            ("stats", _) => srv.cmd_stats(),
            _ => println!("bad command: {}", cmd),
        }
    }

    // Shutdown: stop the worker, then drop what is left without archiving it.
    {
        let (lock, cv) = &*sh;
        lock.lock().unwrap().stop = true;
        cv.notify_all();
    }
    handle.join().unwrap();
    drop(srv);
    println!(
        "exit: alive users={} rooms={}",
        USERS_ALIVE.load(Ordering::SeqCst),
        ROOMS_ALIVE.load(Ordering::SeqCst)
    );
}
