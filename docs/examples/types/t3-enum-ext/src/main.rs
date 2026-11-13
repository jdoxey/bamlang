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

// Closed enums with methods as `match self`, plus one open `Ext` variant each.
mod core {
    // The record of functions an extension must supply (`dyn ShapeFns`).
    pub trait ShapeExt {
        fn name(&self) -> &'static str;
        fn area(&self) -> f64;
    }
    // `close` takes self.
    pub trait WidgetExt {
        fn render_line(&self) -> String;
        fn event(&mut self, ev: Event) -> String;
        fn close(self: Box<Self>) -> String; // RUST-ONLY: Box<Self> receiver spells `take self` on a dyn
    }
    #[derive(Clone, Copy)]
    pub enum Event { Click, Drag(i32), Close }

    // Default focus behaviour: one plain function that each arm / extension calls.
    pub fn focus_next() -> &'static str { "focus moves to next" }
    pub fn indent(depth: usize) -> String { "  ".repeat(depth + 1) }

    pub mod shape {
        use super::ShapeExt;
        pub enum Shape {
            Circle { r: f64 }, // RUST-ONLY: variant fields are public in Rust; the design keeps them module-private
            Rect { w: f64, h: f64 }, // RUST-ONLY: same
            Ext(Box<dyn ShapeExt>),
        }
        impl Shape {
            pub fn circle(r: f64) -> Result<Shape, String> {
                if r > 0.0 { Ok(Shape::Circle { r }) } else { Err(format!("bad radius {}", r)) }
            }
            pub fn rect(w: f64, h: f64) -> Result<Shape, String> {
                if w > 0.0 && h > 0.0 { Ok(Shape::Rect { w, h }) } else { Err(format!("bad size {}x{}", w, h)) }
            }
            pub fn name(&self) -> &'static str {
                match self {
                    Shape::Circle { .. } => "circle",
                    Shape::Rect { .. } => "rect",
                    Shape::Ext(d) => d.name(), // dynamic call
                }
            }
            pub fn area(&self) -> f64 {
                match self {
                    Shape::Circle { r } => std::f64::consts::PI * r * r,
                    Shape::Rect { w, h } => w * h,
                    Shape::Ext(d) => d.area(), // dynamic call
                }
            }
        }
    }

    pub mod widget {
        use super::{focus_next, indent, Event, WidgetExt};
        pub enum Widget {
            Panel { children: Vec<Widget> }, // RUST-ONLY: variant fields are public in Rust
            Button { label: String }, // RUST-ONLY: same
            Ext(Box<dyn WidgetExt>),
        }
        impl Widget {
            pub fn panel(children: Vec<Widget>) -> Widget { Widget::Panel { children } }
            pub fn button(label: &str) -> Result<Widget, String> {
                if label.is_empty() { Err("empty label".to_string()) } else { Ok(Widget::Button { label: label.to_string() }) }
            }
            pub fn render(&self, depth: usize) -> String {
                match self {
                    Widget::Panel { children } => {
                        let mut out = format!("{}Panel\n", indent(depth));
                        for c in children { out.push_str(&c.render(depth + 1)); }
                        out
                    }
                    Widget::Button { label } => format!("{}Button {}\n", indent(depth), label),
                    Widget::Ext(d) => format!("{}{}\n", indent(depth), d.render_line()), // dynamic call
                }
            }
            pub fn event(&mut self, path: &[usize], ev: Event) -> String {
                match self {
                    Widget::Panel { children } => match (path, ev) {
                        ([], _) => "ignored".to_string(),
                        ([i], Event::Close) if *i < children.len() => {
                            let c = children.remove(*i);
                            format!("consumed {}; {}", c.close(), focus_next())
                        }
                        ([i, rest @ ..], _) => match children.get_mut(*i) {
                            Some(c) => c.event(rest, ev),
                            None => "no such widget".to_string(),
                        },
                    },
                    Widget::Button { label } => match ev {
                        Event::Click => format!("pressed {}; {}", label, focus_next()),
                        _ => "ignored".to_string(),
                    },
                    Widget::Ext(d) => d.event(ev), // dynamic call
                }
            }
            pub fn close(self) -> String {
                match self {
                    Widget::Panel { children } => {
                        let parts: Vec<String> = children.into_iter().map(|c| c.close()).collect();
                        format!("Panel[{}]", parts.join(", "))
                    }
                    Widget::Button { label } => format!("Button {}", label),
                    Widget::Ext(d) => d.close(), // dynamic call
                }
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

// The plugin cannot edit `core`; it can only fill the `Ext` variants.
mod plugin {
    // BEGIN hexagon
    pub mod hexagon {
        use crate::core::ShapeExt;
        pub struct Hexagon { side: f64 }
        impl Hexagon {
            pub fn new(side: f64) -> Result<Hexagon, String> {
                if side > 0.0 { Ok(Hexagon { side }) } else { Err(format!("bad side {}", side)) }
            }
        }
        impl ShapeExt for Hexagon {
            fn name(&self) -> &'static str { "hexagon" }
            fn area(&self) -> f64 { 3.0 * 3f64.sqrt() / 2.0 * self.side * self.side }
        }
    }
    // END hexagon

    // BEGIN slider
    pub mod slider {
        use crate::core::{focus_next, Event, WidgetExt};
        pub struct Slider { value: i32, max: i32 }
        impl Slider {
            pub fn new(value: i32, max: i32) -> Result<Slider, String> {
                if value < 0 || value > max { Err("slider out of range".to_string()) } else { Ok(Slider { value, max }) }
            }
        }
        impl WidgetExt for Slider {
            fn render_line(&self) -> String { format!("Slider {}/{}", self.value, self.max) }
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
            fn close(self: Box<Self>) -> String { format!("Slider {}/{}", self.value, self.max) } // RUST-ONLY: Box<Self>
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

use crate::core::shape::Shape;
use crate::core::widget::Widget;
use crate::core::Event;
use plugin::hexagon::Hexagon;
use plugin::slider::Slider;

fn b1() -> Result<(), String> {
    let shapes = vec![
        Shape::circle(1.0)?,
        Shape::Ext(Box::new(Hexagon::new(2.0)?)), // the visible dyn conversion
        Shape::rect(2.0, 3.0)?,
        Shape::Ext(Box::new(Hexagon::new(1.0)?)),
        Shape::circle(2.0)?,
    ];
    let mut total = 0.0;
    for s in &shapes {
        println!("{} {:.2}", s.name(), s.area());
        total += s.area();
    }
    println!("total {:.2}", total);
    Ok(())
}

fn b2() -> Result<(), String> {
    let inner = Widget::panel(vec![Widget::button("Cancel")?]);
    let mut root = Widget::panel(vec![
        Widget::button("OK")?,
        Widget::Ext(Box::new(Slider::new(3, 10)?)),
        inner,
    ]);
    println!("build");
    print!("{}", root.render(0));
    let events: Vec<(&str, Vec<usize>, Event)> = vec![
        ("click OK", vec![0], Event::Click),
        ("drag Slider +4", vec![1], Event::Drag(4)),
        ("click Cancel", vec![2, 0], Event::Click),
        ("close inner panel", vec![2], Event::Close),
    ];
    for (label, path, ev) in events {
        println!("{}: {}", label, root.event(&path, ev));
        print!("{}", root.render(0));
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
