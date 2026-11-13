// O4 model: simplified ownership. Moves everywhere; Rc/Arc only where forced (none needed except stats).
// Server owns everything. Back-references are plain ids. Callbacks receive &mut Server instead of capturing it.
use std::collections::HashMap;
use std::io::BufRead;
use std::sync::{mpsc, Arc, Mutex, Condvar};
use std::thread;

type UserId = u32;
struct Callback(Box<dyn Fn(&mut Server, UserId, &str, &str)>); // (server, recipient, from, text)
struct User { name: String, room: Option<String>, cb: Callback, is_bot: bool }
struct Room { members: Vec<UserId>, history: Vec<String> }
struct Reminder { fire: i64, user: UserId, text: String }

#[derive(Default)] struct Stats { rooms: u64, msgs: u64, log: Vec<String>, pending: u64 }
struct Gate { released: bool, stop: bool }

struct Server {
    users: HashMap<UserId, User>, rooms: HashMap<String, Room>, timers: Vec<Reminder>,
    next_id: UserId, now: i64, tokens: i32,
    tx: mpsc::Sender<(String, Vec<String>)>,
    stats: Arc<Mutex<Stats>>, gate: Arc<(Mutex<Gate>, Condvar)>,
}

impl Server {
    fn find(&self, name: &str) -> Option<UserId> { self.users.iter().find(|(_, u)| u.name == name).map(|(i, _)| *i) }
    fn take_token(&mut self) -> bool { if self.tokens <= 0 { println!("  rate limited"); false } else { self.tokens -= 1; true } }

    fn deliver(&mut self, to: UserId, from: &str, text: &str) {
        // Case 20: the callback needs &mut Server, so we must take it out of the user first (or clone it).
        // Rust rejects `self.users[&to].cb.0(self, ...)` (E0502); the workaround is to move the box out and put it back.
        let Some(u) = self.users.get_mut(&to) else { return };
        let cb = std::mem::replace(&mut u.cb, Callback(Box::new(|_, _, _, _| {})));
        (cb.0)(self, to, from, text);
        if let Some(u) = self.users.get_mut(&to) { u.cb = cb; }
    }

    fn post(&mut self, room: &str, from: &str, text: &str) {
        let Some(r) = self.rooms.get_mut(room) else { return };
        r.history.push(text.to_string());
        let ids = r.members.clone();                       // snapshot
        for id in ids {
            let still = self.users.get(&id).map_or(false, |u| u.room.as_deref() == Some(room) && u.name != from);
            if still { self.deliver(id, from, text); }
        }
    }

    fn leave_room(&mut self, id: UserId) {
        let Some(room) = self.users.get_mut(&id).and_then(|u| u.room.take()) else { return };
        let r = self.rooms.get_mut(&room).unwrap();
        r.members.retain(|m| *m != id);
        if r.members.is_empty() {
            let r = self.rooms.remove(&room).unwrap();     // case 12
            let n = r.history.len();
            self.stats.lock().unwrap().pending += 1;
            self.tx.send((room.clone(), r.history)).unwrap(); // case 23: history moves to the worker
            println!("  room {} closed, {} messages queued for archive", room, n);
        }
    }

    fn join(&mut self, name: &str, room: &str) {
        let id = match self.find(name) {
            Some(id) => { self.leave_room(id); id }
            None => {
                let id = self.next_id; self.next_id += 1;
                let is_bot = name.starts_with("echobot");
                let cb: Callback = if is_bot {
                    Callback(Box::new(|s, me, from, text| {
                        if s.find(from).map_or(false, |f| s.users[&f].is_bot) { return; }
                        let (name, room) = { let u = &s.users[&me]; (u.name.clone(), u.room.clone().unwrap()) };
                        s.post(&room, &name, &format!("echo: {}", text));
                    }))
                } else {
                    Callback(Box::new(|s, me, from, text| {
                        let u = &s.users[&me];
                        println!("  [{}] {} <- {}: {}", u.room.as_deref().unwrap_or("?"), u.name, from, text);
                    }))
                };
                self.users.insert(id, User { name: name.to_string(), room: None, cb, is_bot });
                id
            }
        };
        let r = self.rooms.entry(room.to_string()).or_insert_with(|| Room { members: vec![], history: vec![] });
        r.members.push(id);
        let n = r.members.len();
        self.users.get_mut(&id).unwrap().room = Some(room.to_string());
        println!("  {} joined {} ({} members)", name, room, n);
    }

