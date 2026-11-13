// D3 benchmark, model F1: Crew (scoped threads that own the cancel token and channel endpoints).
use std::any::Any;
use std::cell::Cell;
use std::io::Read;
use std::ops::{Deref, DerefMut};
use std::panic::{self, AssertUnwindSafe, Location, catch_unwind, resume_unwind};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread::{self, Scope};
use std::time::{Duration, Instant};

// ---- MODEL: stands in for a built-in `crew`, `Lock` and channels ----
/// Cancel token. A child's token also reports its parent (the crew's) token.
#[derive(Clone)]
pub struct Token {
    me: Arc<AtomicBool>,
    parent: Option<Arc<AtomicBool>>,
}
impl Token {
    fn root() -> Token {
        Token { me: Arc::new(AtomicBool::new(false)), parent: None }
    }
    fn child(&self) -> Token {
        Token { me: Arc::new(AtomicBool::new(false)), parent: Some(self.me.clone()) }
    }
    pub fn cancelled(&self) -> bool {
        self.me.load(Ordering::SeqCst) || self.parent.as_ref().is_some_and(|p| p.load(Ordering::SeqCst))
    }
    fn cancel(&self) {
        self.me.store(true, Ordering::SeqCst);
    }
    /// `c.check()`: a cancellation point for CPU loops. Exits the child as "cancelled" (not an error).
    pub fn check(&self) {
        if self.cancelled() {
            resume_unwind(Box::new(Cancelled));
        }
    }
}

/// Marker payload: a child that left because it was cancelled. Filtered out of error reports.
struct Cancelled;
type Payload = Box<dyn Any + Send>;

/// Returned by `go`; cancels exactly that job.
pub struct JobHandle(Token);
impl JobHandle {
    pub fn cancel(&self) {
        self.0.cancel();
    }
}

pub struct Crew<'scope, 'env: 'scope> {
    scope: &'scope Scope<'scope, 'env>,
    root: Token,
    errs: Arc<Mutex<Vec<Payload>>>,
}

impl<'scope, 'env> Crew<'scope, 'env> {
    /// Cancel every child of the crew.
    pub fn cancel_all(&self) {
        self.root.cancel();
    }
    /// Start a child (moving closure). A real failure cancels the siblings and is reported when the
    /// crew ends; a cancellation exit is filtered.
    pub fn go<F: FnOnce(&Token) + Send + 'scope>(&self, f: F) -> JobHandle {
        let tok = self.root.child();
        let handle = JobHandle(tok.clone());
        let root = self.root.clone();
        let errs = self.errs.clone();
        self.scope.spawn(move || {
            if let Err(p) = catch_unwind(AssertUnwindSafe(|| f(&tok))) {
                if !p.is::<Cancelled>() {
                    root.cancel();
                    errs.lock().unwrap().push(p);
                }
            }
        });
        handle
    }
    /// Owned channel endpoints; dropping the last sender closes.
    pub fn channel<T>(&self) -> (Tx<T>, Rx<T>) {
        let (tx, rx) = mpsc::channel();
        (Tx(tx), Rx(Arc::new(Mutex::new(rx))))
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

fn message(p: &Payload) -> String {
    if let Some(s) = p.downcast_ref::<String>() {
        s.clone()
    } else if let Some(s) = p.downcast_ref::<&str>() {
        s.to_string()
    } else {
        "child failed".to_string()
    }
}

fn run_crew<'env, R>(body: impl for<'scope> FnOnce(&Crew<'scope, 'env>) -> R, early: fn(&R) -> bool) -> R {
    let root = Token::root();
    let errs: Arc<Mutex<Vec<Payload>>> = Arc::new(Mutex::new(Vec::new()));
    // Early exit (error, panic) cancels first; `thread::scope` then joins every child.
    let out = thread::scope(|s| {
        let c = Crew { scope: s, root: root.clone(), errs: errs.clone() };
        let r = catch_unwind(AssertUnwindSafe(|| body(&c)));
        if r.as_ref().map_or(true, early) {
            root.cancel();
        }
        r
    });
    match out {
        Err(p) => resume_unwind(p), // the parent's error wins
        Ok(r) => {
            let mut errs = errs.lock().unwrap();
            if errs.is_empty() {
                return r;
            }
            let first = errs.remove(0);
            match errs.len() {
                0 => resume_unwind(first),
                n => panic::panic_any(format!("{} (plus {n} more)", message(&first))),
            }
        }
    }
}

