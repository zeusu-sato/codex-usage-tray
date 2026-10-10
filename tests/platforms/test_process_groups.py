import errno
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch
import external_process
import quota_monitor
import storage

class MetadataGroupErrorTests(unittest.TestCase):
    def setUp(self):
        kill_signal = patch.object(signal, 'SIGKILL', 9, create=True)
        kill_signal.start()
        self.addCleanup(kill_signal.stop)

    def test_darwin_reaps_exited_leader_and_requires_group_to_be_gone(self):
        process = Mock(pid=1234)
        process.poll.return_value = 0
        with patch.object(sys, 'platform', 'darwin'), patch.object(os, 'killpg', create=True,
                side_effect=[PermissionError(errno.EPERM, 'fixture'), ProcessLookupError()]) as kill:
            quota_monitor._kill_metadata_group(process, process.pid)
        process.poll.assert_called_once_with()
        process.wait.assert_not_called()
        self.assertEqual(kill.call_args_list, [call(1234, signal.SIGKILL), call(1234, 0)])

    def test_darwin_waits_for_exiting_leader_before_confirming_group_is_gone(self):
        process = Mock(pid=1234)
        process.poll.return_value = None
        process.wait.return_value = 0
        with patch.object(sys, 'platform', 'darwin'), patch.object(os, 'killpg', create=True,
                side_effect=[PermissionError(errno.EPERM, 'fixture'), ProcessLookupError()]) as kill:
            quota_monitor._kill_metadata_group(process, process.pid)
        process.wait.assert_called_once_with(timeout=0.5)
        self.assertEqual(kill.call_args_list, [call(1234, signal.SIGKILL), call(1234, 0)])

    def test_darwin_does_not_ignore_live_child_or_existing_group(self):
        for alive, probe in ((True, None), (False, None),
                             (False, PermissionError(errno.EPERM, 'fixture'))):
            with self.subTest(alive=alive, probe=probe):
                process = Mock(pid=1234)
                process.poll.return_value = None if alive else 0
                process.wait.side_effect = subprocess.TimeoutExpired('fixture', 0.5)
                error = PermissionError(errno.EPERM, 'fixture')
                with patch.object(sys, 'platform', 'darwin'), patch.object(os, 'killpg', create=True,
                        side_effect=[error, probe]) as kill:
                    with self.assertRaises(PermissionError) as raised:
                        quota_monitor._kill_metadata_group(process, process.pid)
                self.assertIs(raised.exception, error)
                self.assertTrue(error.__notes__[0].startswith('Metadata group cleanup:'))
                if alive:
                    process.wait.assert_called_once_with(timeout=0.5)
                else:
                    process.wait.assert_not_called()
                self.assertEqual(kill.call_args_list, [call(1234, signal.SIGKILL)]
                                 + ([] if alive else [call(1234, 0)]))

    def test_unrelated_permission_errors_are_preserved_without_reaping(self):
        for platform, code in (('linux', errno.EPERM), ('darwin', errno.EACCES)):
            with self.subTest(platform=platform, code=code):
                process = Mock(pid=1234)
                error = PermissionError(code, 'fixture')
                with patch.object(sys, 'platform', platform), patch.object(os, 'killpg', create=True,
                        side_effect=error) as kill:
                    with self.assertRaises(PermissionError) as raised:
                        quota_monitor._kill_metadata_group(process, process.pid)
                self.assertIs(raised.exception, error)
                kill.assert_called_once_with(1234, signal.SIGKILL)
                process.poll.assert_not_called()
                process.wait.assert_not_called()

    def test_missing_group_is_already_cleaned(self):
        process = Mock(pid=1234)
        with patch.object(os, 'killpg', create=True, side_effect=ProcessLookupError()) as kill:
            quota_monitor._kill_metadata_group(process, process.pid)
        kill.assert_called_once_with(1234, signal.SIGKILL)
        process.poll.assert_not_called()



