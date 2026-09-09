"""Provider-isolated Claude snapshots. Only global 5-hour and weekly allowance."""
from datetime import datetime
from pathlib import Path
import subprocess
import secrets

import claude_adapter
import client_registry
import quota_monitor as quota
import usage_forecast
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
    result = quota.reply(cache, now)
    for key in ("title", "detail", "tooltip"):
        result[key] = result[key].replace("Codex", "Claude Code")
    result["detail"] += "\n対象: 全体の5時間枠・週間枠。モデル別の制限や追加利用分は含みません。"
    if cache.get("error") == "unsupported_version":
        result["detail"] = "Claude Codeのバージョンを確認できないか、2.1.263より古い版です。\n選択したクライアントをご確認ください。\n" + result["detail"]
    elif cache.get("error") == "incompatible_protocol":
        result["detail"] = "Claude Codeの残量取得への応答が対応形式と一致しません。\n続く場合はアプリの対応更新が必要です。\n" + result["detail"]
    if cache.get("last_ok") and not cache.get("account_scope"):
        result["forecast"] = usage_forecast.pending("unavailable", "アカウントの連続性を確認できないため、残量だけを表示します。")
    return result


def quota_command(folder, now):
    folder = Path(folder)
    with quota.quota_lock(folder):
        cache = {"schema_version": 1}
        try:
            client = client_registry.current_identity(folder)
            source = client_registry.fingerprint(client)
            try:
                existing = read_json(folder / "quota-state.json", {})
                if existing.get("schema_version") == 1 and existing.get("source") == source:
                    quota.reply(existing, now)
                    cache = existing
                attempted = (datetime.fromisoformat(cache["attempted_at"])
                             if cache.get("attempted_at") and cache.get("transport_revision") == TRANSPORT_REVISION else None)
            except (OSError,ValueError,TypeError,KeyError,AttributeError,OverflowError,quota.QuotaError):
                cache = {"schema_version":1}
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
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError,
                quota.QuotaError, subprocess.SubprocessError) as error:
            # Never persist raw process/server output or account identifiers.
            cache.update(attempted_at=now.isoformat(), last_ok=False)
            code = str(error) if isinstance(error, quota.QuotaError) else "unavailable"
            cache["error"] = ("unsupported_version" if code == "unsupported_version" else
                              "incompatible_protocol" if code in ("protocol", "unsupported_response", "incomplete_windows") else
                              "unavailable")
        write_json(folder / "quota-state.json", cache)
        return response(cache, now)
