from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import backend
import client_registry
import policy_manager
import reviews
from storage import write_json
import version_monitor


class WorkflowTestCase(unittest.TestCase):
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


    def cli(self, command, *arguments):
        capture = io.StringIO()
        with redirect_stdout(capture):
            backend.main(["--data-dir", str(self.folder), command, *arguments])
        return json.loads(capture.getvalue())
