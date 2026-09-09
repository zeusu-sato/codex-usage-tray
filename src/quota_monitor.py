"""Read Codex account allowance without creating a conversation or running a model.

Uses the installed official app-server and its existing login. This module never
reads credentials, talks to undocumented HTTP endpoints, or submits a prompt.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import ctypes
import hashlib
from ctypes import wintypes
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from storage import atomic_write, exclusive_file
from external_process import dll_search_context, environment


ALLOWED_METHODS = frozenset(("initialize", "initialized", "account/rateLimits/read"))
MIN_REFRESH_SECONDS = 30
MAX_AGE_SECONDS = 10 * 60
JST = timezone(timedelta(hours=9))


class QuotaError(Exception):
    """Only stable local error categories; never expose raw server errors."""


def send_read_only(stream, message, allow_model_list=False):
    if (message.get("method") not in ALLOWED_METHODS
            and not (allow_model_list and message.get("method") == "model/list")):
        raise QuotaError("forbidden_method")
    stream.write(json.dumps(message) + "\n")
    stream.flush()


@contextmanager
def kill_children_on_exit(process):
    """Windows closes this job on parent exit, including a forced UI timeout."""
    if os.name != "nt":
        yield
        return
    class BasicLimits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                    ("active", wintypes.DWORD), ("affinity", ctypes.c_size_t),
                    ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]
    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("read_ops", "write_ops", "other_ops", "read", "write", "other")]
    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", BasicLimits), ("io", IoCounters),
                    ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                    ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise QuotaError("process_guard")
    try:
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
                or not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle)))):
            raise QuotaError("process_guard")
        yield
    finally:
        kernel.CloseHandle(job)


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
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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
                "clientInfo": {"name": "codex_usage_tray", "title": "Codex Usage Tray", "version": "0.1.0"}}})
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


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise QuotaError("unsupported_response")
    return value


def reset_time(value):
    if value is None:
        return None
    number(value)
    if not isinstance(value, int) or value < 0:
        raise QuotaError("unsupported_response")
    datetime.fromtimestamp(value, timezone.utc)  # Reject timestamps this PC cannot display.
    return value


def normalize(result):
    """Keep only the Codex quota, never substitute Spark/reserve or token totals."""
    buckets = result.get("rateLimitsByLimitId")
    if buckets is not None:
        if not isinstance(buckets, dict) or "codex" not in buckets:
            raise QuotaError("unsupported_response")
        bucket = buckets["codex"]
    else:
        bucket = result.get("rateLimits")
    if not isinstance(bucket, dict) or bucket.get("limitId") not in (None, "codex"):
        raise QuotaError("unsupported_response")
    windows = []
    for key in ("primary", "secondary"):
        raw = bucket.get(key)
        if raw is None:
            continue
        if not isinstance(raw, dict):
            raise QuotaError("unsupported_response")
        used = number(raw.get("usedPercent"))
        if used < 0:
            raise QuotaError("unsupported_response")
        duration = raw.get("windowDurationMins")
        if duration is not None and (number(duration) <= 0 or not isinstance(duration, int)):
            raise QuotaError("unsupported_response")
        windows.append({"kind": key, "remaining_percent": max(0, 100 - used),
                        "duration_mins": duration, "resets_at": reset_time(raw.get("resetsAt"))})
    individual = bucket.get("individualLimit")
    if individual is not None:
        if not isinstance(individual, dict):
            raise QuotaError("unsupported_response")
        remaining = number(individual.get("remainingPercent"))
        if not 0 <= remaining <= 100:
            raise QuotaError("unsupported_response")
        windows.append({"kind": "individual", "remaining_percent": remaining, "duration_mins": None,
                        "resets_at": reset_time(individual.get("resetsAt"))})
    if not windows:
        raise QuotaError("no_windows")
    blocked = bucket.get("spendControlReached") is True or bucket.get("rateLimitReachedType") is not None
    return {"windows": windows, "blocked": blocked}


def label(window):
    if window["kind"] == "individual":
        return "個人上限"
    duration = window["duration_mins"]
    if duration == 10080:
        return "Weekly"
    if duration is None:
        return "枠1" if window["kind"] == "primary" else "枠2"
    if duration % 1440 == 0:
        return str(duration // 1440) + "日枠"
    if duration % 60 == 0:
        return str(duration // 60) + "時間枠"
    return str(duration) + "分枠"


def reply(cache, now):
    snapshot = cache.get("snapshot")
    if snapshot is not None:
        if (not isinstance(snapshot, dict) or not isinstance(snapshot.get("windows"), list)
                or not 1 <= len(snapshot["windows"]) <= 3 or not isinstance(snapshot.get("blocked"), bool)):
            raise ValueError("Invalid cached snapshot")
        seen = set()
        for window in snapshot["windows"]:
            if window["kind"] not in ("primary", "secondary", "individual") or window["kind"] in seen:
                raise ValueError("Invalid cached window")
            seen.add(window["kind"])
            if not 0 <= number(window["remaining_percent"]) <= 100:
                raise ValueError("Invalid cached remaining quota")
            duration = window["duration_mins"]
            if duration is not None and (number(duration) <= 0 or not isinstance(duration, int)):
                raise ValueError("Invalid cached window duration")
            reset_time(window["resets_at"])
    fetched = datetime.fromisoformat(cache["fetched_at"]) if snapshot else None
    if fetched is not None and fetched.tzinfo is None:
        raise ValueError("Cached timestamp must include timezone")
    stale = (snapshot is None or not cache.get("last_ok", False)
             or not 0 <= (now - fetched).total_seconds() <= MAX_AGE_SECONDS
             or any(w["resets_at"] is not None and w["resets_at"] <= now.timestamp() for w in snapshot["windows"]))
    rows = []
    if snapshot:
        for window in snapshot["windows"]:
            reset = window["resets_at"]
            rows.append({"label": label(window), "remaining_percent": window["remaining_percent"],
                         "resets_label": ("リセット " + datetime.fromtimestamp(reset, JST).strftime("%m/%d %H:%M JST")
                                          if reset is not None else "リセット時刻: 未提供")})
    blocked = snapshot is not None and snapshot.get("blocked", False)
    remaining = min((row["remaining_percent"] for row in rows), default=None)
    details = [f'{r["label"]}: 残り {r["remaining_percent"]:g}%  ·  {r["resets_label"]}' for r in rows]
    checked = "最終取得: " + fetched.astimezone(JST).strftime("%m/%d %H:%M:%S JST") if fetched else "取得成功の記録はありません"
    if stale:
        title = "Usageを確認できません"
        details.insert(0, "現在値は未確認です。" + ("以下は前回取得した残量です。" if rows else ""))
        details.append("接続・Codexのログイン状態をご確認ください。5分ごとに再確認します。")
        tooltip = "Codex Usage 未確認" + (" / 前回 " + fetched.astimezone(JST).strftime("%m/%d %H:%M") if fetched else "")
    elif blocked:
        title = "利用制限が通知されています"
        details.append("サーバーが利用制限を通知しています。残量だけでは利用可否を判断できません。")
        tooltip = "Codex Usage 利用制限あり / " + fetched.astimezone(JST).strftime("%H:%M確認")
    else:
        title = f"Usage 残り {remaining:g}%"
        chosen = min(rows, key=lambda row: row["remaining_percent"])
        tooltip = f'Codex {chosen["label"]} 残り{remaining:g}% / ' + chosen["resets_label"] + " / " + fetched.astimezone(JST).strftime("%H:%M取得")
    if len(rows) > 1:
        details.append("トレイには、このCodex枠のうち最も少ない残量を表示します。")
    return {"ok": not stale, "stale": stale, "title": title, "detail": "\n".join(details),
            "checked_label": checked, "tooltip": tooltip[:63], "remaining_percent": None if stale or blocked else remaining,
            "windows": rows, "blocked": blocked}


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
        cache = {"schema_version": 1}
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("schema_version") == 1 and source is not None and existing.get("source") == source:
                reply(existing, now)  # Validate before retaining last-known data.
                cache = existing
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
            cache.update(snapshot=snapshot, fetched_at=now.isoformat(), last_ok=True)
            cache.pop("error", None)
        except (QuotaError, OSError, ValueError, TypeError, KeyError, AttributeError,
                StopIteration, OverflowError, subprocess.SubprocessError) as error:
            cache["error"] = str(error) if isinstance(error, QuotaError) else "unavailable"
        atomic_write(path, (json.dumps(cache, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        return reply(cache, now)


def unavailable_reply(now):
    return reply({}, now)
