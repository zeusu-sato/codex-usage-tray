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

    def test_provider_storage_isolated(self):
        sentinel=b'{"codex":"untouched"}'
        (self.root/'quota-state.json').write_bytes(sentinel)
        args=SimpleNamespace(command='usage-check',data_dir=str(self.root),provider='claude')
        with patch.object(claude_quota,'quota_command',return_value={'ok':True}) as read:
            backend.execute(args,self.now)
            self.assertEqual(read.call_args.args[0],self.folder)
        self.assertEqual((self.root/'quota-state.json').read_bytes(),sentinel)
        self.assertEqual(client_registry.provider_for(self.folder),'claude')

    def test_scope_change_discards_history(self):
        self.read()
        second=copy.deepcopy(self.payload);second['scope_key']='b'*64
        second['rate_limits']['seven_day']['utilization']=21
        self.read(second,self.now+timedelta(minutes=6))
        cache=json.loads((self.folder/'quota-state.json').read_text())
        self.assertEqual([len(row['samples']) for row in cache['history']],[1,1])

    def test_reset_jitter_preserves_history_until_a_forecast_can_be_computed(self):
        for index, seconds in enumerate((0, 60, -60, 0, 60)):
            payload=copy.deepcopy(self.payload)
            for source, raw in payload['rate_limits'].items():
                raw['resets_at']=(datetime.fromisoformat(self.payload['rate_limits'][source]['resets_at'])
                                  +timedelta(seconds=seconds)).isoformat()
                raw['utilization']+=index * (1 if source=='five_hour' else 0.1)
            reply=self.read(payload,self.now+timedelta(minutes=index*15))
        cache=json.loads((self.folder/'quota-state.json').read_text())
        self.assertEqual([len(row['samples']) for row in cache['history']],[5,5])
        self.assertIn(reply['forecast']['status'],('comfortable','tight','at_risk'))
        for index, source in enumerate(('five_hour','seven_day')):
            official=int(datetime.fromisoformat(payload['rate_limits'][source]['resets_at']).timestamp())
            self.assertEqual(cache['snapshot']['windows'][index]['resets_at'],official)
            self.assertEqual(cache['history'][index]['resets_at'],official)

    def test_jitter_cannot_bridge_changed_scope_refill_or_large_reset_shift(self):
        for scenario in ('account','refill','hours','clock'):
            with self.subTest(scenario=scenario):
                (self.folder/'quota-state.json').unlink(missing_ok=True)
                self.read()
                second=copy.deepcopy(self.payload)
                if scenario=='account':second['scope_key']='b'*64
                for raw in second['rate_limits'].values():
                    raw['resets_at']=(datetime.fromisoformat(raw['resets_at'])
                                      +timedelta(seconds=7200 if scenario=='hours' else 60)).isoformat()
                    raw['utilization']+=-1 if scenario=='refill' else 1
                self.read(second,self.now+timedelta(minutes=-6 if scenario=='clock' else 6))
                cache=json.loads((self.folder/'quota-state.json').read_text())
                self.assertEqual([len(row['samples']) for row in cache['history']],[1,1])

    def test_jitter_matching_requires_both_resets_beyond_two_minutes_and_matching_window(self):
        timestamp=self.now.timestamp()
        for old_left, new_left, expected in ((3600,3720,2),(3600,3721,1),(3600,3480,2),
                                             (120,180,1),(180,120,1),(-30,90,1),(None,3600,1),
                                             (3600,None,1),(3600,10800,1)):
            with self.subTest(old_left=old_left,new_left=new_left):
                old_reset=timestamp+old_left if old_left is not None else None
                new_reset=timestamp+new_left if new_left is not None else None
                history=[{'kind':'primary','duration_mins':300,'resets_at':old_reset,
                          'samples':[[timestamp-300,90]]}]
                windows=[{'kind':'primary','duration_mins':300,'resets_at':new_reset,'remaining_percent':89}]
                before=copy.deepcopy((history,windows))
                aligned=claude_quota.align_reset_history(history,windows,timestamp)
                recorded=usage_forecast.record(aligned,windows,timestamp)
                self.assertEqual(len(recorded[0]['samples']),expected)
                self.assertEqual((history,windows),before)
        history=[{'kind':'primary','duration_mins':300,'resets_at':timestamp+3600,
                  'samples':[[timestamp-300,90]]}]
        for kind,duration in (('secondary',300),('primary',10080)):
            windows=[{'kind':kind,'duration_mins':duration,'resets_at':timestamp+3660,'remaining_percent':89}]
            aligned=claude_quota.align_reset_history(history,windows,timestamp)
            self.assertEqual(len(usage_forecast.record(aligned,windows,timestamp)[0]['samples']),1)

    def test_missing_scope_disables_forecast_only(self):
        payload=copy.deepcopy(self.payload);payload.pop('scope_key')
        reply=self.read(payload)
        self.assertEqual(reply['remaining_percent'],80)
        self.assertEqual(reply['forecast']['status'],'unavailable')
        self.assertNotIn('history',json.loads((self.folder/'quota-state.json').read_text()))

    def test_corrupt_cache_recovers_with_fresh_metadata(self):
        (self.folder/'quota-state.json').write_text('{broken',encoding='utf-8')
        reply=self.read()
        self.assertEqual(reply['remaining_percent'],80)
        self.assertTrue(json.loads((self.folder/'quota-state.json').read_text())['last_ok'])

    def test_null_reset_retains_amount_without_green(self):
        self.payload['rate_limits']['five_hour']['resets_at']=None
        reply=self.read()
        self.assertEqual(reply['remaining_percent'],80)
        self.assertNotEqual(reply['forecast']['status'],'comfortable')

    def test_old_version_never_polls_and_explains(self):
        self.identity['cli_version']='2.1.262'
        with patch.object(client_registry,'current_identity',return_value=self.identity),patch('claude_adapter.subprocess.Popen',side_effect=AssertionError('Must not start unsupported binary')):
            reply=claude_quota.quota_command(self.folder,self.now)
        self.assertIsNone(reply['remaining_percent'])
        self.assertIn('古い版',reply['detail'])

    def test_compatible_update_keeps_quota_independent_of_unreviewed_version_alert(self):
        reference=copy.deepcopy(self.identity)
        write_json(self.folder/'settings.json',{'schema_version':1,'provider':'claude',
                   'reference':reference,'reference_kind':'reviewed'})
        active={'enabled':True,'launcher':policy_manager.launcher_identity(),
                'fingerprint':client_registry.fingerprint(reference)}
        write_json(self.folder/'active-policy.json',active)
        self.identity.update(cli_version='2.1.266',extension_version='2.1.266',binary_mtime_ns=2)
        with patch.object(version_monitor,'current_identity',return_value=self.identity):
            monitor=version_monitor.monitor_command(self.folder,'monitor-check',self.now)
        self.assertTrue(monitor['mismatch'])
        self.assertTrue(monitor['alert'])
        self.assertEqual(self.read()['remaining_percent'],80)
        data=json.loads((self.folder/'settings.json').read_text())
        self.assertEqual(data['reference'],reference)
        self.assertEqual(data['reference_kind'],'reviewed')
        with patch.object(policy_manager,'current_identity',return_value=self.identity):
            self.assertEqual(policy_manager.runtime_status(self.folder),{'active':False,'reason':'client_changed'})
        self.assertEqual(json.loads((self.folder/'active-policy.json').read_text()),active)

    def test_app_update_retries_old_version_error_once_then_throttles(self):
        self.identity['cli_version']='2.1.266'
        write_json(self.folder/'quota-state.json',{'schema_version':1,
                   'source':client_registry.fingerprint(self.identity),
                   'attempted_at':self.now.isoformat(),'last_ok':False,'error':'unsupported_version'})
        with patch.object(client_registry,'current_identity',return_value=self.identity), \
                patch.object(claude_quota.claude_adapter,'request_usage',return_value=self.payload) as read:
            first=claude_quota.quota_command(self.folder,self.now)
            second=claude_quota.quota_command(self.folder,self.now+timedelta(seconds=1))
        self.assertEqual(first['remaining_percent'],80)
        self.assertEqual(second['remaining_percent'],80)
        read.assert_called_once()
        cache=json.loads((self.folder/'quota-state.json').read_text())
        self.assertNotIn('error',cache)
        self.assertEqual(cache['transport_revision'],claude_quota.TRANSPORT_REVISION)

    def test_incompatible_reply_remains_unknown_without_raw_output_or_positive_forecast(self):
        self.read()
        malformed=copy.deepcopy(self.payload)
        malformed['rate_limits']['seven_day']['resets_at']='private-invalid-timestamp'
        reply=self.read(malformed,self.now+timedelta(minutes=5))
        self.assertIsNone(reply['remaining_percent'])
        self.assertIn('対応形式と一致しません',reply['detail'])
        self.assertEqual(reply['forecast']['status'],'unavailable')
        self.assertNotIn('private-invalid',json.dumps(reply))
        self.assertNotIn('private-invalid',(self.folder/'quota-state.json').read_text())

    def test_claude_guard_targets_own_folder_and_file(self):
        with patch.dict('os.environ',{'CLAUDE_CONFIG_DIR':str(self.root/'claude-config')}):
            self.assertEqual(policy_manager.instruction_path(self.folder),self.root/'claude-config'/'CLAUDE.md')
        block=policy_manager.owned_block(self.folder,'Keep quality.').decode()
        self.assertIn('"--provider", "claude"',block)
        self.assertIn(json.dumps(str(self.root.resolve())),block)

    def test_review_prompt_and_consent_identify_target_and_cost(self):
        prompt=reviews.build_prompt(self.identity,self.identity)
        self.assertIn('調査対象はVS Codeで使用するClaude Code',prompt)
        self.assertIn('CLAUDE.md',prompt)
        self.assertNotIn('AGENTS.md',prompt)
        with patch.object(reviews,'current_identity',return_value=self.identity):
            write_json(self.folder/'settings.json',{'schema_version':1,'provider':'claude','reference':self.identity})
            from version_monitor import signature_for
            result=reviews.review_command(self.folder,'review-status',self.now,signature_for(self.identity,self.identity))
        self.assertIn('CodexのUsage',result['detail'])


if __name__=='__main__':unittest.main()
