"""Do not pass a frozen Python application's DLL search path to Codex.

https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application
"""
from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import sys
import threading


_dll_lock = threading.Lock()


def environment(source=None):
    env = dict(os.environ if source is None else source)
    for key in ("CODEX_THREAD_ID", "CODEX_INTERNAL_ORIGINATOR_OVERRIDE"):
        env.pop(key, None)
    if getattr(sys, "frozen", False):
        bundle = Path(sys._MEIPASS).resolve()
        def bundled(value):
            try:
                path = Path(value).resolve()
                return path == bundle or bundle in path.parents
            except (OSError, ValueError):
                return False
        env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if p and not bundled(p))
    return env


@contextmanager
def dll_search_context():
    if os.name != "nt" or not getattr(sys, "frozen", False):
        yield
        return
    with _dll_lock:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.SetDllDirectoryW.argtypes = (ctypes.c_wchar_p,)
        kernel.SetDllDirectoryW.restype = ctypes.c_int
        if not kernel.SetDllDirectoryW(None):
            raise OSError("Cannot restore system DLL search")
        try:
            yield
        finally:
            kernel.SetDllDirectoryW(str(sys._MEIPASS))
