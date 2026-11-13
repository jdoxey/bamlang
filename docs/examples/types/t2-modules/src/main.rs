// Built-in stand-ins (counted separately; not user code, and allowed to use generics).
mod builtin {
    #![allow(dead_code)]
    // STAND-IN for the built-in `Pool of T`: slots with generation-checked handles.
    #[derive(Clone, Copy, PartialEq, Eq, Debug)]
    pub struct Handle { idx: usize, generation: u32 }

    pub struct Pool<T> { slots: Vec<(u32, Option<T>)> }

    impl<T> Pool<T> {
        pub fn new() -> Pool<T> { Pool { slots: Vec::new() } }
        pub fn insert(&mut self, v: T) -> Handle {
            for (i, s) in self.slots.iter_mut().enumerate() {
                if s.1.is_none() {
                    s.0 += 1;
                    s.1 = Some(v);
                    return Handle { idx: i, generation: s.0 };
                }
            }
            self.slots.push((0, Some(v)));
            Handle { idx: self.slots.len() - 1, generation: 0 }
        }
        pub fn get(&self, h: Handle) -> Option<&T> {
            match self.slots.get(h.idx) {
                Some((g, Some(v))) if *g == h.generation => Some(v),
                _ => None,
            }
        }
        pub fn get_mut(&mut self, h: Handle) -> Option<&mut T> {
            match self.slots.get_mut(h.idx) {
                Some((g, Some(v))) if *g == h.generation => Some(v),
                _ => None,
            }
        }
        pub fn remove(&mut self, h: Handle) -> Option<T> {
            match self.slots.get_mut(h.idx) {
                Some((g, slot)) if *g == h.generation => slot.take(),
                _ => None,
            }
        }
    }
}

// One module per type. A `dyn` value exists only as an entry of a `Pool of dyn T`, reached by handle.
mod core {
    use crate::builtin::{Handle, Pool};

    // interface Shape (a module declares `is Shape`; checked nominally)
    pub trait Shape {
        fn name(&self) -> &'static str;
        fn area(&self) -> f64;
    }
    // interface Widget; `close` takes self (it is removed from the pool first).
    pub trait Widget {
        fn render_line(&self) -> String;
        fn children(&self) -> Vec<Handle>;
        fn detach(&mut self, child: Handle);
        fn event(&mut self, ev: Event) -> String;
        fn close(self: Box<Self>, pool: &mut WidgetPool) -> String; // RUST-ONLY: Box<Self> receiver spells `take self` on a dyn
    }
    #[derive(Clone, Copy)]
    pub enum Event { Click, Drag(i32), Close }

    pub type ShapePool = Pool<Box<dyn Shape>>; // `Pool of dyn Shape`
    pub type WidgetPool = Pool<Box<dyn Widget>>; // `Pool of dyn Widget`

    // Default focus behaviour: one plain function that each implementation calls.
    pub fn focus_next() -> &'static str { "focus moves to next" }

    // Walk the tree through handles and apply the event to the target widget.
    pub fn render(pool: &WidgetPool, h: Handle, depth: usize) -> String {
        let w = pool.get(h).unwrap();
        let mut out = format!("{}{}\n", "  ".repeat(depth + 1), w.render_line());
        for c in w.children() { out.push_str(&render(pool, c, depth + 1)); }
        out
    }
    pub fn dispatch(pool: &mut WidgetPool, root: Handle, path: &[usize], ev: Event) -> String {
        let mut parent = None;
        let mut cur = root;
        for idx in path {
            match pool.get(cur).unwrap().children().get(*idx) {
                Some(k) => { parent = Some(cur); cur = *k; }
                None => return "no such widget".to_string(),
            }
        }
        match (ev, parent) {
            (Event::Close, Some(p)) => {
                pool.get_mut(p).unwrap().detach(cur);
                let w = pool.remove(cur).unwrap(); // take
                format!("consumed {}; {}", w.close(pool), focus_next())
            }
            (Event::Close, None) => "ignored".to_string(),
            _ => pool.get_mut(cur).unwrap().event(ev),
        }
    }

    pub mod circle {
        use super::Shape;
        pub struct Circle { r: f64 }
        impl Circle {
            pub fn new(r: f64) -> Result<Circle, String> {
                if r > 0.0 { Ok(Circle { r }) } else { Err(format!("bad radius {}", r)) }
            }
        }
        impl Shape for Circle {
            fn name(&self) -> &'static str { "circle" }
            fn area(&self) -> f64 { std::f64::consts::PI * self.r * self.r }
        }
    }

    pub mod rect {
        use super::Shape;
        pub struct Rect { w: f64, h: f64 }
        impl Rect {
            pub fn new(w: f64, h: f64) -> Result<Rect, String> {
                if w > 0.0 && h > 0.0 { Ok(Rect { w, h }) } else { Err(format!("bad size {}x{}", w, h)) }
            }
        }
        impl Shape for Rect {
            fn name(&self) -> &'static str { "rect" }
            fn area(&self) -> f64 { self.w * self.h }
        }
    }

