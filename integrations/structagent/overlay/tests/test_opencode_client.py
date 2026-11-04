import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lib_episode_budget import EpisodeBudget, EpisodeStopped


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


c = load('opencode_client', 'mm_agents/structagent/utils/opencode_client.py')
launcher = load('fusion_launcher', 'scripts/run_fusion_canary.py')


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, {'FUSION_RUN_DIR': self.directory.name,
            'FUSION_MAX_CALLS': '3', 'FUSION_MAX_ALLOWANCE': '1', 'OPENCODE_GO_API_KEY': 'dummy'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.owner = SimpleNamespace(max_tokens=4096, _results_dir='task1')

    def response(self, allowance=0.01):
        return io.BytesIO(json.dumps({'choices': [{'message': {'content': 'OK'}}],
            'usage': {'total_tokens': 20, 'opencode': {'billing_source': 'go', 'allowance': allowance}}}).encode())

    def test_actor_adapter_and_accounting(self):
        with patch.object(c.urllib.request, 'urlopen', return_value=self.response()) as call:
            result = c.RemoteClient(self.owner).create(model='actor', messages=[], max_tokens=1000)
        self.assertEqual(result.choices[0].message.content, 'OK')
        self.assertEqual(c.usage_summary(self.directory.name)['tokens'], 20)
        self.assertEqual(call.call_args.args[0].full_url, 'https://opencode.ai/zen/go/v1/chat/completions')
        self.assertNotIn('dummy', ''.join(p.read_text() for p in Path(self.directory.name).rglob('*.json')))

    def test_allowance_limit_stops_next_call(self):
        with patch.object(c.urllib.request, 'urlopen', return_value=self.response(1.1)):
            c.generate({'messages': []}, self.owner)
        with self.assertRaises(c.RemoteRunStopped):
            c.generate({'messages': []}, self.owner)
        self.assertTrue((Path(self.directory.name) / 'STOP.json').exists())

    def test_call_limit(self):
        with patch.dict(os.environ, {'FUSION_MAX_CALLS': '0'}):
            with self.assertRaises(c.RemoteRunStopped):
                c.generate({'messages': []}, self.owner)

    def test_http_failure_is_recorded_and_stops(self):
        error = urllib.error.HTTPError('url', 429, 'Rate limited', {}, None)
        with patch.object(c.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaises(c.RemoteRunStopped):
                c.generate({'messages': []}, self.owner)
        self.assertEqual(c.usage_summary(self.directory.name)['errors'], 1)

    def test_no_key_no_local_fallback(self):
        with patch.dict(os.environ, {'OPENCODE_GO_API_KEY': ''}):
            with self.assertRaises(RuntimeError):
                c.generate({'messages': []}, self.owner)

    def test_secret_loader_does_not_execute_trailing_lines(self):
        secret = Path(self.directory.name) / 'secret'
        secret.write_text('export OPENCODE_GO_API_KEY="new-key"\n$(touch SHOULD_NOT_EXIST)\n')
        self.assertEqual(launcher.load_key(secret), 'new-key')

    def test_timeout_then_503_then_success(self):
        failure = urllib.error.HTTPError('url', 503, 'Unavailable', {'Retry-After': '4'}, None)
        with patch.object(c.urllib.request, 'urlopen', side_effect=[TimeoutError('timeout'), failure, self.response()]) as call, \
                patch.object(c.time, 'sleep') as sleep:
            self.assertEqual(c.generate({'messages': []}, self.owner), 'OK')
        self.assertEqual(call.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        rows = [json.loads(p.read_text()) for p in Path(self.directory.name).rglob('*.response.json')]
        self.assertEqual(len({r['logical_call_id'] for r in rows}), 1)
        self.assertEqual(sorted(r['attempt'] for r in rows), [1, 2, 3])
        self.assertEqual(c.usage_summary(self.directory.name)['retries'], 2)
        self.assertEqual(c.usage_summary(self.directory.name)['unaccounted_failed_attempts'], 2)

    def test_retry_exhaustion_is_bounded(self):
        with patch.object(c.urllib.request, 'urlopen', side_effect=TimeoutError('timeout')) as call, \
                patch.object(c.time, 'sleep'):
            with self.assertRaises(TimeoutError):
                c.generate({'messages': []}, self.owner)
        self.assertEqual(call.call_count, 3)
        rows = [json.loads(p.read_text()) for p in Path(self.directory.name).rglob('*.response.json')]
        self.assertFalse(next(r for r in rows if r['attempt'] == 3)['will_retry'])

    def test_retry_respects_run_budget(self):
        with patch.dict(os.environ, {'FUSION_MAX_CALLS': '1'}), \
                patch.object(c.urllib.request, 'urlopen', side_effect=TimeoutError('timeout')) as call, \
                patch.object(c.time, 'sleep'):
            with self.assertRaises(c.RemoteRunStopped):
                c.generate({'messages': []}, self.owner)
        self.assertEqual(call.call_count, 1)

    def test_permanent_http_error_not_retried(self):
        with patch.object(c.urllib.request, 'urlopen', side_effect=urllib.error.HTTPError('url',400,'Bad request',{},None)) as call:
            with self.assertRaises(urllib.error.HTTPError):
                c.generate({'messages': []}, self.owner)
        self.assertEqual(call.call_count, 1)

    def test_retry_after_is_capped(self):
        self.assertEqual(c.retry_delay(urllib.error.HTTPError('url',503,'Unavailable',{'Retry-After':'999'},None),1),30)

    def test_rerun_only_unscored_tasks(self):
        root = Path(self.directory.name)
        (root/'run_config.json').write_text(json.dumps({'manifest':{'os':['a','b','c']}}))
        (root/'exit_status.json').write_text('{}')
        for task,score in [('a','1'),('b','0')]:
            path=root/'results'/'model'/'os'/task
            path.mkdir(parents=True)
            (path/'result.txt').write_text(score)
        self.assertEqual(launcher.incomplete_manifest(root), {'os':['c']})

    def test_rerun_rejects_active_parent(self):
        with self.assertRaises(ValueError):
            launcher.incomplete_manifest(self.directory.name)

    def test_main60_requires_explicit_expansion(self):
        manifest=json.loads((ROOT/'evaluation_examples/main60.json').read_text())
        with self.assertRaises(ValueError):
            launcher.validate_selection(manifest)
        self.assertEqual(launcher.validate_selection(manifest, full60=True),60)

    def test_full60_cannot_silently_change_sample_size(self):
        with self.assertRaises(ValueError):
            launcher.validate_selection({'os':['a','b']},full60=True)
        self.assertEqual(launcher.validate_selection({'os':['a','b']},full60=True,rerun=True),2)

    def test_duplicate_tasks_rejected(self):
        with self.assertRaises(ValueError):
            launcher.validate_selection({'os':['a','a']})

    def test_task_call_budget_includes_api_retries(self):
        self.owner._fusion_episode_budget=EpisodeBudget(20,2)
        failure=urllib.error.HTTPError('url',503,'Unavailable',{},None)
        with patch.object(c.urllib.request,'urlopen',side_effect=failure) as call, patch.object(c.time,'sleep'):
            with self.assertRaises(EpisodeStopped) as caught:
                c.generate({'messages':[]},self.owner)
        self.assertEqual(caught.exception.reason,'task_call_budget')
        self.assertEqual(call.call_count,2)
        self.assertEqual(c.usage_summary(self.directory.name)['calls'],2)
        self.assertFalse((Path(self.directory.name)/'STOP.json').exists())

    def test_episode_deadline_records_inflight_failure(self):
        with patch.object(c.urllib.request,'urlopen',side_effect=EpisodeStopped('task_time_budget')):
            with self.assertRaises(EpisodeStopped):
                c.generate({'messages':[]},self.owner)
        rows=[json.loads(p.read_text()) for p in Path(self.directory.name).rglob('*.response.json')]
        self.assertEqual(rows[0]['termination_reason'],'task_time_budget')
        self.assertFalse(rows[0]['will_retry'])

    def test_terminal_task_is_not_selected_again(self):
        root=Path(self.directory.name)
        (root/'run_config.json').write_text(json.dumps({'manifest':{'os':['a','b']}}))
        (root/'exit_status.json').write_text('{}')
        task=root/'results'/'model'/'os'/'a'
        task.mkdir(parents=True)
        (task/'termination.json').write_text(json.dumps({'reason':'verification_budget'}))
        self.assertEqual(launcher.incomplete_manifest(root),{'os':['b']})

    def test_retrospective_close_preserves_trajectory(self):
        root=Path(self.directory.name)
        (root/'exit_status.json').write_text('{}')
        task=root/'results'/'model'/'os'/'a'
        task.mkdir(parents=True)
        trajectory=task/'traj.jsonl';trajectory.write_text('original evidence\n')
        calls=root/'model_calls';calls.mkdir()
        for i in range(2):
            (calls/f'{i}.response.json').write_text(json.dumps({'task_result_dir':str(task)}))
        launcher.close_previous_over_budget(root,2)
        self.assertEqual(trajectory.read_text(),'original evidence\n')
        self.assertFalse((task/'result.txt').exists())
        self.assertEqual(json.loads((task/'termination.json').read_text())['observed_api_receipts'],2)


if __name__ == '__main__':
    unittest.main()
