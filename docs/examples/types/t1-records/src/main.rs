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

    // `dyn Shape(x)` / `dyn Widget(x)`: box x and fill the interface record from x's methods.
    // STAND-IN for the compiler; the rule "dyn values are made only here" is by convention in Rust.
    pub fn dyn_shape<S: Shape + 'static>(x: S) -> Box<dyn Shape> { Box::new(x) } // RUST-ONLY: generic + 'static
    pub fn dyn_widget<W: Widget + 'static>(x: W) -> Box<dyn Widget> { Box::new(x) } // RUST-ONLY: generic + 'static

    // A hand-written record: the interface Shape written out as a record of closures.
    pub struct ShapeRec { pub name: Box<dyn Fn() -> &'static str>, pub area: Box<dyn Fn() -> f64> }
    impl Shape for ShapeRec { // RUST-ONLY: a record IS a dyn Shape in the design
        fn name(&self) -> &'static str { (self.name)() } // RUST-ONLY
        fn area(&self) -> f64 { (self.area)() } // RUST-ONLY
    } // RUST-ONLY
    use crate::core::{Shape, Widget};
}

// The core defines the interfaces and the closed built-in kinds.
mod core {
    // iface Shape { name, area }
    pub trait Shape {
        fn name(&self) -> &'static str;
        fn area(&self) -> f64;
    }
    // iface Widget { render, event, close }; `close` takes self.
    pub trait Widget {
        fn render(&self, depth: usize) -> String;
        fn event(&mut self, path: &[usize], ev: Event) -> String;
        fn close(self: Box<Self>) -> String; // RUST-ONLY: Box<Self> receiver spells `take self` through a dyn
    }
    #[derive(Clone, Copy)]
    pub enum Event { Click, Drag(i32), Close }

    // Default focus behaviour: one plain function that each implementation calls.
    pub fn focus_next() -> &'static str { "focus moves to next" }
    pub fn indent(depth: usize) -> String { "  ".repeat(depth + 1) }

    pub mod circle {
        use super::Shape;
        pub struct Circle { r: f64 }
        impl Circle {
            pub fn new(r: f64) -> Result<Circle, String> {
                if r > 0.0 { Ok(Circle { r }) } else { Err(format!("bad radius {}", r)) }
            }
            pub fn name(&self) -> &'static str { "circle" }
            pub fn area(&self) -> f64 { std::f64::consts::PI * self.r * self.r }
        }
        impl Shape for Circle { // RUST-ONLY: shim the compiler would fill at `dyn Shape(x)`
            fn name(&self) -> &'static str { Circle::name(self) } // RUST-ONLY
            fn area(&self) -> f64 { Circle::area(self) } // RUST-ONLY
        } // RUST-ONLY
    }

    pub mod rect {
        use super::Shape;
        pub struct Rect { w: f64, h: f64 }
        impl Rect {
            pub fn new(w: f64, h: f64) -> Result<Rect, String> {
                if w > 0.0 && h > 0.0 { Ok(Rect { w, h }) } else { Err(format!("bad size {}x{}", w, h)) }
            }
            pub fn name(&self) -> &'static str { "rect" }
            pub fn area(&self) -> f64 { self.w * self.h }
        }
        impl Shape for Rect { // RUST-ONLY: shim
            fn name(&self) -> &'static str { Rect::name(self) } // RUST-ONLY
            fn area(&self) -> f64 { Rect::area(self) } // RUST-ONLY
        } // RUST-ONLY
    }

    pub mod button {
        use super::{focus_next, indent, Event, Widget};
        pub struct Button { label: String }
        impl Button {
            pub fn new(label: &str) -> Result<Button, String> {
                if label.is_empty() { Err("empty label".to_string()) } else { Ok(Button { label: label.to_string() }) }
            }
            pub fn render(&self, depth: usize) -> String { format!("{}Button {}\n", indent(depth), self.label) }
            pub fn event(&mut self, _path: &[usize], ev: Event) -> String {
                match ev {
                    Event::Click => format!("pressed {}; {}", self.label, focus_next()),
                    _ => "ignored".to_string(),
                }
            }
            pub fn close(self) -> String { format!("Button {}", self.label) }
        }
        impl Widget for Button { // RUST-ONLY: shim
            fn render(&self, depth: usize) -> String { Button::render(self, depth) } // RUST-ONLY
            fn event(&mut self, path: &[usize], ev: Event) -> String { Button::event(self, path, ev) } // RUST-ONLY
            fn close(self: Box<Self>) -> String { Button::close(*self) } // RUST-ONLY
        } // RUST-ONLY
    }