    pub mod button {
        use super::{focus_next, Event, Handle, Widget, WidgetPool};
        pub struct Button { label: String }
        impl Button {
            pub fn new(label: &str) -> Result<Button, String> {
                if label.is_empty() { Err("empty label".to_string()) } else { Ok(Button { label: label.to_string() }) }
            }
        }
        impl Widget for Button {
            fn render_line(&self) -> String { format!("Button {}", self.label) }
            fn children(&self) -> Vec<Handle> { Vec::new() }
            fn detach(&mut self, _child: Handle) {}
            fn event(&mut self, ev: Event) -> String {
                match ev {
                    Event::Click => format!("pressed {}; {}", self.label, focus_next()),
                    _ => "ignored".to_string(),
                }
            }
            fn close(self: Box<Self>, _pool: &mut WidgetPool) -> String { format!("Button {}", self.label) } // RUST-ONLY: Box<Self>
        }
    }

    pub mod panel {
        use super::{Event, Handle, Widget, WidgetPool};
        pub struct Panel { children: Vec<Handle> }
        impl Panel {
            pub fn new(children: Vec<Handle>) -> Panel { Panel { children } }
        }
        impl Widget for Panel {
            fn render_line(&self) -> String { "Panel".to_string() }
            fn children(&self) -> Vec<Handle> { self.children.clone() }
            fn detach(&mut self, child: Handle) { self.children.retain(|c| *c != child); }
            fn event(&mut self, _ev: Event) -> String { "ignored".to_string() }
            fn close(self: Box<Self>, pool: &mut WidgetPool) -> String { // RUST-ONLY: Box<Self>
                let mut parts = Vec::new();
                for c in &self.children { parts.push(pool.remove(*c).unwrap().close(pool)); }
                format!("Panel[{}]", parts.join(", "))
            }
        }
    }

    // ---- B3 (identical in all three options) ----
    pub mod money {
        #[derive(Clone, Copy)]
        pub struct Money(i64); // private field: only this module can write a Money literal
        impl Money {
            pub fn new(cents: i64) -> Result<Money, String> {
                if cents < 0 { Err(format!("negative money {}", cents)) } else { Ok(Money(cents)) }
            }
            pub fn cents(self) -> i64 { self.0 }
            pub fn plus(self, o: Money) -> Money { Money(self.0 + o.0) }
            pub fn minus(self, o: Money) -> Option<Money> {
                if o.0 > self.0 { None } else { Some(Money(self.0 - o.0)) }
            }
        }
    }

    pub mod account {
        use super::money::Money;
        use crate::builtin::{Handle, Pool};

        pub struct Account { owner: String, balance: Money }

        impl Account {
            pub fn new(owner: &str, balance: Money) -> Result<Account, String> {
                if owner.is_empty() { return Err("empty owner".to_string()); }
                Ok(Account { owner: owner.to_string(), balance })
            }
            pub fn owner(&self) -> &str { &self.owner }
            pub fn balance(&self) -> Money { self.balance }
            pub fn deposit(&mut self, m: Money) { self.balance = self.balance.plus(m); }
            pub fn withdraw(&mut self, m: Money) -> Result<(), String> {
                match self.balance.minus(m) {
                    Some(b) => { self.balance = b; Ok(()) }
                    None => Err(format!("insufficient funds: balance {}, need {}", self.balance.cents(), m.cents())),
                }
            }
        }

        fn missing() -> String { "no such account".to_string() }

        // A method of `Pool of Account`.
        impl Pool<Account> {
            pub fn transfer(&mut self, a: Handle, b: Handle, m: Money) -> Result<(), String> {
                if self.get(b).is_none() { return Err(missing()); }
                self.get_mut(a).ok_or_else(missing)?.withdraw(m)?;
                self.get_mut(b).ok_or_else(missing)?.deposit(m);
                Ok(())
            }
        }
    }
}

// The plugin cannot edit `core`; it only adds modules that declare `is Shape` / `is Widget`.
mod plugin {
    // BEGIN hexagon
    pub mod hexagon {
        use crate::core::Shape;
        pub struct Hexagon { side: f64 }
        impl Hexagon {
            pub fn new(side: f64) -> Result<Hexagon, String> {
                if side > 0.0 { Ok(Hexagon { side }) } else { Err(format!("bad side {}", side)) }
            }
        }
        impl Shape for Hexagon {
            fn name(&self) -> &'static str { "hexagon" }
            fn area(&self) -> f64 { 3.0 * 3f64.sqrt() / 2.0 * self.side * self.side }
        }
    }
    // END hexagon

