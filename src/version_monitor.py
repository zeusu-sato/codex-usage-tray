"""Compare observed/reviewed client references without AI or web requests."""
from datetime import timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

from client_registry import current_identity, discover, fingerprint, settings
from storage import locked, read_json, write_json


JST = timezone(timedelta(hours=9))


def signature_for(reference, current):
    return hashlib.sha256(json.dumps([fingerprint(reference), fingerprint(current)]).encode()).hexdigest()


def monitor_command(folder, command, now, signature=None):
    folder = Path(folder)
    with locked(folder, "monitor-write"):
        cache = read_json(folder / "monitor-state.json", {"schema_version": 1})
        if command == "monitor-notified":
            if not signature or not re.fullmatch(r"[a-f0-9]{64}", signature) or signature != cache.get("signature"):
                return {"ok": False}
            cache["last_notified_signature"] = signature
            write_json(folder / "monitor-state.json", cache)
            return {"ok": True}
        current = current_identity(folder)
        with locked(folder, "settings-write"):
            data = settings(folder)
            if not data.get("reference"):
                data.update(reference=current, reference_kind="observed", observed_at=now.isoformat())
                write_json(folder / "settings.json", data)
        reference = data["reference"]
        mismatch = fingerprint(reference) != fingerprint(current)
        current_signature = signature_for(reference, current)
        alert = mismatch and cache.get("last_notified_signature") != current_signature
        if not mismatch:
            cache.pop("last_notified_signature", None)
        cache.update(current=current, reference=reference, mismatch=mismatch, signature=current_signature, checked_at=now.isoformat())
        write_json(folder / "monitor-state.json", cache)
        prefix = "見直し済み:" if data.get("reference_kind") == "reviewed" else "監視開始時:"
        def version(label, value):
            return label + " Codex " + value["cli_version"] + " / " + value["label"] + " " + value["extension_version"]
        return {"ok": True, "mismatch": mismatch, "alert": alert, "signature": current_signature,
                "title": "Codexの変更を検知しました" if mismatch else "監視の基準と一致しています",
                "detail": "旧対策は停止します。必要ならAIで見直せます。" if mismatch else "対象: " + current["label"],
                "checked_label": "最終確認: " + now.astimezone(JST).strftime("%m/%d %H:%M JST"),
                "baseline_label": version(prefix, reference), "current_label": version("現在:", current),
                "needs_client_selection": False}


def unavailable_reply(detail):
    return {"ok": False, "mismatch": False, "alert": False, "signature": "", "title": "Codexを確認できません",
            "detail": detail, "checked_label": "", "baseline_label": "", "current_label": "",
            "needs_client_selection": len(discover()) > 1}
