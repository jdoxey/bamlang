// O1 model: pure ARC. Every object is a shared reference (Rc<RefCell<..>>), as in Swift classes.
// Swift is not installed here, so Rust Rc/RefCell/Weak stands in. RefCell makes the aliasing checks visible at run time.
use std::cell::RefCell;
use std::rc::{Rc, Weak};
use std::sync::{mpsc, Arc, Mutex, Condvar};
use std::thread;
use std::io::BufRead;

type UserRef = Rc<RefCell<User>>;
type RoomRef = Rc<RefCell<Room>>;
struct User { name: String, room: Option<Weak<RefCell<Room>>>, is_bot: bool, me: Weak<RefCell<User>> }
// The room holds each member's callback; callbacks capture the user WEAKLY (else cycle: room -> cb -> user -> room).
struct Member { user: UserRef, cb: Rc<dyn Fn(&RoomRef, &str, &str)> }
struct Room { name: String, members: Vec<Member>, history: Vec<String> }
struct Reminder { fire: i64, user: Weak<RefCell<User>>, text: String }
#[derive(Default)] struct Stats { rooms: u64, msgs: u64, log: Vec<String>, pending: u64 }
struct Gate { released: bool, stop: bool }

thread_local! { static LIVE: RefCell<i64> = RefCell::new(0); }

struct World {
    users: Vec<UserRef>, rooms: Vec<RoomRef>, timers: Vec<Reminder>, now: i64, tokens: i32,
    tx: mpsc::Sender<(String, Vec<String>)>, stats: Arc<Mutex<Stats>>, gate: Arc<(Mutex<Gate>, Condvar)>,
}

fn post(room: &RoomRef, from: &str, text: &str) {
    room.borrow_mut().history.push(text.to_string());
    // Case 20: callbacks may call post() again. Holding room.borrow() across the loop would panic
    // (BorrowMutError) when the echobot posts. So snapshot the members before calling out.
    let snap: Vec<(UserRef, Rc<dyn Fn(&RoomRef, &str, &str)>)> =
        room.borrow().members.iter().map(|m| (m.user.clone(), m.cb.clone())).collect();
    for (u, cb) in snap {
        if u.borrow().name == from { continue; }
        let still_here = u.borrow().room.as_ref().and_then(|w| w.upgrade()).map_or(false, |r| Rc::ptr_eq(&r, room));
        if still_here { cb(room, from, text); }
    }
}

impl World {
    fn find(&self, name: &str) -> Option<UserRef> { self.users.iter().find(|u| u.borrow().name == name).cloned() }
    fn take_token(&mut self) -> bool { if self.tokens <= 0 { println!("  rate limited"); false } else { self.tokens -= 1; true } }

    fn leave_room(&mut self, u: &UserRef) {
        let Some(room) = u.borrow_mut().room.take().and_then(|w| w.upgrade()) else { return };
        room.borrow_mut().members.retain(|m| !Rc::ptr_eq(&m.user, u));
        if room.borrow().members.is_empty() {
            self.rooms.retain(|r| !Rc::ptr_eq(r, &room));
            let hist = std::mem::take(&mut room.borrow_mut().history);   // case 23: move out, send to worker
            let name = room.borrow().name.clone();
            println!("  room {} closed, {} messages queued for archive", name, hist.len());
            self.stats.lock().unwrap().pending += 1;
            self.tx.send((name, hist)).unwrap();
        }
    }

    fn join(&mut self, name: &str, rname: &str) {
        let u = match self.find(name) {
            Some(u) => { self.leave_room(&u); u }
            None => {
                let is_bot = name.starts_with("echobot");
                let u = Rc::new(RefCell::new(User { name: name.into(), room: None, is_bot, me: Weak::new() }));
                u.borrow_mut().me = Rc::downgrade(&u);
                self.users.push(u.clone()); u
            }
        };
        let room = match self.rooms.iter().find(|r| r.borrow().name == rname).cloned() {
            Some(r) => r,
            None => { let r = Rc::new(RefCell::new(Room { name: rname.into(), members: vec![], history: vec![] })); self.rooms.push(r.clone()); r }
        };
        let weak_me = Rc::downgrade(&u);                                   // the weak capture is mandatory here
        let is_bot = u.borrow().is_bot;
        let cb: Rc<dyn Fn(&RoomRef, &str, &str)> = if is_bot {
            Rc::new(move |room, from, text| {
                let Some(me) = weak_me.upgrade() else { return };
                // bot ignores bots: needs a lookup of the sender; we get it from room members
                let sender_is_bot = room.borrow().members.iter().any(|m| m.user.borrow().name == from && m.user.borrow().is_bot);
                if sender_is_bot { return; }
                let n = me.borrow().name.clone();
                post(room, &n, &format!("echo: {}", text));
            })
        } else {
            Rc::new(move |room, from, text| {
                let Some(me) = weak_me.upgrade() else { return };
                println!("  [{}] {} <- {}: {}", room.borrow().name, me.borrow().name, from, text);
            })
        };
        room.borrow_mut().members.push(Member { user: u.clone(), cb });
        u.borrow_mut().room = Some(Rc::downgrade(&room));                  // back-reference is weak
        println!("  {} joined {} ({} members)", name, rname, room.borrow().members.len());
    }

