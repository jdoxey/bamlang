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
    }

    // STAND-IN for the built-in `List.take_out(i)`: remove and return the owned element.
    pub trait TakeOut<T> { fn take_out(&mut self, i: usize) -> T; }
    impl<T> TakeOut<T> for Vec<T> { fn take_out(&mut self, i: usize) -> T { self.remove(i) } }
}

mod core {
    // ---- B1: Shape is an open set (others extend): iface + dyn, no enum ----
    pub mod shape {
        pub trait Shape: std::fmt::Debug { // `iface Shape is show`
            fn name(&self) -> &'static str;
            fn area(&self) -> f64;
            fn describe(&self) -> String { format!("{} {:.2}", self.name(), self.area()) } // RUST-ONLY: Rust lets impls override this; the design forbids it
            fn intersects(&self, other: &dyn Shape) -> bool { self.area().sqrt() + other.area().sqrt() > 5.0 } // RUST-ONLY: same (overridable)
        }

        #[derive(Debug)]
        pub struct Circle { r: f64 }
        #[derive(Debug)]
        pub struct Rect { w: f64, h: f64 }
        impl Circle {
            pub fn new(r: f64) -> Result<Circle, String> {
                if r > 0.0 { Ok(Circle { r }) } else { Err(format!("bad radius {}", r)) }
            }
        }
        impl Rect {
            pub fn new(w: f64, h: f64) -> Result<Rect, String> {
                if w > 0.0 && h > 0.0 { Ok(Rect { w, h }) } else { Err(format!("bad size {}x{}", w, h)) }
            }
        }
        impl Shape for Circle {
            fn name(&self) -> &'static str { "circle" }
            fn area(&self) -> f64 { std::f64::consts::PI * self.r * self.r }
        }
        impl Shape for Rect {
            fn name(&self) -> &'static str { "rect" }
            fn area(&self) -> f64 { self.w * self.h }
        }
    }

    // ---- B2: Widget is a closed set we own plus an open set others extend: enum with one Ext(dyn) ----
    pub mod widget {
        #[derive(Clone, Copy)]
        pub enum Event { Click, Drag(i32), Close }

        pub fn focus_text() -> &'static str { "focus moves to next" }
        pub fn indent(depth: usize) -> String { "  ".repeat(depth + 1) }

        pub trait WidgetKind { // `iface WidgetKind`
            fn render(&self, depth: usize) -> String;
            fn event(&mut self, path: &[usize], ev: Event) -> String;
            fn close(self: Box<Self>) -> String; // RUST-ONLY: Box<Self> receiver spells `take self` on a dyn
            fn focus_next(&self) -> &'static str { focus_text() } // RUST-ONLY: overridable in Rust, not in the design
        }

        pub enum Widget {
            Panel { children: Vec<Widget> }, // RUST-ONLY: variant fields are public in Rust; the design keeps them module-private
            Button { label: String }, // RUST-ONLY: same
            Ext(Box<dyn WidgetKind>),
        }

        use crate::builtin::TakeOut;

        // Shared by Panel and by any plugin container: route an event down a path; Close at the last step takes the child out.
        pub fn route(children: &mut Vec<Widget>, path: &[usize], ev: Event) -> String {
            match (path, ev) {
                ([], _) => "ignored".to_string(),
                ([i], Event::Close) if *i < children.len() => {
                    let c = children.take_out(*i);
                    format!("consumed {}; {}", c.close(), focus_text())
                }
                ([i, rest @ ..], _) => match children.get_mut(*i) {
                    Some(c) => c.event(rest, ev),
                    None => "no such widget".to_string(),
                },
            }
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
                    Widget::Ext(d) => d.render(depth), // dynamic call
                }
            }
            pub fn event(&mut self, path: &[usize], ev: Event) -> String { // `mut self`; arm bindings are places
                match self {
                    Widget::Panel { children } => route(children, path, ev),
                    Widget::Button { label } => match ev {
                        Event::Click => format!("pressed {}; {}", label, focus_text()),
                        _ => "ignored".to_string(),
                    },
                    Widget::Ext(d) => d.event(path, ev), // dynamic call
                }
            }
            pub fn collapse(&mut self) { // `mut self = V` replaces the value, dropping the old one
                match self {
                    Widget::Panel { children } => {
                        let n = children.len();
                        *self = Widget::Button { label: format!("panel of {}", n) };
                    }
                    _ => {}
                }
            }
            pub fn close(self) -> String { // `take self`
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

    // ---- B3 ----
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

        // Free function: `Pool of Account` is not our type, so methods-only-in-the-type does not apply (see NOTES).
        pub fn transfer(pool: &mut Pool<Account>, a: Handle, b: Handle, m: Money) -> Result<(), String> {
            if pool.get(b).is_none() { return Err(missing()); }
            pool.get_mut(a).ok_or_else(missing)?.withdraw(m)?;
            pool.get_mut(b).ok_or_else(missing)?.deposit(m);
            Ok(())
        }
    }
}

