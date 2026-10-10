import AppKit

final class FixtureBackend: BackendCalling {
    var calls: [String] = []
    var enabled: [String: Bool] = [:]
    var delayedCommand = ""
    var gate: DispatchSemaphore?
    let lock = NSLock()
    func call(_ command: String, provider: String, extra: [String]) throws -> Reply {
        lock.lock(); calls.append(command + ":" + provider)
        let pause = command == delayedCommand ? gate : nil; lock.unlock()
        if let pause = pause, pause.wait(timeout: .now() + 5) != .success { throw TrayError.message("Fixture gate timed out") }
        lock.lock(); defer { lock.unlock() }
        switch command {
        case "usage-check": return ["ok": true, "stale": false, "blocked": false, "remaining_percent": provider == "codex" ? 68 : 24,
            "title": "Usage 残り " + (provider == "codex" ? "68%" : "24%"), "detail": "Weekly: 残り" + (provider == "codex" ? "68%" : "24%") + " · リセット 09/15 15:29 JST\nテスト用データです。",
            "checked_label": "最終取得: Demo · 通常監視はAIを使いません", "tooltip": provider + " Demo quota",
            "forecast": ["status": provider == "codex" ? "comfortable" : "tight", "title": provider == "codex" ? "このペースなら余裕があります" : "リセットまでのペースに注意",
                         "detail": "最近の利用ペースから計算した目安です。今後の利用量で変わります。"]]
        case "monitor-check": return ["ok": true, "alert": false, "mismatch": false, "signature": String(repeating: "a", count: 64),
            "title": "監視の基準と一致しています", "detail": "対象: VS Code", "baseline_label": "監視開始時: Demo", "current_label": "現在: Demo"]
        case "ui-enable": enabled[provider] = true
        case "ui-disable": enabled[provider] = false
        case "ui-status": break
        case "review-status": return ["ok": true, "can_review": false, "should_prompt": false]
        default: throw TrayError.message("Unexpected fixture command: " + command)
        }
        return ["ok": true, "enabled": enabled[provider] ?? false, "can_enable": true,
                "title": "追加対策の候補があります", "detail": "これはテスト用データです。実際の設定は変更しません。"]
    }
    func count(_ command: String) -> Int { lock.lock(); defer { lock.unlock() }; return calls.filter { $0.hasPrefix(command + ":") }.count }
}

func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw TrayError.message("Self-test: " + message) }
}

func spinUntil(_ condition: () -> Bool) throws {
    let deadline = Date().addingTimeInterval(8)
    while !condition() && Date() < deadline { RunLoop.current.run(until: Date().addingTimeInterval(0.02)) }
    try require(condition(), "async operation timed out")
}

func savePNG(_ image: NSImage, _ destination: URL) throws {
    guard let tiff = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff), let bytes = bitmap.representation(using: .png, properties: [:]) else {
        throw TrayError.message("Cannot render PNG")
    }
    try bytes.write(to: destination)
}

