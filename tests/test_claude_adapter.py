from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import claude_adapter as claude
import quota_monitor as quota


NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)


def usage(five=0, weekly=9):
    return {"rate_limits_available": True, "rate_limits": {
        "five_hour": {"utilization": five, "resets_at": None},
        "seven_day": {"utilization": weekly, "resets_at": "2026-09-15T00:00:00.123456Z"}}}


def envelope(identifier, data=None, subtype="success"):
    return {"type": "control_response", "response": {
        "subtype": subtype, "request_id": identifier, "response": {} if data is None else data}}


class ClaudeNormalizationTest(unittest.TestCase):
    def test_global_windows_have_correct_durations_and_fractional_utc_reset(self):
        result = claude.normalize(usage())
        self.assertEqual(result, {"windows": [
            {"kind": "primary", "remaining_percent": 100, "duration_mins": 300, "resets_at": None},
            {"kind": "secondary", "remaining_percent": 91, "duration_mins": 10080,
             "resets_at": int(datetime(2026, 9, 15, tzinfo=timezone.utc).timestamp())}], "blocked": False})

    def test_null_reset_is_a_known_amount_without_an_invented_forecast(self):
        result = quota.reply({"snapshot": claude.normalize(usage()), "last_ok": True,
                              "fetched_at": NOW.isoformat()}, NOW)
        self.assertTrue(result["ok"])
        self.assertEqual(result["remaining_percent"], 91)
        self.assertIn("未提供", result["detail"])
        self.assertNotIn(result["forecast"]["status"], ("comfortable", "tight", "at_risk"))

    def test_expired_reset_does_not_imply_refill(self):
        data = usage(90)
        data["rate_limits"]["five_hour"]["resets_at"] = NOW.isoformat()
        snapshot = claude.normalize(data)
        self.assertEqual(snapshot["windows"][0]["remaining_percent"], 10)
        result = quota.reply({"snapshot": snapshot, "last_ok": True, "fetched_at": NOW.isoformat()}, NOW)
        self.assertTrue(result["stale"])
        self.assertIsNone(result["remaining_percent"])

    def test_offset_is_converted_to_utc_and_numeric_resets_are_rejected(self):
        data = usage()
        data["rate_limits"]["seven_day"]["resets_at"] = "2026-09-15T09:00:00+09:00"
        self.assertEqual(claude.normalize(data), claude.normalize(usage()))
        for reset in (True, 1789430400, "2026-09-15", "2026-09-15T00:00:00", "invalid",
                      "2026-13-15T00:00:00Z", "1969-12-31T23:59:59Z", [], {}):
            with self.subTest(reset=reset), self.assertRaises(quota.QuotaError):
                data["rate_limits"]["seven_day"]["resets_at"] = reset
                claude.normalize(data)

    def test_unavailable_or_missing_global_windows_never_claim_complete_usage(self):
        for available in (None, False, 0, 1, "true", [], {}):
            with self.subTest(available=available), self.assertRaises(quota.QuotaError):
                claude.normalize(dict(usage(), rate_limits_available=available))
        for source in ("five_hour", "seven_day"):
            for missing in (True, False):
                data = usage()
                if missing:
                    del data["rate_limits"][source]
                else:
                    data["rate_limits"][source] = None
                with self.subTest(source=source, missing=missing), self.assertRaisesRegex(
                        quota.QuotaError, "^incomplete_windows$"):
                    claude.normalize(data)

    def test_invalid_schema_utilization_and_missing_reset_are_rejected(self):
        for invalid in (None, True, False, "9", -1, float("nan"), float("inf"), float("-inf"), [], {}):
            with self.subTest(invalid=invalid), self.assertRaises(quota.QuotaError):
                claude.normalize(usage(invalid))
        for data in (None, [], {}, {"rate_limits_available": True, "rate_limits": []},
                     {"rate_limits_available": True, "rate_limits": {"five_hour": [], "seven_day": {}}}):
            with self.subTest(data=data), self.assertRaises(quota.QuotaError):
                claude.normalize(data)
        data = usage()
        del data["rate_limits"]["five_hour"]["resets_at"]
        with self.assertRaises(quota.QuotaError):
            claude.normalize(data)

    def test_known_exhaustion_is_numeric_zero_and_extra_model_windows_do_not_override_global(self):
        for used, remaining in ((0, 100), (99.5, 0.5), (100, 0), (120, 0)):
            with self.subTest(used=used):
                result = claude.normalize(usage(used))
                self.assertEqual(result["windows"][0]["remaining_percent"], remaining)
                self.assertFalse(result["blocked"])
                if remaining == 0:
                    shown = quota.reply({"snapshot": result, "last_ok": True, "fetched_at": NOW.isoformat()}, NOW)
                    self.assertEqual(shown["remaining_percent"], 0)
        data = usage()
        for source in ("seven_day_sonnet", "seven_day_opus", "extra_usage", "unknown_future_pool"):
            data["rate_limits"][source] = {"utilization": 100, "resets_at": "invalid"}
        self.assertEqual(claude.normalize(data), claude.normalize(usage()))


