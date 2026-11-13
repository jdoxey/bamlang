// D3 benchmark, model F1: Crew (scoped threads that own the cancel token and channel endpoints).
use std::any::Any;
use std::panic::{AssertUnwindSafe, catch_unwind, resume_unwind};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::thread::{self, Scope};

// ---- MODEL: stands in for a built-in `crew` ----
#[derive(Clone)]
pub struct Token(Arc<AtomicBool>);
impl Token {
    pub fn cancelled(&self) -> bool {
        self.0.load(Ordering::SeqCst)
    }
    pub fn cancel(&self) {
        self.0.store(true, Ordering::SeqCst);
    }
}

type Payload = Box<dyn Any + Send>;

pub struct Crew<'scope, 'env: 'scope> {
    scope: &'scope Scope<'scope, 'env>,
    token: Token,
    first: Arc<Mutex<Option<Payload>>>,
}

impl<'scope, 'env> Crew<'scope, 'env> {
    pub fn token(&self) -> &Token {
        &self.token
    }
    /// Start a child. A panic in it cancels the siblings and is re-raised when the crew ends.
    pub fn go<F: FnOnce(&Token) + Send + 'scope>(&self, f: F) {
        let tok = self.token.clone();
        let first = self.first.clone();
        self.scope.spawn(move || {
            if let Err(p) = catch_unwind(AssertUnwindSafe(|| f(&tok))) {
                tok.cancel();
                first.lock().unwrap().get_or_insert(p);
            }
        });
    }
    /// Owned channel endpoints; dropping the last sender closes.
    pub fn channel<T>(&self) -> (Sender<T>, Receiver<T>) {
        mpsc::channel()
    }
    /// One child per disjoint part of `data`; `f(offset, part, token)`.
    pub fn each_part<T, F>(&self, data: &'scope mut [T], parts: usize, f: F)
    where
        T: Send,
        F: Fn(usize, &mut [T], &Token) + Send + Sync + 'scope,
    {
        let f = Arc::new(f);
        let size = data.len().div_ceil(parts);
        for (i, part) in data.chunks_mut(size).enumerate() {
            let f = f.clone();
            self.go(move |t| f(i * size, part, t));
        }
    }
}

/// Run `body` as the crew's owner; joins every child, then re-raises the first child panic.
pub fn crew<'env, R>(body: impl for<'scope> FnOnce(&Crew<'scope, 'env>) -> R) -> R {
    let token = Token(Arc::new(AtomicBool::new(false)));
    let first: Arc<Mutex<Option<Payload>>> = Arc::new(Mutex::new(None));
    let out = thread::scope(|s| {
        let c = Crew { scope: s, token: token.clone(), first: first.clone() };
        catch_unwind(AssertUnwindSafe(|| body(&c))).inspect_err(|_| token.cancel())
    });
    match out {
        Err(p) => resume_unwind(p),
        Ok(r) => match first.lock().unwrap().take() {
            Some(p) => resume_unwind(p),
            None => r,
        },
    }
}
// ---- END MODEL ----

const P: u64 = 1_000_000_007;
const N: u64 = 1_000_000;

// ---- PART A ----
fn part_a() {
    let input: Vec<u64> = (1..=N).collect();
    let mut out = vec![0u64; N as usize];
    let input = &input;
    crew(|c| {
        c.each_part(&mut out, 4, move |offset, part, _| {
            for (j, o) in part.iter_mut().enumerate() {
                let x = input[offset + j];
                *o = x * x;
            }
        });
    });
    let sum = out.iter().fold(0, |a, v| (a + v % P) % P);
    let n = out.len();
    println!("A: sum={sum} first={:?} last={:?}", &out[..3], &out[n - 3..]);
}

// ---- PART B ----
fn bump(counter: &Mutex<u32>) {
    *counter.lock().unwrap() += 1;
}

fn part_b() {
    let counter = Mutex::new(0u32);
    let counter_ref = &counter;
    let (jtx, jrx) = mpsc::channel::<u32>();
    let jrx = Arc::new(Mutex::new(jrx));
    let total: u32 = crew(|c| {
        let (rtx, rrx) = c.channel::<u32>();
        for _ in 0..4 {
            let rtx = rtx.clone();
            let jrx = jrx.clone();
            c.go(move |_| {
                loop {
                    let job = jrx.lock().unwrap().recv();
                    let Ok(n) = job else { break };
                    bump(counter_ref);
                    rtx.send(n * n).expect("collector gone");
                }
            });
        }
        drop(rtx);
        for n in 1..=20 {
            jtx.send(n).unwrap();
        }
        drop(jtx);
        rrx.iter().sum()
    });
    println!("B: total={total} counter={}", counter.into_inner().unwrap());
}

// ---- PART C ----
enum Msg {
    Progress(u32),
    Cancelled { step: u32, partial: Vec<u32> },
    Done(Vec<u32>),
}

fn job(tok: &Token, partial: &Mutex<Vec<u32>>, tx: Sender<Msg>, ack: Receiver<()>) {
    for k in 1..=10 {
        if tok.cancelled() {
            let p = partial.lock().unwrap().clone();
            let _ = tx.send(Msg::Cancelled { step: k - 1, partial: p });
            return;
        }
        partial.lock().unwrap().push(k);
        let _ = tx.send(Msg::Progress(k));
        if ack.recv().is_err() {
            return;
        }
    }
    let p = partial.lock().unwrap().clone();
    let _ = tx.send(Msg::Done(p));
}

/// Receive one message from the job and print it. Returns true when the job has finished.
fn pump(rx: &Receiver<Msg>) -> bool {
    match rx.recv().expect("job vanished") {
        Msg::Progress(k) => {
            println!("C: progress {k}");
            false
        }
        Msg::Cancelled { step, partial } => {
            println!("C: cancelled at step {step}, partial = {partial:?}");
            true
        }
        Msg::Done(partial) => {
            println!("C: done, partial = {partial:?}");
            true
        }
    }
}

fn part_c() {
    let events = ["start", "tick", "tick", "tick", "cancel", "tick", "tick", "quit"];
    let partial = Mutex::new(Vec::new());
    let partial = &partial;
    // Live-crew emulation: one scope around the whole event loop.
    crew(|c| {
        let mut live: Option<(Sender<()>, Receiver<Msg>)> = None;
        for ev in events {
            println!("C: event {ev}");
            match (ev, &live) {
                ("start", None) => {
                    let (tx, rx) = c.channel();
                    let (atx, arx) = mpsc::channel();
                    c.go(move |t| job(t, partial, tx, arx));
                    pump(&rx);
                    live = Some((atx, rx));
                }
                ("tick", Some((ack, rx))) => {
                    let _ = ack.send(());
                    if pump(rx) {
                        live = None;
                    }
                }
                ("cancel", Some((ack, rx))) => {
                    c.token().cancel();
                    let _ = ack.send(());
                    while !pump(rx) {}
                    live = None;
                }
                ("quit", _) => {
                    c.token().cancel();
                    live = None; // drops the ack sender so a waiting job exits
                }
                _ => println!("C: idle, no job"),
            }
        }
    });
    println!("C: joined");
}

fn main() {
    part_a();
    part_b();
    part_c();
}
