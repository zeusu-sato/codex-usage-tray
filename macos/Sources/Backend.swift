import Foundation

typealias Reply = [String: Any]
extension Dictionary where Key == String, Value == Any {
    func text(_ key: String) -> String { self[key] as? String ?? "" }
    func flag(_ key: String) -> Bool { self[key] as? Bool ?? false }
}

enum TrayError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let text) = self { return text }; return nil }
}

final class Child {
    let pid: pid_t
    let output: FileHandle
    private let lock = NSLock()
    private var exitCode: Int32?
    init(executable: URL, arguments: [String]) throws {
        let strings = ([executable.path] + arguments).map { strdup($0) }
        defer { strings.forEach { free($0) } }
        var argv = strings + [nil]
        var descriptor: Int32 = -1
        pid = argv.withUnsafeMutableBufferPointer { usage_spawn(executable.path, $0.baseAddress, &descriptor) }
        guard pid > 1 else { throw TrayError.message("バックエンドを起動できません。アプリをフォルダーごと入れ直してください。") }
        output = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
    }
    func stop(force: Bool = false) {
        lock.lock(); defer { lock.unlock() }
        if exitCode == nil { usage_stop(pid, force ? 1 : 0) }
    }
    func wait() -> Int32 {
        while true {
            lock.lock()
            if let code = exitCode { lock.unlock(); return code }
            var code: Int32 = -1
            let result = usage_poll(pid, &code)
            if result != 0 {
                exitCode = result > 0 ? code : -1
                lock.unlock(); return result > 0 ? code : -1
            }
            lock.unlock()
            Thread.sleep(forTimeInterval: 0.01)
        }
    }
}

protocol BackendCalling: AnyObject {
    func call(_ command: String, provider: String, extra: [String]) throws -> Reply
    func shutdown()
}
extension BackendCalling { func shutdown() {} }

final class Backend: BackendCalling {
    let executable: URL
    let data: URL
    let prefix: [String]
    let timeoutSeconds: TimeInterval?
    let terminationGrace: TimeInterval
    private let childrenLock = NSLock()
    private var children: [pid_t: Child] = [:]
    private var closed = false
    init(executable: URL, data: URL, prefix: [String] = [], timeoutSeconds: TimeInterval? = nil, terminationGrace: TimeInterval = 4) {
        self.executable = executable; self.data = data; self.prefix = prefix
        self.timeoutSeconds = timeoutSeconds; self.terminationGrace = terminationGrace
    }
    func arguments(_ command: String, _ provider: String, _ extra: [String]) -> [String] {
        prefix + [command, "--provider", provider, "--data-dir", data.path] + extra
    }
    static func shellQuote(_ text: String) -> String { "'" + text.replacingOccurrences(of: "'", with: "'\"'\"'") + "'" }
    func reviewLauncher(provider: String, request: String) throws -> URL {
        guard ["codex", "claude"].contains(provider) else { throw TrayError.message("未対応のサービスです。") }
        let root = (provider == "claude" ? data.appendingPathComponent("providers/claude") : data)
            .appendingPathComponent("reviews").resolvingSymlinksInPath()
        let url = URL(fileURLWithPath: request).resolvingSymlinksInPath()
        guard url.lastPathComponent == "request.json", url.deletingLastPathComponent().deletingLastPathComponent() == root else {
            throw TrayError.message("見直し依頼の保存先を確認できません。")
        }
        let command = ([executable.path] + arguments("review-run", provider, ["--request", url.path])).map(Self.shellQuote).joined(separator: " ")
        let launcher = url.deletingLastPathComponent().appendingPathComponent("review-" + UUID().uuidString + ".command")
        let descriptor = open(launcher.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o700)
        guard descriptor >= 0 else { throw TrayError.message("見直し用の起動ファイルを作れません。") }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        try handle.write(contentsOf: Data(("#!/bin/zsh\nexec " + command + "\n").utf8))
        try handle.close()
        return launcher
    }
    func call(_ command: String, provider: String, extra: [String] = []) throws -> Reply {
        let commands = ["status", "ui-status", "ui-enable", "ui-disable", "monitor-check", "monitor-notified", "usage-check",
                        "client-list", "client-select", "review-status", "review-decide", "review-latest"]
        guard commands.contains(command), ["codex", "claude"].contains(provider) else {
            throw TrayError.message("この操作は通常のバックエンド呼び出しでは実行できません。")
        }
        let child: Child
        childrenLock.lock()
        do {
            guard !closed else { throw TrayError.message("アプリを終了しています。") }
            child = try Child(executable: executable, arguments: arguments(command, provider, extra))
            children[child.pid] = child; childrenLock.unlock()
        } catch { childrenLock.unlock(); throw error }
        let timeout = DispatchWorkItem {
            child.stop()
            DispatchQueue.global().asyncAfter(deadline: .now() + self.terminationGrace) { child.stop(force: true) }
        }
        DispatchQueue.global().asyncAfter(deadline: .now() + (timeoutSeconds ?? (command == "usage-check" ? 35 : 12)), execute: timeout)
        defer {
            timeout.cancel(); try? child.output.close()
            childrenLock.lock(); children.removeValue(forKey: child.pid); childrenLock.unlock()
        }
        var bytes = Data()
        do {
            while let chunk = try child.output.read(upToCount: 65536), !chunk.isEmpty {
                bytes.append(chunk)
                if bytes.count > 1024 * 1024 { throw TrayError.message("応答が大きすぎるため、取得を停止しました。") }
            }
        } catch {
            child.stop()
            DispatchQueue.global().asyncAfter(deadline: .now() + terminationGrace) { child.stop(force: true) }
            _ = child.wait(); throw error
        }
        let code = child.wait()
        guard code == 0, let reply = try? JSONSerialization.jsonObject(with: bytes) as? Reply else {
            throw TrayError.message("状態を取得できませんでした。クライアントのインストール・ログインを確認してください。")
        }
        return reply
    }
    func shutdown() {
        childrenLock.lock(); closed = true; let active = Array(children.values); childrenLock.unlock()
        active.forEach { $0.stop() }
        let force = DispatchWorkItem { active.forEach { $0.stop(force: true) } }
        DispatchQueue.global().asyncAfter(deadline: .now() + terminationGrace, execute: force)
        active.forEach { _ = $0.wait() }
        force.cancel()
    }
}
