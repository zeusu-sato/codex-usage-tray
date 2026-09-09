"""Bounded, local arithmetic over quota snapshots. No I/O, network, or AI."""
import math


HISTORY_SECONDS = 24 * 60 * 60
SAMPLE_SECONDS = 5 * 60
MAX_SAMPLES = HISTORY_SECONDS // SAMPLE_SECONDS + 1
MAX_WINDOWS = 3
ROUNDING_POINTS = 1.0
HEADROOM_FRACTION = 0.20


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def key(window):
    return window["kind"], window["duration_mins"], window["resets_at"]


def valid_history(history):
    """Discard malformed analysis data without discarding a valid quota reading."""
    try:
        if not isinstance(history, list) or len(history) > MAX_WINDOWS:
            return {}
        result = {}
        for row in history:
            identifier = key(row)
            if identifier[0] not in ("primary", "secondary", "individual") or identifier in result:
                return {}
            if identifier[1] is not None and (not finite(identifier[1]) or identifier[1] <= 0):
                return {}
            if identifier[2] is not None and (not finite(identifier[2]) or identifier[2] < 0):
                return {}
            samples = row["samples"]
            if not isinstance(samples, list) or len(samples) > MAX_SAMPLES:
                return {}
            previous = None
            for sample in samples:
                if (not isinstance(sample, list) or len(sample) != 2 or not all(finite(v) for v in sample)
                        or sample[0] < 0 or not 0 <= sample[1] <= 100):
                    return {}
                if previous is not None and (sample[0] <= previous[0] or sample[1] > previous[1]):
                    return {}
                previous = sample
            result[identifier] = samples
        return result
    except (KeyError, TypeError, ValueError, OverflowError):
        return {}


def record(history, windows, timestamp):
    old = valid_history(history)
    result = []
    for window in windows[:MAX_WINDOWS]:
        samples = [p[:] for p in old.get(key(window), []) if p[0] >= timestamp - HISTORY_SECONDS]
        remaining = window["remaining_percent"]
        if samples and (timestamp <= samples[-1][0] or remaining > samples[-1][1]):
            samples = []  # Clock reversal, refill, correction, or a different account/cycle.
        point = [timestamp, remaining]
        if samples and int(timestamp // SAMPLE_SECONDS) == int(samples[-1][0] // SAMPLE_SECONDS):
            samples[-1] = point  # Manual refresh cannot grow storage faster than five-minute buckets.
        else:
            samples.append(point)
        result.append({"kind": window["kind"], "duration_mins": window["duration_mins"],
                       "resets_at": window["resets_at"], "samples": samples[-MAX_SAMPLES:]})
    return result


def pending(status="collecting", detail=None):
    return {"status": status, "title": "傾向の判定待ち" if status == "collecting" else "見通しは未確認です",
            "detail": detail or "履歴を集めています。通常の残量取得だけで計算します。",
            "window_label": None, "observed_hours": None, "projected_remaining_percent": None}


def assess_one(window, samples, now, name):
    remaining, reset = window["remaining_percent"], window["resets_at"]
    if remaining == 0:
        return {**pending(), "status": "at_risk", "title": "利用枠を使い切っています",
                "detail": name + ": 現在の残量は0%です。", "window_label": name, "projected_remaining_percent": 0.0}
    if reset is None or reset <= now:
        return pending("unavailable", name + ": 次のリセット時刻を確認できません。")
    samples = [p for p in samples if now - HISTORY_SECONDS <= p[0] <= now]
    duration = window["duration_mins"]
    minimum = min(3600, max(900, duration * 6)) if duration is not None else 3600
    if (len(samples) < 3 or not 0 <= now - samples[-1][0] <= 600
            or samples[-1][1] != remaining or samples[-1][0] - samples[0][0] < minimum):
        return pending(detail=name + f": 判定には同じリセット期間の約{minimum / 60:g}分以上の履歴が必要です。")
    elapsed = samples[-1][0] - samples[0][0]
    spent = samples[0][1] - samples[-1][1]
    time_left = reset - now
    projected_use = spent / elapsed * time_left
    # A one-point reporting step must not turn a flat/short history into false certainty.
    lower_use = max(0, spent - ROUNDING_POINTS) / elapsed * time_left
    upper_use = (spent + ROUNDING_POINTS) / elapsed * time_left
    lower_available = max(0, remaining - ROUNDING_POINTS)
    upper_available = min(100, remaining + ROUNDING_POINTS)
    if lower_use > upper_available:
        status, title = "at_risk", "リセット前に不足しそう"
    elif upper_use <= lower_available * (1 - HEADROOM_FRACTION):
        status, title = "comfortable", "このペースなら余裕あり"
    else:
        status, title = "tight", "リセットまでのペースに注意"
    hours = elapsed / 3600
    projected_remaining = round(max(0, min(100, remaining - projected_use)), 1)
    return {"status": status, "title": title, "window_label": name, "observed_hours": round(hours, 1),
            "projected_remaining_percent": projected_remaining,
            "detail": name + f": 直近{hours:.1f}時間の平均から概算。リセット時の残量目安 {projected_remaining:g}%。\n"
                      "使い方が変わると見通しも変わります。"}


def forecast(history, windows, now, labeler):
    saved = valid_history(history)
    results = [assess_one(window, saved.get(key(window), []), now, labeler(window)) for window in windows]
    if not results:
        return pending("unavailable")
    severity = {"comfortable": 0, "collecting": 1, "unavailable": 1, "tight": 2, "at_risk": 3}
    worst = dict(max(results, key=lambda r: severity[r["status"]]))
    if len(results) > 1:
        worst["detail"] += "\n色は各利用枠の見通しのうち、最も注意が必要なものを示します。"
    return worst
