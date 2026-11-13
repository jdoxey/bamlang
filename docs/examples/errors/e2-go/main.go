// E2: fallible functions return (T, *Err); one Err type; every propagation is a
// single `if err != nil { return ..., err.with("ctx") }` (what a statement-level `check` expands to).
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
)

// ---- the one error type ----

type Err struct {
	Kind  string // parse, io, injected, trap
	Msg   string
	Ctx   []string // innermost first
	Trace []string // appended at each with()
}

func (e *Err) with(c string) *Err {
	n := *e
	n.Ctx = append(append([]string(nil), e.Ctx...), c)
	_, file, line, _ := runtime.Caller(1)
	n.Trace = append(append([]string(nil), e.Trace...), fmt.Sprintf("%s:%d", filepath.Base(file), line))
	return &n
}

func (e *Err) Text() string {
	parts := []string{}
	for i := len(e.Ctx) - 1; i >= 0; i-- {
		parts = append(parts, e.Ctx[i])
	}
	return strings.Join(append(parts, e.Msg), ": ")
}

func ioErr(err error) *Err { return &Err{Kind: "io", Msg: err.Error()} } // glue

// ---- part 1 ----

type entry struct{ section, key, value string }
type Config struct{ entries []entry }

func (c *Config) get(section, key string) (string, bool) {
	for _, e := range c.entries {
		if e.section == section && e.key == key {
			return e.value, true
		}
	}
	return "", false
}

type parser struct {
	cfg     Config
	section string
}

func (p *parser) parseLine(no int, raw string) *Err {
	line := strings.TrimSpace(raw)
	if line == "" || strings.HasPrefix(line, "#") {
		return nil
	}
	if strings.HasPrefix(line, "[") && strings.HasSuffix(line, "]") {
		p.section = line[1 : len(line)-1]
		return nil
	}
	i := strings.Index(line, "=")
	if i < 0 {
		return &Err{Kind: "parse", Msg: fmt.Sprintf("config.ini:%d: missing '='", no)}
	}
	key := strings.TrimSpace(line[:i])
	if key == "" {
		return &Err{Kind: "parse", Msg: fmt.Sprintf("config.ini:%d: empty key", no)}
	}
	if _, dup := p.cfg.get(p.section, key); dup {
		return &Err{Kind: "parse", Msg: fmt.Sprintf("config.ini:%d: duplicate key '%s' in [%s]", no, key, p.section)}
	}
	p.cfg.entries = append(p.cfg.entries, entry{p.section, key, strings.TrimSpace(line[i+1:])})
	return nil
}

func parseFailFast(text string) (Config, *Err) {
	p := parser{}
	for i, l := range strings.Split(text, "\n") {
		if err := p.parseLine(i+1, l); err != nil {
			return Config{}, err
		}
	}
	return p.cfg, nil
}

func parseAll(text string) (Config, []*Err) {
	p := parser{}
	var errs []*Err
	for i, l := range strings.Split(text, "\n") {
		if err := p.parseLine(i+1, l); err != nil {
			errs = append(errs, err)
		}
	}
	return p.cfg, errs
}

func parseInt(s string) (int, *Err) {
	n, e := strconv.Atoi(s)
	if e != nil {
		return 0, &Err{Kind: "parse", Msg: "not an integer: " + s}
	}
	return n, nil
}

const badText = "# sample config\n[server]\nport = 8080\nhost\n= nokey\nport = 9090\n[db]\nname = x\n"
const goodText = "# sample config\n[server]\nport = 8080\nhost = localhost\n[db]\nname = x\n"

func part1() *Err {
	fmt.Println("== part 1: config parser")
	if _, err := parseFailFast(badText); err != nil {
		fmt.Println("fail-fast: " + err.Text())
	}
	_, errs := parseAll(badText)
	fmt.Println("collect-all:")
	for _, e := range errs {
		fmt.Println("  " + e.Text())
	}
	fmt.Printf("%d errors\n", len(errs))

	cfg, err := parseFailFast(goodText)
	if err != nil {
		return err
	}
	if s, ok := cfg.get("server", "port"); ok {
		port, err := parseInt(s)
		if err != nil {
			return err.with("server.port")
		}
		fmt.Printf("server.port = %d\n", port)
	}
	if s, ok := cfg.get("server", "timeout"); ok {
		fmt.Println("server.timeout = " + s)
	} else {
		fmt.Println("timeout not set, using 30")
	}
	return nil
}

// ---- part 2 ----

func inject(failAt, step int) *Err {
	if failAt == step {
		return &Err{Kind: "injected", Msg: "injected failure"}
	}
	return nil
}

