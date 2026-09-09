import AppKit

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
if let index = CommandLine.arguments.firstIndex(of: "--self-test"), CommandLine.arguments.count > index + 1 {
    do { try runSelfTests(output: URL(fileURLWithPath: CommandLine.arguments[index + 1])); exit(0) }
    catch { fputs(error.localizedDescription + "\n", stderr); exit(1) }
}
let resources = Bundle.main.resourceURL ?? Bundle.main.bundleURL
let executable = resources.appendingPathComponent("backend/CodexUsageBackend")
let data = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/CodexUsageTray")
if let existing = NSRunningApplication.runningApplications(withBundleIdentifier: "io.github.zeusu-sato.codex-usage-tray").first(where: { $0.processIdentifier != ProcessInfo.processInfo.processIdentifier }) {
    existing.activate(options: [.activateAllWindows, .activateIgnoringOtherApps]); exit(0)
}
let controller = UsageController(backend: Backend(executable: executable, data: data))
app.delegate = controller
app.run()