/// Run `body` as the crew's owner; joins every child, then re-raises the first real child error.
pub fn crew<'env, R>(body: impl for<'scope> FnOnce(&Crew<'scope, 'env>) -> R) -> R {
    run_crew(body, |_| false)
}

/// Like `crew`, but a body that returns `Err` is an early exit: cancel, then join.
pub fn crew_try<'env, T, E>(body: impl for<'scope> FnOnce(&Crew<'scope, 'env>) -> Result<T, E>) -> Result<T, E> {
    run_crew(body, |r| r.is_err())
}

// Lock rule: a thread holding a user lock may not take another or make a blocking call.
thread_local! {
    static HELD: Cell<Option<&'static Location<'static>>> = const { Cell::new(None) };
}

fn blocking_site(site: &'static Location<'static>) {
    if let Some(held) = HELD.with(|h| h.get()) {
        panic!("TRAP: blocking call while holding lock at {site} (lock taken at {held})");
    }
}

pub struct Lock<T>(Mutex<T>);
pub struct LockGuard<'a, T>(MutexGuard<'a, T>);
impl<T> Lock<T> {
    pub fn new(v: T) -> Self {
        Lock(Mutex::new(v))
    }
    #[track_caller]
    pub fn lock(&self) -> LockGuard<'_, T> {
        let site = Location::caller();
        blocking_site(site);
        let g = self.0.lock().unwrap_or_else(|e| e.into_inner());
        HELD.with(|h| h.set(Some(site)));
        LockGuard(g)
    }
    pub fn into_inner(self) -> T {
        self.0.into_inner().unwrap_or_else(|e| e.into_inner())
    }
}
impl<T> Drop for LockGuard<'_, T> {
    fn drop(&mut self) {
        HELD.with(|h| h.set(None));
    }
}
impl<T> Deref for LockGuard<'_, T> {
    type Target = T;
    fn deref(&self) -> &T {
        &self.0
    }
}
impl<T> DerefMut for LockGuard<'_, T> {
    fn deref_mut(&mut self) -> &mut T {
        &mut self.0
    }
}

/// Sender (non-blocking, unbounded: not a blocking call).
pub struct Tx<T>(Sender<T>);
impl<T> Clone for Tx<T> {
    fn clone(&self) -> Self {
        Tx(self.0.clone())
    }
}
impl<T> Tx<T> {
    pub fn send(&self, v: T) -> Result<(), mpsc::SendError<T>> {
        self.0.send(v)
    }
}
/// Receiver; clonable so several workers can take jobs (std's mpsc has one consumer, so the
/// model hides a leaf mutex inside; that is a stdlib leaf lock and exempt from the rule).
pub struct Rx<T>(Arc<Mutex<Receiver<T>>>);
impl<T> Clone for Rx<T> {
    fn clone(&self) -> Self {
        Rx(self.0.clone())
    }
}
impl<T> Rx<T> {
    /// Blocking; `None` when closed.
    #[track_caller]
    pub fn recv(&self) -> Option<T> {
        blocking_site(Location::caller());
        self.0.lock().unwrap().recv().ok()
    }
    pub fn try_recv(&self) -> Option<T> {
        self.0.lock().unwrap().try_recv().ok()
    }
}

