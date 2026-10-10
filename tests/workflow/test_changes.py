from .support import WorkflowTestCase

from copy import deepcopy
from unittest.mock import patch
import backend
import client_registry
import policy_manager
import version_monitor

class ClientChangeWorkflowTests(WorkflowTestCase):
    def test_first_reference_is_observed_and_leaves_native_behavior(self):
        result = self.observe()
        self.assertFalse(result["mismatch"])
        self.assertFalse(result["alert"])
        self.assertTrue(result["baseline_label"].startswith("監視開始時:"))
        self.assertEqual(client_registry.settings(self.folder)["reference_kind"], "observed")
        ui = policy_manager.ui_snapshot(self.folder)
        self.assertFalse(ui["enabled"])
        self.assertFalse(ui["can_enable"])
        self.assertFalse((self.folder / "proposal.json").exists())
        self.assertEqual(self.agents.read_bytes(), self.original)
        self.process_guard.assert_not_called()


    def test_changed_client_never_silently_updates_reference(self):
        self.observe()
        reference = deepcopy(client_registry.settings(self.folder)["reference"])
        self.identity["cli_version"] = "1.2.4"
        result = self.observe()
        self.assertTrue(result["mismatch"])
        self.assertEqual(client_registry.settings(self.folder)["reference"], reference)
        self.assertEqual(client_registry.settings(self.folder)["reference_kind"], "observed")


    def test_notification_acknowledgement_only_matches_current_signature(self):
        self.observe()
        self.identity["binary_mtime_ns"] += 1
        change = self.observe()
        self.assertTrue(change["alert"])
        self.assertFalse(version_monitor.monitor_command(self.folder, "monitor-notified", self.now, "0" * 64)["ok"])
        self.assertTrue(self.observe()["alert"])
        self.assertTrue(version_monitor.monitor_command(self.folder, "monitor-notified", self.now, change["signature"])["ok"])
        self.assertFalse(self.observe()["alert"])
        self.identity["binary_mtime_ns"] += 1
        self.assertTrue(self.observe()["alert"])


    def test_repeated_metadata_and_no_decision_never_launch_process(self):
        signature = self.observe()["signature"]
        commands = ["status", "ui-status", "ui-disable", "monitor-check", "client-list", "review-latest"]
        for command in commands:
            with self.subTest(command=command):
                self.cli(command)
        self.cli("review-status", "--signature", signature)
        self.cli("review-decide", "--signature", signature, "--decision", "no")
        self.cli("review-status", "--signature", signature)
        self.process_guard.assert_not_called()
        self.assertFalse((self.folder / "reviews").exists())


    def test_usage_route_only_calls_quota_reader(self):
        with patch.object(backend.quota_monitor, "quota_command", return_value={"ok": True}) as quota:
            self.assertTrue(self.cli("usage-check")["ok"])
        quota.assert_called_once()
        self.assertEqual(quota.call_args.args[0], self.folder)
        self.assertEqual(quota.call_args.args[2], self.identity["binary_path"])
        self.process_guard.assert_not_called()


    def test_client_selection_resets_to_observed_without_approving_candidate(self):
        self.candidate()
        self.identity["client_id"] = "newly-selected-client"
        client_registry.client_command(self.folder, "client-select", self.identity["client_id"])
        self.assertNotIn("reference", client_registry.settings(self.folder))
        result = self.observe()
        self.assertFalse(result["mismatch"])
        self.assertEqual(client_registry.settings(self.folder)["reference_kind"], "observed")
        self.assertFalse(policy_manager.ui_snapshot(self.folder)["can_enable"])
        self.assertEqual(self.agents.read_bytes(), self.original)
