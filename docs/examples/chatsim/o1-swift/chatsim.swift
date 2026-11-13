// chatsim under model O1: pure ARC (final classes, weak for back-references), Swift 6.
// Build with -DNAIVE to get the first, leaking version (strong captures, strong user.room).
import Foundation

let rateLimit = 3
// Counters touched by init/deinit on the main thread only. Swift 6 rejects plain global vars,
// so they need nonisolated(unsafe): an unchecked escape hatch.
nonisolated(unsafe) var usersAlive = 0
nonisolated(unsafe) var roomsAlive = 0

func out(_ s: String) { print(s) }

final class User {
    let name: String
#if NAIVE
    var room: Room?        // strong: User -> Room -> callback -> User is a cycle
#else
    weak var room: Room?   // the server owns rooms; a user only observes its room
#endif
    weak var lastFrom: User?  // non-owning: a departed contact must not be kept alive
    var hadContact = false
    var isBot = false
    init(_ n: String) { name = n; usersAlive += 1 }
    deinit { usersAlive -= 1 }
}

final class Job { var roomName: String; var history: [String]
    init(_ n: String, _ h: [String]) { roomName = n; history = h } }

// Everything the worker thread touches. All fields are guarded by `cond` by discipline only;
// the compiler is told so with @unchecked Sendable.
final class Shared: @unchecked Sendable {
    let cond = NSCondition()
    var queue: [Job] = []
    var pending = 0
    var stop = false
    var finished = false
    var messages = 0, archivedRooms = 0, archivedMessages = 0
    var archive: [String] = []
    func countMessage() { cond.lock(); messages += 1; cond.unlock() }
}

final class RateLimiter {
    struct Entry { var tick: Int; var count: Int }
    var entries: [String: Entry] = [:]
    func ok(_ name: String, _ now: Int) -> Bool {
        var e = entries[name] ?? Entry(tick: now, count: 0)
        if e.tick != now { e.tick = now; e.count = 0 }
        if e.count >= rateLimit { out("rate limited: \(name)"); entries[name] = e; return false }
        e.count += 1
        entries[name] = e
        return true
    }
    func forget(_ name: String) { entries[name] = nil }
}

typealias OnMessage = (Room, User, String) -> Void
struct Member { weak var user: User?; var cb: OnMessage }

final class Room {
    let name: String
    var members: [Member] = []
    var history: [String] = []
    let sh: Shared
    init(_ n: String, _ s: Shared) { name = n; sh = s; roomsAlive += 1 }
    deinit { roomsAlive -= 1 }
}

final class Timer {
    let due: Int
    weak var user: User?  // the reminder must not keep its user alive
    let userName: String, text: String
    init(_ d: Int, _ u: User, _ n: String, _ t: String) { due = d; user = u; userName = n; text = t }
}

// Re-entrancy (case 20): a callback may call post() again. Index loop, and the callback is
// copied out of the array first, so a nested append cannot invalidate what runs.
func post(_ room: Room, _ from: User, _ text: String) {
    room.history.append("\(from.name): \(text)")
    room.sh.countMessage()
    out("#\(room.name) \(from.name): \(text)")
    var i = 0
    while i < room.members.count {
        let m = room.members[i]  // copies the closure (retain) and the weak ref (side-table traffic)
        if m.user !== from { m.cb(room, from, text) }
        i += 1
    }
}

func onMessage(_ me: User, _ room: Room, _ from: User, _ text: String) {
    out("  \(me.name) sees \(from.name): \(text)")
    if me.isBot && !from.isBot { post(room, me, "echo: \(text)") }
}

func makeCallback(_ u: User) -> OnMessage {
#if NAIVE
    return { room, from, text in onMessage(u, room, from, text) }  // strong capture: the room's closure owns the user
#else
    return { [weak u] room, from, text in if let me = u { onMessage(me, room, from, text) } }
#endif
}

final class Server {
    var users: [String: User] = [:]
    var rooms: [String: Room] = [:]
    var timers: [Timer] = []  // kept sorted by due, stable
    let rate = RateLimiter()
    let sh = Shared()
    var clockNow = 0

    init() {
        let sh = self.sh
        let t = Thread { Server.worker(sh) }
        t.start()
    }
    deinit {
        sh.cond.lock(); sh.stop = true; sh.cond.broadcast()
        while !sh.finished { sh.cond.wait() }   // Thread has no join(); wait for the worker's flag
        sh.cond.unlock()
    }

    static func worker(_ sh: Shared) {
        sh.cond.lock()
        while true {
            while sh.queue.isEmpty && !sh.stop { sh.cond.wait() }
            if sh.queue.isEmpty { break }
            let j = sh.queue.removeFirst()
            sh.cond.unlock()
            Thread.sleep(forTimeInterval: 0.02)
            var bytes = 0
            for m in j.history { bytes += m.utf8.count }
            let n = j.history.count
            let entry = "\(j.roomName): \(n) messages, \(bytes) bytes"
            j.history = []   // history freed here, on the worker thread
            sh.cond.lock()
            sh.archivedRooms += 1; sh.archivedMessages += n
            sh.archive.append(entry)
            sh.pending -= 1
            sh.cond.broadcast()
        }
        sh.finished = true
        sh.cond.broadcast()
        sh.cond.unlock()
    }

    func openRoom(_ name: String) -> Room {
        let r = Room(name, sh)
        rooms[name] = r
        out("#\(name) opened")
        return r
    }

    func enterRoom(_ u: User, _ roomName: String) {
        let r = rooms[roomName] ?? openRoom(roomName)
        r.members.append(Member(user: u, cb: makeCallback(u)))
        u.room = r
        out("\(u.name) joined #\(r.name)")
    }

