import copy
from datetime import datetime, timezone, timedelta
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import backend
import claude_quota
import client_registry
import policy_manager
import reviews
import usage_forecast
import version_monitor
from storage import write_json


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.folder=self.root/'providers'/'claude'
        self.folder.mkdir(parents=True)
        write_json(self.folder/'settings.json',{'schema_version':1,'provider':'claude'})
        self.now=datetime(2026,9,9,tzinfo=timezone.utc)
        self.identity={'client_id':'vscode-insiders','label':'VS Code Insiders','binary_path':str(self.root/'claude.exe'),
            'cli_version':'2.1.263','extension_version':'2.1.263','binary_size':100,'binary_mtime_ns':1,'provider':'claude'}
        self.payload={'rate_limits_available':True,'scope_key':'a'*64,'rate_limits':{
            'five_hour':{'utilization':10,'resets_at':(self.now+timedelta(hours=4)).isoformat()},
            'seven_day':{'utilization':20,'resets_at':(self.now+timedelta(days=5)).isoformat()}}}

    def read(self,payload=None,now=None):
        with patch.object(client_registry,'current_identity',return_value=self.identity),patch.object(claude_quota.claude_adapter,'request_usage',return_value=payload or self.payload):
            return claude_quota.quota_command(self.folder,now or self.now)

    def test_schema_one_keeps_history_and_credit_refresh_writes_two(self):
        self.read()
        path = self.folder / 'quota-state.json'
        cache = json.loads(path.read_text(encoding='utf-8'))
        history = copy.deepcopy(cache['history'])
        cache['schema_version'] = 1
        cache['snapshot'].pop('credit')
        write_json(path, cache)
        self.payload['rate_limits']['five_hour']['utilization'] = 100
        self.payload['rate_limits']['extra_usage'] = {'is_enabled': True, 'monthly_limit': 68800, 'used_credits': 0}
        result = self.read(now=self.now + timedelta(minutes=5))
        saved = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(saved['schema_version'], 2)
        self.assertEqual(saved['history'][1]['samples'][0], history[1]['samples'][0])
        self.assertEqual(result['credit']['tray_text'], '688')
        self.assertTrue(result['tooltip'].startswith('Claude Code 追加利用中'))
        self.assertNotIn('残高', result['detail'])


    def test_weekly_only_cache_forecast_and_credit(self):
        for missing in (True, False):
            payload = copy.deepcopy(self.payload)
            if missing:
                del payload['rate_limits']['five_hour']
            else:
                payload['rate_limits']['five_hour'] = None
            result = self.read(payload)
            self.assertTrue(result['ok'])
            self.assertEqual(result['remaining_percent'], 80)
            self.assertEqual([w['label'] for w in result['windows']], ['Weekly'])
            self.assertIn('週間枠', result['scope'])
            self.assertNotIn('対象', result['detail'])
            self.assertIn('Weekly', result['tooltip'])
            result = self.read(payload, self.now + timedelta(minutes=5))
            cache = json.loads((self.folder / 'quota-state.json').read_text(encoding='utf-8'))
            self.assertEqual([w['kind'] for w in cache['snapshot']['windows']], ['secondary'])
            self.assertEqual([w['kind'] for w in cache['history']], ['secondary'])
            self.assertIn('status', result['forecast'])
            payload['rate_limits']['seven_day']['utilization'] = 100
            payload['rate_limits']['extra_usage'] = {'is_enabled': True, 'monthly_limit': 1000, 'used_credits': 0}
            result = self.read(payload, self.now + timedelta(minutes=10))
            self.assertEqual(result['credit']['tray_text'], '10')


    def test_provider_storage_isolated(self):
        sentinel=b'{"codex":"untouched"}'
        (self.root/'quota-state.json').write_bytes(sentinel)
        args=SimpleNamespace(command='usage-check',data_dir=str(self.root),provider='claude')
        with patch.object(claude_quota,'quota_command',return_value={'ok':True}) as read:
            backend.execute(args,self.now)
            self.assertEqual(read.call_args.args[0],self.folder)
        self.assertEqual((self.root/'quota-state.json').read_bytes(),sentinel)
        self.assertEqual(client_registry.provider_for(self.folder),'claude')


    def test_failure_categories_stay_diagnosable_without_raw_details(self):
        cases=[(client_registry.ClientError('選択したCodexが見つかりません。'),'client_unavailable'),
               (claude_quota.quota.QuotaError('timeout'),'timeout'),
               (claude_quota.quota.QuotaError('account_unavailable'),'account_unavailable'),
               (claude_quota.quota.QuotaError('unsupported_version'),'unsupported_version'),
               (claude_quota.quota.QuotaError('incomplete_windows'),'incompatible_protocol'),
               (OSError(5,'private path /secret-location'),'unavailable'),
               (claude_quota.quota.QuotaError('Raw server text: 500 /secret-location'),'unavailable')]
        for index,(error,expected) in enumerate(cases):
            with self.subTest(expected=expected):
                identity=patch.object(client_registry,'current_identity',side_effect=error) if isinstance(error,client_registry.ClientError) \
                    else patch.object(client_registry,'current_identity',return_value=self.identity)
                with identity,patch.object(claude_quota.claude_adapter,'request_usage',side_effect=error):
                    reply=claude_quota.quota_command(self.folder,self.now+timedelta(minutes=index))
                cache=json.loads((self.folder/'quota-state.json').read_text(encoding='utf-8'))
                self.assertEqual(cache['error'],expected)
                self.assertFalse(cache['last_ok'])
                self.assertFalse(reply['ok'])
                self.assertNotIn('secret-location',json.dumps(cache))


    def test_error_reasons_and_recovery(self):
        path = self.folder / 'quota-state.json'
        for index, reason in enumerate(('protocol', 'unsupported_response', 'incomplete_windows')):
            with self.subTest(reason=reason), patch.object(client_registry, 'current_identity', return_value=self.identity), \
                    patch.object(claude_quota.claude_adapter, 'request_usage', side_effect=claude_quota.quota.QuotaError(reason)):
                claude_quota.quota_command(self.folder, self.now + timedelta(minutes=5 * index))
                cache = json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual((cache['error'], cache['error_reason']), ('incompatible_protocol', reason))
        previous = self.read(now=self.now + timedelta(minutes=15))
        self.assertEqual(previous['note'], '')
        self.assertNotIn('error_reason', json.loads(path.read_text(encoding='utf-8')))
        result = self.read({'rate_limits_available': True, 'rate_limits': None}, self.now + timedelta(minutes=20))
        cache = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(cache['error'], 'usage_temporarily_unavailable')
        self.assertNotIn('error_reason', cache)
        self.assertEqual(result['title'], 'Usage 未確認')
        self.assertEqual(result['detail'], '\n'.join(f"{w['label']}: 残り {w['remaining_percent']:g}%  ·  {w['resets_label']}" for w in previous['windows']))
        self.assertEqual(result['checked_label'], previous['checked_label'])
        self.assertEqual(result['note'].count('5分ごとに再確認します。'), 1)
        self.assertIn('Claude Code がClaudeのサーバーから利用枠を取得できませんでした。', result['note'])
        self.assertNotIn('Claude Code がClaude', result['detail'])
        self.read(now=self.now + timedelta(minutes=25))
        cache = json.loads(path.read_text(encoding='utf-8'))
        self.assertNotIn('error_reason', cache)


    def test_scope_change_discards_history(self):
        self.read()
        second=copy.deepcopy(self.payload);second['scope_key']='b'*64
        second['rate_limits']['seven_day']['utilization']=21
        self.read(second,self.now+timedelta(minutes=6))
        cache=json.loads((self.folder/'quota-state.json').read_text())
        self.assertEqual([len(row['samples']) for row in cache['history']],[1,1])


    def test_stale_display_reasons(self):
        import quota_monitor
        window = {'kind': 'secondary', 'remaining_percent': 39, 'duration_mins': 10080,
                  'resets_at': int((self.now + timedelta(days=5)).timestamp())}
        cache = {'snapshot': {'windows': [window], 'blocked': False},
                 'fetched_at': self.now.isoformat(), 'last_ok': False}
        expected = 'Weekly: 残り 39%  ·  リセット 09/14 09:00 JST'
        reasons = {
            'unsupported_version': 'Claude Codeのバージョンを確認できないか、2.1.263より古い版です。選択したクライアントをご確認ください。',
            'usage_temporarily_unavailable': 'Claude Code がClaudeのサーバーから利用枠を取得できませんでした。Claude側の一時的な問題の可能性があります。',
            'incompatible_protocol': 'Claude Codeの応答が対応形式と一致しません。続く場合はアプリの更新が必要です。',
        }
        codex = quota_monitor.reply(cache, self.now)
        self.assertEqual((codex['title'], codex['detail'], codex['checked_label']),
                         ('Usage 未確認', expected, '最終取得: 09/09 09:00:00 JST'))
        self.assertEqual(codex['note'], '表示は前回取得した残量です。\n接続とCodexのログイン状態をご確認ください。\n5分ごとに再確認します。')
        for error, reason in reasons.items():
            with self.subTest(error=error):
                result = claude_quota.response(dict(cache, error=error), self.now)
                self.assertEqual((result['title'], result['detail'], result['checked_label']),
                                 (codex['title'], expected, codex['checked_label']))
                self.assertEqual(result['note'], '表示は前回取得した残量です。\n' + reason + '\n5分ごとに再確認します。')
                self.assertNotIn(reason, result['detail'])
        self.assertEqual(quota_monitor.reply(dict(cache, last_ok=True), self.now)['note'], '')
        self.assertEqual(claude_quota.response(dict(cache, last_ok=True), self.now)['note'], '')
        empty = quota_monitor.reply({}, self.now)
        self.assertEqual(empty['detail'], '')
        self.assertNotIn('表示は前回', empty['note'])


if __name__=='__main__':unittest.main()
