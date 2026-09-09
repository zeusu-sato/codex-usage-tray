"""Optional, reviewed, user-enabled instructions with exact ownership checks."""
from datetime import timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from client_registry import current_identity, fingerprint, provider_for, display_name
from storage import atomic_write, exclusive_file, locked, read_json, write_json


BEGIN = "<!-- BEGIN CODEX-USAGE-TRAY-POLICY-V1 -->"
END = "<!-- END CODEX-USAGE-TRAY-POLICY-V1 -->"


def codex_home():
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).resolve()


def instruction_path(folder):
    if provider_for(folder) == "claude":
        return Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))).resolve() / "CLAUDE.md"
    return codex_home() / "AGENTS.md"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def block_span(data):
    begin, end = BEGIN.encode(), END.encode()
    if data.count(begin) != data.count(end) or data.count(begin) > 1:
        raise ValueError("The owned policy markers were edited")
    if begin not in data:
        return None
    first, last = data.index(begin), data.index(end)
    if last < first:
        raise ValueError("Invalid policy markers")
    last += len(end)
    if data[last:last + 2] == b"\r\n":
        last += 2
    elif data[last:last + 1] == b"\n":
        last += 1
    return first, last


def proposal(folder):
    data = read_json(Path(folder) / "proposal.json")
    if data is None:
        return None
    if (data.get("schema_version") != 1 or not isinstance(data.get("instructions"), str)
            or not isinstance(data.get("summary"), str) or not isinstance(data.get("identity"), dict)):
        raise ValueError("Invalid reviewed proposal")
    text = data["instructions"]
    if len(text) > 8000 or "\0" in text or "CODEX-USAGE-TRAY-POLICY" in text:
        raise ValueError("Invalid proposal instructions")
    if data.get("fingerprint") != fingerprint(data["identity"]):
        raise ValueError("Invalid reviewed client identity")
    report = (Path(folder) / "reviews" / data["review_id"] / "report.md").resolve(strict=True)
    if report.parent.parent != (Path(folder) / "reviews").resolve():
        raise ValueError("Invalid review report path")
    if digest(report.read_bytes()) != data.get("report_sha256"):
        raise ValueError("The reviewed report was edited")
    result_path = report.with_name("review-result.json")
    if digest(result_path.read_bytes()) != data.get("result_sha256"):
        raise ValueError("The reviewed result was edited")
    result = read_json(result_path)
    if any(result.get(key) != data[key] for key in ("instructions", "summary", "fingerprint")):
        raise ValueError("The proposal differs from the reviewed result")
    return data


def runtime_status(folder):
    active = read_json(Path(folder) / "active-policy.json", {})
    if active.get("enabled") is not True:
        return {"active": False, "reason": "disabled_or_unconfigured"}
    if active.get("launcher") != launcher_identity():
        return {"active": False, "reason": "application_changed"}
    current = current_identity(folder)
    if active.get("fingerprint") != fingerprint(current):
        return {"active": False, "reason": "client_changed"}
    data = instruction_path(folder).read_bytes()
    span = block_span(data)
    if span is None or digest(data[span[0]:span[1]]) != active.get("owned_block_sha256"):
        return {"active": False, "reason": "instructions_changed"}
    return {"active": True, "reason": "user_enabled_reviewed_policy"}


def launcher_identity():
    path = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()
    stat = path.stat()
    return [str(path), stat.st_size, stat.st_mtime_ns]


