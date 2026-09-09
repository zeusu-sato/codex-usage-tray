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
do { try FileManager.default.createDirectory(at: data, withIntermediateDirectories: true) }
catch { fputs("Cannot open the application data folder.\n", stderr); exit(1) }
let instanceDescriptor = usage_instance_lock(data.appendingPathComponent("menu-bar-instance.lock").path)
let showNotification = Notification.Name("io.github.zeusu-sato.codex-usage-tray.show")
if instanceDescriptor < 0 {
    guard errno == EWOULDBLOCK || errno == EAGAIN else {
        fputs("Cannot acquire the application instance lock.\n", stderr); exit(1)
    }
    if let existing = NSRunningApplication.runningApplications(withBundleIdentifier: "io.github.zeusu-sato.codex-usage-tray").first(where: { $0.processIdentifier != ProcessInfo.processInfo.processIdentifier }) {
        existing.activate(options: [.activateAllWindows, .activateIgnoringOtherApps])
    }
    DistributedNotificationCenter.default().postNotificationName(showNotification, object: nil, userInfo: nil, deliverImmediately: true)
    exit(0)
}
let controller = UsageController(backend: Backend(executable: executable, data: data))
let reopenObserver = DistributedNotificationCenter.default().addObserver(forName: showNotification, object: nil, queue: .main) { _ in controller.showWindow() }
app.delegate = controller
app.run()
DistributedNotificationCenter.default().removeObserver(reopenObserver)
close(instanceDescriptor)
