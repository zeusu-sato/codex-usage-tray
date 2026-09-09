"""Bounded, experimental metadata transport for one verified Claude CLI version.

Only initialize and get_usage control requests can leave this module. No user
message, prompt, model selection, login, or credential-file read is supported.
The installed CLI retains responsibility for its existing authentication. An
optional local random salt derives a pseudonymous account scope in memory from
official initialize metadata; raw account names, email, and organization never
leave the adapter or get persisted.
"""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
from uuid import UUID

from external_process import dll_search_context, environment, metadata_process_options
from quota_monitor import QuotaError, kill_children_on_exit


SUPPORTED_VERSION = "2.1.263"
MAX_TIMEOUT_SECONDS = 16
MAX_LINE_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 2 * MAX_LINE_BYTES
MAX_MESSAGES = 2
INITIALIZE_ID = "usage-tray-initialize"
USAGE_ID = "usage-tray-get-usage"


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


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate field")
        result[key] = value
    return result


def _validate_scope_salt(scope_salt):
    if scope_salt is not None and (not isinstance(scope_salt, bytes) or len(scope_salt) < 32):
        raise QuotaError("invalid_scope_salt")


def _scope_key(initialized, scope_salt=None):
    """HMAC only in-memory official account metadata with an app-generated salt.

    The local salt is not a provider credential. Unsalted callers can only use
    explicit UUID identities, never a guessable email hash.
    """
    _validate_scope_salt(scope_salt)
    account = initialized.get("account")
    if not isinstance(account, dict):
        return None
    if scope_salt is not None:
        email = account.get("email")
        if (not isinstance(email, str) or not 1 <= len(email) <= 320
                or not re.fullmatch(r"[^@\s\x00-\x1f\x7f]+@[^@\s\x00-\x1f\x7f]+", email)):
            return None
        identity = {"email": email}
        for field, maximum in (("organization", 1024), ("apiProvider", 64), ("tokenSource", 128)):
            value = account.get(field)
            if value is None:
                continue
            if (not isinstance(value, str) or not 1 <= len(value) <= maximum
                    or not value.strip() or any(ord(character) < 32 or ord(character) == 127 for character in value)):
                return None
            identity[field] = value
        canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        return hmac.new(scope_salt, b"claude-usage-account-v1\0" + canonical, hashlib.sha256).hexdigest()
    try:
        account_id = str(UUID(account["accountUuid"]))
        organization = account.get("organizationUuid")
        organization_id = str(UUID(organization)) if organization is not None else ""
    except (KeyError, ValueError, TypeError, AttributeError):
        return None
    return hashlib.sha256(("claude-usage-v1\0" + account_id + "\0" + organization_id).encode()).hexdigest()


def _usage_fields(data, initialized, scope_salt=None):
    # Deliberately discard behavioral data, account details, and model windows.
    limits = data.get("rate_limits")
    result = {"rate_limits_available": data.get("rate_limits_available"),
              "rate_limits": ({key: {field: value[field] for field in ("utilization", "resets_at")
                                     if field in value} if isinstance(value, dict) else None
                               for key, value in limits.items() if key in ("five_hour", "seven_day")}
                              if isinstance(limits, dict) else None)}
    scope = _scope_key(initialized, scope_salt=scope_salt)
    if scope is not None:
        result["scope_key"] = scope
    return result


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

    The caller must verify the installed binary's version. Unsupported versions
    fail before process launch because this official extension API is experimental.
    """
    if version != SUPPORTED_VERSION:
        raise QuotaError("unsupported_version")
    _validate_scope_salt(scope_salt)
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not 0 < timeout <= MAX_TIMEOUT_SECONDS):
        raise QuotaError("invalid_timeout")
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("CODEX_") or key in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT"):
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


_ISO_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z")


def _reset_time(value):
    if value is None:
        return None
    if not isinstance(value, str) or not _ISO_TIMESTAMP.fullmatch(value):
        raise QuotaError("unsupported_response")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        timestamp = int(parsed.astimezone(timezone.utc).timestamp())
        if timestamp < 0:
            raise ValueError("Negative timestamp")
        return timestamp
    except (ValueError, OverflowError, OSError):
        raise QuotaError("unsupported_response") from None


def normalize(result):
    """Only the complete pair of global windows can report a current amount.

    Null reset times retain a known amount without inventing a refill or forecast.
    Expired timestamps remain expired so the shared cache renderer marks them stale.
    """
    if not isinstance(result, dict):
        raise QuotaError("unsupported_response")
    if result.get("rate_limits_available") is not True:
        raise QuotaError("account_unavailable")
    limits = result.get("rate_limits")
    if not isinstance(limits, dict):
        raise QuotaError("unsupported_response")
    windows = []
    for source, kind, duration in (("five_hour", "primary", 300), ("seven_day", "secondary", 10080)):
        if source not in limits or limits[source] is None:
            raise QuotaError("incomplete_windows")
        raw = limits[source]
        if not isinstance(raw, dict) or "resets_at" not in raw:
            raise QuotaError("unsupported_response")
        used = raw.get("utilization")
        if (isinstance(used, bool) or not isinstance(used, (int, float))
                or (isinstance(used, float) and not math.isfinite(used)) or used < 0):
            raise QuotaError("unsupported_response")
        windows.append({"kind": kind, "remaining_percent": max(0, 100 - used),
                        "duration_mins": duration, "resets_at": _reset_time(raw["resets_at"])})
    # Shared UI reserves blocked for an explicit non-quota restriction. Known
    # exhaustion remains numeric zero so it can be displayed as a red amount.
    return {"windows": windows, "blocked": False}
