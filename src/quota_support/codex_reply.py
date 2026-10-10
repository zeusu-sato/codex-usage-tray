from datetime import datetime, timedelta, timezone
import math
from quota_support.errors import QuotaError
import usage_forecast


MAX_AGE_SECONDS = 10 * 60
JST = timezone(timedelta(hours=9))


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise QuotaError("unsupported_response")
    return value


def reset_time(value):
    if value is None:
        return None
    number(value)
    if not isinstance(value, int) or value < 0:
        raise QuotaError("unsupported_response")
    datetime.fromtimestamp(value, timezone.utc)  # Reject timestamps this PC cannot display.
    return value


def normalize(result):
    """Keep only the Codex quota, never substitute Spark/reserve or token totals."""
    buckets = result.get("rateLimitsByLimitId")
    if buckets is not None:
        if not isinstance(buckets, dict) or "codex" not in buckets:
            raise QuotaError("unsupported_response")
        bucket = buckets["codex"]
    else:
        bucket = result.get("rateLimits")
    if not isinstance(bucket, dict) or bucket.get("limitId") not in (None, "codex"):
        raise QuotaError("unsupported_response")
    windows = []
    for key in ("primary", "secondary"):
        raw = bucket.get(key)
        if raw is None:
            continue
        if not isinstance(raw, dict):
            raise QuotaError("unsupported_response")
        used = number(raw.get("usedPercent"))
        if used < 0:
            raise QuotaError("unsupported_response")
        duration = raw.get("windowDurationMins")
        if duration is not None and (number(duration) <= 0 or not isinstance(duration, int)):
            raise QuotaError("unsupported_response")
        windows.append({"kind": key, "remaining_percent": max(0, 100 - used),
                        "duration_mins": duration, "resets_at": reset_time(raw.get("resetsAt"))})
    individual = bucket.get("individualLimit")
    if individual is not None:
        if not isinstance(individual, dict):
            raise QuotaError("unsupported_response")
        remaining = number(individual.get("remainingPercent"))
        if not 0 <= remaining <= 100:
            raise QuotaError("unsupported_response")
        windows.append({"kind": "individual", "remaining_percent": remaining, "duration_mins": None,
                        "resets_at": reset_time(individual.get("resetsAt"))})
    if not windows:
        raise QuotaError("no_windows")
    blocked = bucket.get("spendControlReached") is True or bucket.get("rateLimitReachedType") is not None
    return {"windows": windows, "blocked": blocked}


def label(window):
    if window["kind"] == "individual":
        return "個人上限"
    duration = window["duration_mins"]
    if duration == 10080:
        return "Weekly"
    if duration is None:
        return "枠1" if window["kind"] == "primary" else "枠2"
    if duration % 1440 == 0:
        return str(duration // 1440) + "日枠"
    if duration % 60 == 0:
        return str(duration // 60) + "時間枠"
    return str(duration) + "分枠"


def reply(cache, now):
    snapshot = cache.get("snapshot")
    if snapshot is not None:
        if (not isinstance(snapshot, dict) or not isinstance(snapshot.get("windows"), list)
                or not 1 <= len(snapshot["windows"]) <= 3 or not isinstance(snapshot.get("blocked"), bool)):
            raise ValueError("Invalid cached snapshot")
        seen = set()
        for window in snapshot["windows"]:
            if window["kind"] not in ("primary", "secondary", "individual") or window["kind"] in seen:
                raise ValueError("Invalid cached window")
            seen.add(window["kind"])
            if not 0 <= number(window["remaining_percent"]) <= 100:
                raise ValueError("Invalid cached remaining quota")
            duration = window["duration_mins"]
            if duration is not None and (number(duration) <= 0 or not isinstance(duration, int)):
                raise ValueError("Invalid cached window duration")
            reset_time(window["resets_at"])
    fetched = datetime.fromisoformat(cache["fetched_at"]) if snapshot else None
    if fetched is not None and fetched.tzinfo is None:
        raise ValueError("Cached timestamp must include timezone")
    stale = (snapshot is None or not cache.get("last_ok", False)
             or not 0 <= (now - fetched).total_seconds() <= MAX_AGE_SECONDS
             or any(w["resets_at"] is not None and w["resets_at"] <= now.timestamp() for w in snapshot["windows"]))
    rows = []
    if snapshot:
        for window in snapshot["windows"]:
            reset = window["resets_at"]
            rows.append({"label": label(window), "remaining_percent": window["remaining_percent"],
                         "resets_label": ("リセット " + datetime.fromtimestamp(reset, JST).strftime("%m/%d %H:%M JST")
                                          if reset is not None else "リセット時刻: 未提供")})
    blocked = snapshot is not None and snapshot.get("blocked", False)
    remaining = min((row["remaining_percent"] for row in rows), default=None)
    details = [f'{r["label"]}: 残り {r["remaining_percent"]:g}%  ·  {r["resets_label"]}' for r in rows]
    checked = "最終取得: " + fetched.astimezone(JST).strftime("%m/%d %H:%M:%S JST") if fetched else "取得成功の記録はありません"
    if stale:
        title = "Usageを確認できません"
        details.insert(0, "現在値は未確認です。" + ("以下は前回取得した残量です。" if rows else ""))
        details.append("接続・Codexのログイン状態をご確認ください。5分ごとに再確認します。")
        tooltip = "Codex Usage 未確認" + (" / 前回 " + fetched.astimezone(JST).strftime("%m/%d %H:%M") if fetched else "")
    elif blocked:
        title = "利用制限が通知されています"
        details.append("サーバーが利用制限を通知しています。残量だけでは利用可否を判断できません。")
        tooltip = "Codex Usage 利用制限あり / " + fetched.astimezone(JST).strftime("%H:%M確認")
    else:
        title = f"Usage 残り {remaining:g}%"
        chosen = min(rows, key=lambda row: row["remaining_percent"])
        tooltip = f'Codex {chosen["label"]} 残り{remaining:g}% / ' + chosen["resets_label"] + " / " + fetched.astimezone(JST).strftime("%H:%M取得")
    if len(rows) > 1:
        details.append("トレイには、このCodex枠のうち最も少ない残量を表示します。")
    forecast = (usage_forecast.pending("unavailable", "現在の残量を確認できるまで予測を保留します。")
                if stale or blocked else usage_forecast.forecast(cache.get("history"), snapshot["windows"], now.timestamp(), label))
    if not stale and not blocked:
        short = {"comfortable": "余裕あり", "tight": "ペース注意", "at_risk": "不足注意",
                 "collecting": "判定待ち", "unavailable": "見通し未確認"}[forecast["status"]]
        affected = "(" + forecast["window_label"] + ")" if forecast["window_label"] else ""
        tooltip = short + affected + " / " + tooltip
    return {"ok": not stale, "stale": stale, "title": title, "detail": "\n".join(details),
            "checked_label": checked, "tooltip": tooltip[:63], "remaining_percent": None if stale or blocked else remaining,
            "windows": rows, "blocked": blocked, "forecast": forecast}


