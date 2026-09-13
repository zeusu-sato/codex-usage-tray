"""Small, atomic per-user storage. No credentials are read or copied."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def default_data_dir():
    if sys.platform == "linux":
        root = Path(os.environ.get("XDG_DATA_HOME", ""))
        if not root.is_absolute():
            root = Path.home() / ".local/share"
        return root / "CodexUsageTray"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/CodexUsageTray"
    root = os.environ.get("LOCALAPPDATA")
    return Path(root) / "CodexUsageTray" if root else Path.home() / ".local/share/CodexUsageTray"


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, data):
    atomic_write(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


@contextmanager
def exclusive_file(path, timeout=3):
    path = Path(path)
    if os.name != "nt":
        import fcntl
        with path.open("r+b") as stream:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Exclusive file access unavailable") from None
                    time.sleep(0.025)
            try:
                yield stream
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)
        return
    import msvcrt
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    deadline = time.monotonic() + timeout
    invalid = ctypes.c_void_p(-1).value
    while True:
        handle = kernel.CreateFileW(str(path), 0xC0000000, 0, None, 3, 0x80, None)
        if handle != invalid:
            break
        error = ctypes.get_last_error()
        if error not in (32, 33) or time.monotonic() >= deadline:
            raise OSError(error, "Exclusive file access unavailable")
        time.sleep(0.025)
    try:
        descriptor = msvcrt.open_osfhandle(int(handle), os.O_RDWR | os.O_BINARY)
    except Exception:
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(descriptor, "r+b") as stream:
        yield stream


@contextmanager
def locked(folder, name):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (name + ".lock")
    try:
        with path.open("xb"):
            pass
    except FileExistsError:
        pass
    with exclusive_file(path):
        yield
