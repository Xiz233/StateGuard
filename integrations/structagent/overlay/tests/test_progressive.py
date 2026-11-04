import importlib.util
from pathlib import Path
import unittest
import json
import tempfile
import ast
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib_episode_budget import EpisodeStopped

spec = importlib.util.spec_from_file_location('fusion_test.progressive', Path(__file__).resolve().parents[1] /
    'mm_agents/structagent/core/final_audit/progressive.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class ProgressiveTests(unittest.TestCase):
    def test_unknown_without_evidence(self):
        result = p.parse(json.dumps(dict(judgement='verified', confidence='HIGH', evidence_ids=[])), [])
        self.assertEqual(result['judgement'], 'unknown')

    def test_low_confidence(self):
        result = p.parse(json.dumps(dict(judgement='verified', confidence='LOW', evidence_ids=['current'])), ['current'])
        self.assertEqual(result['judgement'], 'unknown')

    def test_invalid_reference(self):
        with self.assertRaises(ValueError):
            p.parse(json.dumps(dict(judgement='verified', confidence='HIGH', evidence_ids=['gold'])), ['current'])

    def test_probe_paths(self):
        self.assertTrue(p.allowed_path('/home/user/test.txt', 'Save to /home/user/test.txt'))
        for path in ['/etc/passwd', '/home/user/.ssh/key', '/home/user/../etc/passwd', '/home/user/gold.txt']:
            self.assertFalse(p.allowed_path(path, path))
        self.assertFalse(p.allowed_path('/home/user/test.txt', 'unrelated task'))

    def run_audit(self, responses, snapshot=None, controller=None, count=1, attributes=None):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = snapshot or SimpleNamespace(task_instruction='Complete the task',
                recent_screenshots_b64=[])
            agent = SimpleNamespace(_results_dir=directory, verifier_model='test')
            agent.__dict__.update(attributes or {})
            replies = iter(responses)
            agent.call_llm = lambda *args: next(replies)
            env = SimpleNamespace(controller=controller)
            p.__package__ = 'fusion_test'
            fake = SimpleNamespace(build_snapshot_from_live_state=lambda _: snapshot)
            with patch.dict(sys.modules, {'fusion_test.snapshot': fake}):
                results = [p.audit(agent, env, {'screenshot': b'screenshot'}, i) for i in range(count)]
            artifacts = [json.loads(f.read_text()) for f in Path(directory).glob('progressive_verification/*.json')]
            return results, artifacts

    def test_static_verified_early_stop(self):
        results, artifacts = self.run_audit([json.dumps(dict(judgement='verified', confidence='HIGH', evidence_ids=['current']))])
        self.assertTrue(results[0][0])
        self.assertEqual(len(artifacts[0]['events']), 1)
        self.assertEqual(artifacts[0]['disposition'], 'accept')

    def test_unknown_switches_to_selected_history(self):
        snap = SimpleNamespace(task_instruction='Complete the task', recent_screenshots_b64=['old', 'current'])
        _, artifacts = self.run_audit([
            json.dumps(dict(judgement='unknown', confidence='LOW', history_ids=['history_0'])),
            json.dumps(dict(judgement='verified', confidence='HIGH', evidence_ids=['history_0']))], snap)
        self.assertEqual([e['stage'] for e in artifacts[0]['events']], ['static', 'retrospection'])

    def test_unknown_uses_read_only_probe(self):
        controller = SimpleNamespace(get_accessibility_tree=lambda: '<text>Saved</text>')
        results, artifacts = self.run_audit([
            json.dumps(dict(judgement='unknown', confidence='LOW', probe_kind='accessibility')),
            json.dumps(dict(judgement='verified', confidence='HIGH', evidence_ids=['accessibility']))], controller=controller)
        self.assertTrue(results[0][0])
        self.assertIn('probe', artifacts[0]['events'][-1]['fingerprints'])

    def test_repeated_unknown_stops_without_repeated_model_calls(self):
        results, _ = self.run_audit([json.dumps(dict(judgement='unknown', confidence='LOW'))], count=3)
        self.assertEqual(results[-1][:2], (False, True))

    def test_parse_failure_is_recorded(self):
        results, artifacts = self.run_audit(['not JSON'])
        self.assertFalse(results[0][0])
        self.assertIn('error', artifacts[0]['events'][0])

    def test_symlink_probe_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'target'
            target.write_text('private')
            link = Path(directory) / 'link'
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                exec(p.probe_code(str(link)), {})

    def test_target_requires_its_own_citation(self):
        raw = dict(judgement='verified', confidence='HIGH', evidence_ids=['current'],
                   outcome_results=[dict(outcome_id='a',judgement='verified',confidence='HIGH',evidence_ids=[])])
        result=p.parse(json.dumps(raw), ['current'], ['a'])
        self.assertEqual(result['judgement'], 'unknown')
        self.assertEqual(result['outcome_results'][0]['judgement'], 'unknown')

    def test_missing_target_prevents_acceptance(self):
        raw = dict(judgement='verified', confidence='HIGH', evidence_ids=['current'])
        self.assertEqual(p.parse(json.dumps(raw), ['current'], ['a'])['judgement'], 'unknown')

    def test_duplicate_target_is_rejected(self):
        row = dict(outcome_id='a',judgement='verified',confidence='HIGH',evidence_ids=['current'])
        raw = dict(judgement='verified',confidence='HIGH',evidence_ids=['current'],outcome_results=[row,row])
        with self.assertRaises(ValueError):
            p.parse(json.dumps(raw), ['current'], ['a'])

    def test_stale_or_dirty_structure_is_not_evidence(self):
        agent=SimpleNamespace(_doc_inspect_block='lh=200',_doc_inspect_step=1,_doc_inspect_dirty=False)
        self.assertFalse(p.current_structure(agent,2))
        agent._doc_inspect_dirty=True
        self.assertFalse(p.current_structure(agent,1))

    def test_pending_ledger_uses_structure_and_then_final_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            outcome=SimpleNamespace(id='spacing',description='Double line spacing',state='pending')
            ledger=SimpleNamespace(required_outcomes=[outcome],
                can_accept_done_claim=lambda: (outcome.state=='verified', 'pending'))
            agent=SimpleNamespace(_results_dir=directory, verifier_model='test',ledger=ledger,
                _doc_inspect_block='paragraph 0 lh=200',_doc_inspect_step=2,_doc_inspect_dirty=False)
            prompts=[]
            def model(payload, model):
                prompt=json.loads(payload['messages'][0]['content'][0]['text'])
                prompts.append(prompt)
                self.assertIn('document_structure', prompt['structured_evidence'])
                self.assertNotIn('evaluator', prompt)
                result=dict(judgement='verified',confidence='HIGH',evidence_ids=['document_structure'])
                if prompt['targets']:
                    result['outcome_results']=[dict(outcome_id='spacing',**result)]
                return json.dumps(result)
            agent.call_llm=model
            p.__package__='fusion_test'
            snap=SimpleNamespace(task_instruction='Double line spacing',recent_screenshots_b64=[])
            with patch.dict(sys.modules,{'fusion_test.snapshot':SimpleNamespace(build_snapshot_from_live_state=lambda _:snap)}):
                accepted, _, _=p.completion_gate(agent,None,{'screenshot':b'image'},2,False,'pending')
            self.assertTrue(accepted)
            self.assertEqual(outcome.state,'verified')
            self.assertEqual(outcome.last_verifier_trace['source'],'progressive_verification')
            self.assertEqual([x['trigger'] for x in prompts],['done_rejected','task_done'])

    def test_contradicted_outcome_is_not_promoted(self):
        outcome=SimpleNamespace(id='a',description='target',state='reverted')
        with patch.object(p,'audit') as audit:
            p.recover_pending(SimpleNamespace(),None,{},1,[outcome],'test')
        audit.assert_not_called()
        self.assertEqual(outcome.state,'reverted')

    def test_parse_failure_can_retry_same_evidence(self):
        results,_=self.run_audit(['not JSON',json.dumps(dict(judgement='verified',confidence='HIGH',evidence_ids=['current']))],count=2)
        self.assertFalse(results[0][0])
        self.assertTrue(results[1][0])

    def test_failed_native_gate_not_bypassed_by_final_audit(self):
        ledger=SimpleNamespace(required_outcomes=[],can_accept_done_claim=lambda:(False,'unresolved contradiction'))
        with patch.object(p,'audit') as audit:
            result=p.completion_gate(SimpleNamespace(ledger=ledger),None,{},0,False,'rejected')
        self.assertFalse(result[0])
        audit.assert_not_called()

    def test_unknown_refreshes_stale_office_probe(self):
        from unittest.mock import Mock
        inspector=Mock(return_value='paragraph 0 lh=200')
        with patch.object(p.importlib,'import_module',return_value=SimpleNamespace(run_inspect=inspector)):
            results, artifacts=self.run_audit([
                json.dumps(dict(judgement='unknown',confidence='LOW',probe_kind='document_structure')),
                json.dumps(dict(judgement='verified',confidence='HIGH',evidence_ids=['document_structure']))],
                attributes={'_current_domain':'libreoffice_writer','_doc_inspect_block':'stale lh=100',
                            '_doc_inspect_step':-1,'_doc_inspect_dirty':False})
        self.assertTrue(results[0][0])
        self.assertEqual(artifacts[0]['events'][0]['prompt']['structured_evidence'],{})
        self.assertEqual(artifacts[0]['events'][-1]['stage'],'probe')
        self.assertEqual(inspector.call_args.kwargs['max_retries'],1)

    def test_actual_boundary_hook_reaches_recovery_when_native_verifier_fails(self):
        from unittest.mock import Mock
        tree=ast.parse((Path(__file__).resolve().parents[1]/'mm_agents/structagent/loop.py').read_text())
        method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_run_boundary_verify')
        namespace={'os':os,'json':json,'logger':None}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'loop.py','exec'),namespace)
        outcome=SimpleNamespace(id='a',state='pending')
        verdict=SimpleNamespace(outcome_id='a',verified=False)
        self_obj=SimpleNamespace(_candidate_step=SimpleNamespace(a11y='',screenshot_b64='image'),
            _current_domain='os',_physical_domain=None,current_subgoal='target',timeline=[],
            _verifier_memory_on=False,instruction='task',current_subgoal_expected_post_state='done',
            actor_history=[],_current_snapshot=None,call_llm=None,verifier_model='test',
            ledger=SimpleNamespace(get=lambda _:outcome))
        recovery=Mock()
        modules={
            'mm_agents.structagent.core.verifier.boundary_verify':SimpleNamespace(
                verify_milestone=lambda *a,**k:[verdict],VerifyContext=SimpleNamespace,
                allowed_probes_for_domain=lambda _:[]),
            'mm_agents.structagent.ledger.core.ledger':SimpleNamespace(OUTCOME_VERIFIED='verified'),
            'mm_agents.structagent.ledger.support.a11y_prefilter':SimpleNamespace(prefilter_linearized_a11y=lambda **k:''),
            'mm_agents.structagent.core.final_audit.progressive':SimpleNamespace(recover_pending=recovery)}
        with patch.dict(sys.modules,modules),patch.dict(os.environ,{'FUSION_PROGRESSIVE':'1'}):
            namespace['_run_boundary_verify'](self_obj,[outcome],3,None,dump_name='test.json',dump_targets=[])
        self.assertEqual(recovery.call_args.args[-1],'boundary_insufficient')
        self.assertEqual(recovery.call_args.args[-2],[outcome])

    def test_exhausted_boundary_verification_escapes_legacy_exception_handlers(self):
        for judgement in ['contradicted','unknown']:
            agent=SimpleNamespace(_fusion_last_result={'judgement':judgement},_fusion_previous_audit='audit1')
            outcome=SimpleNamespace(id='a',description='target',state='pending')
            with patch.object(p,'audit',return_value=(False,True,'no evidence')):
                with self.assertRaises(EpisodeStopped) as stopped:
                    try:
                        p.recover_pending(agent,None,{},3,[outcome],'boundary_insufficient')
                    except Exception:
                        self.fail('Task stop was swallowed by a generic Exception handler')
            self.assertEqual(stopped.exception.reason,'verification_budget')
            self.assertEqual(stopped.exception.details['audit_id'],'audit1')


if __name__ == '__main__':
    unittest.main()
