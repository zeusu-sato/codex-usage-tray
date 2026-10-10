from .support import WorkflowTestCase

from copy import deepcopy
from datetime import timedelta
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock, patch
import client_registry
import model_catalog
import policy_manager
import reviews
from storage import read_json, write_json

class ReviewWorkflowTests(WorkflowTestCase):
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
