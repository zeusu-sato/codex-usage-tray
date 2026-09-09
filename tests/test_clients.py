from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import client_registry as clients
import external_process
import quota_monitor as quota
from test_quota_monitor import response


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
            found = clients.discover(root, which=lambda value: None)
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
        now = datetime.now(timezone.utc)
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

    def test_frozen_environment_removes_bundle_paths_and_preserves_auth_context(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory).resolve()
            other = str(bundle.parent / 'user-tools')
            source = {'PATH': os.pathsep.join((str(bundle), str(bundle / 'bin'), other)),
                      'CODEX_HOME': 'user-defined-location', 'CODEX_THREAD_ID': 'parent-thread', 'AUTH_SENTINEL': 'keep'}
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', str(bundle), create=True):
                result = external_process.environment(source)
            self.assertEqual(result['PATH'], other)
            self.assertEqual(result['CODEX_HOME'], source['CODEX_HOME'])
            self.assertEqual(result['AUTH_SENTINEL'], 'keep')
            self.assertNotIn('CODEX_THREAD_ID', result)
            self.assertIn('CODEX_THREAD_ID', source)


if __name__ == '__main__':
    unittest.main()
