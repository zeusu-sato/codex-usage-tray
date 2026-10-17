"""Read Codex account allowance without creating a conversation or running a model.

Uses the installed official app-server and its existing login. This module never
reads credentials, talks to undocumented HTTP endpoints, or submits a prompt.
"""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from storage import atomic_write, exclusive_file
from external_process import dll_search_context, environment, metadata_process_options
import usage_forecast
from quota_support.errors import QuotaError
from quota_support.process_group import _kill_metadata_group, kill_children_on_exit
from quota_support.codex_reply import MAX_AGE_SECONDS, JST, number, reset_time, normalize, label, reply


ALLOWED_METHODS = frozenset(("initialize", "initialized", "account/rateLimits/read"))
MIN_REFRESH_SECONDS = 30
def send_read_only(stream, message, allow_model_list=False):
    if (message.get("method") not in ALLOWED_METHODS
            and not (allow_model_list and message.get("method") == "model/list")):
        raise QuotaError("forbidden_method")
    stream.write(json.dumps(message) + "\n")
    stream.flush()


def request_rate_limits(binary, timeout=16):
    """One initialized stdio connection, one quota read, then process cleanup."""
    return request_metadata(binary, "account/rateLimits/read", timeout=timeout)


def request_metadata(binary, method, params=None, timeout=16):
    """Two explicitly supported metadata reads; no thread, turn, or tool methods."""
    if method not in ("account/rateLimits/read", "model/list"):
        raise QuotaError("forbidden_method")
    env = os.environ.copy()
    # The tray is not a child reasoning session and never attaches to this turn.
    for key in ("CODEX_THREAD_ID", "CODEX_INTERNAL_ORIGINATOR_OVERRIDE"):
        env.pop(key, None)
    with dll_search_context():
        process = subprocess.Popen([str(binary), "app-server", "--listen", "stdio://"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   text=True, encoding="utf-8", errors="strict", env=environment(env),
                                   cwd=Path(__file__).resolve().parent,
                                   **metadata_process_options())
    messages = queue.Queue(maxsize=128)
    stop = threading.Event()

    def reader():
        try:
            while not stop.is_set():
                line = process.stdout.readline(1024 * 1024 + 1)
                if not line:
                    break
                if len(line) > 1024 * 1024:
                    raise QuotaError("protocol")
                message = json.loads(line)
                messages.put_nowait(message)
        except (ValueError, UnicodeError, OSError, queue.Full, QuotaError):
            pass
        finally:
            try:
                messages.put_nowait(None)
            except queue.Full:
                pass

    def receive(identifier, deadline):
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise QuotaError("timeout")
            try:
                message = messages.get(timeout=left)
            except queue.Empty:
                raise QuotaError("timeout") from None
            if not isinstance(message, dict):
                raise QuotaError("protocol")
            # A metadata-only client has no reason to fulfill server requests.
            if "method" in message and "id" in message:
                raise QuotaError("unexpected_request")
            if message.get("id") == identifier:
                if "error" in message:
                    raise QuotaError("account_unavailable")
                if not isinstance(message.get("result"), dict):
                    raise QuotaError("protocol")
                return message["result"]

    try:
        with kill_children_on_exit(process):
            threading.Thread(target=reader, daemon=True).start()
            deadline = time.monotonic() + timeout
            send_read_only(process.stdin, {"id": 1, "method": "initialize", "params": {
                "clientInfo": {"name": "codex_usage_tray", "title": "Codex Usage Tray", "version": "0.2.0"}}})
            receive(1, deadline)
            send_read_only(process.stdin, {"method": "initialized"})
            request = {"id": 2, "method": method}
            if params is not None:
                request["params"] = params
            send_read_only(process.stdin, request, allow_model_list=method == "model/list")
            return receive(2, deadline)
    finally:
        stop.set()
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
        process.stdout.close()


@contextmanager
def quota_lock(folder):
    path = folder / "quota-write.lock"
    try:
        with path.open("xb"):
            pass
    except FileExistsError:
        pass
    with exclusive_file(path):
        yield


def quota_command(folder, now, binary=None):
    """Independent cache/lock: allowance reads never touch mitigation settings."""
    path = folder / "quota-state.json"
    source = None
    if binary is not None:
        resolved = Path(binary).resolve(strict=True)
        stat = resolved.stat()
        source = hashlib.sha256(str((str(resolved), stat.st_size, stat.st_mtime_ns)).encode()).hexdigest()
    with quota_lock(folder):
        cache = {"schema_version": 2}
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("schema_version") in (1, 2) and source is not None and existing.get("source") == source:
                reply(existing, now)  # Validate before retaining last-known data.
                cache = existing
                if cache["schema_version"] == 1 and isinstance(cache.get("snapshot"), dict):
                    cache["snapshot"]["credit"] = None
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, QuotaError):
            pass
        try:
            attempted = datetime.fromisoformat(cache["attempted_at"]) if cache.get("attempted_at") else None
            if attempted is not None and attempted.tzinfo is None:
                attempted = None
        except (ValueError, TypeError):
            attempted = None
        if attempted and 0 <= (now - attempted).total_seconds() < MIN_REFRESH_SECONDS:
            return reply(cache, now)
        cache.update(attempted_at=now.isoformat(), last_ok=False, source=source)
        try:
            if binary is None:
                raise QuotaError("client_unavailable")
            snapshot = normalize(request_rate_limits(binary))
            cache["history"] = usage_forecast.record(cache.get("history"), snapshot["windows"], now.timestamp())
            cache.update(snapshot=snapshot, fetched_at=now.isoformat(), last_ok=True)
            cache.pop("error", None)
        except (QuotaError, OSError, ValueError, TypeError, KeyError, AttributeError,
                StopIteration, OverflowError, subprocess.SubprocessError) as error:
            cache["error"] = str(error) if isinstance(error, QuotaError) else "unavailable"
        cache["schema_version"] = 2
        atomic_write(path, (json.dumps(cache, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        return reply(cache, now)


def unavailable_reply(now):
    return reply({}, now)
