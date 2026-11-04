import json
from pathlib import Path
import signal
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lib_episode_budget import EpisodeStopped, run_episode


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.agent=SimpleNamespace()

    def test_time_budget_interrupts_blocking_work(self):
        handler=signal.getsignal(signal.SIGALRM)
        self.assertFalse(run_episode(self.agent,self.root,lambda:time.sleep(1),lambda:None,.04,80))
        record=json.loads((self.root/'termination.json').read_text())
        self.assertEqual(record['reason'],'task_time_budget')
        self.assertFalse((self.root/'result.txt').exists())
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0],0)
        self.assertEqual(signal.getsignal(signal.SIGALRM),handler)

    def test_call_limit_stops_before_extra_action(self):
        actions=[]
        def callback():
            for _ in range(3):
                self.agent._fusion_episode_budget.reserve_call()
                actions.append('action')
        self.assertFalse(run_episode(self.agent,self.root,callback,lambda:None,10,2))
        self.assertEqual(actions,['action','action'])
        self.assertEqual(json.loads((self.root/'termination.json').read_text())['reason'],'task_call_budget')

    def test_terminated_episode_does_not_stop_next_episode(self):
        results=[]
        for index in range(2):
            directory=self.root/str(index);directory.mkdir()
            def callback():
                if index==0:
                    raise EpisodeStopped('verification_budget',audit_id='a')
                self.assertEqual(self.agent._fusion_episode_budget.calls,0)
                (directory/'result.txt').write_text('1.0')
            results.append(run_episode(self.agent,directory,callback,lambda:None,10,2))
        self.assertEqual(results,[False,True])
        self.assertFalse((self.root/'0'/'result.txt').exists())
        self.assertEqual((self.root/'1'/'result.txt').read_text(),'1.0')

    def test_cleanup_cannot_block_queue(self):
        def callback():raise EpisodeStopped('verification_budget')
        self.assertFalse(run_episode(self.agent,self.root,callback,lambda:time.sleep(1),10,2,cleanup_seconds=.04))
        self.assertIn('cleanup_error',json.loads((self.root/'termination.json').read_text()))

    def test_global_stop_is_not_downgraded_to_task_stop(self):
        def callback():raise SystemExit('global budget')
        with self.assertRaises(SystemExit):
            run_episode(self.agent,self.root,callback,lambda:None,10,2)
        self.assertFalse((self.root/'termination.json').exists())
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0],0)

    def test_exception_keeps_error_and_trace(self):
        def callback():raise RuntimeError('API exhausted')
        run_episode(self.agent,self.root,callback,lambda:None,10,2)
        record=json.loads((self.root/'termination.json').read_text())
        self.assertEqual(record['reason'],'episode_exception')
        self.assertIn('API exhausted',record['details']['traceback'])

    def test_missing_evaluator_score_is_not_success(self):
        self.assertFalse(run_episode(self.agent,self.root,lambda:None,lambda:None,10,2))
        self.assertEqual(json.loads((self.root/'termination.json').read_text())['reason'],'evaluator_no_score')

    def test_local_unbounded_stop_advances_and_preserves_score(self):
        results = []
        for index in range(2):
            directory = self.root / str(index)
            directory.mkdir()
            def callback():
                self.assertIsNone(self.agent._fusion_episode_budget)
                self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)
                if index == 0:
                    raise EpisodeStopped('verification_budget')
                (directory / 'result.txt').write_text('1.0')
            results.append(run_episode(self.agent, directory, callback, lambda: None, None, None))
        self.assertEqual(results, [False, True])
        terminal = json.loads((self.root / '0' / 'termination.json').read_text())
        self.assertEqual(terminal['reason'], 'verification_budget')
        self.assertIsNone(terminal['budget']['max_seconds'])
        self.assertIsNone(terminal['budget']['api_attempts'])


if __name__=='__main__':unittest.main()
