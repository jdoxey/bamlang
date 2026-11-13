// Option A: closed set of built-in generics + user logic over element-free data.
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

// ===== the LRU logic, written ONCE, over element-free data (slot ids) =====

type lruOrder struct {
	cap   int
	used  []int // slot ids, least recently used first
	count int   // slots handed out so far
}

func newOrder(cap int) *lruOrder { return &lruOrder{cap: cap} }

func (o *lruOrder) touch(slot int) {
	if i := slices.Index(o.used, slot); i >= 0 {
		o.used = slices.Delete(o.used, i, i+1)
	}
	o.used = append(o.used, slot)
}

// acquire hands out a slot for a new entry. evicted means the slot still holds
// the least-recently-used live entry, which the caller must forget.
func (o *lruOrder) acquire() (slot int, evicted bool) {
	if o.count < o.cap {
		slot = o.count
		o.count++
	} else {
		slot, evicted = o.used[0], true
	}
	o.touch(slot)
	return slot, evicted
}

// ===== per-use glue: typed storage in built-in containers (UserKey -> Profile) =====

type profileCache struct {
	ord   *lruOrder
	slots map[UserKey]int
	keys  []UserKey
	vals  []Profile
}

func newProfileCache(cap int) *profileCache {
	return &profileCache{newOrder(cap), map[UserKey]int{}, make([]UserKey, cap), make([]Profile, cap)}
}

func (c *profileCache) Get(k UserKey) (Profile, bool) {
	s, ok := c.slots[k]
	if !ok {
		return Profile{}, false
	}
	c.ord.touch(s)
	return c.vals[s], true
}

func (c *profileCache) Put(k UserKey, v Profile) (UserKey, bool) {
	if s, ok := c.slots[k]; ok {
		c.vals[s] = v
		c.ord.touch(s)
		return UserKey{}, false
	}
	s, ev := c.ord.acquire()
	old := c.keys[s]
	if ev {
		delete(c.slots, old)
	}
	c.slots[k], c.keys[s], c.vals[s] = s, k, v
	return old, ev
}

// ===== per-use glue: String -> List of Int =====

type queryCache struct {
	ord   *lruOrder
	slots map[string]int
	keys  []string
	vals  [][]int
}

func newQueryCache(cap int) *queryCache {
	return &queryCache{newOrder(cap), map[string]int{}, make([]string, cap), make([][]int, cap)}
}

func (c *queryCache) Get(k string) ([]int, bool) {
	s, ok := c.slots[k]
	if !ok {
		return nil, false
	}
	c.ord.touch(s)
	return c.vals[s], true
}

func (c *queryCache) Put(k string, v []int) (string, bool) {
	if s, ok := c.slots[k]; ok {
		c.vals[s] = v
		c.ord.touch(s)
		return "", false
	}
	s, ev := c.ord.acquire()
	old := c.keys[s]
	if ev {
		delete(c.slots, old)
	}
	c.slots[k], c.keys[s], c.vals[s] = s, k, v
	return old, ev
}

// ===== end of LRU =====

func part2() {
	fmt.Println("== Part 2: LRU cache reused for two key/value pairs ==")
	pc, qc := newProfileCache(2), newQueryCache(3)
	putP := func(k UserKey, p Profile) {
		fmt.Printf("profiles put %d/%d\n", k.tenant, k.id)
		if old, ev := pc.Put(k, p); ev {
			fmt.Printf("profiles evict %d/%d\n", old.tenant, old.id)
		}
	}
	getP := func(k UserKey) {
		if p, ok := pc.Get(k); ok {
			fmt.Printf("profiles get %d/%d hit %s <%s>\n", k.tenant, k.id, p.name, p.email)
		} else {
			fmt.Printf("profiles get %d/%d miss\n", k.tenant, k.id)
		}
	}
	putQ := func(k string, v []int) {
		fmt.Printf("queries put %s\n", k)
		if old, ev := qc.Put(k, v); ev {
			fmt.Printf("queries evict %s\n", old)
		}
	}
	getQ := func(k string) {
		if v, ok := qc.Get(k); ok {
			fmt.Printf("queries get %s hit %v\n", k, v)
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