class ClaudeTransportTest(unittest.TestCase):
    def fake_server(self, directory, behavior):
        folder = Path(directory)
        server = folder / "fake.py"
        capture = folder / "messages.json"
        server.write_text("import json,sys,time\nfrom pathlib import Path\n"
                          "messages=[]\n"
                          "def read():\n"
                          "    message=json.loads(sys.stdin.readline())\n"
                          "    messages.append(message)\n"
                          "    Path(sys.argv[1]).write_text(json.dumps(messages))\n"
                          "    return message\n"
                          "def emit(message):\n"
                          "    print(json.dumps(message), flush=True)\n"
                          "read()\n" + behavior, encoding="utf-8")
        return server, capture

    def run_fake(self, behavior, timeout=3, expected_error=None, scope_salt=None, version="2.1.263", **patches):
        with tempfile.TemporaryDirectory() as directory:
            server, capture = self.fake_server(directory, behavior)
            original_popen = subprocess.Popen
            created = []
            commands = []
            options = []

            def launch(command, **kwargs):
                commands.append(command)
                options.append(kwargs)
                self.assertEqual(list(Path(kwargs["cwd"]).iterdir()), [])
                created.append(original_popen([sys.executable, "-u", str(server), str(capture)], **kwargs))
                return created[-1]

            with patch.object(claude.subprocess, "Popen", side_effect=launch), \
                    (patch.multiple(claude, **patches) if patches else nullcontext()):
                if expected_error is not None:
                    with self.assertRaisesRegex(quota.QuotaError, "^" + expected_error + "$"):
                        claude.request_usage("fixture-claude.exe", version,
                                             timeout=timeout, scope_salt=scope_salt)
                    result = None
                else:
                    result = claude.request_usage("fixture-claude.exe", version,
                                                  timeout=timeout, scope_salt=scope_salt)
            self.assertEqual(len(created), 1)
            self.assertIsNotNone(created[0].poll())
            self.assertTrue(created[0].stdin.closed)
            self.assertTrue(created[0].stdout.closed)
            self.assertFalse(Path(options[0]["cwd"]).exists())
            sent = json.loads(capture.read_text()) if capture.exists() else []
            return result, sent, commands[0], options[0]

    def test_exact_handshake_no_prompt_flags_and_only_sanitized_fields_returned(self):
        init = {"account": {"accountUuid": "edacfc78-1e4e-423c-baa5-8d63bdc0c2e7",
                             "organizationUuid": "c3a788dc-7f29-4f99-9c44-cef638ab0f90",
                             "email": "private@example.invalid", "name": "private fixture"},
                "models": [{"name": "private-model"}]}
        data = usage()
        data["rate_limits"]["seven_day_sonnet"] = {"utilization": 90, "resets_at": None}
        data["rate_limits"]["five_hour"]["private"] = "private-value"
        data["behavior"] = "private-behavior"
        data["token"] = "private-token"
        behavior = ("emit(" + repr(envelope(claude.INITIALIZE_ID, init)) + ")\nread()\n"
                    "emit(" + repr(envelope(claude.USAGE_ID, data)) + ")\ntime.sleep(60)\n")
        with patch.dict(claude.os.environ, {"CODEX_THREAD_ID": "private-thread", "CODEX_OTHER": "private-value",
                                          "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "private-session",
                                          "CLAUDE_CODE_ENTRYPOINT": "sdk", "CLAUDE_CODE_SSE_PORT": "12345",
                                          "VSCODE_IPC_HOOK_CLI": "private-ide", "VSCODE_PID": "123"}):
            result, sent, command, options = self.run_fake(behavior)
        self.assertEqual(sent, [claude._initialize(), claude._get_usage()])
        self.assertEqual(command, ["fixture-claude.exe", "--print", "--input-format", "stream-json",
                                  "--output-format", "stream-json", "--verbose", "--safe-mode",
                                  "--no-session-persistence", "--strict-mcp-config", "--no-chrome",
                                  "--disable-slash-commands", "--tools", "", "--setting-sources="])
        for forbidden in ("--bare", "--max-budget-usd", "--model", "--system-prompt", "--resume", "--continue"):
            self.assertNotIn(forbidden, command)
        self.assertFalse(any(key.startswith(("CODEX_", "VSCODE_")) for key in options["env"]))
        for key in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT"):
            self.assertNotIn(key, options["env"])
        for key in ("DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING", "DISABLE_AUTOUPDATER"):
            self.assertEqual(options["env"][key], "1")
        self.assertEqual(options["stderr"], subprocess.DEVNULL)
        self.assertEqual(result["rate_limits"], usage()["rate_limits"])
        self.assertRegex(result["scope_key"], "^[0-9a-f]{64}$")
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("edacfc78", json.dumps(result))

    def test_exact_allowlist_rejects_user_input_controls_and_extra_fields(self):
        forbidden = [{"type": "user", "message": {"role": "user", "content": "hi"}},
                     {"type": "control_request", "request": {"subtype": "set_model", "model": "other"}},
                     dict(claude._initialize(), prompt="hi")]
        for field, value in (("promptSuggestions", True), ("promptSuggestions", 0),
                             ("agentProgressSummaries", True), ("skills", ["a"]), ("plugins", ["b"])):
            message = claude._initialize()
            message["request"][field] = value
            forbidden.append(message)
        for skip in (False, 1, None):
            message = claude._get_usage()
            message["request"]["skip_behaviors"] = skip
            forbidden.append(message)
        for message in forbidden:
            stream = io.BytesIO()
            with self.subTest(message=message), self.assertRaisesRegex(quota.QuotaError, "^forbidden_method$"):
                claude.send_read_only(stream, message)
            self.assertEqual(stream.getvalue(), b"")

    def test_old_or_unidentified_version_and_unbounded_timeouts_fail_before_launch(self):
        with patch.object(claude.subprocess, "Popen") as launch:
            for version in (None, "", 266, [], "2.1.262", "2.0.999", "1.99.999", "2.1.263-beta",
                            "Claude Code 2.1.263", "2.1.266\n", "2.1." + "9" * 100):
                with self.subTest(version=version), self.assertRaisesRegex(quota.QuotaError, "^unsupported_version$"):
                    claude.request_usage("unused", version)
            for timeout in (None, False, 0, -1, float("nan"), float("inf"), 17, "1"):
                with self.subTest(timeout=timeout), self.assertRaisesRegex(quota.QuotaError, "^invalid_timeout$"):
                    claude.request_usage("unused", "2.1.263", timeout=timeout)
            launch.assert_not_called()

    def test_newer_versions_use_only_the_same_metadata_controls(self):
        behavior = ("emit(" + repr(envelope(claude.INITIALIZE_ID)) + ")\nread()\n"
                    "emit(" + repr(envelope(claude.USAGE_ID, usage())) + ")\n")
        for version in ("2.1.264", "2.1.266", "2.1.999", "2.2.0", "3.0.0"):
            with self.subTest(version=version):
                result, sent, _, _ = self.run_fake(behavior, version=version)
                self.assertEqual(sent, [claude._initialize(), claude._get_usage()])
                self.assertEqual(claude.normalize(result)["windows"][1]["remaining_percent"], 91)

    def test_new_version_cannot_bypass_response_or_skip_behaviors_contract(self):
        for response in (envelope("new-protocol-id"), {"type": "result"}):
            with self.subTest(response=response):
                _, sent, _, _ = self.run_fake("emit(" + repr(response) + ")\ntime.sleep(60)\n",
                                              version="3.0.0", expected_error="protocol")
                self.assertEqual(sent, [claude._initialize()])
        for behaviors in ({}, [], "private", False):
            data = dict(usage(), behaviors=behaviors)
            behavior = ("emit(" + repr(envelope(claude.INITIALIZE_ID)) + ")\nread()\n"
                        "emit(" + repr(envelope(claude.USAGE_ID, data)) + ")\n")
            with self.subTest(behaviors=behaviors):
                _, sent, _, _ = self.run_fake(behavior, version="2.1.266", expected_error="protocol")
                self.assertEqual(sent, [claude._initialize(), claude._get_usage()])

    def test_failed_initialize_cannot_send_usage_or_expose_error_text(self):
        bad = envelope(claude.INITIALIZE_ID, subtype="error")
        bad["response"]["error"] = "private-token"
        _, sent, _, _ = self.run_fake("emit(" + repr(bad) + ")\ntime.sleep(60)\n",
                                      expected_error="account_unavailable")
        self.assertEqual(sent, [claude._initialize()])

    def test_unexpected_categories_wrong_id_and_bad_json_abort_before_usage(self):
        invalid = [{"type": "assistant", "message": {"content": "private"}},
                   {"type": "system", "subtype": "init"}, {"type": "result"},
                   {"type": "control_request", "request": {"subtype": "can_use_tool"}},
                   envelope("wrong-id"), {"type": "control_response", "response": []},
                   {"type": "control_response", "response": {"subtype": "success", "request_id": claude.INITIALIZE_ID}}]
        for message in invalid:
            with self.subTest(message=message):
                _, sent, _, _ = self.run_fake("emit(" + repr(message) + ")\ntime.sleep(60)\n", expected_error="protocol")
                self.assertEqual(sent, [claude._initialize()])
        for line in ("not json", '{"type":"assistant","type":"control_response"}', "[]"):
            with self.subTest(line=line):
                self.run_fake("print(" + repr(line) + ", flush=True)\ntime.sleep(60)\n", expected_error="protocol")

    def test_oversized_line_aggregate_output_and_message_count_abort(self):
        self.run_fake("print('x' * 80, flush=True)\ntime.sleep(60)\n", expected_error="protocol", MAX_LINE_BYTES=64)
        first = envelope(claude.INITIALIZE_ID)
        second = envelope(claude.USAGE_ID, usage())
        behavior = ("emit(" + repr(first) + ")\nread()\n"
                    "emit(" + repr(second) + ")\ntime.sleep(60)\n")
        self.run_fake(behavior, expected_error="protocol", MAX_OUTPUT_BYTES=140)
        self.run_fake(behavior, expected_error="protocol", MAX_MESSAGES=1)

    def test_hung_initialization_and_usage_time_out_with_cleanup(self):
        for behavior in ("time.sleep(60)\n", "emit(" + repr(envelope(claude.INITIALIZE_ID)) + ")\nread()\ntime.sleep(60)\n"):
            with self.subTest(behavior=behavior):
                started = time.monotonic()
                self.run_fake(behavior, timeout=0.3, expected_error="timeout")
                self.assertLess(time.monotonic() - started, 4)

    def test_job_guard_failure_still_kills_launched_process(self):
        with patch.object(claude, "kill_children_on_exit", side_effect=quota.QuotaError("process_guard")):
            self.run_fake("time.sleep(60)\n", expected_error="process_guard")

    def test_existing_process_authentication_is_preserved_without_auth_file_reads(self):
        behavior = ("emit(" + repr(envelope(claude.INITIALIZE_ID)) + ")\nread()\n"
                    "emit(" + repr(envelope(claude.USAGE_ID, usage())) + ")\n")
        with patch.dict(claude.os.environ, {"ANTHROPIC_API_KEY": "fixture-existing-auth"}):
            result, _, _, options = self.run_fake(behavior)
        self.assertEqual(options["env"]["ANTHROPIC_API_KEY"], "fixture-existing-auth")
        self.assertNotIn("scope_key", result)
        self.assertNotIn("fixture-existing-auth", json.dumps(result))

    def test_account_scope_is_stable_uuid_only_and_changes_across_accounts(self):
        first = {"account": {"accountUuid": "edacfc78-1e4e-423c-baa5-8d63bdc0c2e7", "email": "a@example.invalid"}}
        second = deepcopy(first)
        second["account"]["email"] = "b@example.invalid"
        self.assertEqual(claude._scope_key(first), claude._scope_key(second))
        second["account"]["accountUuid"] = "c3a788dc-7f29-4f99-9c44-cef638ab0f90"
        self.assertNotEqual(claude._scope_key(first), claude._scope_key(second))
        for account in (None, {}, {"email": "a@example.invalid"}, {"accountUuid": "not-a-uuid"},
                        {"accountUuid": True}, dict(first["account"], organizationUuid="not-a-uuid")):
            with self.subTest(account=account):
                self.assertIsNone(claude._scope_key({"account": account}))

    def test_salted_scope_is_stable_and_separates_account_org_backend_and_local_install(self):
        salt = bytes(range(32))
        account = {"email": "private@example.invalid", "organization": "private organization",
                   "apiProvider": "firstParty", "tokenSource": "claude.ai", "name": "private name"}
        first = claude._scope_key({"account": account}, scope_salt=salt)
        self.assertRegex(first, "^[0-9a-f]{64}$")
        reordered = dict(reversed(list(account.items())))
        reordered.update(name="another display name", subscriptionType="another plan")
        self.assertEqual(first, claude._scope_key({"account": reordered}, scope_salt=salt))
        self.assertNotEqual(first, claude._scope_key({"account": account}, scope_salt=bytes(range(64))))
        for field, value in (("email", "other@example.invalid"), ("organization", "other organization"),
                             ("apiProvider", "gateway"), ("tokenSource", "profile")):
            with self.subTest(field=field):
                changed = dict(account, **{field: value})
                self.assertNotEqual(first, claude._scope_key({"account": changed}, scope_salt=salt))
        self.assertIsNone(claude._scope_key({"account": account}))

    def test_salted_scope_requires_valid_bounded_email_and_optional_metadata(self):
        salt = b"local-random-salt-fixture-32bytes!"
        for email in (None, True, [], {}, "", " ", "not-email", "a@", "@domain", "a@b@c",
                      "a b@example.invalid", "a\x00@example.invalid", "a" * 321 + "@example.invalid"):
            with self.subTest(email=email):
                account = {"email": email, "accountUuid": "edacfc78-1e4e-423c-baa5-8d63bdc0c2e7"}
                self.assertIsNone(claude._scope_key({"account": account}, scope_salt=salt))
        minimal = {"email": "a@example.invalid"}
        self.assertIsNotNone(claude._scope_key({"account": minimal}, scope_salt=salt))
        for field, maximum in (("organization", 1024), ("apiProvider", 64), ("tokenSource", 128)):
            for value in (False, [], {}, "", " ", "a\n", "a" * (maximum + 1)):
                with self.subTest(field=field, value=value):
                    account = dict(minimal, **{field: value})
                    self.assertIsNone(claude._scope_key({"account": account}, scope_salt=salt))
        with patch.object(claude.subprocess, "Popen") as launch:
            for salt in (True, "a" * 32, b"", b"a" * 31, bytearray(32), [], 32):
                with self.subTest(salt=salt), self.assertRaisesRegex(quota.QuotaError, "^invalid_scope_salt$"):
                    claude.request_usage("unused", "2.1.263", scope_salt=salt)
            launch.assert_not_called()

    def test_salted_transport_returns_no_raw_email_organization_name_or_salt(self):
        salt = b"local-random-salt-fixture-32bytes!"
        init = {"account": {"email": "private@example.invalid", "organization": "private organization",
                             "name": "private name", "apiProvider": "firstParty", "tokenSource": "claude.ai"}}
        behavior = ("emit(" + repr(envelope(claude.INITIALIZE_ID, init)) + ")\nread()\n"
                    "emit(" + repr(envelope(claude.USAGE_ID, usage())) + ")\n")
        result, sent, command, options = self.run_fake(behavior, scope_salt=salt)
        self.assertEqual(result["scope_key"], claude._scope_key(init, scope_salt=salt))
        self.assertEqual(set(result), {"rate_limits_available", "rate_limits", "scope_key"})
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("firstParty", json.dumps(result))
        self.assertNotIn("claude.ai", json.dumps(result))
        self.assertNotIn(salt.decode(), json.dumps((result, sent, command, options["env"])))


if __name__ == "__main__":
    unittest.main()
