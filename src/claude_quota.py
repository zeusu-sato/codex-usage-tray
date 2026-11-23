"""Provider-isolated Claude snapshots. Only global 5-hour and weekly allowance."""
from datetime import datetime
from pathlib import Path
import re
import subprocess
import secrets

import claude_adapter
import client_registry
import quota_monitor as quota
import usage_forecast
from quota_support.codex_reply import stale_note, reset_time, number, JST
import unicodedata
from storage import read_json, write_json


RESET_JITTER_SECONDS = 120
TRANSPORT_REVISION = 2


def align_reset_history(history, windows, timestamp):
    """Match small Claude reset-time jitter, only away from either reset boundary.

    The caller has already established the same account scope. Only the history
    key changes; the current server snapshot remains untouched. record() still
    discards refills, clock reversals, and old samples normally.
    """
    saved = usage_forecast.valid_history(history)
    result = []
    for (kind, duration, old_reset), samples in saved.items():
        candidates = [window for window in windows
                      if window["kind"] == kind and window["duration_mins"] == duration]
        reset = old_reset
        if len(candidates) == 1:
            new_reset = candidates[0]["resets_at"]
            if (old_reset is not None and new_reset is not None
                    and old_reset > timestamp + RESET_JITTER_SECONDS
                    and new_reset > timestamp + RESET_JITTER_SECONDS
                    and abs(old_reset - new_reset) <= RESET_JITTER_SECONDS):
                reset = new_reset
        result.append({"kind": kind, "duration_mins": duration, "resets_at": reset, "samples": samples})
    return result


def response(cache, now):
    snapshot = cache.get("snapshot")
    models = snapshot.get("model_windows") if isinstance(snapshot, dict) else None
    try:
        if models is not None:
            if not isinstance(models, list) or len(models) > 4:
                raise ValueError()
            for model in models:
                name = model["name"]
                if (set(model) != {"name", "remaining_percent", "resets_at"} or not isinstance(name, str)
                        or not 1 <= len(name) <= 40 or name != name.strip()
                        or any(unicodedata.category(c) == "Cc" for c in name)
                        or not 0 <= number(model["remaining_percent"]) <= 100):
                    raise ValueError()
                reset_time(model["resets_at"])
    except (ValueError, TypeError, KeyError, OverflowError, quota.QuotaError, OSError):
        snapshot.pop("model_windows", None)
        models = None
    result = quota.reply(cache, now)
    if models:
        lines = result["detail"].splitlines()
        index = max((i for i, line in enumerate(lines) if any(
            line.startswith(row["label"] + ": 残り ") for row in result["windows"])), default=-1) + 1
        for model in models:
            reset = model["resets_at"]
            reset_label = ("リセット " + datetime.fromtimestamp(reset, JST).strftime("%m/%d %H:%M JST")
                           if reset is not None else "リセット時刻: 未提供")
            lines.insert(index, f'{model["name"]}: 残り {model["remaining_percent"]:g}%  ·  {reset_label}')
            index += 1
        result["detail"] = "\n".join(lines)
    for key in ("title", "detail", "tooltip", "note"):
        result[key] = result[key].replace("Codex", "Claude Code")
    windows = (cache.get("snapshot") or {}).get("windows", [])
    if windows and not any(w["kind"] == "primary" for w in windows):
        result["scope"] = "対象: 全体の週間枠。モデル別の制限は含みません。追加利用は Usage を使い切ったときだけ表示します。"
    else:
        result["scope"] = "対象: 全体の5時間枠・週間枠。モデル別の制限は含みません。追加利用は Usage を使い切ったときだけ表示します。"
    if models:
        target = "全体の週間枠" if windows and not any(w["kind"] == "primary" for w in windows) else "全体の5時間枠・週間枠"
        result["scope"] = "対象: " + target + "。モデル別の枠は一覧だけに表示します。追加利用は Usage を使い切ったときだけ表示します。"
    reasons = {
        "unsupported_version": "Claude Codeのバージョンを確認できないか、2.1.263より古い版です。選択したクライアントをご確認ください。",
        "usage_temporarily_unavailable": "Claude Code がClaudeのサーバーから利用枠を取得できませんでした。Claude側の一時的な問題の可能性があります。",
        "incompatible_protocol": "Claude Codeの応答が対応形式と一致しません。続く場合はアプリの更新が必要です。",
    }
    if result["stale"] and cache.get("error") in reasons:
        result["note"] = stale_note(bool(windows), reasons[cache["error"]])
    if cache.get("last_ok") and not cache.get("account_scope") and result["credit"] is None:
        result["forecast"] = usage_forecast.pending("unavailable", "アカウントの連続性を確認できないため、残量だけを表示します。")
    return result


