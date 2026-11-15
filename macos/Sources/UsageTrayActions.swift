import AppKit
import ServiceManagement

extension UsageController {
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
            let alert = NSAlert(); alert.messageText = state.name + "のAIレビューを開始しますか？"
            alert.informativeText = reply.text("detail") + "\n\n「はい」でTerminalを開き、対話形式でAIレビューを行います。ClaudeのAIレビューにもCodexのUsageを使います。"
            alert.addButton(withTitle: "いいえ"); alert.addButton(withTitle: "はい")
            alert.beginSheetModal(for: self.window) { response in
                self.releaseModal(); state.busy = false
                guard !self.exiting else { return }
                let yes = response == .alertSecondButtonReturn
                self.perform(state, command: "review-decide", extra: ["--signature", signature, "--decision", yes ? "yes" : "no"]) { decision in
                    if yes {
                        guard decision.flag("ok"), !decision.text("request_path").isEmpty, let actual = self.backend as? Backend else {
                            self.setFeedback("AIレビューを開始できませんでした。状態を更新してください。", for: state); return
                        }
                        do {
                            let launcher = try actual.reviewLauncher(provider: state.id, request: decision.text("request_path"))
                            let terminal = URL(fileURLWithPath: "/System/Applications/Utilities/Terminal.app")
                            NSWorkspace.shared.open([launcher], withApplicationAt: terminal, configuration: NSWorkspace.OpenConfiguration()) { _, error in
                                DispatchQueue.main.async {
                                    guard !self.exiting else { return }
                                    if let error = error { self.failure(error, for: state) }
                                    else { self.setFeedback("TerminalでAIレビューを開始しました。完了後、結果を確認してください。", for: state) }
                                }
                            }
                        } catch { self.failure(error, for: state) }
                    } else { self.setFeedback("AIレビューは開始していません。通常の監視を続けます。", for: state) }
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
