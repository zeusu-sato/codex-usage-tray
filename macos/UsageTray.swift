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
    var remaining: Double? {
        guard quota.flag("ok"), !quota.flag("stale"), !quota.flag("blocked"),
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
    let checked = NSTextField(wrappingLabelWithString: "通常監視ではAIを使いません")
    let forecastTitle = NSTextField(wrappingLabelWithString: "見通しを確認しています")
    let forecastDetail = NSTextField(wrappingLabelWithString: "")
    let policyTitle = NSTextField(wrappingLabelWithString: "追加対策")
    let policyDetail = NSTextField(wrappingLabelWithString: "")
    let policySwitch = NSSwitch()
    let policyState = NSTextField(labelWithString: "OFF")
    let monitorTitle = NSTextField(wrappingLabelWithString: "バージョンを確認しています")
    let monitorDetail = NSTextField(wrappingLabelWithString: "")
    let feedback = NSTextField(wrappingLabelWithString: "")
    let refreshButton = NSButton(title: "更新", target: nil, action: nil)
    let reviewButton = NSButton(title: "AIで見直す…", target: nil, action: nil)
    let reportButton = NSButton(title: "結果を開く", target: nil, action: nil)
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
    func row(_ views: [NSView]) -> NSStackView {
        let stack = NSStackView(views: views); stack.orientation = .horizontal; stack.spacing = 10; stack.alignment = .centerY
        return stack
    }
    func spacer() -> NSView { let v = NSView(); v.setContentHuggingPriority(.defaultLow, for: .horizontal); return v }
    func label(_ text: String, size: CGFloat = 12, secondary: Bool = false) -> NSTextField {
        let field = NSTextField(wrappingLabelWithString: text); field.font = .systemFont(ofSize: size)
        if secondary { field.textColor = .secondaryLabelColor }
        return field
    }
    func buildWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 540, height: 760), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Codex + Claude Usage"; window.minSize = NSSize(width: 520, height: 540); window.delegate = self
        window.isReleasedWhenClosed = false; window.center()
        window.contentView = TrayBackground(frame: NSRect(x: 0, y: 0, width: 540, height: 760))
        selector.selectedSegment = selected; selector.target = self; selector.action = #selector(providerChanged(_:))
        selector.setAccessibilityLabel("表示するサービス")
        refreshButton.target = self; refreshButton.action = #selector(refreshClicked)
        remaining.font = .monospacedDigitSystemFont(ofSize: 48, weight: .semibold)
        remaining.setAccessibilityLabel("残り使用枠")
        usageTitle.font = .systemFont(ofSize: 15, weight: .semibold)
        quotaDetail.font = .systemFont(ofSize: 12); checked.font = .systemFont(ofSize: 11); checked.textColor = .secondaryLabelColor
        forecastTitle.font = .systemFont(ofSize: 14, weight: .semibold)
        forecastDetail.font = .systemFont(ofSize: 12); forecastDetail.textColor = .secondaryLabelColor
        policyTitle.font = .systemFont(ofSize: 14, weight: .semibold)
        policySwitch.target = self; policySwitch.action = #selector(togglePolicy)
        policySwitch.setAccessibilityLabel("追加対策の有効・無効")
        policyState.font = .systemFont(ofSize: 12, weight: .semibold)
        policyDetail.font = .systemFont(ofSize: 12)
        monitorTitle.font = .systemFont(ofSize: 13, weight: .semibold)
        monitorDetail.font = .systemFont(ofSize: 11); monitorDetail.textColor = .secondaryLabelColor
        feedback.font = .systemFont(ofSize: 12); feedback.textColor = .secondaryLabelColor
        reviewButton.target = self; reviewButton.action = #selector(reviewClicked)
        reportButton.target = self; reportButton.action = #selector(reportClicked)
        clientButton.target = self; clientButton.action = #selector(clientClicked)
        loginButton.target = self; loginButton.action = #selector(loginChanged)
        loginButton.state = SMAppService.mainApp.status == .enabled ? .on : .off
        quitButton.target = self; quitButton.action = #selector(quit)
        let line = NSBox(); line.boxType = .separator
        let line2 = NSBox(); line2.boxType = .separator
        let stack = NSStackView(views: [row([selector, spacer(), refreshButton]), remaining, usageTitle, quotaDetail, checked,
            forecastTitle, forecastDetail, line, row([policyTitle, spacer(), policyState, policySwitch]), policyDetail,
            label("環境が変わると旧対策は適用しません · 固定期限なし", size: 11, secondary: true),
            row([reviewButton, reportButton, spacer()]), feedback, monitorTitle, monitorDetail,
            row([clientButton, spacer()]), line2, row([loginButton, spacer(), quitButton]),
            label("残量は5分ごと、バージョンは15分ごとに確認します。通常監視はAI推論を使いません。", size: 11, secondary: true)])
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 12; stack.translatesAutoresizingMaskIntoConstraints = false
        let scroll = NSScrollView(); scroll.hasVerticalScroller = true; scroll.drawsBackground = false
        scroll.translatesAutoresizingMaskIntoConstraints = false
        let document = TrayDocument(); document.translatesAutoresizingMaskIntoConstraints = false; document.addSubview(stack)
        scroll.documentView = document; window.contentView!.addSubview(scroll)
        NSLayoutConstraint.activate([
            scroll.topAnchor.constraint(equalTo: window.contentView!.topAnchor), scroll.bottomAnchor.constraint(equalTo: window.contentView!.bottomAnchor),
            scroll.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor), scroll.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor),
            document.widthAnchor.constraint(equalTo: scroll.contentView.widthAnchor), stack.topAnchor.constraint(equalTo: document.topAnchor, constant: 20),
            stack.leadingAnchor.constraint(equalTo: document.leadingAnchor, constant: 24), stack.trailingAnchor.constraint(equalTo: document.trailingAnchor, constant: -24),
            stack.bottomAnchor.constraint(equalTo: document.bottomAnchor, constant: -20)])
        for view in stack.arrangedSubviews { view.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true }
        render()
    }
    func renderIcon(_ state: ProviderState) {
        state.statusItem?.button?.image = TrayImage.make(provider: state.id, remaining: state.remaining, status: state.forecast.text("status"))
        let tooltip = state.quota.text("tooltip")
        state.statusItem?.button?.toolTip = state.name + " · " + (tooltip.isEmpty ? "残量を確認しています" : tooltip)
        state.statusItem?.button?.setAccessibilityLabel(state.name + " 使用枠 " + (state.remaining.map { String(Int($0)) + "%" } ?? "未確認"))
    }
    func render() {
        guard window != nil else { return }
        let state = states[selected]
        feedback.stringValue = state.feedback
        selector.selectedSegment = selected
        remaining.stringValue = state.remaining.map { String(Int(floor($0))) + "%" } ?? "?"
        remaining.textColor = TrayImage.color(state.remaining, state.forecast.text("status"))
        usageTitle.stringValue = state.quota.text("title").isEmpty ? state.name + "の残量を確認しています" : state.quota.text("title")
        quotaDetail.stringValue = state.quota.text("detail")
        checked.stringValue = state.quota.text("checked_label")
        forecastTitle.stringValue = state.forecast.text("title")
        forecastTitle.textColor = remaining.textColor; forecastDetail.stringValue = state.forecast.text("detail")
        policyTitle.stringValue = state.policy.text("title").isEmpty ? "追加対策" : state.policy.text("title")
        policyDetail.stringValue = state.policy.text("detail")
        policySwitch.state = state.policy.flag("enabled") ? .on : .off
        policyState.stringValue = policySwitch.state == .on ? "ON" : "OFF"
        policySwitch.isEnabled = !state.busy && (state.policy.flag("enabled") || state.policy.flag("can_enable"))
        monitorTitle.stringValue = state.monitor.text("title")
        monitorDetail.stringValue = [state.monitor.text("detail"), state.monitor.text("baseline_label"), state.monitor.text("current_label"), state.monitor.text("checked_label")].filter { !$0.isEmpty }.joined(separator: "\n")
        refreshButton.isEnabled = !state.busy; clientButton.isEnabled = !state.busy && !promptVisible
        reviewButton.isEnabled = !state.busy && !promptVisible && state.monitor.flag("ok") && !state.monitor.text("signature").isEmpty
        reportButton.isEnabled = !state.busy
    }
    func refreshAll(usage: Bool, monitor: Bool) { for state in states { refresh(state, usage: usage, monitor: monitor) } }
    func refresh(_ state: ProviderState, usage: Bool, monitor: Bool) {
        guard !exiting, !state.busy else { return }
        state.busy = true; render()
        let generation = state.generation
        DispatchQueue.global(qos: .utility).async {
            var quota: Reply?, version: Reply?, policy: Reply?, failure: String?
            do {
                if usage { quota = try self.backend.call("usage-check", provider: state.id, extra: []) }
                if monitor { version = try self.backend.call("monitor-check", provider: state.id, extra: []) }
                policy = try self.backend.call("ui-status", provider: state.id, extra: [])
            } catch { failure = error.localizedDescription }
            DispatchQueue.main.async {
                guard !self.exiting, state.generation == generation else { return }
                state.busy = false
                if let quota = quota { state.quota = quota }
                if let version = version { state.monitor = version }
                if let policy = policy { state.policy = policy }
                if let failure = failure {
                    if usage { state.quota = ["ok": false, "title": "現在の残量は未確認です", "detail": failure] }
                    if monitor { state.monitor = ["ok": false, "title": "バージョンは未確認です", "detail": failure] }
                    state.policy = ["enabled": false, "can_enable": false, "title": "状態を確認できません", "detail": failure]
                    state.feedback = failure
                }
                self.renderIcon(state); self.render()
                if version?.flag("alert") == true { self.offerReview(state, manual: false) }
            }
        }
    }
    func showWindow() { showRequested = true; NSApp.activate(ignoringOtherApps: true); window?.makeKeyAndOrderFront(nil) }
    @objc func trayClicked(_ sender: NSStatusBarButton) {
        selected = sender.tag; render()
        if NSApp.currentEvent?.type == .rightMouseUp {
            let menu = NSMenu()
            let open = menu.addItem(withTitle: states[selected].name + "の残量を開く", action: #selector(openFromMenu), keyEquivalent: ""); open.target = self
            let update = menu.addItem(withTitle: "更新", action: #selector(refreshClicked), keyEquivalent: ""); update.target = self
            menu.addItem(.separator()); let exit = menu.addItem(withTitle: "終了", action: #selector(quit), keyEquivalent: "q"); exit.target = self
            states[selected].statusItem?.menu = menu
            sender.performClick(nil)
            states[selected].statusItem?.menu = nil
        } else { showWindow() }
    }
    @objc func openFromMenu() { showWindow() }
    @objc func providerChanged(_ sender: NSSegmentedControl) {
        guard states.indices.contains(sender.selectedSegment) else { return }
        selected = sender.selectedSegment; render()
    }
    @objc func refreshClicked() { refresh(states[selected], usage: true, monitor: true) }
    @objc func quit() { NSApp.terminate(nil) }
    func setFeedback(_ text: String, for state: ProviderState) { state.feedback = text; render() }
    func failure(_ error: Error, for state: ProviderState? = nil) {
        setFeedback(error.localizedDescription, for: state ?? states[selected]); showWindow()
    }
    func reserveModal() -> Bool {
        guard !exiting, !promptVisible, window.attachedSheet == nil else { return false }
        promptVisible = true; render(); return true
    }
    func releaseModal() { promptVisible = false; render() }
    func perform(_ state: ProviderState, command: String, extra: [String] = [], onFailure: (() -> Void)? = nil, done: @escaping (Reply) -> Void) {
        guard !exiting, !state.busy else { onFailure?(); return }
        state.busy = true; render()
        let generation = state.generation
        DispatchQueue.global(qos: .utility).async {
            let result = Result { try self.backend.call(command, provider: state.id, extra: extra) }
            DispatchQueue.main.async {
                guard !self.exiting, generation == state.generation else { onFailure?(); return }
                state.busy = false; self.render()
                switch result { case .success(let reply): done(reply); case .failure(let error): onFailure?(); self.failure(error, for: state) }
            }
        }
    }
    @objc func togglePolicy() {
        let state = states[selected]; let command = policySwitch.state == .on ? "ui-enable" : "ui-disable"
        render()
        perform(state, command: command) { reply in state.policy = reply; self.render() }
    }
    @objc func reviewClicked() { offerReview(states[selected], manual: true) }
    func offerReview(_ state: ProviderState, manual: Bool) {
        let signature = state.monitor.text("signature")
        guard !signature.isEmpty, !state.busy, manual || !state.prompted.contains(signature), reserveModal() else { return }
        perform(state, command: "review-status", extra: ["--signature", signature], onFailure: { self.releaseModal() }) { reply in
            guard reply.flag("ok"), reply.flag("can_review"), manual || reply.flag("should_prompt") else { self.releaseModal(); return }
            state.busy = true; state.prompted.insert(signature)
            self.selected = self.states.firstIndex { $0 === state }!; self.render(); self.showWindow()
            let alert = NSAlert(); alert.messageText = state.name + "の対策をAIで見直しますか？"
            alert.informativeText = reply.text("detail") + "\n\n「はい」でTerminalを開き、対話形式で見直します。Claudeの見直しにもCodexのUsageを使います。"
            alert.addButton(withTitle: "いいえ (No)"); alert.addButton(withTitle: "はい (Yes)")
            alert.beginSheetModal(for: self.window) { response in
                self.releaseModal(); state.busy = false
                guard !self.exiting else { return }
                let yes = response == .alertSecondButtonReturn
                self.perform(state, command: "review-decide", extra: ["--signature", signature, "--decision", yes ? "yes" : "no"]) { decision in
                    if yes {
                        guard decision.flag("ok"), !decision.text("request_path").isEmpty, let actual = self.backend as? Backend else {
                            self.setFeedback("AI見直しを開始できませんでした。状態を更新してください。", for: state); return
                        }
                        do {
                            let launcher = try actual.reviewLauncher(provider: state.id, request: decision.text("request_path"))
                            let terminal = URL(fileURLWithPath: "/System/Applications/Utilities/Terminal.app")
                            NSWorkspace.shared.open([launcher], withApplicationAt: terminal, configuration: NSWorkspace.OpenConfiguration()) { _, error in
                                DispatchQueue.main.async {
                                    guard !self.exiting else { return }
                                    if let error = error { self.failure(error, for: state) }
                                    else { self.setFeedback("Terminalで見直しを開始しました。完了後、結果を確認してください。", for: state) }
                                }
                            }
                        } catch { self.failure(error, for: state) }
                    } else { self.setFeedback("AI見直しは開始していません。通常の監視を続けます。", for: state) }
                }
            }
        }
    }
    @objc func reportClicked() {
        let state = states[selected]
        perform(state, command: "review-latest") { reply in
            guard reply.flag("ok"), let actual = self.backend as? Backend else { self.setFeedback(reply.text("detail"), for: state); return }
            let root = (state.id == "claude" ? actual.data.appendingPathComponent("providers/claude") : actual.data).appendingPathComponent("reviews").resolvingSymlinksInPath()
            let url = URL(fileURLWithPath: reply.text("report_path")).resolvingSymlinksInPath()
            guard url.lastPathComponent == "report.md", url.deletingLastPathComponent().deletingLastPathComponent() == root else {
                self.setFeedback("レポートの保存先を確認できません。", for: state); return
            }
            NSWorkspace.shared.open(url)
        }
    }
    @objc func clientClicked() {
        let state = states[selected]
        guard !state.busy, reserveModal() else { return }
        perform(state, command: "client-list", onFailure: { self.releaseModal() }) { reply in
            let clients = reply["clients"] as? [Reply] ?? []
            let alert = NSAlert(); alert.messageText = "監視する" + state.name + "を選択"
            alert.informativeText = clients.isEmpty ? "対応するクライアントが見つかりません。VS Code拡張または公式CLIをインストールし、ログインしてください。" : "選択だけではAIは起動しません。"
            let choices = NSPopUpButton(frame: NSRect(x: 0, y: 0, width: 350, height: 28))
            for client in clients { choices.addItem(withTitle: client.text("label")) }
            if let index = clients.firstIndex(where: { $0.text("id") == reply.text("selected_id") }) { choices.selectItem(at: index) }
            alert.accessoryView = choices; alert.addButton(withTitle: "キャンセル")
            if !clients.isEmpty { alert.addButton(withTitle: "選択") }
            state.busy = true; self.render()
            alert.beginSheetModal(for: self.window) { response in
                state.busy = false; self.releaseModal()
                guard !self.exiting else { return }
                guard response == .alertSecondButtonReturn, clients.indices.contains(choices.indexOfSelectedItem) else { return }
                self.perform(state, command: "client-select", extra: ["--client-id", clients[choices.indexOfSelectedItem].text("id")]) { result in
                    guard result.flag("ok") else { self.setFeedback(result.text("detail"), for: state); return }
                    state.generation += 1; state.quota = [:]; state.policy = [:]; state.monitor = [:]; state.prompted = []
                    state.feedback = ""
                    self.renderIcon(state); self.render(); self.refresh(state, usage: true, monitor: true)
                }
            }
        }
    }
    @objc func loginChanged() {
        do {
            if loginButton.state == .on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
            if SMAppService.mainApp.status == .requiresApproval {
                setFeedback("システム設定のログイン項目で許可してください。", for: states[selected]); SMAppService.openSystemSettingsLoginItems()
            }
        } catch { failure(error) }
        loginButton.state = SMAppService.mainApp.status == .enabled ? .on : .off
    }
}
