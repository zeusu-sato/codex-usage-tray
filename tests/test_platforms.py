"""Platform fixtures only: no installed client, account, or inference."""
import ctypes
import errno
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

import client_registry as clients
import external_process
import policy_manager
import quota_monitor
import reviews
import storage


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        directories = patch.object(clients, 'default_cli_directories',
                                   side_effect=lambda home: [self.root / '.local/bin', self.root / 'homebrew/bin'])
        directories.start()
        self.addCleanup(directories.stop)

    def executable(self, relative, data=b'fixture native binary'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o755)
        return path

    def register(self, provider, editor, binary_relative):
        extension_id = 'anthropic.claude-code' if provider == 'claude' else 'openai.chatgpt'
        relative = extension_id + '-2.1.263-darwin-arm64'
        root = self.root / editor / 'extensions'
        binary = self.executable(root / relative / binary_relative)
        (root / 'extensions.json').write_text(json.dumps([{
            'identifier': {'id': extension_id}, 'relativeLocation': relative, 'version': '2.1.263'}]), encoding='utf-8')
        return binary

    def test_registered_macos_codex_architecture_layouts(self):
        for machine, arch in (('arm64', 'aarch64'), ('aarch64', 'aarch64'), ('x86_64', 'x86_64')):
            with self.subTest(machine=machine):
                binary = self.register('codex', '.vscode', 'bin/macos-' + arch + '/codex')
                found = clients.discover(self.root, which=lambda _: None, platform_name='darwin', machine=machine)
                self.assertEqual([item['binary_path'] for item in found], [str(binary.resolve())])
        self.assertEqual(clients.discover(self.root, which=lambda _: None, platform_name='darwin', machine='unknown'), [])

    def test_claude_registered_universal_and_platform_specific_layouts(self):
        generic = self.register('claude', '.vscode-insiders', 'resources/native-binary/claude')
        found = clients.discover(self.root, which=lambda _: None, provider='claude', platform_name='darwin', machine='arm64')
        self.assertEqual(found[0]['binary_path'], str(generic))
        native = self.executable(generic.parent.parent / 'native-binaries/darwin-arm64/claude')
        found = clients.discover(self.root, which=lambda _: None, provider='claude', platform_name='darwin', machine='arm64')
        self.assertEqual(found[0]['binary_path'], str(native))
        self.assertEqual(found[0]['client_id'], 'vscode-insiders')

    def test_registered_extension_cannot_escape_root(self):
        root = self.root / '.vscode/extensions'
        root.mkdir(parents=True)
        (root / 'extensions.json').write_text(json.dumps([{
            'identifier': {'id': 'openai.chatgpt'}, 'relativeLocation': '../openai.chatgpt-escape', 'version': '1'}]))
        self.executable(self.root / '.vscode/openai.chatgpt-escape/bin/macos-aarch64/codex')
        self.assertEqual(clients.discover(self.root, which=lambda _: None, platform_name='darwin', machine='arm64'), [])

    def test_finder_fallback_and_path_precedence(self):
        fallback = self.executable('.local/bin/claude')
        explicit = self.executable('custom/bin/claude')
        options = {'provider': 'claude', 'platform_name': 'darwin', 'machine': 'arm64'}
        self.assertEqual(clients.discover(self.root, which=lambda _: None, **options)[0]['binary_path'], str(fallback))
        self.assertEqual(clients.discover(self.root, which=lambda _: str(explicit), **options)[0]['binary_path'], str(explicit))

    @unittest.skipIf(os.name == 'nt', 'Native POSIX symlink and execute-mode behavior is exercised on macOS/POSIX CI')
    def test_native_version_symlink_and_npm_native_resolution(self):
        target = self.executable('.local/share/claude/versions/2.1.263')
        launcher = self.root / '.local/bin/claude'
        launcher.parent.mkdir(parents=True)
        launcher.symlink_to(target)
        found = clients.discover(self.root, which=lambda _: None, provider='claude', platform_name='darwin', machine='arm64')
        self.assertEqual(found[0]['binary_path'], str(target))
        target.chmod(0o644)
        self.assertEqual(clients.discover(self.root, which=lambda _: None, provider='claude', platform_name='darwin', machine='arm64'), [])
        script = self.executable('node_modules/@openai/codex/bin/codex.js')
        (script.parent.parent / 'package.json').write_text('{"name":"@openai/codex"}')
        native = self.executable('node_modules/@openai/codex-darwin-arm64/vendor/aarch64-apple-darwin/bin/codex')
        (self.root / 'node_modules/@openai/codex-darwin-arm64/package.json').write_text('{"name":"@openai/codex-darwin-arm64"}')
        codex = launcher.with_name('codex')
        codex.symlink_to(script)
        found = clients.discover(self.root, which=lambda _: str(codex), platform_name='darwin', machine='arm64')
        self.assertEqual(found[0]['binary_path'], str(native))
        (script.parent.parent / 'package.json').write_text('{"name":"unrelated-package"}')
        self.assertEqual(clients.discover(self.root, which=lambda _: str(codex), platform_name='darwin', machine='arm64'), [])

    def test_mac_storage_ignores_windows_appdata_and_sanitizes_bundle_dyld(self):
        bundle = self.root / 'App.app/Contents/Frameworks'
        user = str(self.root / 'user-libraries')
        source = {'PATH': str(self.root / 'tools'), 'DYLD_LIBRARY_PATH': os.pathsep.join((str(bundle), user)),
                  'DYLD_INSERT_LIBRARIES': str(bundle / 'private.dylib'), 'AUTH_SENTINEL': 'preserve',
                  'CLAUDE_CONFIG_DIR': 'custom config', 'CODEX_THREAD_ID': 'remove'}
        with patch.object(sys, 'platform', 'darwin'), patch.object(Path, 'home', return_value=self.root), \
                patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', str(bundle), create=True):
            self.assertEqual(storage.default_data_dir(), self.root / 'Library/Application Support/CodexUsageTray')
            result = external_process.environment(source)
        self.assertEqual(result['DYLD_LIBRARY_PATH'], user)
        self.assertNotIn('DYLD_INSERT_LIBRARIES', result)
        self.assertEqual(result['AUTH_SENTINEL'], 'preserve')
        self.assertEqual(result['CLAUDE_CONFIG_DIR'], 'custom config')
        self.assertIn(str(self.root / '.local/bin'), result['PATH'].split(os.pathsep))
        self.assertNotIn('CODEX_THREAD_ID', result)
        self.assertIn('CODEX_THREAD_ID', source)

    def test_darwin_process_start_time_prevents_pid_reuse(self):
        info = {'seconds': 12345, 'microseconds': 42, 'status': 2, 'pid': 123, 'flags': 0, 'size': 136}
        def query(pid, flavor, argument, pointer, size):
            self.assertEqual((pid, flavor, argument, size), (123, 3, 0, 136))
            value = ctypes.cast(pointer, ctypes.POINTER(reviews._ProcBSDInfo)).contents
            value.pid, value.status, value.flags = info['pid'], info['status'], info['flags']
            value.started_seconds, value.started_microseconds = info['seconds'], info['microseconds']
            return info['size']
        library = SimpleNamespace(proc_pidinfo=Mock(side_effect=query))
        with patch.object(sys, 'platform', 'darwin'), patch.object(ctypes, 'CDLL', return_value=library):
            identity = reviews.process_identity(123)
            self.assertEqual(identity, 'darwin:12345:42')
            record = {'status': 'running', 'pid': 123, 'process_created': identity}
            self.assertTrue(reviews.running(record))
            info['microseconds'] += 1
            self.assertFalse(reviews.running(record))
            for field, value in (('status', 5), ('flags', 4), ('pid', 999), ('size', 0)):
                previous = info[field]; info[field] = value
                self.assertIsNone(reviews.process_identity(123))
                info[field] = previous
        for pid in (None, True, 0, -1, '123'):
            self.assertIsNone(reviews.process_identity(pid))

    @unittest.skipUnless(sys.platform == 'darwin', 'Calls the actual macOS libproc ABI in macOS CI')
    def test_live_macos_process_identity_is_stable_and_gone_after_exit(self):
        current = reviews.process_identity(os.getpid())
        self.assertRegex(current, r'^darwin:\d+:\d+$')
        self.assertEqual(reviews.process_identity(os.getpid()), current)
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        try:
            self.assertRegex(reviews.process_identity(process.pid), r'^darwin:\d+:\d+$')
        finally:
            process.terminate()
            process.wait(timeout=3)
        self.assertIsNone(reviews.process_identity(process.pid))

    @unittest.skipIf(os.name == 'nt', 'POSIX quoting and executable invocation use the real platform')
    def test_policy_posix_shell_literal_arguments(self):
        folder = self.root / "Application Support/quote ' 日本語 $()"
        storage.write_json(folder / 'settings.json', {'schema_version': 1})
        block = policy_manager.owned_block(folder, 'Keep quality.').decode()
        quoted = block.split('```sh\n', 1)[1].split('\n```', 1)[0]
        command = shlex.split(quoted)
        self.assertEqual(command[-3:], ['--data-dir', str(folder), 'status'])
        self.assertEqual(Path(command[1]).name, 'backend.py')


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


if __name__ == '__main__':
    unittest.main()
