import AppKit
import ServiceManagement

extension UsageController {
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
}
