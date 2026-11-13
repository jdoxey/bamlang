// E1: every fallible function `throws`; one error type (Err) used everywhere; `try` at every call;
// context added with the `ctx` helper; Optional for absence.
import Foundation

// ---- the one error type ----

enum Kind: String, Sendable { case parse, io, injected, trap }

struct Err: Error, Sendable, CustomStringConvertible {
    var kind: Kind
    var message: String
    var context: [String] = []  // innermost first
    var trace: [String] = []    // appended at each propagation helper
    var description: String { (context.reversed() + [message]).joined(separator: ": ") }
}

/// Propagation helper: adds context and a trace entry to whatever the body throws.
func ctx<T>(_ c: String, line: Int = #line, function: String = #function, _ body: () throws -> T) throws -> T {
    do {
        return try body()
    } catch var e as Err {
        e.context.append(c)
        e.trace.append("\(function):\(line)")
        throw e
    } catch {  // conversion glue: foreign errors become Err
        throw Err(kind: .io, message: "\(error)", context: [c], trace: ["\(function):\(line)"])
    }
}

// ---- part 1 ----

struct Config {
    var entries: [(section: String, key: String, value: String)] = []
    func get(_ section: String, _ key: String) -> String? {
        entries.first { $0.section == section && $0.key == key }?.value
    }
}

struct Parser {
    var cfg = Config()
    var section = ""
}

func parseLine(_ p: inout Parser, _ no: Int, _ raw: String) throws {
    let line = raw.trimmingCharacters(in: .whitespaces)
    if line.isEmpty || line.hasPrefix("#") { return }
    if line.hasPrefix("[") && line.hasSuffix("]") {
        p.section = String(line.dropFirst().dropLast())
        return
    }
    guard let eq = line.firstIndex(of: "=") else {
        throw Err(kind: .parse, message: "config.ini:\(no): missing '='")
    }
    let key = line[..<eq].trimmingCharacters(in: .whitespaces)
    if key.isEmpty { throw Err(kind: .parse, message: "config.ini:\(no): empty key") }
    if p.cfg.get(p.section, key) != nil {
        throw Err(kind: .parse, message: "config.ini:\(no): duplicate key '\(key)' in [\(p.section)]")
    }
    let value = line[line.index(after: eq)...].trimmingCharacters(in: .whitespaces)
    p.cfg.entries.append((p.section, key, value))
}

func parseFailFast(_ text: String) throws -> Config {
    var p = Parser()
    for (i, l) in text.split(separator: "\n", omittingEmptySubsequences: false).enumerated() {
        try parseLine(&p, i + 1, String(l))
    }
    return p.cfg
}

func parseAll(_ text: String) -> (Config, [Err]) {
    var p = Parser()
    var errs: [Err] = []
    for (i, l) in text.split(separator: "\n", omittingEmptySubsequences: false).enumerated() {
        do { try parseLine(&p, i + 1, String(l)) } catch let e as Err { errs.append(e) } catch {}
    }
    return (p.cfg, errs)
}

func parseInt(_ s: String) throws -> Int {
    guard let n = Int(s) else { throw Err(kind: .parse, message: "not an integer: \(s)") }
    return n
}

let badText = "# sample config\n[server]\nport = 8080\nhost\n= nokey\nport = 9090\n[db]\nname = x\n"
let goodText = "# sample config\n[server]\nport = 8080\nhost = localhost\n[db]\nname = x\n"

func part1() throws {
    print("== part 1: config parser")
    do { _ = try parseFailFast(badText) } catch { print("fail-fast: \(error)") }
    let (_, errs) = parseAll(badText)
    print("collect-all:")
    for e in errs { print("  \(e)") }
    print("\(errs.count) errors")

    let cfg = try parseFailFast(goodText)
    if let s = cfg.get("server", "port") {
        let port = try ctx("server.port") { try parseInt(s) }
        print("server.port = \(port)")
    }
    if let s = cfg.get("server", "timeout") {
        print("server.timeout = \(s)")
    } else {
        print("timeout not set, using 30")
    }
}

// ---- part 2 ----

func inject(_ failAt: Int, _ step: Int) throws {
    if failAt == step { throw Err(kind: .injected, message: "injected failure") }
}

func posix(_ rc: Int32) throws {
    if rc != 0 { throw Err(kind: .io, message: String(cString: strerror(errno))) }
}

