// D3 benchmark, model F3: a main loop plus `offload` tasks; `par_map` for A, `offload_each` for B.
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};

// ---- MODEL: stands in for built-ins `par_map`, `offload_each`, `offload`, `App` ----
/// Scoped compute with borrows: `f` over `items` on `threads` threads, results in order.
pub fn par_map<T: Sync, U: Send + Default + Clone>(items: &[T], threads: usize, f: impl Fn(&T) -> U + Sync) -> Vec<U> {
    let mut out = vec![U::default(); items.len()];
    let size = items.len().div_ceil(threads);
    thread::scope(|s| {
        for (inp, o) in items.chunks(size).zip(out.chunks_mut(size)) {
            let f = &f;
            s.spawn(move || {
                for (x, slot) in inp.iter().zip(o.iter_mut()) {
                    *slot = f(x);
                }
            });
        }
    });
    out
}

/// Built-in worker pool: `workers` threads take `items` from an internal queue; results come back in a Vec
/// (order not guaranteed). The channels are hidden inside.
pub fn offload_each<J: Send, R: Send>(items: Vec<J>, workers: usize, f: impl Fn(J) -> R + Sync) -> Vec<R> {
    let (jtx, jrx) = mpsc::channel::<J>();
    let (rtx, rrx) = mpsc::channel::<R>();
    let jrx = Mutex::new(jrx);
    thread::scope(|s| {
        for _ in 0..workers {
            let rtx = rtx.clone();
            let (jrx, f) = (&jrx, &f);
            s.spawn(move || {
                loop {
                    let job = jrx.lock().unwrap().recv();
                    let Ok(j) = job else { break };
                    rtx.send(f(j)).expect("collector gone");
                }
            });
        }
        drop(rtx);
        for j in items {
            jtx.send(j).unwrap();
        }
        drop(jtx);
        rrx.iter().collect()
    })
}

enum Ev<P, T> {
    Progress(P),
    Done(T),
    Failed,
}

/// What the offloaded function sees.
pub struct TaskCtx<P> {
    cancel: Arc<AtomicBool>,
    post: Box<dyn Fn(P) + Send>,
    ack: Receiver<()>,
}

pub struct Task {
    cancel: Arc<AtomicBool>,
    ack: Sender<()>,
    handle: JoinHandle<()>,
}

impl Task {
    pub fn cancel(&self) {
        self.cancel.store(true, Ordering::SeqCst);
    }
    /// Determinism harness for the benchmark: release a job that is waiting in `me.wait_tick()`.
    pub fn tick(&self) {
        let _ = self.ack.send(());
    }
    pub fn join(self) {
        drop(self.ack);
        self.handle.join().unwrap();
    }
}

impl<P> TaskCtx<P> {
    pub fn cancelled(&self) -> bool {
        self.cancel.load(Ordering::SeqCst)
    }
    pub fn post(&self, p: P) {
        (self.post)(p);
    }
    /// Determinism harness: block until the main loop ticks. False if the main loop is gone.
    pub fn wait_tick(&self) -> bool {
        self.ack.recv().is_ok()
    }
}

/// The main loop's event queue; callbacks run on the thread that calls `next`.
pub struct App<P, T> {
    tx: Sender<Ev<P, T>>,
    rx: Receiver<Ev<P, T>>,
    on_progress: Option<Box<dyn FnMut(P)>>,
    on_done: Option<Box<dyn FnMut(T)>>,
}

