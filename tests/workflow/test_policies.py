from .support import WorkflowTestCase

from datetime import timedelta
import json
from pathlib import Path
import client_registry
import policy_manager
import reviews
from storage import read_json

class PolicyWorkflowTests(WorkflowTestCase):
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
