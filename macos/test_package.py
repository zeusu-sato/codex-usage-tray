"""Exercise the signed app and frozen backend using native account-free fixtures."""
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

app = Path(sys.argv[1]).resolve()
arch = sys.argv[2]
source = Path(__file__).with_name('FixtureClient.m')
with (app / 'Contents/Info.plist').open('rb') as stream:
    info = plistlib.load(stream)
assert info['LSUIElement'] and info['LSMinimumSystemVersion'] == '13.0'
backend = app / 'Contents/Resources/backend/CodexUsageBackend'
native = app / 'Contents/MacOS/CodexUsageTray'
assert os.access(backend, os.X_OK) and os.access(native, os.X_OK)
assert subprocess.check_output(['lipo', '-archs', str(native)], text=True).strip() == arch
with tempfile.TemporaryDirectory(prefix='usage-tray-mac-') as temporary:
    root = Path(temporary).resolve()
    fake_home = root / 'home'; extensions = fake_home / '.vscode/extensions'
    extensions.mkdir(parents=True)
    fixture = root / 'fixture'
    subprocess.run(['xcrun', 'clang', '-fobjc-arc', '-framework', 'Foundation', '-w', str(source), '-o', str(fixture)], check=True)
    rows = []
    cpu = 'aarch64' if arch == 'arm64' else 'x86_64'
    for provider, extension_id, version, relative in [('codex', 'openai.chatgpt', 'fixture-1.0', f'bin/macos-{cpu}/codex'), ('claude', 'anthropic.claude-code', '2.1.263', 'resources/native-binary/claude')]:
        directory = extension_id + '-' + version
        binary = extensions / directory / relative
        binary.parent.mkdir(parents=True)
        shutil.copy2(fixture, binary)
        rows.append({'identifier': {'id': extension_id}, 'relativeLocation': directory, 'version': version})
    (extensions / 'extensions.json').write_text(json.dumps(rows), encoding='utf8')
    capture = root / 'messages.jsonl'; capture.touch()
    env = {**os.environ, 'HOME': str(fake_home), 'PATH': '/usr/bin:/bin', 'TRAY_FIXTURE_CAPTURE': str(capture)}
    # Child-only HOME isolates discovery and state; the build user's home is not changed.
    env.pop('PYTHONPATH', None); env.pop('PYTHONHOME', None)
    data = root / 'state'
    def call(command, provider='codex', extra=(), folder=data, custom_env=None):
        output = subprocess.check_output([str(backend), command, '--provider', provider, '--data-dir', str(folder), *extra], env=custom_env or env, timeout=40)
        return json.loads(output)
    for provider, expected in [('codex', 74), ('claude', 73)]:
        clients = call('client-list', provider)
        assert clients['ok'] and len(clients['clients']) == 1, clients
        monitor = call('monitor-check', provider)
        assert monitor['ok'] and not monitor['mismatch'], monitor
        quota = call('usage-check', provider)
        if not quota['ok']:
            print('Fixture capture on failure:', capture.read_text()[-5000:], flush=True)
            if provider == 'codex':
                binary = extensions / rows[0]['relativeLocation'] / f'bin/macos-{cpu}/codex'
                controls = [{'id': 1, 'method': 'initialize', 'params': {}}, {'method': 'initialized'}, {'id': 2, 'method': 'account/rateLimits/read'}]
                probe = subprocess.run([str(binary), 'app-server', '--listen', 'stdio://'], input=''.join(json.dumps(m)+'\n' for m in controls), capture_output=True, text=True, env=env, timeout=10)
                print('Direct native fixture:', probe.returncode, probe.stdout[:1500], probe.stderr[:1500], flush=True)
                sys.path.insert(0, str(source.parent.parent / 'src'))
                import quota_monitor
                try:
                    print('Source adapter:', quota_monitor.request_rate_limits(binary), flush=True)
                except Exception as error:
                    print('Source adapter failed:', type(error).__name__, str(error), flush=True)
        assert quota['ok'] and quota['remaining_percent'] == expected, quota
        toggle = call('ui-enable', provider)
        assert not toggle['enabled'] and not toggle['can_enable'], toggle
        before = capture.read_bytes()
        call('usage-check', provider)
        assert capture.read_bytes() == before, 'Throttled read started another client'
    messages = [json.loads(line) for line in capture.read_text().splitlines()]
    assert [m['method'] for m in messages if 'method' in m] == ['initialize', 'initialized', 'account/rateLimits/read']
    controls = [m for m in messages if 'request' in m]
    assert [m['request']['subtype'] for m in controls] == ['initialize', 'get_usage']
    assert controls[0]['request'] == {'subtype': 'initialize', 'promptSuggestions': False, 'agentProgressSummaries': False, 'skills': [], 'plugins': []}
    assert controls[1]['request'] == {'subtype': 'get_usage', 'skip_behaviors': True}
    persisted = '\n'.join(p.read_text() for p in data.rglob('*.json'))
    assert 'private-fixture@example.invalid' not in persisted and 'fixture-private-organization' not in persisted
    before = capture.read_bytes()
    unsupported = call('usage-check', 'claude', folder=root/'unsupported', custom_env={**env, 'TRAY_FIXTURE_VERSION': '2.1.264'})
    assert not unsupported['ok'] and capture.read_bytes() == before, 'Unsupported Claude started metadata'
    assert not (fake_home / '.codex/AGENTS.md').exists() and not (fake_home / '.claude/CLAUDE.md').exists()
    subprocess.run([str(native), '--self-test', str(root / 'native-validation')], env=env, check=True, timeout=45)
print('PASS: frozen backend without Python on PATH; both providers; controls only; version gate; throttle; account privacy; unreviewed policy remains OFF; signed native UI')
