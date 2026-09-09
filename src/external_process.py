"""Do not pass a frozen Python application's DLL search path to Codex.

https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application
"""
from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading


_dll_lock = threading.Lock()


def default_cli_directories(home=None):
    """Finder omits common user-installed CLI locations; never search the cwd."""
    home = Path.home() if home is None else Path(home)
    return [home / ".local/bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin")]


def metadata_process_options():
    # A private session lets metadata cleanup terminate descendants as well.
    return ({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt"
            else {"start_new_session": True})


def install_termination_handlers():
    """Give bounded subprocess finally blocks a chance to run on native UI exit."""
    if os.name == "nt":
        return
    def terminate(signum, frame):
        for item in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(item, signal.SIG_IGN)
        raise SystemExit(128 + signum)
    for item in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(item, terminate)


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
        for key in ("PATH", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH",
                    "DYLD_FALLBACK_FRAMEWORK_PATH", "DYLD_INSERT_LIBRARIES"):
            if key in env:
                clean = os.pathsep.join(p for p in env[key].split(os.pathsep) if p and not bundled(p))
                if clean or key == "PATH":
                    env[key] = clean
                else:
                    env.pop(key)
        if sys.platform.startswith("linux"):
            original = env.pop("LD_LIBRARY_PATH_ORIG", None)
            if original is None:
                env.pop("LD_LIBRARY_PATH", None)
            else:
                env["LD_LIBRARY_PATH"] = original
    if sys.platform == "darwin":
        paths = [item for item in env.get("PATH", "").split(os.pathsep) if item and Path(item).is_absolute()]
        for path in default_cli_directories():
            if str(path) not in paths:
                paths.append(str(path))
        env["PATH"] = os.pathsep.join(paths)
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
