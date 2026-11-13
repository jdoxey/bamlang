// D3 benchmark, model F2: std::thread::scope for A and B; a must-join detached spawn for C.
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};

// ---- MODEL: stands in for a built-in must-consume `Join` ----
// Rust only warns when a #[must_use] value is dropped unused; the real language makes it a compile error.
// The Drop check below is a runtime stand-in for that error.
#[must_use = "a spawned thread must be joined"]
pub struct Join<T>(Option<JoinHandle<T>>);

pub fn spawn<T: Send + 'static>(f: impl FnOnce() -> T + Send + 'static) -> Join<T> {
    Join(Some(thread::spawn(f)))
}

impl<T> Join<T> {
    pub fn join(mut self) -> thread::Result<T> {
        self.0.take().unwrap().join()
    }
}

impl<T> Drop for Join<T> {
    fn drop(&mut self) {
        if self.0.is_some() && !thread::panicking() {
            panic!("Join dropped without being joined");
        }
    }
}
// ---- END MODEL ----

const P: u64 = 1_000_000_007;
const N: u64 = 1_000_000;

// ---- PART A ----
fn part_a() {
    let input: Vec<u64> = (1..=N).collect();
    let mut out = vec![0u64; N as usize];
    let size = out.len().div_ceil(4);
    thread::scope(|s| {
        for (i, part) in out.chunks_mut(size).enumerate() {
            let input = &input;
            s.spawn(move || {
                for (j, o) in part.iter_mut().enumerate() {
                    let x = input[i * size + j];
                    *o = x * x;
                }
            });
        }
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
    let (jtx, jrx) = mpsc::channel::<u32>();
    let (rtx, rrx) = mpsc::channel::<u32>();
    let jrx = Mutex::new(jrx);
    let total: u32 = thread::scope(|s| {
        for _ in 0..4 {
            let rtx = rtx.clone();
            let (jrx, counter) = (&jrx, &counter);
            s.spawn(move || {
                loop {
                    let job = jrx.lock().unwrap().recv();
                    let Ok(n) = job else { break };
                    bump(counter);
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

// Cancellation is a convention: a shared Arc<AtomicBool> that the job polls at its checkpoint.
fn job(cancel: Arc<AtomicBool>, partial: Arc<Mutex<Vec<u32>>>, tx: Sender<Msg>, ack: Receiver<()>) {
    for k in 1..=10 {
        if cancel.load(Ordering::SeqCst) {
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
    let cancel = Arc::new(AtomicBool::new(false));
    let partial = Arc::new(Mutex::new(Vec::new()));
    let mut handle: Option<Join<()>> = None;
    let mut live: Option<(Sender<()>, Receiver<Msg>)> = None;
    for ev in events {
        println!("C: event {ev}");
        match (ev, &live) {
            ("start", None) => {
                let (tx, rx) = mpsc::channel();
                let (atx, arx) = mpsc::channel();
                let (c, p) = (cancel.clone(), partial.clone());
                handle = Some(spawn(move || job(c, p, tx, arx)));
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
                cancel.store(true, Ordering::SeqCst);
                let _ = ack.send(());
                while !pump(rx) {}
                live = None;
            }
            ("quit", _) => {
                cancel.store(true, Ordering::SeqCst);
                live = None; // drops the ack sender so a waiting job exits
                if let Some(h) = handle.take() {
                    h.join().expect("job panicked");
                }
            }
            _ => println!("C: idle, no job"),
        }
    }
    println!("C: joined");
}

fn main() {
    part_a();
    part_b();
    part_c();
}