    pub mod panel {
        use super::{focus_next, indent, Event, Widget};
        pub struct Panel { children: Vec<Box<dyn Widget>> }
        impl Panel {
            pub fn new(children: Vec<Box<dyn Widget>>) -> Panel { Panel { children } }
            pub fn render(&self, depth: usize) -> String {
                let mut out = format!("{}Panel\n", indent(depth));
                for c in &self.children { out.push_str(&c.render(depth + 1)); }
                out
            }
            pub fn event(&mut self, path: &[usize], ev: Event) -> String {
                match (path, ev) {
                    ([], _) => "ignored".to_string(),
                    ([i], Event::Close) if *i < self.children.len() => {
                        let c = self.children.remove(*i);
                        format!("consumed {}; {}", c.close(), focus_next())
                    }
                    ([i, rest @ ..], _) => match self.children.get_mut(*i) {
                        Some(c) => c.event(rest, ev),
                        None => "no such widget".to_string(),
                    },
                }
            }
            pub fn close(self) -> String {
                let parts: Vec<String> = self.children.into_iter().map(|c| c.close()).collect();
                format!("Panel[{}]", parts.join(", "))
            }
        }
        impl Widget for Panel { // RUST-ONLY: shim
            fn render(&self, depth: usize) -> String { Panel::render(self, depth) } // RUST-ONLY
            fn event(&mut self, path: &[usize], ev: Event) -> String { Panel::event(self, path, ev) } // RUST-ONLY
            fn close(self: Box<Self>) -> String { Panel::close(*self) } // RUST-ONLY
        } // RUST-ONLY
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

// The plugin cannot edit `core`; it only uses its public items.
mod plugin {
    // BEGIN hexagon
    pub mod hexagon {
        use crate::core::Shape;
        pub struct Hexagon { side: f64 }
        impl Hexagon {
            pub fn new(side: f64) -> Result<Hexagon, String> {
                if side > 0.0 { Ok(Hexagon { side }) } else { Err(format!("bad side {}", side)) }
            }
            pub fn name(&self) -> &'static str { "hexagon" }
            pub fn area(&self) -> f64 { 3.0 * 3f64.sqrt() / 2.0 * self.side * self.side }
        }
        impl Shape for Hexagon { // RUST-ONLY: shim
            fn name(&self) -> &'static str { Hexagon::name(self) } // RUST-ONLY
            fn area(&self) -> f64 { Hexagon::area(self) } // RUST-ONLY
        } // RUST-ONLY
    }
    // END hexagon

    // BEGIN byhand
    // The same interface written by hand: a record of closures, no Hexagon type at all.
    pub fn hexagon_by_hand(side: f64) -> Result<crate::builtin::ShapeRec, String> {
        if side <= 0.0 { return Err(format!("bad side {}", side)); }
        Ok(crate::builtin::ShapeRec {
            name: Box::new(|| "hexagon"),
            area: Box::new(move || 3.0 * 3f64.sqrt() / 2.0 * side * side),
        })
    }
    // END byhand

    // BEGIN slider
    pub mod slider {
        use crate::core::{focus_next, indent, Event, Widget};
        pub struct Slider { value: i32, max: i32 }
        impl Slider {
            pub fn new(value: i32, max: i32) -> Result<Slider, String> {
                if value < 0 || value > max { Err("slider out of range".to_string()) } else { Ok(Slider { value, max }) }
            }
            pub fn render(&self, depth: usize) -> String { format!("{}Slider {}/{}\n", indent(depth), self.value, self.max) }
            pub fn event(&mut self, _path: &[usize], ev: Event) -> String {
                match ev {
                    Event::Drag(d) => {
                        let old = self.value;
                        self.value = (old + d).clamp(0, self.max);
                        format!("value {} -> {}; {}", old, self.value, focus_next())
                    }
                    _ => "ignored".to_string(),
                }
            }
            pub fn close(self) -> String { format!("Slider {}/{}", self.value, self.max) }
        }
        impl Widget for Slider { // RUST-ONLY: shim
            fn render(&self, depth: usize) -> String { Slider::render(self, depth) } // RUST-ONLY
            fn event(&mut self, path: &[usize], ev: Event) -> String { Slider::event(self, path, ev) } // RUST-ONLY
            fn close(self: Box<Self>) -> String { Slider::close(*self) } // RUST-ONLY
        } // RUST-ONLY
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

use builtin::{dyn_shape, dyn_widget};
use crate::core::button::Button;
use crate::core::circle::Circle;
use crate::core::panel::Panel;
use crate::core::rect::Rect;
use crate::core::{Event, Shape};
use plugin::hexagon::Hexagon;
use plugin::hexagon_by_hand;
use plugin::slider::Slider;

fn b1() -> Result<(), String> {
    let shapes: Vec<Box<dyn Shape>> = vec![
        dyn_shape(Circle::new(1.0)?),
        dyn_shape(Hexagon::new(2.0)?),
        dyn_shape(Rect::new(2.0, 3.0)?),
        dyn_shape(hexagon_by_hand(1.0)?),
        dyn_shape(Circle::new(2.0)?),
    ];
    let mut total = 0.0;
    for s in &shapes {
        println!("{} {:.2}", s.name(), s.area()); // dynamic call: s is a `dyn Shape`
        total += s.area();
    }
    println!("total {:.2}", total);
    Ok(())
}

fn b2() -> Result<(), String> {
    let inner = dyn_widget(Panel::new(vec![dyn_widget(Button::new("Cancel")?)]));
    let mut root = dyn_widget(Panel::new(vec![
        dyn_widget(Button::new("OK")?),
        dyn_widget(Slider::new(3, 10)?),
        inner,
    ]));
    println!("build");
    print!("{}", root.render(0));
    let events: Vec<(&str, Vec<usize>, Event)> = vec![
        ("click OK", vec![0], Event::Click),
        ("drag Slider +4", vec![1], Event::Drag(4)),
        ("click Cancel", vec![2, 0], Event::Click),
        ("close inner panel", vec![2], Event::Close),
    ];
    for (label, path, ev) in events {
        println!("{}: {}", label, root.event(&path, ev)); // dynamic call
        print!("{}", root.render(0)); // dynamic call
    }
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
