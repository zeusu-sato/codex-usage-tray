from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import backend
import client_registry as clients
import external_process
import quota_monitor as quota
from storage import read_json, write_json
from test_quota_monitor import NOW, response
import version_monitor


class ClientTests(unittest.TestCase):
    def test_only_registered_extension_is_selected_not_highest_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extensions = root / '.vscode/extensions'
            for version in ('1.0', '99.0'):
                binary = extensions / ('openai.chatgpt-' + version) / 'bin/windows-x86_64/codex.exe'
                binary.parent.mkdir(parents=True)
                binary.write_bytes(b'fixture')
            (extensions / 'extensions.json').write_text(json.dumps([{
                'identifier': {'id': 'openai.chatgpt'}, 'version': '1.0', 'relativeLocation': 'openai.chatgpt-1.0'}]))
            found = clients.discover(root, which=lambda value: None, platform_name='win32', machine='AMD64')
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]['extension_version'], '1.0')

    def test_multiple_clients_require_choice_and_switch_does_not_certify(self):
        values = [{'client_id': 'one', 'label': 'One', 'extension_version': '1'},
                  {'client_id': 'two', 'label': 'Two', 'extension_version': '2'}]
        with tempfile.TemporaryDirectory() as directory, patch.object(clients, 'discover', return_value=values):
            folder = Path(directory)
            with self.assertRaises(clients.ClientError):
                clients.choose_client(folder)
            clients.client_command(folder, 'client-select', 'one')
            self.assertEqual(clients.choose_client(folder)['client_id'], 'one')
            data = clients.settings(folder)
            data.update(reference={'old': 'value'}, reference_kind='reviewed')
            clients.write_json(folder / 'settings.json', data)
            clients.client_command(folder, 'client-select', 'two')
            self.assertNotIn('reference', clients.settings(folder))
            with self.assertRaises(clients.ClientError):
                clients.client_command(folder, 'client-select', 'invented')

    def test_changed_or_missing_source_cannot_reuse_other_quota(self):
        now = NOW
        with tempfile.TemporaryDirectory() as directory, patch.object(quota, 'request_rate_limits', return_value=response()) as read:
            folder = Path(directory)
            binary = folder / 'codex.exe'
            binary.write_bytes(b'one')
            quota.quota_command(folder, now, binary)
            read.return_value = response(70)
            binary.write_bytes(b'other-version')
            changed = quota.quota_command(folder, now + timedelta(seconds=1), binary)
            self.assertEqual(changed['remaining_percent'], 30)
            missing = quota.quota_command(folder, now + timedelta(seconds=2), None)
            self.assertIsNone(missing['remaining_percent'])
            self.assertEqual(missing['windows'], [])

    def test_selected_extension_replaced_by_newer_version_keeps_reading(self):
        """An editor update re-registers the extension under a new folder while a
        terminal-injected PATH entry still points at the obsolete one."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            extensions = root / '.vscode-insiders/extensions'
            binaries = {}
            for version in ('26.901.22334', '26.908.40401'):
                binary = extensions / ('openai.chatgpt-' + version + '-win32-x64') / 'bin/windows-x86_64/codex.exe'
                binary.parent.mkdir(parents=True)
                binary.write_bytes(version.encode())
                binaries[version] = binary
            (extensions / 'extensions.json').write_text(json.dumps([{
                'identifier': {'id': 'openai.chatgpt'}, 'version': '26.908.40401',
                'relativeLocation': 'openai.chatgpt-26.908.40401-win32-x64'}]))
            stale_path = lambda name: str(binaries['26.901.22334'])
            original = clients.discover
            fixture = lambda *args, **kwargs: original(root, which=stale_path, platform_name='win32', machine='AMD64')
            found = fixture()
            self.assertEqual([(item['client_id'], item['extension_version']) for item in found], [('vscode-insiders', '26.908.40401')])
            folder = root / 'data'
            folder.mkdir()
            previous = {**found[0], 'extension_version': '26.901.22334', 'binary_path': str(binaries['26.901.22334']),
                        'binary_size': 12, 'binary_mtime_ns': 1, 'cli_version': '0.153.0', 'provider': 'codex'}
            write_json(folder / 'settings.json', {'schema_version': 1, 'selected_client': 'vscode-insiders',
                                                  'reference': previous, 'reference_kind': 'observed'})
            write_json(folder / 'monitor-state.json', {'schema_version': 1, 'current': {**found[0], 'cli_version': '0.154.0'}})
            with (patch.object(clients, 'discover', side_effect=fixture),
                  patch.object(quota, 'request_rate_limits', return_value=response(70)) as read,
                  patch('subprocess.Popen', side_effect=AssertionError('Unexpected process launch'))):
                self.assertEqual(clients.choose_client(folder)['binary_path'], str(binaries['26.908.40401']))
                args = SimpleNamespace(command='usage-check', data_dir=str(folder), provider='codex')
                self.assertEqual(backend.execute(args, NOW)['remaining_percent'], 30)
                read.assert_called_once_with(str(binaries['26.908.40401']))
                self.assertIsNotNone(read_json(folder / 'quota-state.json')['source'])
                # The version monitor still reports the change for review, without stopping reads.
                monitor = version_monitor.monitor_command(folder, 'monitor-check', NOW)
                self.assertTrue(monitor['mismatch'])
                self.assertTrue(monitor['alert'])
                self.assertFalse(monitor['needs_client_selection'])
                self.assertEqual(clients.settings(folder)['reference'], previous)
                # Without any stored choice the registered extension is the default as well.
                write_json(folder / 'settings.json', {'schema_version': 1})
                self.assertEqual(clients.choose_client(folder)['extension_version'], '26.908.40401')
                self.assertEqual(clients.client_command(folder, 'client-list')['selected_id'], 'vscode-insiders')

    def test_missing_selected_client_follows_registered_extension(self):
        values = [{'client_id': 'vscode', 'label': 'VS Code', 'extension_version': '1'},
                  {'client_id': 'cli-path', 'label': 'Codex CLI (PATH)', 'extension_version': 'standalone'}]
        installed = lambda *args, **kwargs: list(values)
        with (tempfile.TemporaryDirectory() as directory, patch.object(clients, 'discover', side_effect=installed),
              patch.object(version_monitor, 'discover', side_effect=installed)):
            folder = Path(directory)
            # Unselected: the registered extension is the default and the CLI stays selectable.
            self.assertEqual(clients.choose_client(folder)['client_id'], 'vscode')
            self.assertEqual(clients.client_command(folder, 'client-list')['selected_id'], 'vscode')
            self.assertFalse(version_monitor.unavailable_reply('detail')['needs_client_selection'])
            clients.client_command(folder, 'client-select', 'cli-path')
            self.assertEqual(clients.choose_client(folder)['client_id'], 'cli-path')
            del values[1]  # The CLI is uninstalled: the stored choice is kept, reads follow the extension.
            self.assertEqual(clients.choose_client(folder)['client_id'], 'vscode')
            self.assertEqual(clients.settings(folder)['selected_client'], 'cli-path')
            self.assertEqual(clients.client_command(folder, 'client-list')['selected_id'], 'vscode')
            values.append({'client_id': 'vscode-insiders', 'label': 'VS Code Insiders', 'extension_version': '2'})
            with self.assertRaises(clients.ClientError):
                clients.choose_client(folder)
            self.assertTrue(version_monitor.unavailable_reply('detail')['needs_client_selection'])
            self.assertEqual(clients.client_command(folder, 'client-list')['selected_id'], 'cli-path')
            values.clear()
            with self.assertRaises(clients.ClientError):
                clients.choose_client(folder)
            self.assertFalse(version_monitor.unavailable_reply('detail')['needs_client_selection'])

    def test_frozen_environment_removes_bundle_paths_and_preserves_auth_context(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory).resolve()
            other = str(bundle.parent / 'user-tools')
            source = {'PATH': os.pathsep.join((str(bundle), str(bundle / 'bin'), other)),
                      'CODEX_HOME': 'user-defined-location', 'CODEX_THREAD_ID': 'parent-thread', 'AUTH_SENTINEL': 'keep'}
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', str(bundle), create=True), \
                    patch.object(external_process, 'default_cli_directories', return_value=[]):
                result = external_process.environment(source)
            self.assertEqual(result['PATH'], other)
            self.assertEqual(result['CODEX_HOME'], source['CODEX_HOME'])
            self.assertEqual(result['AUTH_SENTINEL'], 'keep')
            self.assertNotIn('CODEX_THREAD_ID', result)
            self.assertIn('CODEX_THREAD_ID', source)


if __name__ == '__main__':
    unittest.main()