def ui_snapshot(folder):
    active = read_json(Path(folder) / "active-policy.json", {})
    current = current_identity(folder)
    current_fingerprint = fingerprint(current)
    candidate = proposal(folder)
    enabled = runtime_status(folder)["active"] if active.get("enabled") is True else False
    can_enable = bool(candidate and candidate["instructions"].strip() and candidate["fingerprint"] == current_fingerprint)
    if enabled:
        title, detail = "追加対策は有効です", "確認した環境で、ユーザーが選んだ追加指示を使用します。"
    elif candidate is None:
        title, detail = "追加対策は未設定です", display_name(folder) + "の通常動作を使用します。必要なら「AIで見直す…」で調査できます。"
    elif candidate["fingerprint"] != current_fingerprint:
        title, detail = "以前の追加対策は停止しています", "環境が変わったため、旧対策は適用しません。見直しが必要です。"
    elif not candidate["instructions"].strip():
        title, detail = "追加対策なしで使用します", candidate["summary"]
    else:
        title, detail = "追加対策の候補があります", candidate["summary"] + "\n「見直し結果を開く」で内容を確認し、有効にしてください。"
    return {"ok": True, "enabled": enabled, "can_enable": can_enable, "title": title, "detail": detail,
            "expires_label": "環境が変わると旧対策は適用しません · 固定期限なし"}


def owned_block(folder, instructions):
    provider = provider_for(folder)
    root = Path(folder).parent.parent if provider == "claude" else Path(folder)
    if getattr(sys, "frozen", False):
        command = [str(Path(sys.executable).resolve()), "--data-dir", str(root.resolve()), "status"]
    else:
        command = [str(Path(sys.executable).resolve()), str(Path(__file__).with_name("backend.py").resolve()),
                   "--data-dir", str(root.resolve()), "status"]
    if provider == "claude":
        command += ["--provider", "claude"]
    text = (BEGIN + "\nOptional instructions controlled by Codex Usage Tray:\n"
            "- Before applying the following instructions, once per user turn, execute this command with its literal arguments: "
            + json.dumps(command, ensure_ascii=False) + ".\n"
            "- Apply them only when a fresh response explicitly says active:true. A missing application, failed check, disabled switch, "
            "or changed client means use native behavior. This also applies to stale copies of these instructions.\n"
            "- Preserve the user's selected model, reasoning effort, required context, evidence and independent verification. "
            "Do not sacrifice quality or correctness to reduce Usage.\n"
            + instructions.strip() + "\n" + END + "\n")
    return text.encode("utf-8")


def ui_command(folder, command, now):
    folder = Path(folder)
    if command == "ui-status":
        return ui_snapshot(folder)
    if command not in ("ui-enable", "ui-disable"):
        raise ValueError("Unsupported policy action")
    with locked(folder, "policy-write"):
        active_path = folder / "active-policy.json"
        active = read_json(active_path, {"schema_version": 1, "enabled": False})
        desired = command == "ui-enable"
        candidate = proposal(folder) if desired else None
        if desired and not ui_snapshot(folder)["can_enable"]:
            return {**ui_snapshot(folder), "ok": False}
        agents = instruction_path(folder)
        if desired:
            agents.parent.mkdir(parents=True, exist_ok=True)
            try:
                with agents.open("xb"):
                    pass
            except FileExistsError:
                pass
        # Save the disabled state before touching global text: a partial write cannot activate a policy.
        active["enabled"] = False
        write_json(active_path, active)
        if not agents.exists():
            return ui_snapshot(folder)
        with exclusive_file(agents) as stream:
            original = stream.read()
            span = block_span(original)
            if span is not None and digest(original[span[0]:span[1]]) != active.get("owned_block_sha256"):
                raise ValueError("ユーザーが編集した追加指示を保護しました。自動では上書きしません。")
            remaining = original if span is None else original[:span[0]] + original[span[1]:]
            block = owned_block(folder, candidate["instructions"]) if desired else b""
            updated = remaining + (b"\n" if remaining and not remaining.endswith(b"\n") else b"") + block
            if updated != original:
                backup = folder / "backups" / (now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-AGENTS.md")
                atomic_write(backup, original)
                try:
                    stream.seek(0)
                    stream.write(updated)
                    stream.truncate()
                    stream.flush()
                    os.fsync(stream.fileno())
                except OSError:
                    stream.seek(0)
                    stream.write(original)
                    stream.truncate()
                    stream.flush()
                    raise
        if desired:
            active.update(enabled=True, fingerprint=candidate["fingerprint"], owned_block_sha256=digest(block),
                          review_id=candidate["review_id"], changed_at=now.isoformat(), launcher=launcher_identity())
        write_json(active_path, active)
        return ui_snapshot(folder)
