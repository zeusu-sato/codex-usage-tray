"""Bounded, experimental Claude metadata transport with response validation.

Only initialize and get_usage control requests can leave this module. No user
message, prompt, model selection, login, or credential-file read is supported.
The installed CLI retains responsibility for its existing authentication. An
optional local random salt derives a pseudonymous account scope in memory from
official initialize metadata; raw account names, email, and organization never
leave the adapter or get persisted.
"""
import json
import os
import queue
import re
import subprocess
import tempfile
import threading
import time

from external_process import dll_search_context, environment, metadata_process_options
from quota_monitor import QuotaError, kill_children_on_exit
from quota_support.claude_usage import _unique_object, _validate_scope_salt, _scope_key, _usage_fields, _ISO_TIMESTAMP, _reset_time, normalize


MINIMUM_VERSION = (2, 1, 263)
MAX_TIMEOUT_SECONDS = 16
MAX_LINE_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 2 * MAX_LINE_BYTES
MAX_MESSAGES = 2
INITIALIZE_ID = "usage-tray-initialize"
USAGE_ID = "usage-tray-get-usage"


def can_probe_version(version):
    """Accept identified releases from the first inspected protocol onward.

    A newer number is not proof of compatibility: the exact control exchange
    and quota schema must still validate on every read. There is no upper pin.
    """
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]{1,9}\.[0-9]{1,9}\.[0-9]{1,9}", version):
        return False
    return tuple(int(part) for part in version.split(".")) >= MINIMUM_VERSION


def _initialize():
    return {"type": "control_request", "request_id": INITIALIZE_ID,
            "request": {"subtype": "initialize", "promptSuggestions": False,
                        "agentProgressSummaries": False, "skills": [], "plugins": []}}


def _get_usage():
    return {"type": "control_request", "request_id": USAGE_ID,
            "request": {"subtype": "get_usage", "skip_behaviors": True}}


_ALLOWED_WIRE = frozenset(json.dumps(message, sort_keys=True)
                          for message in (_initialize(), _get_usage()))


def send_read_only(stream, message):
    """Exact envelopes, including false/true types; no caller-supplied content."""
    try:
        wire = json.dumps(message, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError, OverflowError):
        raise QuotaError("forbidden_method") from None
    if wire not in _ALLOWED_WIRE:
        raise QuotaError("forbidden_method")
    stream.write((wire + "\n").encode("utf-8"))
    stream.flush()


def _cleanup(process, stop, reader):
    stop.set()
    try:
        process.stdin.close()
    except OSError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            raise QuotaError("process_cleanup") from None
    finally:
        if reader is not None:
            reader.join(timeout=0.2)
        process.stdout.close()


def request_usage(binary, version, timeout=16, *, scope_salt=None):
    """Two metadata control requests, bounded output/time, then kill the job.

    Newer client releases may use this same control-only exchange. Invalid or
    older identities fail before launch; incompatible replies fail without a
    prompt, fallback conversation, model change, or automatic AI review.
    """
    if not can_probe_version(version):
        raise QuotaError("unsupported_version")
    _validate_scope_salt(scope_salt)
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not 0 < timeout <= MAX_TIMEOUT_SECONDS):
        raise QuotaError("invalid_timeout")
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(("CODEX_", "VSCODE_")) or key in (
                "CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT"):
            env.pop(key, None)
    for key in ("DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING", "DISABLE_AUTOUPDATER"):
        env[key] = "1"
    command = [str(binary), "--print", "--input-format", "stream-json", "--output-format", "stream-json",
               "--verbose", "--safe-mode", "--no-session-persistence", "--strict-mcp-config",
               "--no-chrome", "--disable-slash-commands", "--tools", "", "--setting-sources="]
    # A fresh empty working directory cannot contribute project settings.
    with tempfile.TemporaryDirectory(prefix="claude-usage-") as folder:
        deadline = time.monotonic() + timeout
        with dll_search_context():
            process = subprocess.Popen(command, cwd=folder, env=environment(env), stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       **metadata_process_options())
        messages = queue.Queue(maxsize=MAX_MESSAGES + 1)
        stop = threading.Event()
        failed = threading.Event()
        reader = None

        def read():
            total = count = 0
            try:
                while not stop.is_set():
                    line = process.stdout.readline(MAX_LINE_BYTES + 1)
                    if not line:
                        break
                    count += 1
                    total += len(line)
                    if len(line) > MAX_LINE_BYTES or total > MAX_OUTPUT_BYTES or count > MAX_MESSAGES:
                        raise ValueError("Output limit")
                    item = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_object)
                    if not isinstance(item, dict) or item.get("type") != "control_response":
                        raise ValueError("Unexpected category")
                    messages.put_nowait(item)
            except (ValueError, UnicodeError, OSError, queue.Full, RecursionError):
                failed.set()
            finally:
                try:
                    messages.put_nowait(None)
                except queue.Full:
                    failed.set()

        def receive(identifier):
            left = deadline - time.monotonic()
            if left <= 0:
                raise QuotaError("timeout")
            if failed.is_set():
                raise QuotaError("protocol")
            try:
                item = messages.get(timeout=left)
            except queue.Empty:
                raise QuotaError("timeout") from None
            if failed.is_set() or not isinstance(item, dict):
                raise QuotaError("protocol")
            response = item.get("response")
            if not isinstance(response, dict) or response.get("request_id") != identifier:
                raise QuotaError("protocol")
            if response.get("subtype") == "error":
                raise QuotaError("account_unavailable")
            if response.get("subtype") != "success" or "error" in response:
                raise QuotaError("protocol")
            data = response.get("response")
            if not isinstance(data, dict):
                raise QuotaError("protocol")
            return data

        try:
            with kill_children_on_exit(process):
                reader = threading.Thread(target=read, daemon=True)
                reader.start()
                send_read_only(process.stdin, _initialize())
                initialized = receive(INITIALIZE_ID)
                if failed.is_set():
                    raise QuotaError("protocol")
                if time.monotonic() >= deadline:
                    raise QuotaError("timeout")
                send_read_only(process.stdin, _get_usage())
                data = receive(USAGE_ID)
                return _usage_fields(data, initialized, scope_salt=scope_salt)
        finally:
            _cleanup(process, stop, reader)
