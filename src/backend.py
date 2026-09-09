"""Codex Usage Tray command boundary. Only review-run may invoke AI."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import client_registry
import policy_manager
import quota_monitor
import reviews
import version_monitor
from external_process import install_termination_handlers
from storage import default_data_dir, locked, read_json, write_json


COMMANDS = ("status", "ui-status", "ui-enable", "ui-disable", "monitor-check", "monitor-notified",
            "usage-check", "client-list", "client-select", "review-status", "review-decide", "review-run", "review-latest")


def execute(args, now):
    folder = Path(args.data_dir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    provider = getattr(args, "provider", "codex")
    if provider == "claude":
        folder = folder / "providers" / "claude"
        with locked(folder, "settings-write"):
            data = read_json(folder / "settings.json", {"schema_version": 1})
            if data.get("provider") != "claude":
                data["provider"] = "claude"
                write_json(folder / "settings.json", data)
    command = args.command
    if command == "status":
        return policy_manager.runtime_status(folder)
    if command.startswith("ui-"):
        return policy_manager.ui_command(folder, command, now)
    if command.startswith("client-"):
        return client_registry.client_command(folder, command, args.client_id)
    if command.startswith("monitor-"):
        return version_monitor.monitor_command(folder, command, now, args.signature)
    if command == "usage-check":
        if provider == "claude":
            from claude_quota import quota_command
            return quota_command(folder, now)
        try:
            binary = client_registry.choose_client(folder)["binary_path"]
        except client_registry.ClientError:
            binary = None
        return quota_monitor.quota_command(folder, now, binary)
    if command == "review-latest":
        return reviews.latest_report(folder)
    if command in ("review-status", "review-decide"):
        return reviews.review_command(folder, command, now, args.signature, args.decision)
    raise ValueError("Unsupported background command")


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--data-dir", default=str(default_data_dir()))
    parser.add_argument("--provider", choices=("codex", "claude"), default="codex")
    parser.add_argument("--signature")
    parser.add_argument("--decision", choices=("yes", "no"))
    parser.add_argument("--client-id")
    parser.add_argument("--request")
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    if args.command == "review-run":
        try:
            if not args.request:
                raise ValueError("Missing request")
            review_folder = Path(args.data_dir) / "providers" / "claude" if args.provider == "claude" else Path(args.data_dir)
            code = reviews.run_console(review_folder, args.request, now)
            if code:
                print("Codexが正常に終了しませんでした。モデルの変更や自動再試行は行っていません。")
        except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError):
            print("見直しを完了できませんでした。アプリで再確認してください。未完成の結果を自動適用することはありません。")
        try:
            input("Enterキーで閉じます。")
        except (EOFError, KeyboardInterrupt):
            pass
        return
    try:
        result = execute(args, now)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError,
            StopIteration, subprocess.SubprocessError, quota_monitor.QuotaError) as error:
        detail = str(error) if isinstance(error, client_registry.ClientError) else "状態を確認できません。Codexのインストール・ログインと保存先をご確認ください。"
        if args.command == "status":
            result = {"active": False, "reason": "unavailable"}
        elif args.command.startswith("monitor-"):
            result = version_monitor.unavailable_reply(detail)
            if args.provider == "claude":
                result["needs_client_selection"] = len(client_registry.discover(provider="claude")) > 1
        elif args.command == "usage-check":
            result = quota_monitor.unavailable_reply(now)
        else:
            result = {"ok": False, "enabled": False, "can_enable": False, "can_review": False,
                      "should_prompt": False, "title": "確認できません", "detail": detail}
    if args.provider == "claude":
        # Provider-specific user-facing labels; reviewed prose itself is never rewritten.
        for key in ("title", "detail", "baseline_label", "current_label", "tooltip"):
            if isinstance(result.get(key), str) and args.command not in ("review-latest", "ui-status", "ui-enable", "ui-disable"):
                if not args.command.startswith("review-"):
                    result[key] = result[key].replace("Codex", "Claude Code")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    install_termination_handlers()
    main()