func replaceFile(dir: String, name: String, content: String, failAt: Int) throws {
    let lock = dir + "/" + name + ".lock"
    let tmp = dir + "/" + name + ".tmp"
    let dst = dir + "/" + name
    let fm = FileManager.default
    var held = false
    defer {  // cleanup cannot fail
        if held { try? fm.removeItem(atPath: lock) }
        try? fm.removeItem(atPath: tmp)
    }

    try ctx("step 1: create lock") {
        let fd = open(lock, O_CREAT | O_EXCL | O_WRONLY, 0o644)
        if fd < 0 { try posix(-1) }
        close(fd)
        held = true
        try inject(failAt, 1)
    }
    try ctx("step 2: write temp") {
        try Data(content.utf8).write(to: URL(fileURLWithPath: tmp))
        try inject(failAt, 2)
    }
    try ctx("step 3: rename temp") {
        try inject(failAt, 3)
        try posix(rename(tmp, dst))
    }
    try ctx("step 4: remove lock") {
        try inject(failAt, 4)
        try fm.removeItem(atPath: lock)
        held = false
    }
}

func part2() throws {
    print("== part 2: replace_file")
    let fm = FileManager.default
    let dir = NSTemporaryDirectory() + "errors-e1-\(getpid())"
    try ctx("make temp dir") { try fm.createDirectory(atPath: dir, withIntermediateDirectories: true) }
    defer { try? fm.removeItem(atPath: dir) }
    try ctx("seed data.txt") { try Data("old".utf8).write(to: URL(fileURLWithPath: dir + "/data.txt")) }
    print("start: content old")
    let labels = ["no failure", "fail at step 1", "fail at step 2", "fail at step 3", "fail at step 4"]
    for run in 0..<5 {
        var res = "ok"
        do { try replaceFile(dir: dir, name: "data.txt", content: "v\(run + 1)", failAt: run) } catch { res = "error: \(error)" }
        print("run \(run + 1), \(labels[run]): \(res)")
        let files = try ctx("list dir") { try fm.contentsOfDirectory(atPath: dir).sorted().joined(separator: " ") }
        let content = try ctx("read data.txt") { try String(contentsOfFile: dir + "/data.txt", encoding: .utf8) }
        print("  files: \(files)\n  content: \(content)")
    }
}

// ---- part 3 ----

let workerTexts = [
    "[a]\nx = 1\n",
    "[b]\nname = w2\nbroken line\n",
    "[c]\nz = 3\n",
    "[d]\nk = 4\n",
]

/// Runs in a child process (re-exec of self): swift traps are not catchable in-process.
func trapChild() -> Never {
    let m = NSLock()
    m.lock()  // holding the lock when the trap happens
    let keys = ((try? parseFailFast(workerTexts[2])) ?? Config()).entries.map { $0.key }
    let idx = keys.count + 5
    print(keys[idx])  // out of range: trap
    exit(0)
}

final class Shared: @unchecked Sendable {
    private let lock = NSLock()
    private var results: [Result<Int, Err>?] = Array(repeating: nil, count: 4)
    private var poisonedFlag = false
    func set(_ i: Int, _ r: Result<Int, Err>) { lock.lock(); results[i] = r; lock.unlock() }
    func get(_ i: Int) -> Result<Int, Err>? { lock.lock(); defer { lock.unlock() }; return results[i] }
    func poison() { lock.lock(); poisonedFlag = true; lock.unlock() }
    var poisoned: Bool { lock.lock(); defer { lock.unlock() }; return poisonedFlag }
}

func runTrapChild() throws -> Int {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: CommandLine.arguments[0])
    p.arguments = ["--trap-worker3"]
    p.standardOutput = FileHandle.nullDevice
    p.standardError = FileHandle.nullDevice
    try p.run()
    p.waitUntilExit()
    if p.terminationReason == .uncaughtSignal { throw Err(kind: .trap, message: "trapped") }
    return 0
}

func worker(_ n: Int, _ text: String, _ shared: Shared) throws -> Int {
    try ctx("worker \(n)") {
        let cfg = try parseFailFast(text)
        if n == 3 {
            do { return try runTrapChild() } catch let e as Err where e.kind == .trap {
                shared.poison()  // model limitation: flag set by the parent when the child reports the trap
                throw e
            }
        }
        return cfg.entries.count
    }
}

func part3() throws {
    print("== part 3: crew")
    let shared = Shared()
    DispatchQueue.concurrentPerform(iterations: 4) { i in
        do { shared.set(i, .success(try worker(i + 1, workerTexts[i], shared))) }
        catch let e as Err { shared.set(i, .failure(e)) }
        catch {}
    }
    var errs: [Err] = []
    for i in 0..<4 { if case .failure(let e)? = shared.get(i) { errs.append(e) } }
    if let first = errs.first {
        let more = errs.count - 1
        print("error: \(first)" + (more > 0 ? " (plus \(more) more)" : ""))
    }
    print("mutex poisoned: \(shared.poisoned ? "yes" : "no")")
    guard case .failure(let e3)? = shared.get(2), e3.kind == .trap else {
        throw Err(kind: .injected, message: "worker 3 did not trap")
    }
    print("expect_trap ok")
}

func main() {
    if CommandLine.arguments.contains("--trap-worker3") { trapChild() }
    do {
        try part1()
        try part2()
        try part3()
    } catch {
        print("fatal: \(error)")
        exit(1)
    }
}
main()