#[track_caller]
pub fn sleep(d: Duration) {
    blocking_site(Location::caller());
    thread::sleep(d);
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
fn bump(counter: &Lock<u32>) {
    *counter.lock() += 1;
}

fn part_b() {
    let counter = Lock::new(0u32);
    let counter_ref = &counter;
    let total: u32 = crew(|c| {
        let (jtx, jrx) = c.channel::<u32>();
        let (rtx, rrx) = c.channel::<u32>();
        for _ in 0..4 {
            let rtx = rtx.clone();
            let jrx = jrx.clone();
            c.go(move |_| {
                while let Some(n) = jrx.recv() {
                    bump(counter_ref);
                    rtx.send(n * n).expect("collector gone");
                }
            });
        }
        drop(rtx);
        drop(jrx);
        for n in 1..=20 {
            jtx.send(n).unwrap();
        }
        drop(jtx);
        let mut sum = 0;
        while let Some(v) = rrx.recv() {
            sum += v;
        }
        sum
    });
    println!("B: total={total} counter={}", counter.into_inner());
}

// ---- PART C ----
enum Msg {
    Progress(u32),
    Cancelled { step: u32, partial: Vec<u32> },
    Done(Vec<u32>),
}

fn job(tok: &Token, partial: &Lock<Vec<u32>>, tx: Tx<Msg>, ack: Rx<()>) {
    for k in 1..=10 {
        if tok.cancelled() {
            let p = partial.lock().clone();
            let _ = tx.send(Msg::Cancelled { step: k - 1, partial: p });
            return;
        }
        partial.lock().push(k);
        let _ = tx.send(Msg::Progress(k));
        if ack.recv().is_none() {
            return;
        }
    }
    let p = partial.lock().clone();
    let _ = tx.send(Msg::Done(p));
}

struct App<'env> {
    partial: &'env Lock<Vec<u32>>,
    tx: Tx<Msg>,
    rx: Rx<Msg>,
    live: Option<(JobHandle, Tx<()>)>,
}

impl<'env> App<'env> {
    /// Drain with `try_recv` until the job's reply for this step arrives (the tick handshake
    /// guarantees exactly one). Returns true when the job has finished.
    fn pump(&self) -> bool {
        loop {
            match self.rx.try_recv() {
                Some(Msg::Progress(k)) => {
                    println!("C: progress {k}");
                    return false;
                }
                Some(Msg::Cancelled { step, partial }) => {
                    println!("C: cancelled at step {step}, partial = {partial:?}");
                    return true;
                }
                Some(Msg::Done(partial)) => {
                    println!("C: done, partial = {partial:?}");
                    return true;
                }
                None => sleep(Duration::from_millis(1)),
            }
        }
    }

    /// The handler gets `c` for this call only.
    fn on_event(&mut self, c: &Crew<'_, 'env>, ev: &str) {
        println!("C: event {ev}");
        match (ev, &self.live) {
            ("start", None) => {
                let (atx, arx) = c.channel();
                let (tx, partial) = (self.tx.clone(), self.partial);
                let handle = c.go(move |t| job(t, partial, tx, arx));
                self.pump();
                self.live = Some((handle, atx));
            }
            ("tick", Some((_, ack))) => {
                let _ = ack.send(());
                if self.pump() {
                    self.live = None;
                }
            }
            ("cancel", Some((handle, ack))) => {
                handle.cancel(); // this job only
                let _ = ack.send(());
                while !self.pump() {}
                self.live = None;
            }
            ("quit", _) => {
                c.cancel_all();
                self.live = None; // drops the ack sender so a waiting job exits
            }
            _ => println!("C: idle, no job"),
        }
    }
}

fn app_run<'env>(c: &Crew<'_, 'env>, partial: &'env Lock<Vec<u32>>, events: &[&str]) {
    let (tx, rx) = c.channel();
    let mut app = App { partial, tx, rx, live: None };
    for ev in events {
        app.on_event(c, ev);
    }
}

fn part_c() {
    let events = ["start", "tick", "tick", "tick", "cancel", "tick", "tick", "quit"];
    let partial = Lock::new(Vec::new());
    crew(|c| app_run(c, &partial, &events));
    println!("C: joined");
}

// ---- SELFTEST ----
fn silently<R>(f: impl FnOnce() -> R) -> R {
    panic::set_hook(Box::new(|_| {}));
    let r = f();
    let _ = panic::take_hook();
    r
}

fn run_trap_child(mode: &str) -> Result<String, String> {
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let mut child = Command::new(exe)
        .arg(mode)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| e.to_string())?;
    let start = Instant::now();
    let status = loop {
        if let Some(s) = child.try_wait().map_err(|e| e.to_string())? {
            break s;
        }
        if start.elapsed() > Duration::from_secs(10) {
            let _ = child.kill();
            return Err(format!("{mode}: hung"));
        }
        thread::sleep(Duration::from_millis(10));
    };
    let mut out = String::new();
    child.stdout.take().unwrap().read_to_string(&mut out).map_err(|e| e.to_string())?;
    if status.success() {
        return Err(format!("{mode}: child exited cleanly"));
    }
    Ok(out)
}

