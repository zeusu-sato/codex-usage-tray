from datetime import datetime, timezone
import unittest
import claude_adapter as claude
import quota_monitor as quota

from .fixtures import NOW, usage


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