    // BEGIN slider
    pub mod slider {
        use crate::builtin::Handle;
        use crate::core::{focus_next, Event, Widget, WidgetPool};
        pub struct Slider { value: i32, max: i32 }
        impl Slider {
            pub fn new(value: i32, max: i32) -> Result<Slider, String> {
                if value < 0 || value > max { Err("slider out of range".to_string()) } else { Ok(Slider { value, max }) }
            }
        }
        impl Widget for Slider {
            fn render_line(&self) -> String { format!("Slider {}/{}", self.value, self.max) }
            fn children(&self) -> Vec<Handle> { Vec::new() }
            fn detach(&mut self, _child: Handle) {}
            fn event(&mut self, ev: Event) -> String {
                match ev {
                    Event::Drag(d) => {
                        let old = self.value;
                        self.value = (old + d).clamp(0, self.max);
                        format!("value {} -> {}; {}", old, self.value, focus_next())
                    }
                    _ => "ignored".to_string(),
                }
            }
            fn close(self: Box<Self>, _pool: &mut WidgetPool) -> String { format!("Slider {}/{}", self.value, self.max) } // RUST-ONLY: Box<Self>
        }
    }
    // END slider
}

mod adversary {
    use crate::builtin::{Handle, Pool};
    use crate::core::account::Account;
    use crate::core::money::Money;

    // Returns how many attempts were refused. The ATTACK lines are enabled only in scratch copies.
    pub fn run(pool: &mut Pool<Account>, h: Handle) -> usize {
        let mut refused = 0;
        if Money::new(-5).is_err() { refused += 1; }
        // ATTACK1: let _m = Money(-5);
        // ATTACK2: pool.get_mut(h).unwrap().balance = Money::new(1_000_000).unwrap();
        // ATTACK3: pool.get_mut(h).unwrap().withdraw(Money::new(1).unwrap());
        if pool.get_mut(h).unwrap().withdraw(Money::new(10_000_000).unwrap()).is_err() { refused += 1; }
        refused
    }
}

use crate::builtin::Pool;
use crate::core::button::Button;
use crate::core::circle::Circle;
use crate::core::panel::Panel;
use crate::core::rect::Rect;
use crate::core::{dispatch, render, Event, ShapePool, WidgetPool};
use plugin::hexagon::Hexagon;
use plugin::slider::Slider;

fn b1() -> Result<(), String> {
    let mut pool: ShapePool = Pool::new();
    let handles = vec![
        pool.insert(Box::new(Circle::new(1.0)?)),
        pool.insert(Box::new(Hexagon::new(2.0)?)),
        pool.insert(Box::new(Rect::new(2.0, 3.0)?)),
        pool.insert(Box::new(Hexagon::new(1.0)?)),
        pool.insert(Box::new(Circle::new(2.0)?)),
    ];
    let mut total = 0.0;
    for h in &handles {
        let s = pool.get(*h).unwrap(); // dynamic call: pool[h].area()
        println!("{} {:.2}", s.name(), s.area());
        total += s.area();
    }
    println!("total {:.2}", total);
    Ok(())
}

fn b2() -> Result<(), String> {
    let mut pool: WidgetPool = Pool::new();
    let ok = pool.insert(Box::new(Button::new("OK")?));
    let slider = pool.insert(Box::new(Slider::new(3, 10)?));
    let cancel = pool.insert(Box::new(Button::new("Cancel")?));
    let inner = pool.insert(Box::new(Panel::new(vec![cancel])));
    let root = pool.insert(Box::new(Panel::new(vec![ok, slider, inner])));
    println!("build");
    print!("{}", render(&pool, root, 0));
    let events: Vec<(&str, Vec<usize>, Event)> = vec![
        ("click OK", vec![0], Event::Click),
        ("drag Slider +4", vec![1], Event::Drag(4)),
        ("click Cancel", vec![2, 0], Event::Click),
        ("close inner panel", vec![2], Event::Close),
    ];
    for (label, path, ev) in events {
        println!("{}: {}", label, dispatch(&mut pool, root, &path, ev)); // dynamic call inside dispatch
        print!("{}", render(&pool, root, 0));
    }
    assert!(pool.get(inner).is_none() && pool.get(cancel).is_none()); // stale handles are caught
    Ok(())
}

fn b3() -> Result<(), String> {
    use crate::builtin::Pool;
    use crate::core::account::Account;
    use crate::core::money::Money;
    let mut pool: Pool<Account> = Pool::new();
    let alice = pool.insert(Account::new("alice", Money::new(100)?)?);
    let bob = pool.insert(Account::new("bob", Money::new(50)?)?);
    pool.get_mut(alice).unwrap().deposit(Money::new(25)?);
    println!("deposit alice 25");
    pool.transfer(alice, bob, Money::new(75)?)?;
    println!("transfer alice -> bob 75");
    match pool.get_mut(bob).unwrap().withdraw(Money::new(200)?) {
        Ok(()) => println!("withdraw bob 200 ok"),
        Err(e) => println!("withdraw bob 200 failed: {}", e),
    }
    assert_eq!(adversary::run(&mut pool, alice), 2);
    for h in [alice, bob] {
        let a = pool.get(h).unwrap();
        println!("{}: {}", a.owner(), a.balance().cents());
    }
    Ok(())
}

fn main() -> Result<(), String> {
    println!("== B1 shapes ==");
    b1()?;
    println!("== B2 widgets ==");
    b2()?;
    println!("== B3 accounts ==");
    b3()
}