fn selftest() -> Result<(), String> {
    // 1. two failing children: first error plus "plus 1 more".
    let r = silently(|| {
        catch_unwind(AssertUnwindSafe(|| {
            crew(|c| {
                c.go(|_| panic!("boom"));
                c.go(|_| panic!("bang"));
            })
        }))
    });
    let msg = message(&r.err().ok_or("no error re-raised")?);
    if !msg.contains("plus 1 more") {
        return Err(format!("aggregate message was {msg:?}"));
    }
    println!("selftest ok: two failures -> {msg:?}");

    // 2. a cancellation-caused exit is not reported; only the real error is.
    let r = silently(|| {
        catch_unwind(AssertUnwindSafe(|| {
            crew(|c| {
                c.go(|t| loop {
                    t.check();
                    thread::yield_now();
                });
                c.go(|_| panic!("real"));
            })
        }))
    });
    let msg = message(&r.err().ok_or("no error re-raised")?);
    if msg != "real" {
        return Err(format!("cancelled child leaked into report: {msg:?}"));
    }
    println!("selftest ok: cancelled child filtered -> {msg:?}");

    // 3. early return from the body cancels, then joins, the siblings.
    let seen = AtomicBool::new(false);
    let seen_ref = &seen;
    let r: Result<(), &str> = crew_try(|c| {
        let (tx, rx) = c.channel::<()>();
        c.go(move |t| {
            let _ = tx.send(());
            while !t.cancelled() {
                thread::yield_now();
            }
            seen_ref.store(true, Ordering::SeqCst);
        });
        rx.recv();
        Err("early")
    });
    if r != Err("early") || !seen.load(Ordering::SeqCst) {
        return Err("early exit did not cancel and join the sibling".into());
    }
    println!("selftest ok: early exit cancelled and joined the sibling");

    // 4. a handle cancels only its own job.
    let (a, b) = (AtomicBool::new(false), AtomicBool::new(false));
    let (a, b) = (&a, &b);
    crew(|c| {
        let h1 = c.go(move |t| {
            while !t.cancelled() {
                thread::yield_now();
            }
            a.store(true, Ordering::SeqCst);
        });
        let h2 = c.go(move |t| {
            while !t.cancelled() {
                thread::yield_now();
            }
            b.store(true, Ordering::SeqCst);
        });
        h1.cancel();
        while !a.load(Ordering::SeqCst) {
            sleep(Duration::from_millis(1));
        }
        sleep(Duration::from_millis(20));
        assert!(!b.load(Ordering::SeqCst), "job 2 was cancelled by job 1's handle");
        h2.cancel();
    });
    println!("selftest ok: handle.cancel() cancels only its job");

    // 5, 6. lock rule traps (child process so a hang would show as a timeout).
    for (mode, what) in [("--trap-relock", "re-lock in helper"), ("--trap-recv", "recv while holding")] {
        let out = run_trap_child(mode)?;
        if !out.contains("TRAP:") {
            return Err(format!("{mode}: no TRAP in {out:?}"));
        }
        println!("selftest ok: {what} -> {}", out.lines().find(|l| l.contains("TRAP:")).unwrap_or(""));
    }
    Ok(())
}

fn trap_child(mode: &str) {
    panic::set_hook(Box::new(|info| println!("{info}")));
    let m = Lock::new(0u32);
    let _held = m.lock();
    if mode == "--trap-relock" {
        bump(&m); // a helper that locks again: traps instead of hanging
    } else {
        let (tx, rx) = mpsc::channel::<u32>();
        let rx = Rx(Arc::new(Mutex::new(rx)));
        rx.recv(); // would block forever (tx alive): traps instead
        drop(tx);
    }
}

// ---- MAIN ----
fn main() {
    match std::env::args().nth(1).as_deref() {
        Some("--selftest") => {
            if let Err(e) = selftest() {
                eprintln!("selftest FAILED: {e}");
                std::process::exit(1);
            }
        }
        Some(m @ ("--trap-relock" | "--trap-recv")) => trap_child(m),
        _ => {
            part_a();
            part_b();
            part_c();
        }
    }
}
