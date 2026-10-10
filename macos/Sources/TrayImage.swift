import AppKit

enum TrayImage {
    private static var masks: [String: NSImage] = [:]
    private static var attempted: Set<String> = []
    static func color(_ remaining: Double?, _ status: String) -> NSColor {
        guard let remaining = remaining else { return NSColor(srgbRed: 0.37, green: 0.42, blue: 0.45, alpha: 1) }
        if remaining == 0 || status == "at_risk" { return NSColor(srgbRed: 0.68, green: 0.17, blue: 0.15, alpha: 1) }
        if status == "tight" { return NSColor(srgbRed: 0.62, green: 0.41, blue: 0, alpha: 1) }
        if status == "comfortable" { return NSColor(srgbRed: 0.11, green: 0.44, blue: 0.33, alpha: 1) }
        return NSColor(srgbRed: 0.37, green: 0.42, blue: 0.45, alpha: 1)
    }
    static func symbol(_ provider: String) -> NSImage? {
        if attempted.contains(provider) { return masks[provider] }
        attempted.insert(provider)
        let home = FileManager.default.homeDirectoryForCurrentUser
        let id = provider == "claude" ? "anthropic.claude-code" : "openai.chatgpt"
        for editor in [".vscode-insiders", ".vscode"] {
            let root = home.appendingPathComponent(editor + "/extensions").resolvingSymlinksInPath()
            guard let data = try? Data(contentsOf: root.appendingPathComponent("extensions.json")), data.count < 4 * 1024 * 1024,
                  let entries = try? JSONSerialization.jsonObject(with: data) as? [Reply] else { continue }
            for entry in entries where (entry["identifier"] as? Reply)?.text("id") == id {
                let name = entry.text("relativeLocation")
                guard name.hasPrefix(id + "-"), !name.contains("/"), !name.contains("\\") else { continue }
                let extensionURL = root.appendingPathComponent(name).resolvingSymlinksInPath()
                guard extensionURL.deletingLastPathComponent() == root else { continue }
                let file = extensionURL.appendingPathComponent("resources/" + (provider == "claude" ? "claude-logo.png" : "blossom.dark.png"))
                if let image = whiteMask(file) { masks[provider] = image; return image }
            }
        }
        return nil
    }
    private static func whiteMask(_ url: URL) -> NSImage? {
        guard let size = try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize, size < 2 * 1024 * 1024,
              let data = try? Data(contentsOf: url), let source = NSBitmapImageRep(data: data),
              source.pixelsWide <= 1024, source.pixelsHigh <= 1024,
              let mask = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: source.pixelsWide, pixelsHigh: source.pixelsHigh,
                                         bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                         colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { return nil }
        var left = source.pixelsWide, top = source.pixelsHigh, right = -1, bottom = -1
        for y in 0..<source.pixelsHigh { for x in 0..<source.pixelsWide {
            guard let c = source.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB) else { continue }
            let brightness = min(c.redComponent, min(c.greenComponent, c.blueComponent))
            let alpha = c.alphaComponent * max(0, min(1, (brightness - 190.0 / 255) / (55.0 / 255)))
            mask.setColor(NSColor(deviceRed: 1, green: 1, blue: 1, alpha: alpha), atX: x, y: y)
            if alpha > 0 { left = min(left, x); top = min(top, y); right = max(right, x); bottom = max(bottom, y) }
        } }
        guard right >= left, let image = mask.cgImage?.cropping(to: CGRect(x: left, y: top, width: right - left + 1, height: bottom - top + 1)) else { return nil }
        return NSImage(cgImage: image, size: NSSize(width: image.width, height: image.height))
    }
    static func make(provider: String, remaining: Double?, status: String, includeSymbol: Bool = true) -> NSImage {
        let size = NSSize(width: 32, height: 22)
        let result = NSImage(size: size, flipped: false) { bounds in
            color(remaining, status).setFill()
            NSBezierPath(roundedRect: bounds.insetBy(dx: 0, dy: 1), xRadius: 3, yRadius: 3).fill()
            if includeSymbol, let mark = symbol(provider) {
                let scale = min(29 / mark.size.width, 20 / mark.size.height)
                let target = NSRect(x: (32 - mark.size.width * scale) / 2, y: (22 - mark.size.height * scale) / 2,
                                    width: mark.size.width * scale, height: mark.size.height * scale)
                mark.draw(in: target, from: .zero, operation: .sourceOver, fraction: 0.18)
            }
            let text = remaining.map { String(Int(floor($0))) } ?? "?"
            let attributes: [NSAttributedString.Key: Any] = [.font: NSFont.monospacedDigitSystemFont(ofSize: text.count == 3 ? 13 : 16, weight: .bold),
                .foregroundColor: NSColor.white, .strokeColor: NSColor(srgbRed: 0.02, green: 0.07, blue: 0.06, alpha: 0.8), .strokeWidth: -3]
            let string = NSAttributedString(string: text, attributes: attributes)
            let measured = string.size()
            string.draw(at: NSPoint(x: (32 - measured.width) / 2, y: (24 - measured.height) / 2))
            NSColor.black.withAlphaComponent(0.25).setFill()
            NSRect(x: 3, y: 2, width: 26, height: 1.5).fill()
            if let value = remaining { NSColor.white.setFill(); NSRect(x: 3, y: 2, width: 26 * value / 100, height: 1.5).fill() }
            return true
        }
        result.isTemplate = false
        return result
    }
}
