"""An explicit, fresh Yes starts one visible review. Polling never calls a model."""
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
import uuid

from client_registry import current_identity, fingerprint, settings, provider_for, display_name
from external_process import dll_search_context, environment
from policy_manager import digest, proposal
from storage import atomic_write, locked, read_json, write_json
from version_monitor import signature_for
from review_support.process_identity import _ProcBSDInfo, darwin_process_identity, process_identity
from review_support.prompt import build_prompt


class ReviewError(ValueError):
    pass


def load_state(folder):
    state = read_json(Path(folder) / "review-state.json", {"schema_version": 1, "decisions": {}})
    if state.get("schema_version") != 1 or not isinstance(state.get("decisions"), dict):
        raise ReviewError("Unsupported review state")
    return state


def current_change(folder, signature):
    reference = settings(folder).get("reference")
    current = current_identity(folder)
    if not reference or not isinstance(signature, str) or signature != signature_for(reference, current):
        raise ReviewError("環境が変わりました。アプリで再確認してください。")
    return reference, current


def running(record):
    return (record.get("status") == "running" and record.get("process_created") is not None
            and process_identity(record.get("pid", 0)) == record["process_created"])


def reply(signature, record=None):
    record = record or {}
    active = running(record)
    status = record.get("status", "unanswered")
    if status == "running" and not active:
        status = "interrupted"
    return {"ok": True, "should_prompt": status == "unanswered", "can_review": not active,
            "status": status, "signature": signature, "request_path": record.get("request_path", ""),
            "title": "AIで対策を見直しますか？",
            "detail": ("見直し用のCodex画面が起動しています。" if active else
                       "はい (Yes) を押すと、その時点で利用可能な最上位モデル・最大推論強度で調査し、Usageを使用します。\n"
                       "いいえ (No) ならAIを起動しません。通常の監視は続きます。")}


def review_command(folder, command, now, signature, decision=None):
    folder = Path(folder)
    with locked(folder, "review-write"):
        reference, current = current_change(folder, signature)
        state = load_state(folder)
        active = next((record for record in state["decisions"].values() if running(record)), None)
        if active:
            return {**reply(signature, active), "ok": command == "review-status"}
        record = state["decisions"].get(signature)
        if command == "review-status":
            result = reply(signature, record)
            if provider_for(folder) == "claude":
                result["title"] = "Claude Codeの対策を見直しますか？"
                result["detail"] = "調査対象はClaude Codeです。見直しにはCodexを使い、CodexのUsageを消費します。\n" + result["detail"]
            return result
        if command != "review-decide" or decision not in ("yes", "no"):
            raise ReviewError("Explicit yes/no decision required")
        if decision == "no":
            record = {"status": "declined", "decided_at": now.isoformat()}
        else:
            workspace = folder / "reviews" / (now.strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12])
            workspace.mkdir(parents=True, exist_ok=False)
            request_path = workspace / "request.json"
            prompt = build_prompt(reference, current).encode("utf-8")
            request = {"schema_version": 1, "decision": "yes", "requested_at": now.isoformat(),
                       "signature": signature, "folder": str(folder.resolve()), "identity": current,
                       "prompt_sha256": digest(prompt), "model_policy": "best_available",
                       "reasoning_policy": "maximum_supported"}
            atomic_write(workspace / "prompt.md", prompt)
            write_json(request_path, request)
            record = {"status": "prepared", "decided_at": now.isoformat(), "request_path": str(request_path.resolve())}
        state["decisions"][signature] = record
        write_json(folder / "review-state.json", state)
        return reply(signature, record)


def accept_result(folder, workspace, identity, selected, now):
    """Validate completed artifacts, never assume exit code zero means a review exists."""
    if fingerprint(current_identity(folder)) != fingerprint(identity):
        raise ReviewError("調査中にCodexが変わったため、結果の適用を保留しました。")
    report = workspace / "report.md"
    result_path = workspace / "review-result.json"
    if report.is_symlink() or result_path.is_symlink():
        raise ReviewError("Unsupported report link")
    raw = report.read_bytes()
    if not 20 <= len(raw) <= 1024 * 1024:
        raise ReviewError("調査レポートが未完成です。")
    result = read_json(result_path)
    if (not isinstance(result, dict) or result.get("schema_version") != 1
            or result.get("review_complete") is not True or result.get("quality_preserved") is not True
            or result.get("fingerprint") != fingerprint(identity)):
        raise ReviewError("完了した見直し結果を確認できません。")
    if (not isinstance(result.get("instructions"), str) or len(result["instructions"]) > 8000
            or "\0" in result["instructions"] or "CODEX-USAGE-TRAY-POLICY" in result["instructions"]
            or not isinstance(result.get("summary"), str) or not 1 <= len(result["summary"]) <= 2000):
        raise ReviewError("未対応の対策案です。")
    for key in ("sources", "validation"):
        values = result.get(key)
        if not isinstance(values, list) or not values or len(values) > 100 or any(not isinstance(v, str) or not v.strip() or len(v) > 4000 for v in values):
            raise ReviewError("見直しの根拠と検証記録が必要です。")
    if any(not re.match(r"https://[^\s/]+/", url) for url in result["sources"]):
        raise ReviewError("確認した一次情報のURLが必要です。")
    candidate = {"schema_version": 1, "identity": identity, "fingerprint": fingerprint(identity),
                 "summary": result["summary"], "instructions": result["instructions"],
                 "review_id": workspace.name, "report_sha256": digest(raw),
                 "result_sha256": digest(result_path.read_bytes()), "selected_model": selected,
                 "reviewed_at": now.isoformat()}
    # Stop any earlier policy before registering a new review; never silently re-enable.
    with locked(folder, "policy-write"):
        active = read_json(folder / "active-policy.json", {"schema_version": 1})
        active["enabled"] = False
        write_json(folder / "active-policy.json", active)
        write_json(folder / "proposal.json", candidate)
        with locked(folder, "settings-write"):
            data = settings(folder)
            data.update(reference=identity, reference_kind="reviewed", reviewed_at=now.isoformat())
            write_json(folder / "settings.json", data)
    return candidate


