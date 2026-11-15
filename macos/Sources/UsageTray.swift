import AppKit
import ServiceManagement

final class TrayBackground: NSView {
    override func draw(_ dirtyRect: NSRect) { NSColor.windowBackgroundColor.setFill(); dirtyRect.fill() }
}
final class TrayDocument: NSView {
    override var isFlipped: Bool { true }
}

final class ProviderState {
    let id: String
    var quota: Reply = [:], policy: Reply = [:], monitor: Reply = [:]
    var busy = false
    var generation = 0
    var prompted = Set<String>()
    var feedback = ""
    var statusItem: NSStatusItem?
    init(_ id: String) { self.id = id }
    var name: String { id == "claude" ? "Claude Code" : "Codex" }
    var credit: Reply? {
        guard let credit = quota["credit"] as? Reply,
              ["codex_credits", "claude_extra_usage"].contains(credit.text("kind")),
              let text = credit["tray_text"] as? String, text.range(of: #"\A(?:[0-9]{1,3}|[1-9][0-9]?[kMG]|\.[1-9][MG]|\u221e|\u00a4)\z"#, options: .regularExpression) != nil,
              let known = credit["amount_known"] as? NSNumber, CFGetTypeID(known) == CFBooleanGetTypeID(),
              credit["title"] is String, credit["summary"] is String else { return nil }
        return credit
    }
    var remaining: Double? {
        guard quota.flag("ok"), !quota.flag("stale"), !quota.flag("blocked"),
              (quota["credit"] == nil || quota["credit"] is NSNull || credit != nil),
              let number = quota["remaining_percent"] as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite, (0...100).contains(number.doubleValue) else { return nil }
        return number.doubleValue
    }
    var forecast: Reply { quota["forecast"] as? Reply ?? [:] }
}

final class UsageController: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let backend: BackendCalling
    let states = [ProviderState("codex"), ProviderState("claude")]
    var selected = 0
    var window: NSWindow!
    var timers: [Timer] = []
    var exiting = false
    var promptVisible = false
    var initialized = false
    var showRequested = false
    let selector = NSSegmentedControl(labels: ["Codex", "Claude"], trackingMode: .selectOne, target: nil, action: nil)
    let remaining = NSTextField(labelWithString: "?")
    let usageTitle = NSTextField(wrappingLabelWithString: "残量を確認しています")
    let quotaDetail = NSTextField(wrappingLabelWithString: "")
    let checked = NSTextField(wrappingLabelWithString: "")
    let forecastTitle = NSTextField(wrappingLabelWithString: "予測: 未確認")
    let policyTitle = NSTextField(wrappingLabelWithString: "追加対策")
    let policyDetail = NSTextField(wrappingLabelWithString: "")
    let policySwitch = NSSwitch()
    let policyState = NSTextField(labelWithString: "OFF")
    let monitorTitle = NSTextField(wrappingLabelWithString: "バージョンを確認しています")
    let monitorDetail = NSTextField(wrappingLabelWithString: "")
    let feedback = NSTextField(wrappingLabelWithString: "")
    let refreshButton = NSButton(title: "更新", target: nil, action: nil)
    let reviewButton = NSButton(title: "AIレビュー…", target: nil, action: nil)
    let reportButton = NSButton(title: "AIレビューの結果", target: nil, action: nil)
    let clientButton = NSButton(title: "クライアントを選ぶ…", target: nil, action: nil)
    let loginButton = NSButton(checkboxWithTitle: "ログイン時に起動", target: nil, action: nil)
    let quitButton = NSButton(title: "終了", target: nil, action: nil)

    init(backend: BackendCalling) { self.backend = backend; super.init() }
    func applicationDidFinishLaunching(_ notification: Notification) {
        buildWindow()
        installStatusItems()
        initialized = true
        refreshAll(usage: true, monitor: true)
        timers.append(Timer.scheduledTimer(withTimeInterval: 300, repeats: true) { [weak self] _ in self?.refreshAll(usage: true, monitor: false) })
        timers.append(Timer.scheduledTimer(withTimeInterval: 900, repeats: true) { [weak self] _ in self?.refreshAll(usage: false, monitor: true) })
        let opened = UserDefaults.standard.bool(forKey: "HasOpened")
        if !opened || showRequested { UserDefaults.standard.set(true, forKey: "HasOpened"); showWindow() }
    }
    func installStatusItems() {
        for (index, state) in states.enumerated() {
            guard state.statusItem == nil else { continue }
            let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
            state.statusItem = item
            item.autosaveName = "usage-" + state.id
            item.button?.tag = index
            item.button?.target = self; item.button?.action = #selector(trayClicked(_:))
            item.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])
            renderIcon(state)
        }
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { showWindow(); return true }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationWillTerminate(_ notification: Notification) {
        exiting = true; timers.forEach { $0.invalidate() }
        backend.shutdown()
        for state in states { if let item = state.statusItem { NSStatusBar.system.removeStatusItem(item) } }
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool { sender.orderOut(nil); return false }
    func windowDidBecomeKey(_ notification: Notification) {
        if initialized { refresh(states[selected], usage: false, monitor: false) }
    }
}
