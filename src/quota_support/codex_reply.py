from datetime import datetime, timedelta, timezone
import math
import re
from decimal import Decimal, localcontext, ROUND_DOWN
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
    credits = bucket.get("credits")
    reached = bucket.get("rateLimitReachedType")
    credit = None
    if ((any(w["remaining_percent"] == 0 for w in windows) or reached == "rate_limit_reached")
            and isinstance(credits, dict)
            and (credits.get("unlimited") is True or credits.get("hasCredits") is True)
            and bucket.get("spendControlReached") is not True
            and reached in (None, "rate_limit_reached")):
        credit = {"kind": "codex_credits", "unlimited": credits.get("unlimited") is True,
                  "balance": credit_balance(credits.get("balance"))}
        blocked = False
    return {"windows": windows, "blocked": blocked, "credit": credit}


def credit_balance(value):
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?", value):
        return value.replace(",", "")
    return None


def credit_number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and (not isinstance(value, float) or math.isfinite(value)) and value >= 0)


def validate_credit(credit):
    if credit is None:
        return
    if not isinstance(credit, dict):
        raise ValueError("Invalid cached credit")
    if credit.get("kind") == "codex_credits":
        balance = credit.get("balance")
        valid = (set(credit) == {"kind", "unlimited", "balance"}
                 and isinstance(credit.get("unlimited"), bool)
                 and (balance is None or isinstance(balance, str)
                      and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", balance) is not None))
    elif credit.get("kind") == "claude_extra_usage":
        currency = credit.get("currency")
        valid = (set(credit) == {"kind", "currency", "monthly_limit", "limit_known", "used_credits"}
                 and isinstance(credit.get("limit_known"), bool)
                 and (currency is None or isinstance(currency, str) and re.fullmatch(r"[A-Z]{3}", currency))
                 and all(credit.get(k) is None or credit_number(credit[k]) for k in ("monthly_limit", "used_credits"))
                 and (credit["limit_known"] or credit["monthly_limit"] is None))
    else:
        valid = False
    if not valid:
        raise ValueError("Invalid cached credit")


def compact_credit(integer, dollars=False):
    if integer < 1000:
        text = str(integer)
    else:
        unit, scale = ("k", 1000)
        for candidate, divisor in (("M", 10**6), ("B", 10**9)):
            if integer >= divisor:
                unit, scale = candidate, divisor
        if integer >= 10**12:
            text = "999B"
        elif integer < scale * 10 and (dollars or scale > 1000):
            tenths = integer * 10 // scale
            text = str(tenths // 10) + ("." + str(tenths % 10) if tenths % 10 else "") + unit
        else:
            text = str(integer // scale) + unit
    if dollars and len(text) > 4:
        text = "999B"
    return ("$" if dollars else "") + text


def credit_display(credit):
    kind = credit["kind"]
    known = True
    if kind == "codex_credits":
        title = "Credit 利用中"
        if credit["unlimited"]:
            tray, summary = "∞", "Credit 無制限"
        elif credit["balance"] is not None:
            integer, dot, fraction = credit["balance"].partition(".")
            tray = compact_credit(int(integer))
            summary = "残り" + format(int(integer), ",") + dot + fraction + "クレジット"
        else:
            tray, known, summary = "¤", False, "Credit 残高未提供"
        tooltip_summary = summary
    else:
        title = "追加利用中"
        values = [str(credit[k]) for k in ("monthly_limit", "used_credits") if credit[k] is not None]
        with localcontext() as context:
            context.prec = max([50] + [len(v) + abs(Decimal(v).adjusted()) + 10 for v in values])
            limit = Decimal(str(credit["monthly_limit"])) if credit["monthly_limit"] is not None else None
            used = Decimal(str(credit["used_credits"])) if credit["used_credits"] is not None else None
            def money(cents):
                return "$" + format((cents / 100).quantize(Decimal("0.01"), rounding=ROUND_DOWN), ",.2f")
            if credit["currency"] != "USD":
                tray, known, summary = "¤", False, "追加利用中（USD 以外の通貨のため金額は表示しません）"
            elif credit["limit_known"] and limit is None:
                tray = "∞"
                summary = "追加利用：上限なし（今月の使用 " + money(used) + "）" if used is not None else "追加利用：上限なし（今月の使用額 未提供）"
            elif credit["limit_known"] and used is not None:
                left = max(Decimal(0), limit - used)
                tray = compact_credit(int(left / 100), dollars=True)
                summary = "追加利用：今月の上限まで残り " + money(left) + "（使用 " + money(used) + "）"
            else:
                tray, known = "¤", False
                summary = "追加利用：今月の上限 " + money(limit) + "（使用額 未提供）" if limit is not None else "追加利用中（金額未提供）"
            tooltip_summary = ("上限まで残り" + money(left)
                               if credit["currency"] == "USD" and credit["limit_known"] and limit is not None and used is not None
                               else summary)
    return {"kind": kind, "tray_text": tray, "amount_known": known, "title": title, "summary": summary}, tooltip_summary


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
    cached_credit = snapshot.get("credit") if isinstance(snapshot, dict) and cache.get("schema_version") != 1 else None
    validate_credit(cached_credit)
    if cached_credit is not None and snapshot.get("blocked") is not False:
        raise ValueError("Blocked cached credit")
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
    credit = None
    if not stale and cached_credit is not None:
        credit, credit_summary = credit_display(cached_credit)
    if stale:
        title = "Usageを確認できません"
        details.insert(0, "現在値は未確認です。" + ("以下は前回取得した残量です。" if rows else ""))
        details.append("接続・Codexのログイン状態をご確認ください。5分ごとに再確認します。")
        tooltip = "Codex Usage 未確認" + (" / 前回 " + fetched.astimezone(JST).strftime("%m/%d %H:%M") if fetched else "")
    elif credit is not None:
        title = credit["title"]
        details[0:0] = [credit["summary"], "Usage は使い切っています。"]
        tooltip = "Codex " + title + " / " + credit_summary + " / " + fetched.astimezone(JST).strftime("%H:%M取得")
    elif blocked:
        title = "利用制限が通知されています"
        details.append("サーバーが利用制限を通知しています。残量だけでは利用可否を判断できません。")
        tooltip = "Codex Usage 利用制限あり / " + fetched.astimezone(JST).strftime("%H:%M確認")
    else:
        title = f"Usage 残り {remaining:g}%"
        chosen = min(rows, key=lambda row: row["remaining_percent"])
        tooltip = f'Codex {chosen["label"]} 残り{remaining:g}% / ' + chosen["resets_label"] + " / " + fetched.astimezone(JST).strftime("%H:%M取得")
    if len(rows) > 1 and credit is None:
        details.append("トレイには、このCodex枠のうち最も少ない残量を表示します。")
    forecast = (usage_forecast.pending("unavailable", "現在の残量を確認できるまで予測を保留します。")
                if stale or blocked or credit is not None else usage_forecast.forecast(cache.get("history"), snapshot["windows"], now.timestamp(), label))
    if credit is not None:
        forecast = usage_forecast.pending("unavailable", "Credit 利用中は見通しを表示しません。")
    if not stale and not blocked and credit is None:
        short = {"comfortable": "余裕あり", "tight": "ペース注意", "at_risk": "不足注意",
                 "collecting": "判定待ち", "unavailable": "見通し未確認"}[forecast["status"]]
        affected = "(" + forecast["window_label"] + ")" if forecast["window_label"] else ""
        tooltip = short + affected + " / " + tooltip
    return {"ok": not stale, "stale": stale, "title": title, "detail": "\n".join(details),
            "checked_label": checked, "tooltip": tooltip[:63], "remaining_percent": None if stale or blocked else remaining,
            "windows": rows, "blocked": blocked, "forecast": forecast, "credit": credit}