def run_console(folder, request_path, now=None, selector=None, launch=None):
    folder = Path(folder).resolve()
    now = now or datetime.now(timezone.utc)
    request_path = Path(request_path).resolve(strict=True)
    if request_path.name != "request.json" or request_path.parent.parent != folder / "reviews":
        raise ReviewError("Invalid review request path")
    request = read_json(request_path)
    if (request.get("schema_version") != 1 or request.get("decision") != "yes" or request.get("folder") != str(folder)
            or request.get("model_policy") != "best_available" or request.get("reasoning_policy") != "maximum_supported"):
        raise ReviewError("Invalid review request")
    requested = datetime.fromisoformat(request["requested_at"])
    if requested.tzinfo is None or not 0 <= (now - requested).total_seconds() <= 300:
        raise ReviewError("Yesの確認から時間が経過しました。アプリで再度Yesを選んでください。")
    prompt_path = request_path.with_name("prompt.md")
    if prompt_path.is_symlink() or digest(prompt_path.read_bytes()) != request.get("prompt_sha256"):
        raise ReviewError("The approved prompt was changed")
    signature = request["signature"]
    with locked(folder, "review-write"):
        _, current = current_change(folder, signature)
        if fingerprint(request["identity"]) != fingerprint(current):
            raise ReviewError("Client changed after approval")
        state = load_state(folder)
        record = state["decisions"].get(signature, {})
        if (record.get("status") != "prepared" or record.get("request_path") != str(request_path)
                or any(running(r) for r in state["decisions"].values())):
            raise ReviewError("このYesは使用済みか、別の見直しが実行中です。")
        created = process_identity(os.getpid())
        if created is None:
            raise ReviewError("Cannot track review process")
        record.update(status="running", pid=os.getpid(), process_created=created, started_at=now.isoformat())
        write_json(folder / "review-state.json", state)
    exit_code, accepted = -1, False
    try:
        if selector is None:
            from model_catalog import select_for_review
            selector = select_for_review
        reviewer = current_identity(folder.parent.parent) if provider_for(folder) == "claude" else current
        selected = selector(reviewer["binary_path"])
        write_json(request_path.with_name("selected-model.json"), selected)
        current_change(folder, signature)
        command = [reviewer["binary_path"], "--no-alt-screen", "--search", "-m", selected["model"],
                   "-c", "model_reasoning_effort=" + selected["effort"], "-c", "service_tier=default",
                   "--sandbox", "workspace-write", "-C", str(request_path.parent),
                   "Read prompt.md in this workspace and perform the user-authorized review. Write report.md and review-result.json as specified. Respond in Japanese."]
        print(selected["display_name"] + " / " + selected["effort"] + " で見直します。この操作はUsageを使用します。", flush=True)
        with dll_search_context():
            process = (launch or subprocess.Popen)(command, cwd=request_path.parent, env=environment())
        try:
            exit_code = process.wait()
        except BaseException:
            # Interactive Codex shares Terminal's foreground process group.
            # Closing Terminal signals that group; direct backend interruption
            # also explicitly terminates/reaps the native Codex child here.
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
            raise
        if exit_code == 0:
            accept_result(folder, request_path.parent, current, selected, datetime.now(timezone.utc))
            accepted = True
            print("見直し結果を保存しました。アプリで結果を読み、必要な対策をONにしてください。", flush=True)
        return exit_code
    finally:
        with locked(folder, "review-write"):
            state = load_state(folder)
            record = state["decisions"].get(signature, {})
            if record.get("request_path") == str(request_path):
                record.update(status="finished" if accepted else "incomplete", exit_code=exit_code,
                              ended_at=datetime.now(timezone.utc).isoformat())
                write_json(folder / "review-state.json", state)


def latest_report(folder):
    candidate = proposal(folder)
    if candidate is None:
        return {"ok": False, "report_path": "", "detail": "完了した見直し結果はありません。"}
    return {"ok": True, "report_path": str((Path(folder) / "reviews" / candidate["review_id"] / "report.md").resolve()),
            "detail": candidate["summary"]}
