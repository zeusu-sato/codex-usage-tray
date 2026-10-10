from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import errno
import os
import signal
import subprocess
import sys
from quota_support.errors import QuotaError


def _kill_metadata_group(process, group):
    try:
        os.killpg(group, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError as error:
        # Darwin excludes zombies from killpg's eligible targets and returns
        # EPERM while a leader is exiting, before waitpid can reap it. Allow a
        # short bounded wait for our child, then suppress that error only if its
        # entire group is confirmed gone.
        # Do not retry SIGKILL after reaping: the group ID could have been reused.
        if sys.platform != "darwin" or error.errno != errno.EPERM:
            raise
        if process.poll() is None:
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                error.add_note("Metadata group cleanup: child did not exit within the 0.5 second Darwin grace.")
                raise error from None
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            return
        except OSError as probe_error:
            error.add_note("Metadata group cleanup: group probe failed after child was reaped.")
            raise error from probe_error
        error.add_note("Metadata group cleanup: group still exists after child was reaped.")
        raise error


@contextmanager
def kill_children_on_exit(process):
    """Windows Job or POSIX private process group; metadata only, never the UI group."""
    if os.name != "nt":
        try:
            group = os.getpgid(process.pid)
        except ProcessLookupError:
            group = process.pid  # Exited leader may still have live descendants.
        if group != process.pid or group == os.getpgrp():
            raise QuotaError("process_guard")
        try:
            yield
        finally:
            _kill_metadata_group(process, group)
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