impl<P: Send + 'static, T: Send + 'static> App<P, T> {
    pub fn new() -> Self {
        let (tx, rx) = mpsc::channel();
        App { tx, rx, on_progress: None, on_done: None }
    }
    pub fn offload(&self, f: impl FnOnce(&TaskCtx<P>) -> T + Send + 'static) -> Task {
        let cancel = Arc::new(AtomicBool::new(false));
        let (ack, arx) = mpsc::channel();
        let tx = self.tx.clone();
        let ptx = tx.clone();
        let post = Box::new(move |p| {
            let _ = ptx.send(Ev::Progress(p));
        });
        let ctx = TaskCtx { cancel: cancel.clone(), post, ack: arx };
        let handle = thread::spawn(move || {
            let r = catch_unwind(AssertUnwindSafe(|| f(&ctx)));
            let _ = tx.send(match r {
                Ok(v) => Ev::Done(v),
                Err(_) => Ev::Failed,
            });
        });
        Task { cancel, ack, handle }
    }
    pub fn on(&mut self, progress: impl FnMut(P) + 'static, done: impl FnMut(T) + 'static) {
        self.on_progress = Some(Box::new(progress));
        self.on_done = Some(Box::new(done));
    }
    /// Block for the next task event and run its callback here, on the main thread.
    pub fn next(&mut self) {
        match self.rx.recv().expect("no tasks") {
            Ev::Progress(p) => (self.on_progress.as_mut().unwrap())(p),
            Ev::Done(v) => (self.on_done.as_mut().unwrap())(v),
            Ev::Failed => panic!("task failed"),
        }
    }
}
// ---- END MODEL ----

const P: u64 = 1_000_000_007;
const N: u64 = 1_000_000;

// ---- PART A ----
fn part_a() {
    let input: Vec<u64> = (1..=N).collect();
    let out = par_map(&input, 4, |x| x * x);
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
    let results = offload_each((1..=20u32).collect(), 4, |n| {
        bump(&counter);
        n * n
    });
    let total: u32 = results.iter().sum();
    println!("B: total={total} counter={}", counter.into_inner().unwrap());
}

// ---- PART C ----
enum Outcome {
    Cancelled { step: u32, partial: Vec<u32> },
    Done(Vec<u32>),
}

fn job(me: &TaskCtx<u32>, partial: &Mutex<Vec<u32>>) -> Outcome {
    for k in 1..=10 {
        if me.cancelled() {
            return Outcome::Cancelled { step: k - 1, partial: partial.lock().unwrap().clone() };
        }
        partial.lock().unwrap().push(k);
        me.post(k);
        if !me.wait_tick() {
            return Outcome::Cancelled { step: k, partial: partial.lock().unwrap().clone() };
        }
    }
    Outcome::Done(partial.lock().unwrap().clone())
}

fn part_c() {
    use std::cell::Cell;
    use std::rc::Rc;
    let events = ["start", "tick", "tick", "tick", "cancel", "tick", "tick", "quit"];
    let mut app: App<u32, Outcome> = App::new();
    let finished = Rc::new(Cell::new(false)); // main-thread state, touched only by callbacks
    let fin = finished.clone();
    app.on(
        |k| println!("C: progress {k}"),
        move |o| {
            match o {
                Outcome::Cancelled { step, partial } => {
                    println!("C: cancelled at step {step}, partial = {partial:?}")
                }
                Outcome::Done(partial) => println!("C: done, partial = {partial:?}"),
            }
            fin.set(true);
        },
    );
    let mut task: Option<Task> = None;
    for ev in events {
        println!("C: event {ev}");
        match (ev, &task) {
            ("start", None) => {
                let partial = Arc::new(Mutex::new(Vec::new()));
                task = Some(app.offload(move |me| job(me, &partial)));
                app.next();
            }
            ("tick", Some(t)) => {
                t.tick();
                app.next();
            }
            ("cancel", Some(t)) => {
                t.cancel();
                t.tick();
                while !finished.get() {
                    app.next();
                }
            }
            ("quit", _) => {
                if let Some(t) = task.take() {
                    t.cancel();
                    t.join();
                }
            }
            _ => println!("C: idle, no job"),
        }
        if finished.get() {
            task.take().unwrap().join();
            finished.set(false);
        }
    }
    println!("C: joined");
}

fn main() {
    part_a();
    part_b();
    part_c();
}
