"""Synthetic Linux UI demo data; never discovers clients or launches processes."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import quota_monitor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--provider", choices=("codex", "claude"), required=True)
    parser.add_argument("--client-id")
    parser.add_argument("--signature")
    args = parser.parse_args()
    name = "Codex" if args.provider == "codex" else "Claude Code"
    if args.command == "usage-check":
        now = datetime.now(timezone.utc)
        cache = {"fetched_at": now.isoformat(), "last_ok": True,
                 "snapshot": {"blocked": False, "windows": [
                     {"kind": "primary", "remaining_percent": 73 if args.provider == "codex" else 62,
                      "duration_mins": 300, "resets_at": int((now + timedelta(hours=3)).timestamp())},
                     {"kind": "secondary", "remaining_percent": 48 if args.provider == "codex" else 85,
                      "duration_mins": 10080, "resets_at": int((now + timedelta(days=4)).timestamp())}]}}
        result = quota_monitor.reply(cache, now)
        result["detail"] = "デモ：架空の残量です。\n" + result["detail"].replace("Codex", name)
        result["tooltip"] = "デモ / " + result["tooltip"].replace("Codex", name)
    elif args.command == "client-list":
        result = {"ok": True, "selected_id": "fixture", "clients": [{"id": "fixture", "label": name + " デモ"}]}
    elif args.command == "monitor-check":
        result = {"ok": True, "title": name + " デモクライアント", "alert": False,
                  "baseline_label": "監視開始時: デモ", "current_label": "現在: デモ", "checked_label": "外部通信なし"}
    else:
        raise ValueError("Unsupported fixture command")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
