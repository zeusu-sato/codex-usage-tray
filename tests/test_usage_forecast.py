from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import quota_monitor as quota
import usage_forecast as trend
from test_quota_monitor import NOW, response


T = NOW.timestamp()


def window(remaining, reset=T + 6 * 86400, duration=10080, kind="primary"):
    return {"kind": kind, "duration_mins": duration, "resets_at": reset, "remaining_percent": remaining}


def series(values, hours=6, **options):
    data = []
    for i, remaining in enumerate(values):
        at = T - hours * 3600 + i * hours * 3600 / (len(values) - 1)
        data = trend.record(data, [window(remaining, **options)], at)
    return data


def predict(values, hours=6, **options):
    return trend.forecast(series(values, hours, **options), [window(values[-1], **options)], T, quota.label)


class ForecastTests(unittest.TestCase):
    def test_low_remaining_can_be_green_when_reset_is_near(self):
        result = predict([12, 11, 10], reset=T + 3600)
        self.assertEqual(result['status'], 'comfortable')
        self.assertAlmostEqual(result['projected_remaining_percent'], 9.7)

    def test_high_remaining_can_be_red_at_a_fast_pace(self):
        self.assertEqual(predict([100, 96, 90])['status'], 'at_risk')

    def test_borderline_pace_is_yellow(self):
        self.assertEqual(predict([100, 99, 97])['status'], 'tight')

    def test_initial_flat_history_cannot_invent_green(self):
        history = trend.record(None, [window(93)], T)
        self.assertEqual(trend.forecast(history, [window(93)], T, quota.label)['status'], 'collecting')
        self.assertEqual(predict([93, 93, 93], hours=1)['status'], 'tight')
        self.assertEqual(predict([93, 93, 93], hours=6)['status'], 'comfortable')

    def test_rounding_step_does_not_create_confident_red(self):
        self.assertEqual(predict([100, 100, 99], hours=1)['status'], 'tight')

    def test_rounding_also_bounds_the_remaining_allowance(self):
        # Reported 2 -> 1 could represent 2.49 -> 0.51: the actual 20-minute
        # projection can exceed the true available allowance despite reporting 1%.
        self.assertEqual(predict([2, 2, 1], hours=1, reset=T+1200)['status'], 'tight')
        # Conversely, 2.1 points of projected use need not exhaust a rounded 2%.
        self.assertEqual(predict([6, 4, 2], hours=1, reset=T+2520)['status'], 'tight')

    def test_zero_does_not_need_observation_history(self):
        result = trend.forecast(None, [window(0)], T, quota.label)
        self.assertEqual(result['status'], 'at_risk')
        self.assertEqual(result['projected_remaining_percent'], 0)

    def test_short_windows_require_a_proportional_minimum(self):
        options = dict(reset=T + 3600, duration=300)
        self.assertEqual(predict([90, 85, 80], hours=.4, **options)['status'], 'collecting')
        self.assertEqual(predict([90, 85, 80], hours=.5, **options)['status'], 'comfortable')

    def test_reset_change_refill_and_clock_reversal_restart_history(self):
        old = series([100, 98, 96])
        for current, timestamp in ((window(95, reset=T + 8 * 86400), T + 300),
                                   (window(100), T + 300), (window(95), T - 300)):
            recorded = trend.record(old, [current], timestamp)
            self.assertEqual(len(recorded[0]['samples']), 1)
            self.assertEqual(trend.forecast(recorded, [current], timestamp, quota.label)['status'], 'collecting')

    def test_no_reset_cannot_forecast(self):
        self.assertEqual(predict([100, 98, 96], reset=None)['status'], 'unavailable')
        self.assertEqual(predict([100, 98, 96], reset=T)['status'], 'unavailable')

    def test_history_older_than_a_day_and_stale_endpoints_cannot_forecast(self):
        history = series([100, 98, 96])
        self.assertEqual(trend.forecast(history, [window(96)], T + 601, quota.label)['status'], 'collecting')
        recorded = trend.record(history, [window(95)], T + 90000)
        self.assertEqual(len(recorded[0]['samples']), 1)

    def test_manual_refresh_storage_is_bounded_and_old_points_are_pruned(self):
        history = None
        for i in range(1800):
            history = trend.record(history, [window(95)], T + i * 60)
        samples = history[0]['samples']
        self.assertLessEqual(len(samples), 289)
        self.assertGreaterEqual(samples[0][0], T + 1799 * 60 - 86400)
        self.assertEqual(len(set(int(p[0] // 300) for p in samples)), len(samples))

    def test_corrupt_or_oversized_history_does_not_hide_quota(self):
        for malformed in ({}, [{'samples': []}], [dict(kind='primary', duration_mins=10080, resets_at=T+86400, samples=[[T, 95]]*290)]):
            self.assertEqual(trend.forecast(malformed, [window(95)], T, quota.label)['status'], 'collecting')
            self.assertEqual(len(trend.record(malformed, [window(95)], T)[0]['samples']), 1)

    def test_multiple_windows_use_the_worst_forecast_not_lowest_percentage(self):
        low = window(10, reset=T+3600)
        high = window(90, reset=T+2*3600, duration=300, kind='secondary')
        history = series([12, 11, 10], reset=low['resets_at']) + series([100, 96, 90], hours=.5,
                    reset=high['resets_at'], duration=300, kind='secondary')
        # A 20-point/hour pace fits the high window, while a larger drop does not.
        history[1] = series([100, 65, 30], hours=.5, reset=high['resets_at'], duration=300, kind='secondary')[0]
        high['remaining_percent'] = 30
        result = trend.forecast(history, [low, high], T, quota.label)
        self.assertEqual(result['status'], 'at_risk')
        self.assertEqual(result['window_label'], '5時間枠')

    def test_one_unknown_window_prevents_an_all_clear(self):
        history = series([12, 11, 10], reset=T+3600)
        self.assertEqual(trend.forecast(history, [window(10,reset=T+3600),window(80,kind='secondary')], T, quota.label)['status'], 'collecting')

    def test_existing_poll_updates_history_without_extra_reads_or_other_files(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(quota, 'request_rate_limits', return_value=response()) as read:
            folder=Path(directory)
            binary=folder/'codex.exe'
            binary.write_bytes(b'fixture')
            first=quota.quota_command(folder,NOW,binary)
            self.assertEqual(first['forecast']['status'],'collecting')
            quota.quota_command(folder,NOW+timedelta(seconds=10),binary)
            quota.quota_command(folder,NOW+timedelta(minutes=5),binary)
            self.assertEqual(read.call_count,2)
            self.assertEqual({p.name for p in folder.iterdir()},{'codex.exe','quota-state.json','quota-write.lock'})

    def test_stale_and_blocked_quota_override_a_previous_positive_forecast(self):
        normalized=quota.normalize(response())
        history=series([100,99,98])
        cache={'snapshot':normalized,'history':history,'last_ok':True,'fetched_at':NOW.isoformat()}
        self.assertEqual(quota.reply(cache,NOW)['forecast']['status'],'comfortable')
        cache['last_ok']=False
        self.assertEqual(quota.reply(cache,NOW)['forecast']['status'],'unavailable')
        cache['last_ok']=True
        normalized['blocked']=True
        self.assertEqual(quota.reply(cache,NOW)['forecast']['status'],'unavailable')


if __name__ == '__main__':
    unittest.main()
