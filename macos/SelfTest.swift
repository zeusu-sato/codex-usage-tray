import AppKit

final class FixtureBackend: BackendCalling {
    var calls: [String] = []
    var enabled: [String: Bool] = [:]
    let lock = NSLock()
    func call(_ command: String, provider: String, extra: [String]) throws -> Reply {
        lock.lock(); defer { lock.unlock() }; calls.append(command + ":" + provider)
        switch command {
        case "usage-check": return ["ok": true, "stale": false, "blocked": false, "remaining_percent": provider == "codex" ? 68 : 24,
            "title": "Usage 残り " + (provider == "codex" ? "68%" : "24%"), "detail": "Weekly: 残り68% · リセット 09/15 15:29 JST\nテスト用データです。",
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
    controller.window.orderOut(nil)
    print("PASS: native provider selection, isolated ON/OFF, stale/invalid quota, icon sizes, no overlap, no routine AI, review quoting")
}