func runSelfTests(output: URL) throws {
    try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
    let fixture = FixtureBackend()
    let controller = UsageController(backend: fixture)
    controller.buildWindow()
    controller.installStatusItems()
    defer { controller.applicationWillTerminate(Notification(name: NSApplication.willTerminateNotification)) }
    try require(controller.states.allSatisfy { $0.statusItem?.button != nil }, "Two actual menu-bar status items created")
    try require(controller.states[0].statusItem !== controller.states[1].statusItem, "Distinct provider status items")
    try require(controller.states.enumerated().allSatisfy { $0.element.statusItem?.button?.tag == $0.offset }, "Provider tray targets")
    controller.refreshAll(usage: true, monitor: true)
    try spinUntil { controller.states.allSatisfy { !$0.busy && !$0.quota.isEmpty } }
    try require(controller.remaining.stringValue == "68%", "Codex remaining")
    controller.selector.selectedSegment = 1; controller.providerChanged(controller.selector)
    try require(controller.remaining.stringValue == "24%", "Claude selection")
    controller.policySwitch.state = .on; controller.togglePolicy()
    try spinUntil { !controller.states[1].busy }
    try require(controller.states[1].policy.flag("enabled"), "Claude toggle enabled")
    try require(!controller.states[0].policy.flag("enabled"), "Codex policy isolation")
    controller.policySwitch.state = .off; controller.togglePolicy()
    try spinUntil { !controller.states[1].busy }
    try require(!controller.states[1].policy.flag("enabled"), "Claude toggle disabled")
    fixture.delayedCommand = "review-status"; fixture.gate = DispatchSemaphore(value: 0)
    controller.offerReview(controller.states[0], manual: true)
    controller.offerReview(controller.states[1], manual: true)
    controller.clientClicked()
    try require(controller.promptVisible && !controller.states[1].busy, "Modal reserved before asynchronous provider replies")
    try spinUntil { fixture.count("review-status") == 1 }
    try require(fixture.count("client-list") == 0, "Client sheet cannot race review confirmation")
    fixture.gate?.signal()
    try spinUntil { !controller.promptVisible && !controller.states[0].busy }
    fixture.delayedCommand = "ui-status"; fixture.gate = DispatchSemaphore(value: 0)
    var appliedLate = false, cancelledLate = false
    let state = controller.states[1]
    controller.perform(state, command: "ui-status", onFailure: { cancelledLate = true }) { _ in appliedLate = true }
    state.generation += 1; state.busy = false
    fixture.gate?.signal()
    try spinUntil { cancelledLate }
    try require(!appliedLate, "Reply from a previous client generation was discarded")
    fixture.delayedCommand = ""; fixture.gate = nil
    controller.setFeedback("Codex fixture message", for: controller.states[0])
    try require(controller.feedback.stringValue.isEmpty, "Inactive provider feedback does not leak into current tab")
    controller.states[0].feedback = ""
    let stale = ProviderState("codex"); stale.quota = ["ok": true, "stale": true, "remaining_percent": 93]
    try require(stale.remaining == nil, "Stale reading hidden")
    stale.quota = ["ok": true, "remaining_percent": true]
    try require(stale.remaining == nil, "Boolean is not a quota")
    for id in ["codex", "claude"] { for value in [0.0, 8, 11, 68, 88, 100] {
        try savePNG(TrayImage.make(provider: id, remaining: value, status: "comfortable", includeSymbol: false), output.appendingPathComponent("icon-\(id)-\(Int(value)).png"))
    } }
    try savePNG(TrayImage.make(provider: "codex", remaining: nil, status: "unavailable", includeSymbol: false), output.appendingPathComponent("icon-unavailable.png"))
    for index in 0...1 {
        controller.selected = index; controller.render(); controller.window.contentView?.layoutSubtreeIfNeeded()
        guard let view = controller.window.contentView, let image = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { throw TrayError.message("Cannot capture native window") }
        view.cacheDisplay(in: view.bounds, to: image)
        if let bytes = image.representation(using: .png, properties: [:]) { try bytes.write(to: output.appendingPathComponent("window-\(controller.states[index].id).png")) }
        let toggleFrame = controller.policySwitch.convert(controller.policySwitch.bounds, to: view)
        let textFrame = controller.policyTitle.convert(controller.policyTitle.bounds, to: view)
        try require(!toggleFrame.intersects(textFrame), "Toggle obscures text")
        try require(toggleFrame.width >= 30, "Native switch has usable size")
    }
    try require(!fixture.calls.contains(where: { $0.hasPrefix("review-run") || $0.hasPrefix("review-decide") }), "Routine UI started AI")
    try require(Backend.shellQuote("a'b $(x)") == "'a'\"'\"'b $(x)'", "Literal shell quoting")
    try runProcessSelfTests()
    controller.window.orderOut(nil)
    print("PASS: two menu-bar items, provider isolation, modal reservation, stale callback rejection, process timeout/shutdown, instance lock, no routine AI, review quoting")
}