@unittest.skipIf(os.name == 'nt', 'Real process groups, signals, and flock are POSIX-only; Windows has separate job-object tests')
class PosixLifecycleTests(unittest.TestCase):
    def test_darwin_exit_grace_reaps_real_child_after_initial_eperm(self):
        process = subprocess.Popen([sys.executable, '-u', '-c',
            'import sys,time; print("ready", flush=True); sys.stdin.read(1); time.sleep(0.03)'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, **external_process.metadata_process_options())
        original_killpg = os.killpg
        def killpg(group, signum):
            if signum == signal.SIGKILL:
                process.stdin.write(b'x')
                process.stdin.flush()
                raise PermissionError(errno.EPERM, 'Simulated Darwin exit transition')
            return original_killpg(group, signum)
        try:
            self.assertEqual(process.stdout.readline(), b'ready\n')
            self.assertIsNone(process.poll())
            with patch.object(sys, 'platform', 'darwin'), patch.object(os, 'killpg', side_effect=killpg) as kill:
                quota_monitor._kill_metadata_group(process, process.pid)
            self.assertEqual(process.returncode, 0)
            self.assertEqual(kill.call_args_list, [call(process.pid, signal.SIGKILL), call(process.pid, 0)])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)
            process.stdin.close()
            process.stdout.close()

    def test_exited_metadata_leader_is_cleaned_without_reaping_in_caller(self):
        process = subprocess.Popen([sys.executable, '-c', 'print("finished")'],
                                   stdout=subprocess.PIPE, **external_process.metadata_process_options())
        try:
            with quota_monitor.kill_children_on_exit(process):
                self.assertEqual(process.stdout.read(), b'finished\n')
                # EOF precedes reaping. Give the exited leader time to become a
                # zombie, reproducing the macOS native metadata fixture's exit.
                time.sleep(0.05)
            self.assertEqual(process.wait(timeout=2), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)
            process.stdout.close()

    def test_metadata_group_cleanup_kills_descendant_and_closes_inherited_pipe(self):
        process = subprocess.Popen([sys.executable, '-u', '-c',
            'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); print("ready",flush=True); time.sleep(60)'],
            stdout=subprocess.PIPE, **external_process.metadata_process_options())
        with quota_monitor.kill_children_on_exit(process):
            self.assertEqual(process.stdout.readline(), b'ready\n')
        process.wait(timeout=2)
        # EOF proves the descendant which inherited the pipe was also killed.
        self.assertEqual(process.communicate(timeout=2)[0], b'')
        process.stdout.close()

    def test_group_guard_refuses_the_callers_own_process_group(self):
        with self.assertRaisesRegex(quota_monitor.QuotaError, 'process_guard'):
            with quota_monitor.kill_children_on_exit(SimpleNamespace(pid=os.getpid())):
                self.fail('Unsafe group entered')

    def test_sigterm_runs_backend_finally(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'cleaned'
            script = ('from external_process import install_termination_handlers; import pathlib,sys,time\n'
                      'install_termination_handlers()\ntry:\n print("ready",flush=True)\n time.sleep(60)\n'
                      'finally:\n pathlib.Path(sys.argv[1]).write_text("cleaned")\n')
            env = dict(os.environ, PYTHONPATH=str(Path(external_process.__file__).parent))
            process = subprocess.Popen([sys.executable, '-u', '-c', script, str(marker)], env=env,
                                       stdout=subprocess.PIPE, **external_process.metadata_process_options())
            try:
                self.assertEqual(process.stdout.readline(), b'ready\n')
                process.terminate()
                process.wait(timeout=3)
                self.assertEqual(marker.read_text(), 'cleaned')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=3)
                process.stdout.close()

    def test_sigterm_backend_reaps_metadata_group_and_descendants(self):
        native = ('import subprocess,sys,time; subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
                  'print("ready",flush=True); time.sleep(60)')
        script = ('import subprocess,sys\nfrom external_process import install_termination_handlers,metadata_process_options\n'
                  'from quota_monitor import kill_children_on_exit\ninstall_termination_handlers()\n'
                  'process=subprocess.Popen([sys.executable,"-u","-c",sys.argv[1]],**metadata_process_options())\n'
                  'try:\n with kill_children_on_exit(process):\n  process.wait()\n'
                  'finally:\n process.wait(timeout=2)\n')
        env = dict(os.environ, PYTHONPATH=str(Path(external_process.__file__).parent))
        process = subprocess.Popen([sys.executable, '-u', '-c', script, native], env=env, stdout=subprocess.PIPE)
        self.assertEqual(process.stdout.readline(), b'ready\n')
        process.terminate()
        # Both descendants inherited stdout. EOF proves they cannot outlive cleanup.
        self.assertEqual(process.communicate(timeout=3)[0], b'')

    def test_file_lock_timeout_is_bounded(self):
        import fcntl
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / 'fixture.lock'; lock.write_bytes(b'')
            with lock.open('r+b') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX)
                started = time.monotonic()
                with self.assertRaises(TimeoutError):
                    with storage.exclusive_file(lock, timeout=0.1):
                        self.fail('Conflicting lock entered')
                self.assertLess(time.monotonic() - started, 1)
