import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys


class _ProcBSDInfo(ctypes.Structure):
    # Apple's public ABI: https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/proc_info.h
    # PROC_PIDTBSDINFO includes the kernel's microsecond process-start timestamp.
    _fields_ = ([(name, ctypes.c_uint32) for name in
                 ("flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid", "rgid", "svuid", "svgid", "reserved")]
                + [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)]
                + [(name, ctypes.c_uint32) for name in ("nfiles", "pgid", "pjobc", "tdev", "tpgid")]
                + [("nice", ctypes.c_int32), ("started_seconds", ctypes.c_uint64), ("started_microseconds", ctypes.c_uint64)])


def darwin_process_identity(pid):
    try:
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        query = library.proc_pidinfo
        query.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int)
        query.restype = ctypes.c_int
        info = _ProcBSDInfo()
        size = ctypes.sizeof(info)
        if (query(pid, 3, 0, ctypes.byref(info), size) != size or info.pid != pid
                or info.status == 5 or info.flags & 4 or info.started_seconds == 0):
            return None
        return "darwin:" + str(info.started_seconds) + ":" + str(info.started_microseconds)
    except (OSError, AttributeError):
        return None


def process_identity(pid):
    if isinstance(pid, bool) or not isinstance(pid, int) or not 0 < pid <= 0x7fffffff:
        return None
    if sys.platform == "darwin":
        return darwin_process_identity(pid)
    if os.name != "nt":
        try:
            fields = Path("/proc", str(pid), "stat").read_text().rsplit(")", 1)[1].split()
            boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            return "linux:" + boot + ":" + fields[19] if fields[0] != "Z" else None
        except (OSError, ValueError, IndexError):
            return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return None
    try:
        code = wintypes.DWORD()
        times = [ctypes.c_uint64() for _ in range(4)]
        if (not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259
                or not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times))):
            return None
        return str(times[0].value)
    finally:
        kernel.CloseHandle(handle)


