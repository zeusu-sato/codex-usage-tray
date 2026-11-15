import AppKit

extension UsageController {
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
                    if usage { state.quota = ["ok": false, "title": "Usage 未確認", "detail": "", "note": failure + "\n5分ごとに再確認します。"] }
                    if monitor { state.monitor = ["ok": false, "title": "バージョンは未確認です", "detail": failure] }
                    state.policy = ["enabled": false, "can_enable": false, "title": "状態を確認できません", "detail": failure]
                    state.feedback = failure
                }
                self.renderIcon(state); self.render()
                if version?.flag("alert") == true { self.offerReview(state, manual: false) }
            }
        }
    }
}