func replaceFile(dir, name, content string, failAt int) (err *Err) {
	lock := filepath.Join(dir, name+".lock")
	tmp := filepath.Join(dir, name+".tmp")
	dst := filepath.Join(dir, name)
	held := false
	defer func() { // cleanup cannot fail
		if held {
			os.Remove(lock)
		}
		os.Remove(tmp)
	}()

	f, e := os.OpenFile(lock, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
	if e != nil {
		return ioErr(e).with("step 1: create lock")
	}
	f.Close()
	held = true
	if err := inject(failAt, 1); err != nil {
		return err.with("step 1: create lock")
	}
	if e := os.WriteFile(tmp, []byte(content), 0o644); e != nil {
		return ioErr(e).with("step 2: write temp")
	}
	if err := inject(failAt, 2); err != nil {
		return err.with("step 2: write temp")
	}
	if err := inject(failAt, 3); err != nil {
		return err.with("step 3: rename temp")
	}
	if e := os.Rename(tmp, dst); e != nil {
		return ioErr(e).with("step 3: rename temp")
	}
	if err := inject(failAt, 4); err != nil {
		return err.with("step 4: remove lock")
	}
	if e := os.Remove(lock); e != nil {
		return ioErr(e).with("step 4: remove lock")
	}
	held = false
	return nil
}

func listing(dir string) (string, *Err) {
	ents, e := os.ReadDir(dir) // sorted by filename
	if e != nil {
		return "", ioErr(e).with("list dir")
	}
	names := []string{}
	for _, en := range ents {
		names = append(names, en.Name())
	}
	return strings.Join(names, " "), nil
}

func part2() *Err {
	fmt.Println("== part 2: replace_file")
	dir, e := os.MkdirTemp("", "errors-e2-")
	if e != nil {
		return ioErr(e).with("make temp dir")
	}
	defer os.RemoveAll(dir)
	if e := os.WriteFile(filepath.Join(dir, "data.txt"), []byte("old"), 0o644); e != nil {
		return ioErr(e).with("seed data.txt")
	}
	fmt.Println("start: content old")
	labels := []string{"no failure", "fail at step 1", "fail at step 2", "fail at step 3", "fail at step 4"}
	for run := 0; run < 5; run++ {
		res := "ok"
		if err := replaceFile(dir, "data.txt", fmt.Sprintf("v%d", run+1), run); err != nil {
			res = "error: " + err.Text()
		}
		fmt.Printf("run %d, %s: %s\n", run+1, labels[run], res)
		files, err := listing(dir)
		if err != nil {
			return err
		}
		b, e := os.ReadFile(filepath.Join(dir, "data.txt"))
		if e != nil {
			return ioErr(e).with("read data.txt")
		}
		fmt.Printf("  files: %s\n  content: %s\n", files, b)
	}
	return nil
}

// ---- part 3 ----

type poisonMutex struct {
	mu       sync.Mutex
	poisoned bool
}

var workerTexts = []string{
	"[a]\nx = 1\n",
	"[b]\nname = w2\nbroken line\n",
	"[c]\nz = 3\n",
	"[d]\nk = 4\n",
}

func worker(n int, text string, pm *poisonMutex) (count int, err *Err) {
	if n == 3 {
		pm.mu.Lock()
		defer pm.mu.Unlock()
		defer func() { // models "trap caught at the crew brace"; runs while the lock is held
			if r := recover(); r != nil {
				pm.poisoned = true
				err = &Err{Kind: "trap", Msg: fmt.Sprint("trapped: ", r)}
			}
		}()
	}
	cfg, err := parseFailFast(text)
	if err != nil {
		return 0, err.with(fmt.Sprintf("worker %d", n))
	}
	if n == 3 {
		keys := []string{}
		for _, e := range cfg.entries {
			keys = append(keys, e.key)
		}
		idx := len(keys) + 5
		return len(keys[idx]), nil // out of range: trap
	}
	return len(cfg.entries), nil
}

func part3() *Err {
	fmt.Println("== part 3: crew")
	pm := &poisonMutex{}
	errs := make([]*Err, 4)
	var wg sync.WaitGroup
	for i := range workerTexts {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, errs[i] = worker(i+1, workerTexts[i], pm)
		}()
	}
	wg.Wait()
	first, more := -1, 0
	for i, e := range errs {
		if e == nil {
			continue
		}
		if first < 0 {
			first = i
		} else {
			more++
		}
	}
	if first >= 0 {
		msg := "error: " + errs[first].Text()
		if more > 0 {
			msg += fmt.Sprintf(" (plus %d more)", more)
		}
		fmt.Println(msg)
	}
	pm.mu.Lock()
	fmt.Printf("mutex poisoned: %s\n", map[bool]string{true: "yes", false: "no"}[pm.poisoned])
	pm.mu.Unlock()
	if errs[2] == nil || errs[2].Kind != "trap" {
		return &Err{Kind: "assert", Msg: "worker 3 did not trap"}
	}
	fmt.Println("expect_trap ok")
	return nil
}

func main() {
	for _, p := range []func() *Err{part1, part2, part3} {
		if err := p(); err != nil {
			fmt.Println("fatal: " + err.Text())
			os.Exit(1)
		}
	}
}