    fn tick(&mut self, n: i64) {
        for _ in 0..n {
            self.now += 1; if self.tokens < 3 { self.tokens += 1; }
            let mut i = 0;
            while i < self.timers.len() {
                if self.timers[i].fire <= self.now {
                    let rm = self.timers.swap_remove(i);
                    match rm.user.upgrade() {   // case 15: weak upgrade fails once the user is gone
                        Some(u) => println!("  reminder for {}: {}", u.borrow().name, rm.text),
                        None => println!("  reminder dropped (user gone)"),
                    }
                } else { i += 1; }
            }
        }
        println!("  now={}", self.now);
    }
}

fn split(line: &str) -> Vec<String> {
    let mut out = vec![]; let mut cs = line.chars().peekable();
    while let Some(&c) = cs.peek() {
        if c == ' ' { cs.next(); continue; }
        let mut w = String::new();
        if c == '"' { cs.next(); while let Some(c) = cs.next() { if c == '"' { break; } w.push(c); } }
        else { while let Some(&c) = cs.peek() { if c == ' ' { break; } w.push(c); cs.next(); } }
        out.push(w);
    }
    out
}

fn main() {
    let (tx, rx) = mpsc::channel::<(String, Vec<String>)>();
    let stats = Arc::new(Mutex::new(Stats::default()));
    let gate = Arc::new((Mutex::new(Gate { released: false, stop: false }), Condvar::new()));
    let (s2, g2) = (stats.clone(), gate.clone());
    let worker = thread::spawn(move || loop {
        { let (m, cv) = &*g2; let mut g = m.lock().unwrap(); while !g.released && !g.stop { g = cv.wait(g).unwrap(); } if g.stop { break; } }
        while let Ok((room, lines)) = rx.try_recv() {
            let bytes: usize = lines.iter().map(|l| l.len()).sum();
            let mut s = s2.lock().unwrap();
            s.rooms += 1; s.msgs += lines.len() as u64; s.pending -= 1;
            s.log.push(format!("archived {}: {} msgs, {} bytes", room, lines.len(), bytes));
        }
        let (m, cv) = &*g2; m.lock().unwrap().released = false; cv.notify_all();
    });
    let mut w = World { users: vec![], rooms: vec![], timers: vec![], now: 0, tokens: 3, tx, stats: stats.clone(), gate: gate.clone() };
    let flush = |w: &World| {
        let (m, cv) = &*w.gate; let mut g = m.lock().unwrap(); g.released = true; cv.notify_all();
        while g.released { g = cv.wait(g).unwrap(); }
        for l in w.stats.lock().unwrap().log.drain(..) { println!("  {}", l); }
    };
    for line in std::io::stdin().lock().lines() {
        let line = line.unwrap(); let line = line.split("  #").next().unwrap().trim_end().to_string();
        if line.is_empty() || line.starts_with('#') { continue; }
        println!("> {}", line);
        let a = split(&line);
        match (a[0].as_str(), a.len()) {
            ("join", 3) | ("move", 3) => w.join(&a[1], &a[2]),
            ("leave", 2) => match w.find(&a[1]) {
                Some(u) => { w.leave_room(&u); w.users.retain(|x| !Rc::ptr_eq(x, &u)); println!("  {} left", a[1]); }
                None => println!("  no such user"),
            },
            ("say", 3) => match w.find(&a[1]).and_then(|u| u.borrow().room.as_ref().and_then(|r| r.upgrade())) {
                Some(room) => if w.take_token() { post(&room, &a[1], &a[2]) },
                None => println!("  not in a room"),
            },
            ("dm", 4) => match (w.find(&a[1]), w.find(&a[2])) {
                (None, _) => println!("  no such user"),
                (_, None) => println!("  dm failed: {} is not here", a[2]),
                (Some(_), Some(to)) => if w.take_token() {
                    let room = to.borrow().room.as_ref().and_then(|r| r.upgrade()).unwrap();
                    let cb = room.borrow().members.iter().find(|m| Rc::ptr_eq(&m.user, &to)).unwrap().cb.clone();
                    cb(&room, &a[1], &a[3]);
                },
            },
            ("remind", 4) => match w.find(&a[1]) {
                Some(u) => { let fire = w.now + a[2].parse::<i64>().unwrap(); w.timers.push(Reminder { fire, user: Rc::downgrade(&u), text: a[3].clone() }); println!("  reminder set"); }
                None => println!("  no such user"),
            },
            ("tick", 2) => w.tick(a[1].parse().unwrap()),
            ("flush", _) => flush(&w),
            ("stats", _) => { let s = stats.lock().unwrap();
                println!("  users={} rooms={} timers={} archived_rooms={} archived_msgs={} pending={}", w.users.len(), w.rooms.len(), w.timers.len(), s.rooms, s.msgs, s.pending); }
            _ => println!("  bad command"),
        }
    }
    let us: Vec<_> = w.users.clone();
    for u in us { w.leave_room(&u); println!("  {} left", u.borrow().name); }
    w.users.clear();
    flush(&w);
    { let (m, cv) = &*gate; m.lock().unwrap().stop = true; cv.notify_all(); }
    worker.join().unwrap();
    LIVE.with(|_| {});
}