// The plugin cannot edit `core`; it adds types and conformances.
mod plugin {
    // BEGIN hexagon
    pub mod hexagon {
        use crate::core::shape::Shape;
        #[derive(Debug)]
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
        use crate::core::widget::{Event, WidgetKind};
        pub struct SliderSpec { pub value: i32, pub max: i32 }
        impl SliderSpec { pub const DEFAULTS: SliderSpec = SliderSpec { value: 0, max: 10 }; } // RUST-ONLY: Rust has no field defaults
        pub struct Slider { value: i32, max: i32 }
        impl Slider {
            pub fn new(s: SliderSpec) -> Result<Slider, String> {
                if s.value < 0 || s.value > s.max { Err("slider out of range".to_string()) } else { Ok(Slider { value: s.value, max: s.max }) }
            }
        }
        impl WidgetKind for Slider {
            fn render(&self, depth: usize) -> String { format!("{}Slider {}/{}\n", crate::core::widget::indent(depth), self.value, self.max) }
            fn event(&mut self, _path: &[usize], ev: Event) -> String {
                match ev {
                    Event::Drag(d) => {
                        let old = self.value;
                        self.value = (old + d).clamp(0, self.max);
                        format!("value {} -> {}; {}", old, self.value, self.focus_next())
                    }
                    _ => "ignored".to_string(),
                }
            }
            fn close(self: Box<Self>) -> String { format!("Slider {}/{}", self.value, self.max) } // RUST-ONLY: Box<Self>
        }
    }
    // END slider

    // BEGIN tabs
    pub mod tabs {
        use crate::core::widget::{indent, route, Event, Widget, WidgetKind};
        pub struct Tabs { children: Vec<Widget> }
        impl Tabs {
            pub fn new(children: Vec<Widget>) -> Result<Tabs, String> {
                if children.is_empty() { Err("empty tabs".to_string()) } else { Ok(Tabs { children }) }
            }
        }
        impl WidgetKind for Tabs {
            fn render(&self, depth: usize) -> String {
                let mut out = format!("{}Tabs\n", indent(depth));
                for c in &self.children { out.push_str(&c.render(depth + 1)); }
                out
            }
            fn event(&mut self, path: &[usize], ev: Event) -> String { route(&mut self.children, path, ev) }
            fn close(self: Box<Self>) -> String { // RUST-ONLY: Box<Self>
                let parts: Vec<String> = self.children.into_iter().map(|c| c.close()).collect();
                format!("Tabs[{}]", parts.join(", "))
            }
        }
    }
    // END tabs
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

use crate::core::shape::{Circle, Rect, Shape};
use crate::core::widget::{Event, Widget};
use plugin::hexagon::Hexagon;
use plugin::slider::{Slider, SliderSpec};
use plugin::tabs::Tabs;

fn b1() -> Result<(), String> {
    let shapes: Vec<Box<dyn Shape>> = vec![
        Box::new(Circle::new(1.0)?),
        Box::new(Hexagon::new(2.0)?),
        Box::new(Rect::new(2.0, 3.0)?),
        Box::new(Hexagon::new(1.0)?),
        Box::new(Circle::new(2.0)?),
    ];
    let mut total = 0.0;
    for s in &shapes {
        println!("{}", s.describe());
        total += s.area();
    }
    println!("total {:.2}", total);
    // Not in expected.txt: borrowed-dyn parameter and derived show, to stderr.
    eprintln!("intersects: {} {:?}", shapes[0].intersects(shapes[1].as_ref()), shapes[1]);
    Ok(())
}

fn b2() -> Result<(), String> {
    let inner = Widget::panel(vec![Widget::button("Cancel")?]);
    let mut root = Widget::panel(vec![
        Widget::button("OK")?,
        Widget::Ext(Box::new(Slider::new(SliderSpec { value: 3, ..SliderSpec::DEFAULTS })?)), // RUST-ONLY: `..DEFAULTS` stands for field defaults
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

// Not in expected.txt: a plugin container (Tabs) holding core children, to stderr.
fn b2_tabs() -> Result<(), String> {
    let mut root = Widget::panel(vec![
        Widget::button("A")?,
        Widget::Ext(Box::new(Tabs::new(vec![
            Widget::button("X")?,
            Widget::panel(vec![Widget::button("Y")?]),
        ])?)),
    ]);
    eprint!("{}", root.render(0));
    eprintln!("click Y: {}", root.event(&[1, 1, 0], Event::Click));
    eprintln!("close tab panel: {}", root.event(&[1, 1], Event::Close));
    root.collapse();
    eprint!("{}", root.render(0));
    eprintln!("closed all: {}", root.close());
    Ok(())
}

fn b3() -> Result<(), String> {
    use crate::builtin::Pool;
    use crate::core::account::{transfer, Account};
    use crate::core::money::Money;
    let mut pool: Pool<Account> = Pool::new();
    let alice = pool.insert(Account::new("alice", Money::new(100)?)?);
    let bob = pool.insert(Account::new("bob", Money::new(50)?)?);
    pool.get_mut(alice).unwrap().deposit(Money::new(25)?);
    println!("deposit alice 25");
    transfer(&mut pool, alice, bob, Money::new(75)?)?;
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
    b2_tabs()?;
    println!("== B3 accounts ==");
    b3()
}