    fn tick(&mut self, n: i64) {
        for _ in 0..n {
            self.now += 1; if self.tokens < 3 { self.tokens += 1; }
            let mut i = 0;
            while i < self.timers.len() {
                if self.timers[i].fire <= self.now {
                    let rm = self.timers.swap_remove(i);
                    match self.users.get(&rm.user) {
                        Some(u) => println!("  reminder for {}: {}", u.name, rm.text),
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
    let worker = thread::spawn(move || {
        // Jobs queue up in the channel; the worker only starts consuming when released (deterministic script).
        loop {
            { let (m, cv) = &*g2; let mut g = m.lock().unwrap(); while !g.released && !g.stop { g = cv.wait(g).unwrap(); } if g.stop { break; } }
            while let Ok((room, lines)) = rx.try_recv() {
                let bytes: usize = lines.iter().map(|l| l.len()).sum();
                let mut s = s2.lock().unwrap();
                s.rooms += 1; s.msgs += lines.len() as u64; s.pending -= 1;
                s.log.push(format!("archived {}: {} msgs, {} bytes", room, lines.len(), bytes));
            }
            let (m, cv) = &*g2; let mut g = m.lock().unwrap(); g.released = false; cv.notify_all();
        }
    });
    let mut sv = Server { users: HashMap::new(), rooms: HashMap::new(), timers: vec![], next_id: 1, now: 0, tokens: 3,
                          tx, stats: stats.clone(), gate: gate.clone() };
    let flush = |sv: &Server| {
        let (m, cv) = &*sv.gate; let mut g = m.lock().unwrap(); g.released = true; cv.notify_all();
        while g.released { g = cv.wait(g).unwrap(); }
        let mut s = sv.stats.lock().unwrap();
        for l in s.log.drain(..) { println!("  {}", l); }
    };
    for line in std::io::stdin().lock().lines() {
        let line = line.unwrap(); let line = line.split("  #").next().unwrap().trim_end().to_string();
        if line.is_empty() || line.starts_with('#') { continue; }
        println!("> {}", line);
        let w = split(&line); let n = w.len();
        match (w[0].as_str(), n) {
            ("join", 3) | ("move", 3) => sv.join(&w[1], &w[2]),
            ("leave", 2) => match sv.find(&w[1]) {
                Some(id) => { sv.leave_room(id); sv.users.remove(&id); println!("  {} left", w[1]); }
                None => println!("  no such user"),
            },
            ("say", 3) => match sv.find(&w[1]).and_then(|i| sv.users[&i].room.clone().map(|r| (i, r))) {
                Some((_, room)) => if sv.take_token() { sv.post(&room, &w[1], &w[2]) },
                None => println!("  not in a room"),
            },
            ("dm", 4) => match (sv.find(&w[1]), sv.find(&w[2])) {
                (None, _) => println!("  no such user"),
                (_, None) => println!("  dm failed: {} is not here", w[2]),
                (Some(_), Some(to)) => if sv.take_token() { sv.deliver(to, &w[1], &w[3]) },
            },
            ("remind", 4) => match sv.find(&w[1]) {
                Some(id) => { let fire = sv.now + w[2].parse::<i64>().unwrap(); sv.timers.push(Reminder { fire, user: id, text: w[3].clone() }); println!("  reminder set"); }
                None => println!("  no such user"),
            },
            ("tick", 2) => sv.tick(w[1].parse().unwrap()),
            ("flush", _) => flush(&sv),
            ("stats", _) => { let s = stats.lock().unwrap();
                println!("  users={} rooms={} timers={} archived_rooms={} archived_msgs={} pending={}", sv.users.len(), sv.rooms.len(), sv.timers.len(), s.rooms, s.msgs, s.pending); }
            _ => println!("  bad command"),
        }
    }
    let ids: Vec<_> = sv.users.keys().cloned().collect();
    for id in ids { sv.leave_room(id); let n = sv.users.remove(&id).unwrap().name; println!("  {} left", n); }
    flush(&sv);
    { let (m, cv) = &*gate; m.lock().unwrap().stop = true; cv.notify_all(); }
    worker.join().unwrap();
}
