from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import quota_monitor as quota


NOW = datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc)
RESET = int((NOW + timedelta(days=6)).timestamp())


def bucket(used=2, duration=10080):
    return {"limitId": "codex", "primary": {"usedPercent": used, "windowDurationMins": duration,
                                          "resetsAt": RESET}, "secondary": None}


def response(used=2):
    return {"rateLimits": bucket(used), "rateLimitsByLimitId": {"codex": bucket(used)}}


class QuotaMonitorTest(unittest.TestCase):
    def folder(self, path):
        folder = Path(path)
        (folder / "policy-sentinel.json").write_text("unchanged")
        (folder / "codex.exe").write_bytes(b"fake-not-executable")
        return folder

    def check(self, folder, now=NOW, data=None, error=None):
        with patch.object(quota, "request_rate_limits", return_value=data or response(), side_effect=error):
            return quota.quota_command(folder, now, folder / "codex.exe")

    def test_weekly_is_selected_by_duration_even_when_it_is_primary(self):
        snapshot = quota.normalize(response())
        result = quota.reply({"snapshot": snapshot, "last_ok": True, "fetched_at": NOW.isoformat()}, NOW)
        self.assertEqual(result["remaining_percent"], 98)
        self.assertIn("Weekly", result["tooltip"])
        self.assertIn("09/15 09:00 JST", result["detail"])

    def test_other_pools_do_not_override_codex_remaining(self):
        data = response()
        data["rateLimitsByLimitId"]["codex_spark"] = bucket(99)
        self.assertEqual(quota.normalize(data)["windows"][0]["remaining_percent"], 98)
        del data["rateLimitsByLimitId"]["codex"]
        with self.assertRaises(quota.QuotaError):
            quota.normalize(data)

    def test_legacy_bucket_is_accepted_without_multi_bucket_map(self):
        self.assertEqual(quota.normalize({"rateLimits": bucket()})["windows"][0]["remaining_percent"], 98)

    def test_two_windows_display_minimum_and_each_reset(self):
        data = response()
        data["rateLimitsByLimitId"]["codex"]["secondary"] = bucket(85, 300)["primary"]
        snapshot = quota.normalize(data)
        result = quota.reply({"snapshot": snapshot, "last_ok": True, "fetched_at": NOW.isoformat()}, NOW)
        self.assertEqual(result["remaining_percent"], 15)
        self.assertEqual(len(result["windows"]), 2)
        self.assertIn("5時間枠", result["tooltip"])

    def test_zero_full_and_exceeded_are_not_confused(self):
        for used, expected in ((0, 100), (100, 0), (120, 0)):
            self.assertEqual(quota.normalize(response(used))["windows"][0]["remaining_percent"], expected)

    def test_invalid_or_missing_windows_are_not_invented(self):
        for invalid in (None, True, "2", -1, float("nan"), float("inf")):
            with self.subTest(invalid=invalid), self.assertRaises(quota.QuotaError):
                quota.normalize(response(invalid))
        with self.assertRaises(quota.QuotaError):
            quota.normalize({"rateLimits": {"primary": None, "credits": {"unlimited": True}}})

    def test_spend_control_is_not_shown_as_available_quota(self):
        data = response()
        data["rateLimitsByLimitId"]["codex"]["spendControlReached"] = True
        result = quota.reply({"snapshot": quota.normalize(data), "last_ok": True, "fetched_at": NOW.isoformat()}, NOW)
        self.assertIsNone(result["remaining_percent"])
        self.assertTrue(result["blocked"])

    def test_failed_refresh_keeps_previous_value_explicitly_stale_without_error_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = self.folder(directory)
            self.check(folder)
            result = self.check(folder, NOW + timedelta(minutes=5), error=OSError("private-token-do-not-display"))
            self.assertFalse(result["ok"])
            self.assertTrue(result["stale"])
            self.assertIsNone(result["remaining_percent"])
            self.assertIn("前回取得", result["detail"])
            self.assertIn("98%", result["detail"])
            self.assertNotIn("private-token", (folder / "quota-state.json").read_text())

    def test_elapsed_reset_and_old_cache_never_assume_refill_to_100(self):
        cache = {"snapshot": quota.normalize(response()), "last_ok": True, "fetched_at": NOW.isoformat()}
        for later in (NOW + timedelta(minutes=11), NOW + timedelta(days=6), NOW - timedelta(seconds=1)):
            result = quota.reply(cache, later)
            self.assertTrue(result["stale"])
            self.assertIsNone(result["remaining_percent"])

    def test_manual_refresh_is_throttled_and_never_changes_policy(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(quota, "request_rate_limits", return_value=response()) as read:
            folder = self.folder(directory)
            before = (folder / "policy-sentinel.json").read_bytes()
            quota.quota_command(folder, NOW, folder / "codex.exe")
            quota.quota_command(folder, NOW + timedelta(seconds=10), folder / "codex.exe")
            self.assertEqual(read.call_count, 1)
            quota.quota_command(folder, NOW + timedelta(minutes=5), folder / "codex.exe")
            self.assertEqual(read.call_count, 2)
            self.assertEqual(before, (folder / "policy-sentinel.json").read_bytes())

    def test_corrupt_cache_recovers_from_live_read(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = self.folder(directory)
            (folder / "quota-state.json").write_text('{"schema_version":1,"snapshot":{"windows":[{}]}}')
            self.assertEqual(self.check(folder)["remaining_percent"], 98)

    def test_only_three_metadata_methods_are_allowed(self):
        self.assertEqual(quota.ALLOWED_METHODS, {"initialize", "initialized", "account/rateLimits/read"})
        for forbidden in ("turn/start", "thread/start", "thread/resume", "account/rateLimitResetCredit/consume"):
            output = io.StringIO()
            with self.assertRaises(quota.QuotaError):
                quota.send_read_only(output, {"method": forbidden})
            self.assertEqual(output.getvalue(), "")

    def fake_server(self, directory, behavior):
        # This is a plain Python process: no Codex, network, login, or inference.
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
                          "read()\n"
                          + behavior, encoding="utf-8")
        return server, capture

    def test_wire_protocol_reads_only_quota_and_cleans_up_process(self):
        with tempfile.TemporaryDirectory() as directory:
            behavior = ("print(json.dumps({'id':1,'result':{}}), flush=True)\nread()\nread()\n"
                        "print(json.dumps({'id':2,'result':" + repr(response()) + "}), flush=True)\n"
                        "time.sleep(60)\n")
            server, capture = self.fake_server(directory, behavior)
            original_popen = subprocess.Popen
            created = []
            def launch(command, **kwargs):
                self.assertEqual(command, ["test-codex.exe", "app-server", "--listen", "stdio://"])
                created.append(original_popen([sys.executable, "-u", str(server), str(capture)], **kwargs))
                return created[-1]
            with patch.object(quota.subprocess, "Popen", side_effect=launch):
                self.assertEqual(quota.request_rate_limits("test-codex.exe"), response())
            sent = json.loads(capture.read_text())
            self.assertEqual([m["method"] for m in sent], ["initialize", "initialized", "account/rateLimits/read"])
            self.assertNotIn("model", json.dumps(sent))
            self.assertIsNotNone(created[0].poll())

    def test_hung_server_times_out_and_is_killed(self):
        with tempfile.TemporaryDirectory() as directory:
            server, capture = self.fake_server(directory, "time.sleep(60)\n")
            original_popen = subprocess.Popen
            created = []
            def launch(command, **kwargs):
                created.append(original_popen([sys.executable, "-u", str(server), str(capture)], **kwargs))
                return created[-1]
            beginning = time.monotonic()
            with patch.object(quota.subprocess, "Popen", side_effect=launch), self.assertRaises(quota.QuotaError):
                quota.request_rate_limits("test-codex.exe", timeout=0.3)
            self.assertLess(time.monotonic() - beginning, 4)
            self.assertIsNotNone(created[0].poll())


if __name__ == "__main__":
    unittest.main()