def error_category(error):
    """Fixed local category names only, so a failed read stays diagnosable.

    Client selection problems and transport categories are kept apart, as the
    Codex cache already does; anything else is the generic unavailable.
    """
    if isinstance(error, client_registry.ClientError):
        return "client_unavailable"
    code = str(error) if isinstance(error, quota.QuotaError) else "unavailable"
    if code == "unsupported_version":
        return code
    if code in ("protocol", "unsupported_response", "incomplete_windows"):
        return "incompatible_protocol"
    return code if re.fullmatch(r"[a-z_]{1,40}", code) else "unavailable"


def quota_command(folder, now):
    folder = Path(folder)
    with quota.quota_lock(folder):
        cache = {"schema_version": 2}
        try:
            client = client_registry.current_identity(folder)
            source = client_registry.fingerprint(client)
            try:
                existing = read_json(folder / "quota-state.json", {})
                if existing.get("schema_version") in (1, 2) and existing.get("source") == source:
                    quota.reply(existing, now)
                    cache = existing
                    if cache["schema_version"] == 1 and isinstance(cache.get("snapshot"), dict):
                        cache["snapshot"]["credit"] = None
                attempted = (datetime.fromisoformat(cache["attempted_at"])
                             if cache.get("attempted_at") and cache.get("transport_revision") == TRANSPORT_REVISION else None)
            except (OSError,ValueError,TypeError,KeyError,AttributeError,OverflowError,quota.QuotaError):
                cache = {"schema_version":2}
                attempted = None
            if attempted and attempted.tzinfo and 0 <= (now-attempted).total_seconds() < quota.MIN_REFRESH_SECONDS:
                return response(cache, now)
            cache.update(source=source, attempted_at=now.isoformat(), last_ok=False, transport_revision=TRANSPORT_REVISION)
            salt = cache.get("scope_salt")
            try:
                if not isinstance(salt,str) or len(bytes.fromhex(salt)) != 32:
                    raise ValueError("Invalid local salt")
            except ValueError:
                salt = secrets.token_hex(32)
                cache.pop("history",None)
            cache["scope_salt"] = salt
            payload = claude_adapter.request_usage(client["binary_path"], client["cli_version"], scope_salt=bytes.fromhex(salt))
            snapshot = claude_adapter.normalize(payload)
            scope = payload.get("scope_key")
            if not isinstance(scope, str) or len(scope) != 64:
                scope = None
            if not scope or cache.get("account_scope") != scope:
                cache.pop("history", None)
            else:
                cache["history"] = align_reset_history(cache.get("history"), snapshot["windows"], now.timestamp())
            if scope:
                cache["history"] = usage_forecast.record(cache.get("history"), snapshot["windows"], now.timestamp())
            cache.update(snapshot=snapshot, account_scope=scope, fetched_at=now.isoformat(), last_ok=True)
            cache.pop("error", None)
            cache.pop("error_reason", None)
            cache.pop("error_detail", None)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError,
                quota.QuotaError, subprocess.SubprocessError) as error:
            # Never persist raw process/server output or account identifiers.
            cache.update(attempted_at=now.isoformat(), last_ok=False)
            cache["error"] = error_category(error)
            reason = str(error) if isinstance(error, quota.QuotaError) else None
            diagnostic = getattr(error, "reason", None) if isinstance(error, quota.QuotaError) else None
            if reason == "timeout":
                diagnostic = "timeout"
            if diagnostic in ("line_type", "line_limit", "json", "envelope", "behaviors", "timestamp", "utilization", "missing_weekly", "timeout", "process_exit"):
                cache["error_reason"] = diagnostic
            elif reason in ("protocol", "unsupported_response", "incomplete_windows"):
                cache["error_reason"] = reason
            else:
                cache.pop("error_reason", None)
            detail = getattr(error, "detail", None)
            if diagnostic == "line_type" and isinstance(detail, str) and re.fullmatch(r"[a-z_]{1,40}", detail):
                cache["error_detail"] = detail
            else:
                cache.pop("error_detail", None)
        cache["schema_version"] = 2
        write_json(folder / "quota-state.json", cache)
        return response(cache, now)
