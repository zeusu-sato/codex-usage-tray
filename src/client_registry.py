"""Discover user-installed Codex clients. Never bundle Codex or read auth files."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from external_process import dll_search_context, environment
from storage import locked, read_json, write_json


IDENTITY_KEYS = ("client_id", "cli_version", "extension_version", "binary_path", "binary_size", "binary_mtime_ns")


class ClientError(ValueError):
    pass


def descriptor(binary, client_id, label, extension_version="standalone"):
    binary = Path(binary).resolve(strict=True)
    if binary.name.casefold() != "codex.exe":
        raise ClientError("Unexpected executable name")
    stat = binary.stat()
    return {"client_id": client_id, "label": label, "extension_version": extension_version,
            "binary_path": str(binary), "binary_size": stat.st_size, "binary_mtime_ns": stat.st_mtime_ns}


def discover(home=None, which=shutil.which):
    home = Path(home or Path.home())
    found = []
    for client_id, label, name in (("vscode", "VS Code", ".vscode"), ("vscode-insiders", "VS Code Insiders", ".vscode-insiders")):
        root = (home / name / "extensions").resolve()
        try:
            entries = read_json(root / "extensions.json", [])
            matches = [entry for entry in entries if entry.get("identifier", {}).get("id") == "openai.chatgpt"]
            if len(matches) != 1:
                continue
            entry = matches[0]
            relative = entry.get("relativeLocation", "")
            if not re.fullmatch(r"openai\.chatgpt-[A-Za-z0-9_.-]+", relative):
                continue
            extension = (root / relative).resolve()
            if extension.parent != root:
                continue
            binary = extension / "bin/windows-x86_64/codex.exe"
            found.append(descriptor(binary, client_id, label, str(entry["version"])))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    binary = which("codex.exe")
    if binary and all(Path(item["binary_path"]) != Path(binary).resolve() for item in found):
        try:
            found.append(descriptor(binary, "cli-path", "Codex CLI (PATH)"))
        except (OSError, ValueError):
            pass
    return found


def settings(folder):
    data = read_json(Path(folder) / "settings.json", {"schema_version": 1})
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ClientError("Unsupported settings")
    return data


def choose_client(folder):
    clients = discover()
    selected = settings(folder).get("selected_client")
    if selected:
        matches = [client for client in clients if client["client_id"] == selected]
        if len(matches) == 1:
            return matches[0]
        raise ClientError("選択したCodexが見つかりません。Codexを選び直してください。")
    if len(clients) == 1:
        return clients[0]
    if not clients:
        raise ClientError("Codexが見つかりません。VS Code版またはCLI版をインストールしてログインしてください。")
    raise ClientError("複数のCodexがあります。「Codexを選ぶ…」で使用するものを選んでください。")


def client_command(folder, command, client_id=None):
    clients = discover()
    if command == "client-select":
        if client_id not in [client["client_id"] for client in clients]:
            raise ClientError("現在インストールされているCodexを選択してください。")
        with locked(folder, "settings-write"):
            data = settings(folder)
            if data.get("selected_client") != client_id:
                data["selected_client"] = client_id
                # References belong to their own client; switching cannot certify a policy.
                data.pop("reference", None)
                data.pop("reference_kind", None)
                write_json(Path(folder) / "settings.json", data)
    return {"ok": True, "selected_id": settings(folder).get("selected_client", ""),
            "clients": [{"id": client["client_id"], "label": client["label"] + " / " + client["extension_version"]} for client in clients]}


def current_identity(folder):
    client = choose_client(folder)
    cached = read_json(Path(folder) / "monitor-state.json", {}).get("current", {})
    if all(cached.get(key) == client.get(key) for key in ("client_id", "extension_version", "binary_path", "binary_size", "binary_mtime_ns")):
        version = cached.get("cli_version")
    else:
        version = None
    if not isinstance(version, str):
        with dll_search_context():
            process = subprocess.Popen([client["binary_path"], "--version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       text=True, encoding="utf-8", env=environment(),
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            output = process.communicate(timeout=5)[0]
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
            raise ClientError("Codexのバージョン確認がタイムアウトしました。") from None
        matched = re.fullmatch(r"codex-cli (\S+)\s*", output)
        if process.returncode or not matched:
            raise ClientError("Codexのバージョンを確認できません。")
        version = matched.group(1)
    return {**client, "cli_version": version}


def fingerprint(identity):
    return hashlib.sha256(json.dumps({k: identity[k] for k in IDENTITY_KEYS}, sort_keys=True).encode("utf-8")).hexdigest()
