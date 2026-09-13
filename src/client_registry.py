"""Discover installed Codex/Claude clients without reading credentials."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

from external_process import default_cli_directories, dll_search_context, environment, metadata_process_options
from storage import locked, read_json, write_json


IDENTITY_KEYS = ("client_id", "cli_version", "extension_version", "binary_path", "binary_size", "binary_mtime_ns")


class ClientError(ValueError):
    pass


def native_arch(machine=None):
    return {"arm64": "aarch64", "aarch64": "aarch64", "x86_64": "x86_64",
            "amd64": "x86_64", "x64": "x86_64"}.get((machine or platform.machine()).lower())


def npm_codex_binary(launcher, arch):
    """Resolve the official npm launcher to its native optional dependency.

    Layout: https://github.com/openai/codex/blob/main/codex-cli/bin/codex.js
    No Node/shell is executed.
    """
    package = launcher.parent.parent
    if read_json(package / "package.json", {}).get("name") != "@openai/codex":
        raise ClientError("Unsupported CLI launcher")
    package_name = "codex-darwin-" + ("arm64" if arch == "aarch64" else "x64")
    roots = (package / "node_modules/@openai" / package_name, package.parent / package_name)
    for root in roots:
        if read_json(root / "package.json", {}).get("name") == "@openai/" + package_name:
            candidate = root / "vendor" / (arch + "-apple-darwin") / "bin/codex"
            if candidate.is_file():
                return candidate.resolve(strict=True)
    candidate = package / "vendor" / (arch + "-apple-darwin") / "bin/codex"
    if candidate.is_file():
        return candidate.resolve(strict=True)
    raise ClientError("Native Codex dependency is missing")


def descriptor(binary, client_id, label, extension_version="standalone", provider="codex", *, platform_name=None, machine=None):
    platform_name = sys.platform if platform_name is None else platform_name
    launcher = Path(binary)
    expected = provider + (".exe" if platform_name == "win32" else "")
    if launcher.name.casefold() != expected:
        raise ClientError("Unexpected executable name")
    binary = launcher.resolve(strict=True)
    if platform_name == "win32" and binary.name.casefold() != expected:
        raise ClientError("Unexpected executable name")
    if platform_name == "darwin" and provider == "codex" and binary.name == "codex.js":
        arch = native_arch(machine)
        if arch is None:
            raise ClientError("Unsupported architecture")
        binary = npm_codex_binary(binary, arch)
    if not binary.is_file() or (platform_name != "win32" and not os.access(binary, os.X_OK)):
        raise ClientError("CLI is not executable")
    stat = binary.stat()
    return {"client_id": client_id, "label": label, "extension_version": extension_version,
            "binary_path": str(binary), "binary_size": stat.st_size, "binary_mtime_ns": stat.st_mtime_ns}


def discover(home=None, which=shutil.which, provider="codex", *, platform_name=None, machine=None):
    platform_name = sys.platform if platform_name is None else platform_name
    if platform_name not in ("win32", "darwin", "linux") or provider not in ("codex", "claude"):
        return []
    home = Path(home or Path.home())
    arch = native_arch(machine)
    if arch is None:
        return []
    name = provider + (".exe" if platform_name == "win32" else "")
    found = []
    for client_id, label, directory_name in (("vscode", "VS Code", ".vscode"), ("vscode-insiders", "VS Code Insiders", ".vscode-insiders")):
        root = (home / directory_name / "extensions").resolve()
        try:
            entries = read_json(root / "extensions.json", [])
            extension_id = "anthropic.claude-code" if provider == "claude" else "openai.chatgpt"
            matches = [entry for entry in entries if entry.get("identifier", {}).get("id") == extension_id]
            if len(matches) != 1:
                continue
            entry = matches[0]
            relative = entry.get("relativeLocation", "")
            if not re.fullmatch(re.escape(extension_id) + r"-[A-Za-z0-9_.-]+", relative):
                continue
            extension = (root / relative).resolve()
            if extension.parent != root:
                continue
            if provider == "claude":
                node_arch = "arm64" if arch == "aarch64" else "x64"
                candidates = [extension / "resources/native-binaries" / (platform_name + "-" + node_arch) / name,
                              extension / "resources/native-binary" / name]
            else:
                # The official extension maps darwin/arm64 to macos-aarch64.
                system = {"win32": "windows", "darwin": "macos", "linux": "linux"}[platform_name]
                candidates = [extension / "bin" / (system + "-" + arch) / name]
            binary = next((path for path in candidates if path.is_file()), candidates[-1])
            found.append(descriptor(binary, client_id, label, str(entry["version"]), provider,
                                    platform_name=platform_name, machine=machine))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    binary = which(name)
    candidates = [Path(binary)] if binary else []
    if platform_name == "darwin":
        candidates.extend(path / name for path in default_cli_directories(home))
    for candidate in candidates:
        try:
            suffix = " CLI (PATH)" if platform_name == "win32" else " CLI"
            item = descriptor(candidate, "cli-path", ("Claude Code" if provider == "claude" else "Codex") + suffix,
                              provider=provider, platform_name=platform_name, machine=machine)
            if all(item["binary_path"] != existing["binary_path"] for existing in found):
                found.append(item)
            # PATH precedence is preserved; fallback directories are for Finder.
            break
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    return found


def settings(folder):
    data = read_json(Path(folder) / "settings.json", {"schema_version": 1})
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ClientError("Unsupported settings")
    return data


def provider_for(folder):
    value = settings(folder).get("provider", "codex")
    if value not in ("codex", "claude"):
        raise ClientError("Unsupported provider")
    return value


def clients_for(folder):
    return discover(provider="claude") if provider_for(folder) == "claude" else discover()


def display_name(folder):
    return "Claude Code" if provider_for(folder) == "claude" else "Codex"


def choose_client(folder):
    clients = clients_for(folder)
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
    clients = clients_for(folder)
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
        from quota_monitor import kill_children_on_exit
        with dll_search_context():
            process = subprocess.Popen([client["binary_path"], "--version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       text=True, encoding="utf-8", env=environment(),
                                       **metadata_process_options())
        try:
            with kill_children_on_exit(process):
                output = process.communicate(timeout=5)[0]
        except subprocess.TimeoutExpired:
            raise ClientError("Codexのバージョン確認がタイムアウトしました。") from None
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=1)
            process.stdout.close()
        matched = re.fullmatch(r"(\d+\.\d+\.\d+) \(Claude Code\)\s*" if provider_for(folder) == "claude" else r"codex-cli (\S+)\s*", output)
        if process.returncode or not matched:
            raise ClientError("Codexのバージョンを確認できません。")
        version = matched.group(1)
    return {**client, "cli_version": version, "provider": provider_for(folder)}


def fingerprint(identity):
    return hashlib.sha256(json.dumps({k: identity[k] for k in IDENTITY_KEYS}, sort_keys=True).encode("utf-8")).hexdigest()
