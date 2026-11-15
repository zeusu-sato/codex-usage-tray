import AppKit

extension UsageController {
    func renderIcon(_ state: ProviderState) {
        state.statusItem?.button?.image = TrayImage.make(provider: state.id, remaining: state.remaining, status: state.forecast.text("status"), credit: state.remaining == nil ? nil : state.credit)
        let tooltip = state.quota.text("tooltip")
        state.statusItem?.button?.toolTip = state.credit != nil && state.remaining != nil ? tooltip : state.name + " · " + (tooltip.isEmpty ? "残量を確認しています" : tooltip)
        state.statusItem?.button?.setAccessibilityLabel(state.name + " 使用枠 " + (state.remaining == nil ? "未確認" : state.credit?.text("title") ?? (state.remaining.map { String(Int($0)) + "%" } ?? "未確認")))
    }
    func render() {
        guard window != nil else { return }
        let state = states[selected]
        feedback.stringValue = state.feedback
        selector.selectedSegment = selected
        let credit = state.remaining == nil ? nil : state.credit
        remaining.stringValue = credit?.text("title") ?? (state.remaining.map { String(Int(floor($0))) + "%" } ?? "?")
        remaining.textColor = TrayImage.color(state.remaining, state.forecast.text("status"), credit: credit)
        usageTitle.isHidden = credit != nil
        usageTitle.stringValue = state.quota.text("title").isEmpty ? state.name + "の残量を確認しています" : state.quota.text("title")
        quotaDetail.stringValue = state.quota.text("detail")
        checked.stringValue = state.quota.text("checked_label")
        forecastTitle.isHidden = credit != nil
        forecastTitle.stringValue = credit != nil ? "" : !state.quota.isEmpty && state.remaining == nil
            ? (state.quota.flag("blocked") && !state.quota.flag("stale") ? "予測: 利用制限中" : "予測: 未確認")
            : (state.credit == nil && state.remaining == 0 ? "予測: 残量なし" : "予測: " + (state.forecast.text("title").isEmpty ? "未確認" : state.forecast.text("title")))
        forecastTitle.textColor = remaining.textColor
        let quotaNote = [state.quota.text("note"), state.quota.text("scope")].filter { !$0.isEmpty }.joined(separator: "\n")
        quotaDetail.toolTip = quotaNote.isEmpty ? nil : quotaNote
        usageTitle.toolTip = quotaDetail.toolTip
        let forecastNote = state.quota.flag("blocked") && !state.quota.flag("stale") ? "利用制限があるため予測を判定できません。" : (state.credit == nil && state.remaining == 0 ? "対象の利用枠の残量は0%です。" : state.forecast.text("detail"))
        forecastTitle.toolTip = forecastNote.isEmpty ? nil : forecastNote
        policyTitle.stringValue = state.policy.text("title").isEmpty ? "追加対策" : state.policy.text("title")
        policyDetail.stringValue = state.policy.text("detail")
        policyDetail.isHidden = policyDetail.stringValue.isEmpty
        let policyTooltip = state.policy.text("tooltip")
        policyTitle.toolTip = policyTooltip.isEmpty ? nil : policyTooltip
        policyDetail.toolTip = policyTitle.toolTip
        policySwitch.state = state.policy.flag("enabled") ? .on : .off
        policyState.stringValue = policySwitch.state == .on ? "ON" : "OFF"
        policySwitch.isEnabled = !state.busy && (state.policy.flag("enabled") || state.policy.flag("can_enable"))
        // Normal state is shown only as a tooltip; the text appears when the user has to act.
        let monitorOk = state.monitor.flag("ok")
        let needsAction = !monitorOk || (state.monitor.flag("mismatch") && state.monitor.flag("policy_stopped"))
        monitorTitle.stringValue = needsAction ? state.monitor.text("title") : ""
        monitorDetail.stringValue = !needsAction ? "" : monitorOk ? state.monitor.text("current_label") : state.monitor.text("detail")
        monitorTitle.isHidden = !needsAction; monitorDetail.isHidden = !needsAction
        clientButton.toolTip = ([state.monitor.text("title"), state.monitor.flag("mismatch") ? state.monitor.text("detail") : "", state.monitor.text("baseline_label"), state.monitor.text("current_label"), state.monitor.text("checked_label")] + ["残量は5分ごと、バージョンは15分ごとに確認します。通常監視はAI推論を使いません。"]).filter { !$0.isEmpty }.joined(separator: "\n")
        refreshButton.isEnabled = !state.busy; clientButton.isEnabled = !state.busy && !promptVisible
        reviewButton.isEnabled = !state.busy && !promptVisible && state.monitor.flag("ok") && !state.monitor.text("signature").isEmpty
        reportButton.isEnabled = !state.busy
    }
}
