import ctypes
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import client_registry as clients
import external_process
import policy_manager
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
