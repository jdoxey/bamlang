// Option I: user generic functions with inferred type parameters; struct fields concrete.
// Every type-parameter list below is "inferred, not written by the user" in the real language.
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

// ===== the LRU, written ONCE as generic functions over parts of a concrete state =====

// touch moves k to the most-recently-used end of order.
func touch[K comparable](order *[]K, k K) { // inferred, not written by the user
	if i := slices.Index(*order, k); i >= 0 {
		*order = slices.Delete(*order, i, i+1)
	}
	*order = append(*order, k)
}

func lruGet[K comparable, V any](order *[]K, vals map[K]V, k K) (V, bool) { // inferred, not written by the user
	v, ok := vals[k]
	if ok {
		touch(order, k)
	}
	return v, ok
}

// lruPut returns the evicted key, if any.
func lruPut[K comparable, V any](cap int, order *[]K, vals map[K]V, k K, v V) (K, bool) { // inferred, not written by the user
	var old K
	ev := false
	if _, ok := vals[k]; !ok && len(vals) == cap {
		old, ev = (*order)[0], true
		*order = (*order)[1:]
		delete(vals, old)
	}
	vals[k] = v
	touch(order, k)
	return old, ev
}

// ===== per-use concrete state: only fields, no behaviour =====

type profileCache struct {
	cap   int
	order []UserKey
	vals  map[UserKey]Profile
}

type queryCache struct {
	cap   int
	order []string
	vals  map[string][]int
}

// ===== end of LRU =====

func part2() {
	fmt.Println("== Part 2: LRU cache reused for two key/value pairs ==")
	pc := &profileCache{cap: 2, vals: map[UserKey]Profile{}}
	qc := &queryCache{cap: 3, vals: map[string][]int{}}
	putP := func(k UserKey, p Profile) {
		fmt.Printf("profiles put %d/%d\n", k.tenant, k.id)
		if old, ev := lruPut(pc.cap, &pc.order, pc.vals, k, p); ev {
			fmt.Printf("profiles evict %d/%d\n", old.tenant, old.id)
		}
	}
	getP := func(k UserKey) {
		if p, ok := lruGet(&pc.order, pc.vals, k); ok {
			fmt.Printf("profiles get %d/%d hit %s <%s>\n", k.tenant, k.id, p.name, p.email)
		} else {
			fmt.Printf("profiles get %d/%d miss\n", k.tenant, k.id)
		}
	}
	putQ := func(k string, v []int) {
		fmt.Printf("queries put %s\n", k)
		if old, ev := lruPut(qc.cap, &qc.order, qc.vals, k, v); ev {
			fmt.Printf("queries evict %s\n", old)
		}
	}
	getQ := func(k string) {
		if v, ok := lruGet(&qc.order, qc.vals, k); ok {
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