func runProcessSelfTests() throws {
    let temporary = FileManager.default.temporaryDirectory.appendingPathComponent("usage-native-test-" + UUID().uuidString)
    try FileManager.default.createDirectory(at: temporary, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: temporary) }
    let instancePath = temporary.appendingPathComponent("instance.lock").path
    let first = usage_instance_lock(instancePath)
    try require(first >= 0, "First instance lock")
    let second = usage_instance_lock(instancePath)
    if second >= 0 { close(second) }
    close(first)
    try require(second < 0, "Concurrent instance rejected")
    let reopened = usage_instance_lock(instancePath)
    try require(reopened >= 0, "Instance lock released on close")
    close(reopened)
    let successful = Backend(executable: URL(fileURLWithPath: "/bin/sh"), data: temporary,
                             prefix: ["-c", "printf '{\"ok\":true}\\n'"], timeoutSeconds: 2, terminationGrace: 0.1)
    let successfulReply = try successful.call("usage-check", provider: "codex")
    try require(successfulReply.flag("ok"), "Native pipe JSON reply")
    for command in ["review-run", "unrecognized-command"] {
        var rejected = false
        do { _ = try successful.call(command, provider: "codex") } catch { rejected = true }
        try require(rejected, "Routine allowlist rejected " + command)
    }
    let child = try Child(executable: URL(fileURLWithPath: "/bin/sh"), arguments: ["-c", "exit 7"])
    try require(child.wait() == 7 && child.wait() == 7, "Wait results are cached atomically")
    child.stop(force: true); try child.output.close()
    let hanging = Backend(executable: URL(fileURLWithPath: "/bin/sh"), data: temporary,
                          prefix: ["-c", "trap '' TERM; while :; do sleep 1; done"], timeoutSeconds: 0.1, terminationGrace: 0.1)
    var timedOut = false
    let started = Date()
    do { _ = try hanging.call("usage-check", provider: "codex") } catch { timedOut = true }
    try require(timedOut && Date().timeIntervalSince(started) < 3, "Ignoring TERM still has a bounded group timeout")
    let ready = temporary.appendingPathComponent("ready")
    let stopping = Backend(executable: URL(fileURLWithPath: "/bin/sh"), data: temporary,
                           prefix: ["-c", "trap '' TERM; : > " + Backend.shellQuote(ready.path) + "; while :; do sleep 1; done"],
                           timeoutSeconds: 10, terminationGrace: 0.1)
    let completed = DispatchSemaphore(value: 0)
    DispatchQueue.global().async { _ = try? stopping.call("usage-check", provider: "claude"); completed.signal() }
    try spinUntil { FileManager.default.fileExists(atPath: ready.path) }
    stopping.shutdown()
    try require(completed.wait(timeout: .now() + 2) == .success, "Application exit reaps active backends and pipe descendants")
    var closed = false
    do { _ = try stopping.call("ui-status", provider: "claude") } catch { closed = true }
    try require(closed, "No backend launches after shutdown")
    let request = temporary.appendingPathComponent("reviews/approved/request.json")
    try FileManager.default.createDirectory(at: request.deletingLastPathComponent(), withIntermediateDirectories: true)
    try Data("{}".utf8).write(to: request)
    let launcher = try successful.reviewLauncher(provider: "codex", request: request.path)
    let permissions = try FileManager.default.attributesOfItem(atPath: launcher.path)[.posixPermissions] as? NSNumber
    try require(permissions?.intValue == 0o700, "Review launcher is private and executable")
    var escaped = false
    do { _ = try successful.reviewLauncher(provider: "claude", request: request.path) } catch { escaped = true }
    try require(escaped, "Review launcher cannot cross provider folders")
}
