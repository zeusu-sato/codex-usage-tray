"""Isolated workflow checks: no installed Codex, real AGENTS file, network, or AI."""
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import backend
import client_registry
import model_catalog
import policy_manager
import reviews
from storage import read_json, write_json
import version_monitor


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="codex-tray-workflow-"))).resolve()
        self.folder = root / "profile with spaces 日本語"
        self.folder.mkdir()
        self.codex_home = root / "isolated-codex-home"
        self.codex_home.mkdir()
        self.agents = self.codex_home / "AGENTS.md"
        self.original = "# Personal instructions\r\nKeep the user's evidence. 日本語\r\n".encode("utf-8")
        self.agents.write_bytes(self.original)
        self.now = datetime(2026, 9, 9, 1, 0, tzinfo=timezone.utc)
        self.identity = {
            "client_id": "fixture-client", "label": "Fixture Codex", "cli_version": "1.2.3",
            "extension_version": "4.5.6", "binary_path": str(root / "unexecuted" / "codex.exe"),
            "binary_size": 12345, "binary_mtime_ns": 123456789,
        }
        self.stack.enter_context(patch.dict(os.environ, {"CODEX_HOME": str(self.codex_home)}))
        for module in (reviews, version_monitor, policy_manager):
            self.stack.enter_context(patch.object(module, "current_identity", side_effect=lambda folder: deepcopy(self.identity)))
        self.stack.enter_context(patch.object(client_registry, "discover", side_effect=lambda: [deepcopy(self.identity)]))
        self.stack.enter_context(patch.object(reviews, "process_identity", return_value="fixture-process-created"))
        self.process_guard = self.stack.enter_context(patch("subprocess.Popen", side_effect=AssertionError("Unexpected real process launch")))
        self.output = io.StringIO()
        self.stack.enter_context(redirect_stdout(self.output))
        self.selected = {"model": "fixture-most-capable", "display_name": "Fixture Most Capable", "effort": "ultra"}

    def observe(self):
        return version_monitor.monitor_command(self.folder, "monitor-check", self.now)

    def prepare(self):
        signature = self.observe()["signature"]
        result = reviews.review_command(self.folder, "review-decide", self.now, signature, "yes")
        return signature, Path(result["request_path"])

    def artifacts(self, workspace, instructions="Keep necessary independent verification.", **changes):
        (workspace / "report.md").write_text("# Fixture review\nEvidence and validation are synthetic; no live AI ran.\n", encoding="utf-8")
        result = {"schema_version": 1, "review_complete": True, "quality_preserved": True,
                  "fingerprint": client_registry.fingerprint(self.identity), "summary": "Fixture proposal",
                  "instructions": instructions, "sources": ["https://example.org/fixture-only"],
                  "validation": ["Fixture result; no production claim"]}
        result.update(changes)
        write_json(workspace / "review-result.json", result)

    def finish(self, request_path, instructions="Keep necessary independent verification.", exit_code=0):
        def launch(command, **options):
            self.artifacts(request_path.parent, instructions)
            return SimpleNamespace(wait=lambda: exit_code)
        selector, launcher = Mock(return_value=self.selected), Mock(side_effect=launch)
        code = reviews.run_console(self.folder, request_path, self.now, selector=selector, launch=launcher)
        return code, selector, launcher

    def candidate(self, instructions="Keep necessary independent verification."):
        _, request = self.prepare()
        self.finish(request, instructions)
        return request

    def test_interrupted_review_reaps_child_and_never_accepts_results(self):
        signature, request = self.prepare()
        child = Mock()
        child.wait.side_effect = [KeyboardInterrupt(), subprocess.TimeoutExpired('fixture', 1), -9]
        child.poll.return_value = None
        with self.assertRaises(KeyboardInterrupt):
            reviews.run_console(self.folder, request, self.now, selector=lambda _: self.selected,
                                launch=lambda *args, **kwargs: child)
        child.terminate.assert_called_once()
        child.kill.assert_called_once()
        self.assertEqual(read_json(self.folder / 'review-state.json')['decisions'][signature]['status'], 'incomplete')
        self.assertFalse((self.folder / 'proposal.json').exists())

    def cli(self, command, *arguments):
        capture = io.StringIO()
        with redirect_stdout(capture):
            backend.main(["--data-dir", str(self.folder), command, *arguments])
        return json.loads(capture.getvalue())

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

    def test_no_is_remembered_and_manual_yes_requires_new_action(self):
        signature = self.observe()["signature"]
        self.assertTrue(reviews.review_command(self.folder, "review-status", self.now, signature)["should_prompt"])
        result = reviews.review_command(self.folder, "review-decide", self.now, signature, "no")
        self.assertEqual(result["status"], "declined")
        self.assertFalse(reviews.review_command(self.folder, "review-status", self.now, signature)["should_prompt"])
        self.assertFalse((self.folder / "reviews").exists())
        result = reviews.review_command(self.folder, "review-decide", self.now, signature, "yes")
        self.assertEqual(result["status"], "prepared")
        self.process_guard.assert_not_called()

    def test_decision_requires_explicit_yes_or_no(self):
        signature = self.observe()["signature"]
        for decision in (None, "", "true", True, "YES"):
            with self.subTest(decision=decision), self.assertRaises(reviews.ReviewError):
                reviews.review_command(self.folder, "review-decide", self.now, signature, decision)
        self.assertFalse((self.folder / "reviews").exists())

    def test_yes_only_prepares_request_and_does_not_touch_global_text(self):
        _, request = self.prepare()
        data = read_json(request)
        self.assertEqual(data["decision"], "yes")
        self.assertEqual(data["model_policy"], "best_available")
        self.assertEqual(data["reasoning_policy"], "maximum_supported")
        self.assertEqual(self.agents.read_bytes(), self.original)
        self.assertFalse((self.folder / "proposal.json").exists())
        self.process_guard.assert_not_called()

    def test_yes_expiration_future_timestamp_and_client_change_prevent_model_lookup(self):
        _, request = self.prepare()
        selector, launcher = Mock(), Mock()
        for when in (self.now + timedelta(seconds=301), self.now - timedelta(seconds=1)):
            with self.subTest(when=when), self.assertRaises(reviews.ReviewError):
                reviews.run_console(self.folder, request, when, selector, launcher)
        self.identity["cli_version"] = "changed-after-yes"
        with self.assertRaises(reviews.ReviewError):
            reviews.run_console(self.folder, request, self.now, selector, launcher)
        selector.assert_not_called()
        launcher.assert_not_called()

    def test_modified_prompt_and_invalid_request_path_prevent_launch(self):
        _, request = self.prepare()
        selector, launcher = Mock(), Mock()
        request.with_name("prompt.md").write_text("Replacement unapproved prompt", encoding="utf-8")
        with self.assertRaises(reviews.ReviewError):
            reviews.run_console(self.folder, request, self.now, selector, launcher)
        outside = self.folder / "request.json"
        outside.write_bytes(request.read_bytes())
        with self.assertRaises(reviews.ReviewError):
            reviews.run_console(self.folder, outside, self.now, selector, launcher)
        selector.assert_not_called()
        launcher.assert_not_called()

    def test_superseded_prepared_request_cannot_be_replayed(self):
        _, first = self.prepare()
        _, second = self.prepare()
        self.assertNotEqual(first, second)
        selector, launcher = Mock(), Mock()
        with self.assertRaises(reviews.ReviewError):
            reviews.run_console(self.folder, first, self.now, selector, launcher)
        selector.assert_not_called()
        launcher.assert_not_called()

    def test_explicit_yes_launches_selected_maximum_model_in_review_workspace(self):
        _, request = self.prepare()
        catalog = [
            {"model": "default-fast", "description": "A fast model", "isDefault": True,
             "supportedReasoningEfforts": [{"reasoningEffort": "low"}]},
            {"model": "fixture-most-capable", "displayName": "Fixture Top", "description": "Our most capable model",
             "supportedReasoningEfforts": [{"reasoningEffort": "high"}, {"reasoningEffort": "ultra"}]},
        ]
        def selector(binary):
            self.assertEqual(binary, self.identity["binary_path"])
            with patch.object(model_catalog, "catalog", return_value=catalog):
                return model_catalog.select_for_review(binary, read_input=Mock(side_effect=AssertionError("Unexpected choice")))
        def launch(command, **options):
            self.artifacts(request.parent)
            return SimpleNamespace(wait=lambda: 0)
        launcher = Mock(side_effect=launch)
        self.assertEqual(reviews.run_console(self.folder, request, self.now, selector, launcher), 0)
        command = launcher.call_args.args[0]
        self.assertEqual(command[0], self.identity["binary_path"])
        self.assertEqual(command[command.index("-m") + 1], "fixture-most-capable")
        self.assertIn("model_reasoning_effort=ultra", command)
        self.assertIn("service_tier=default", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "workspace-write")
        self.assertEqual(command[command.index("-C") + 1], str(request.parent))
        self.assertEqual(launcher.call_args.kwargs["cwd"], request.parent)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertNotIn("CODEX_THREAD_ID", launcher.call_args.kwargs["env"])
        self.assertEqual(self.agents.read_bytes(), self.original)
        self.process_guard.assert_not_called()

    def test_completed_yes_is_single_use(self):
        _, request = self.prepare()
        self.finish(request)
        selector, launcher = Mock(), Mock()
        with self.assertRaises(reviews.ReviewError):
            reviews.run_console(self.folder, request, self.now, selector, launcher)
        selector.assert_not_called()
        launcher.assert_not_called()

    def test_running_review_blocks_another_signature_without_spawning(self):
        signature, request = self.prepare()
        state = reviews.load_state(self.folder)
        state["decisions"][signature].update(status="running", pid=123, process_created="fixture-process-created")
        write_json(self.folder / "review-state.json", state)
        self.identity["cli_version"] = "next-version"
        new_signature = self.observe()["signature"]
        result = reviews.review_command(self.folder, "review-decide", self.now, new_signature, "yes")
        self.assertFalse(result["ok"])
        self.assertFalse(result["can_review"])
        self.assertEqual(len(list((self.folder / "reviews").iterdir())), 1)
        self.process_guard.assert_not_called()

    def test_reused_pid_does_not_look_like_live_review(self):
        self.assertFalse(reviews.running({"status": "running", "pid": 123, "process_created": "different-generation"}))
        self.assertTrue(reviews.running({"status": "running", "pid": 123, "process_created": "fixture-process-created"}))

    def test_client_change_during_model_selection_prevents_inference(self):
        signature, request = self.prepare()
        def selector(binary):
            self.identity["binary_size"] += 1
            return self.selected
        launcher = Mock()
        with self.assertRaises(reviews.ReviewError):
            reviews.run_console(self.folder, request, self.now, selector, launcher)
        launcher.assert_not_called()
        self.assertEqual(reviews.load_state(self.folder)["decisions"][signature]["status"], "incomplete")

    def test_launch_failure_and_nonzero_exit_never_auto_retry_or_accept(self):
        signature, request = self.prepare()
        launcher = Mock(side_effect=OSError("fixture launch failure"))
        with self.assertRaises(OSError):
            reviews.run_console(self.folder, request, self.now, Mock(return_value=self.selected), launcher)
        launcher.assert_called_once()
        self.assertFalse((self.folder / "proposal.json").exists())
        self.assertEqual(reviews.load_state(self.folder)["decisions"][signature]["status"], "incomplete")
        _, second = self.prepare()
        code, _, launcher = self.finish(second, exit_code=7)
        self.assertEqual(code, 7)
        launcher.assert_called_once()
        self.assertFalse((self.folder / "proposal.json").exists())

    def test_zero_exit_without_artifacts_never_certifies_reference(self):
        _, request = self.prepare()
        launcher = Mock(return_value=SimpleNamespace(wait=lambda: 0))
        with self.assertRaises(OSError):
            reviews.run_console(self.folder, request, self.now, Mock(return_value=self.selected), launcher)
        self.assertEqual(client_registry.settings(self.folder)["reference_kind"], "observed")
        self.assertFalse((self.folder / "proposal.json").exists())

    def test_acceptance_requires_completion_quality_identity_and_evidence_records(self):
        _, request = self.prepare()
        invalid = [
            {"review_complete": False}, {"quality_preserved": False}, {"fingerprint": "wrong"},
            {"schema_version": 2}, {"sources": []}, {"sources": ["not-a-url"]}, {"validation": []},
            {"instructions": "x\0y"}, {"instructions": policy_manager.BEGIN}, {"instructions": "x" * 8001},
            {"summary": ""},
        ]
        for changes in invalid:
            with self.subTest(changes=list(changes)):
                self.artifacts(request.parent, **changes)
                with self.assertRaises(reviews.ReviewError):
                    reviews.accept_result(self.folder, request.parent, self.identity, self.selected, self.now)
                self.assertFalse((self.folder / "proposal.json").exists())
                self.assertEqual(client_registry.settings(self.folder)["reference_kind"], "observed")

    def test_client_changed_during_review_prevents_acceptance(self):
        _, request = self.prepare()
        before = deepcopy(self.identity)
        self.artifacts(request.parent)
        self.identity["extension_version"] = "changed"
        with self.assertRaises(reviews.ReviewError):
            reviews.accept_result(self.folder, request.parent, before, self.selected, self.now)
        self.assertFalse((self.folder / "proposal.json").exists())

    def test_valid_result_becomes_reviewed_but_stays_disabled_until_on(self):
        request = self.candidate()
        self.assertEqual(client_registry.settings(self.folder)["reference_kind"], "reviewed")
        snapshot = policy_manager.ui_snapshot(self.folder)
        self.assertFalse(snapshot["enabled"])
        self.assertTrue(snapshot["can_enable"])
        self.assertEqual(self.agents.read_bytes(), self.original)
        self.assertTrue(self.observe()["baseline_label"].startswith("見直し済み:"))
        report = reviews.latest_report(self.folder)
        self.assertEqual(Path(report["report_path"]), request.parent / "report.md")
        self.assertTrue(report["ok"])

    def test_review_can_conclude_no_additional_policy_needed(self):
        self.candidate(instructions="")
        self.assertFalse(policy_manager.ui_snapshot(self.folder)["can_enable"])
        self.assertFalse(policy_manager.ui_command(self.folder, "ui-enable", self.now)["ok"])
        self.assertEqual(self.agents.read_bytes(), self.original)

    def test_explicit_on_backups_original_and_off_preserves_unrelated_edits(self):
        self.candidate()
        result = policy_manager.ui_command(self.folder, "ui-enable", self.now)
        self.assertTrue(result["enabled"])
        self.assertTrue(policy_manager.runtime_status(self.folder)["active"])
        owned = self.agents.read_bytes()
        self.assertTrue(owned.startswith(self.original))
        self.assertIn(policy_manager.BEGIN.encode(), owned)
        first_backups = list((self.folder / "backups").iterdir())
        self.assertEqual(len(first_backups), 1)
        self.assertEqual(first_backups[0].read_bytes(), self.original)
        suffix = b"\n# Added by user while ON\nDo not discard this.\n"
        self.agents.write_bytes(owned + suffix)
        self.assertTrue(policy_manager.runtime_status(self.folder)["active"])
        result = policy_manager.ui_command(self.folder, "ui-disable", self.now + timedelta(seconds=1))
        self.assertFalse(result["enabled"])
        self.assertEqual(self.agents.read_bytes(), self.original + suffix)

    def test_on_is_idempotent_and_client_change_disables_old_policy(self):
        self.candidate()
        policy_manager.ui_command(self.folder, "ui-enable", self.now)
        content = self.agents.read_bytes()
        policy_manager.ui_command(self.folder, "ui-enable", self.now + timedelta(seconds=1))
        self.assertEqual(self.agents.read_bytes(), content)
        self.identity["binary_mtime_ns"] += 1
        self.assertFalse(policy_manager.runtime_status(self.folder)["active"])
        self.assertFalse(policy_manager.ui_snapshot(self.folder)["can_enable"])
        self.assertFalse(policy_manager.ui_snapshot(self.folder)["enabled"])
        self.assertEqual(self.agents.read_bytes(), content)

    def test_manually_modified_owned_block_is_protected_and_disabled(self):
        self.candidate()
        policy_manager.ui_command(self.folder, "ui-enable", self.now)
        edited = self.agents.read_bytes().replace(b"Keep necessary independent verification.", b"User edited this instruction.")
        self.agents.write_bytes(edited)
        self.assertFalse(policy_manager.runtime_status(self.folder)["active"])
        with self.assertRaises(ValueError):
            policy_manager.ui_command(self.folder, "ui-disable", self.now + timedelta(seconds=1))
        self.assertEqual(self.agents.read_bytes(), edited)
        self.assertFalse(read_json(self.folder / "active-policy.json")["enabled"])

    def test_corrupt_marker_pairs_never_overwrite_global_text(self):
        self.candidate()
        corrupted = self.original + policy_manager.BEGIN.encode() + b"\nMissing end marker\n"
        self.agents.write_bytes(corrupted)
        with self.assertRaises(ValueError):
            policy_manager.ui_command(self.folder, "ui-enable", self.now)
        self.assertEqual(self.agents.read_bytes(), corrupted)
        self.assertFalse(read_json(self.folder / "active-policy.json")["enabled"])

    def test_modified_report_invalidates_proposal_and_no_global_write_occurs(self):
        request = self.candidate()
        request.with_name("report.md").write_text("Changed report contents invalidate the reviewed proposal.", encoding="utf-8")
        with self.assertRaises(ValueError):
            policy_manager.ui_command(self.folder, "ui-enable", self.now)
        with self.assertRaises(ValueError):
            reviews.latest_report(self.folder)
        self.assertEqual(self.agents.read_bytes(), self.original)

    def test_new_accepted_review_turns_off_existing_policy_without_replacing_text(self):
        self.candidate()
        policy_manager.ui_command(self.folder, "ui-enable", self.now)
        old = self.agents.read_bytes()
        self.candidate("New separately approved proposal.")
        self.assertFalse(policy_manager.runtime_status(self.folder)["active"])
        self.assertEqual(self.agents.read_bytes(), old)
        self.assertTrue(policy_manager.ui_snapshot(self.folder)["can_enable"])
        policy_manager.ui_command(self.folder, "ui-enable", self.now + timedelta(seconds=1))
        self.assertIn(b"New separately approved proposal.", self.agents.read_bytes())
        self.assertEqual(self.agents.read_bytes().count(policy_manager.BEGIN.encode()), 1)

    def test_backend_corrupt_state_fails_closed_without_exposing_raw_file_data(self):
        (self.folder / "active-policy.json").write_text("PRIVATE_INVALID_JSON", encoding="utf-8")
        result = self.cli("status")
        self.assertFalse(result["active"])
        result = self.cli("ui-status")
        self.assertFalse(result["ok"])
        self.assertNotIn("PRIVATE_INVALID_JSON", json.dumps(result))
        self.assertEqual(self.agents.read_bytes(), self.original)
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


if __name__ == "__main__":
    unittest.main()