    func exitRoom(_ u: User) {
        guard let r = u.room else { return }
#if NAIVE
        u.room = nil
#endif
        if let i = r.members.firstIndex(where: { $0.user === u }) { r.members.remove(at: i) }
        out("\(u.name) left #\(r.name)")
        if r.members.isEmpty {
            rooms[r.name] = nil
            out("#\(r.name) closed, \(r.history.count) messages sent to archive")
            let job = Job(r.name, r.history)   // array buffer is shared (COW), not copied
            r.history = []                      // ...and the room drops its reference: effectively a move
            sh.cond.lock(); sh.queue.append(job); sh.pending += 1; sh.cond.broadcast(); sh.cond.unlock()
        }
    }  // last strong ref to Room dies here -> deinit

    func deliverDm(_ from: User, _ to: User, _ text: String) {
        out("dm \(from.name) -> \(to.name): \(text)")
        out("  \(to.name) sees dm from \(from.name): \(text)")
        to.lastFrom = from; to.hadContact = true
        sh.countMessage()
    }

    func join(_ name: String, _ room: String) {
        if users[name] != nil { out("join failed: \(name) is already here"); return }
        let u = User(name)
        u.isBot = name == "echobot"
        users[name] = u
        enterRoom(u, room)
    }
    func say(_ name: String, _ text: String) {
        guard let u = users[name] else { out("say failed: \(name) is not here"); return }
        if !rate.ok(name, clockNow) { return }
        guard let r = u.room else { return }
        post(r, u, text)
    }
    func dm(_ fromName: String, _ toName: String, _ text: String) {
        guard let from = users[fromName] else { out("dm failed: \(fromName) is not here"); return }
        if !rate.ok(fromName, clockNow) { return }
        guard let to = users[toName] else { out("dm failed: \(toName) is not here"); return }
        deliverDm(from, to, text)
    }
    func reply(_ name: String, _ text: String) {
        guard let u = users[name] else { out("reply failed: \(name) is not here"); return }
        if !rate.ok(name, clockNow) { return }
        guard let to = u.lastFrom else {   // liveness comes from the weak ref reading nil
            out(u.hadContact ? "reply failed: \(name)'s last contact has left"
                             : "reply failed: \(name) has no one to reply to")
            return
        }
        deliverDm(u, to, text)
    }
    func remind(_ name: String, _ delay: Int, _ text: String) {
        guard let u = users[name] else { out("remind failed: \(name) is not here"); return }
        let t = Timer(clockNow + delay, u, name, text)
        let idx = timers.firstIndex(where: { $0.due > t.due }) ?? timers.count
        timers.insert(t, at: idx)
        out("reminder for \(name) set for tick \(t.due)")
    }
    func tick(_ n: Int) {
        for _ in 0..<max(n, 0) {
            clockNow += 1
            while let t = timers.first, t.due <= clockNow {
                timers.removeFirst()
                if let u = t.user { out("reminder for \(u.name): \(t.text)") }
                else { out("reminder for \(t.userName) dropped: user has left") }
            }
        }
        out("clock is \(clockNow)")
    }
    func move(_ name: String, _ room: String) {
        guard let u = users[name] else { out("move failed: \(name) is not here"); return }
        exitRoom(u)
        enterRoom(u, room)
    }
    func leave(_ name: String) {
        guard let u = users[name] else { out("leave failed: \(name) is not here"); return }
        exitRoom(u)
        users[name] = nil
        rate.forget(name)
    }  // u dies here -> deinit (unless something else still holds it)
    func stats() {
        sh.cond.lock()
        while sh.pending > 0 { sh.cond.wait() }
        out("stats: users=\(users.count) rooms=\(rooms.count) messages=\(sh.messages) archived_rooms=\(sh.archivedRooms) archived_messages=\(sh.archivedMessages)")
        for e in sh.archive { out("  archive \(e)") }
        sh.cond.unlock()
        out("  alive: users=\(usersAlive) rooms=\(roomsAlive)")
    }
}

func nextWord(_ s: [Character], _ p: inout Int) -> String? {
    while p < s.count && s[p] == " " { p += 1 }
    if p >= s.count { return nil }
    let b = p
    while p < s.count && s[p] != " " { p += 1 }
    return String(s[b..<p])
}
func rest(_ s: [Character], _ p: Int) -> String {
    var p = p
    while p < s.count && s[p] == " " { p += 1 }
    return String(s[p...])
}

func runServer() {
    let srv = Server()
    while var line = readLine(strippingNewline: true) {
        while line.hasSuffix("\r") { line.removeLast() }
        if line.isEmpty || line.hasPrefix("#") { continue }
        out("> \(line)")
        let s = Array(line)
        var p = 0
        guard let cmd = nextWord(s, &p) else { continue }
        var a: String?, b: String?
        func w1() -> Bool { a = nextWord(s, &p); return a != nil }
        func w2() -> Bool { w1() && { b = nextWord(s, &p); return b != nil }() }
        switch cmd {
        case "join" where w2(): srv.join(a!, b!)
        case "say" where w1(): srv.say(a!, rest(s, p))
        case "dm" where w2(): srv.dm(a!, b!, rest(s, p))
        case "reply" where w1(): srv.reply(a!, rest(s, p))
        case "remind" where w2(): srv.remind(a!, Int(b!) ?? 0, rest(s, p))
        case "tick" where w1(): srv.tick(Int(a!) ?? 0)
        case "move" where w2(): srv.move(a!, b!)
        case "leave" where w1(): srv.leave(a!)
        case "stats": srv.stats()
        default: out("bad command: \(cmd)")
        }
    }
}  // Server released here: worker joined, then maps, timers, rooms, users released

runServer()
out("exit: alive users=\(usersAlive) rooms=\(roomsAlive)")
