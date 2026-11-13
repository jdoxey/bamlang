// Option C: user-written container holding `any`, checked narrowing at use sites.
// No type parameters are declared in this file.
package main

import (
	"cmp"
	"fmt"
	"slices"
	"sync"
)

// ---------------------------------------------------------------- Part 1

type Employee struct {
	name   string
	dept   string
	salary int
}

var employees = []Employee{
	{"Grace", "sales", 60000},
	{"Bob", "eng", 70000},
	{"Dave", "ops", 45000},
	{"Carol", "eng", 90000},
	{"Heidi", "sales", 40000},
	{"Alice", "eng", 70000},
	{"Erin", "ops", 55000},
	{"Frank", "sales", 40000},
}

func part1() {
	fmt.Println("== Part 1: algorithms over Employee ==")
	sorted := slices.Clone(employees)
	slices.SortFunc(sorted, func(a, b Employee) int {
		return cmp.Or(cmp.Compare(a.dept, b.dept), cmp.Compare(b.salary, a.salary), cmp.Compare(a.name, b.name))
	})
	fmt.Println("sorted by dept, salary desc, name:")
	for _, e := range sorted {
		fmt.Printf("  %-5s %-6s %d\n", e.dept, e.name, e.salary)
	}
	byPay := func(a, b Employee) bool { return a.salary < b.salary }
	lo, hi := MinBy(employees, byPay), MaxBy(employees, byPay)
	fmt.Printf("min_by salary: %s %d\n", lo.name, lo.salary)
	fmt.Printf("max_by salary: %s %d\n", hi.name, hi.salary)
	groups := GroupBy(employees, func(e Employee) string { return e.dept })
	fmt.Println("group_by dept:")
	for _, d := range SortedKeys(groups) {
		total := 0
		for _, e := range groups[d] {
			total += e.salary
		}
		fmt.Printf("  %-5s count=%d total=%d\n", d, len(groups[d]), total)
	}
	rich := Filter(employees, func(e Employee) bool { return e.salary > 50000 })
	fmt.Println("salary > 50000:", Map(rich, func(e Employee) string { return e.name }))
}

// ---------------------------------------------------------------- Part 2

type UserKey struct{ tenant, id int }
type Profile struct{ name, email string }

// ===== the LRU, written ONCE, holding `any` keys and values =====

type entry struct{ key, val any }

type LRU struct {
	cap   int
	order []*entry // least recently used first
	idx   map[any]*entry
}

func NewLRU(cap int) *LRU { return &LRU{cap: cap, idx: map[any]*entry{}} }

func (c *LRU) touch(e *entry) {
	if i := slices.Index(c.order, e); i >= 0 {
		c.order = slices.Delete(c.order, i, i+1)
	}
	c.order = append(c.order, e)
}

func (c *LRU) Get(k any) (any, bool) {
	e, ok := c.idx[k]
	if !ok {
		return nil, false
	}
	c.touch(e)
	return e.val, true
}

// Put returns the evicted key, if any.
func (c *LRU) Put(k, v any) (any, bool) {
	if e, ok := c.idx[k]; ok {
		e.val = v
		c.touch(e)
		return nil, false
	}
	var old any
	var ev bool
	if len(c.idx) == c.cap {
		victim := c.order[0]
		c.order = c.order[1:]
		delete(c.idx, victim.key)
		old, ev = victim.key, true
	}
	e := &entry{k, v}
	c.idx[k] = e
	c.touch(e)
	return old, ev
}

// ===== end of LRU =====

func part2() {
	fmt.Println("== Part 2: LRU cache reused for two key/value pairs ==")
	pc, qc := NewLRU(2), NewLRU(3)
	putP := func(k UserKey, p Profile) {
		fmt.Printf("profiles put %d/%d\n", k.tenant, k.id)
		if old, ev := pc.Put(k, p); ev {
			ok := old.(UserKey) // assertion 1
			fmt.Printf("profiles evict %d/%d\n", ok.tenant, ok.id)
		}
	}
	getP := func(k UserKey) {
		v, hit := pc.Get(k)
		p, ok := v.(Profile) // assertion 2: checked narrowing
		if hit && ok {
			fmt.Printf("profiles get %d/%d hit %s <%s>\n", k.tenant, k.id, p.name, p.email)
		} else {
			fmt.Printf("profiles get %d/%d miss\n", k.tenant, k.id)
		}
	}
	putQ := func(k string, v []int) {
		fmt.Printf("queries put %s\n", k)
		if old, ev := qc.Put(k, v); ev {
			s, _ := old.(string) // assertion 3
			fmt.Printf("queries evict %s\n", s)
		}
	}
	getQ := func(k string) {
		v, hit := qc.Get(k)
		xs, ok := v.([]int) // assertion 4: checked narrowing
		if hit && ok {
			fmt.Printf("queries get %s hit %v\n", k, xs)
		} else {
			fmt.Printf("queries get %s miss\n", k)
		}
	}
	putP(UserKey{1, 1}, Profile{"Ann", "ann@example.com"})
	putP(UserKey{1, 2}, Profile{"Ben", "ben@example.com"})
	getP(UserKey{1, 1})
	putP(UserKey{2, 1}, Profile{"Cy", "cy@example.com"})
	getP(UserKey{1, 2})
	putP(UserKey{1, 3}, Profile{"Di", "di@example.com"})
	getP(UserKey{2, 1})
	getP(UserKey{1, 1})

	putQ("a", []int{1})
	putQ("b", []int{2, 2})
	putQ("c", []int{3})
	getQ("a")
	putQ("d", []int{4})
	getQ("b")
	putQ("a", []int{1, 1})
	putQ("e", []int{5})
	getQ("c")
	getQ("a")
}

// ---------------------------------------------------------------- Part 3

type Address struct{ street, city string }

type User struct {
	id   int
	name string
	addr Optional[Address]
}

var users = map[int]User{
	1: {1, "Ann", Some(Address{"10 Main St", "Springfield"})},
	2: {2, "Ben", None[Address]()},
}

func findUser(id int) Optional[User] {
	if u, ok := users[id]; ok {
		return Some(u)
	}
	return None[User]()
}

type result struct {
	id   int
	addr Optional[Address]
}

func part3() {
	fmt.Println("== Part 3: Optional pipeline across a thread ==")
	ch := make(chan result)
	var wg sync.WaitGroup
	wg.Add(1)
	go func() { // the worker is the only printer
		defer wg.Done()
		for r := range ch {
			if a, ok := r.addr.Get(); ok {
				fmt.Printf("addr for %d: %s, %s\n", r.id, a.street, a.city)
			} else {
				fmt.Printf("addr for %d: none\n", r.id)
			}
		}
	}()
	for id := 1; id <= 3; id++ {
		ch <- result{id, Then(findUser(id), func(u User) Optional[Address] { return u.addr })}
	}
	close(ch)
	wg.Wait()
}

func main() {
	part1()
	part2()
	part3()
}
