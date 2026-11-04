import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('endpoints', ROOT / 'mm_agents/model_endpoints.py')
endpoints = importlib.util.module_from_spec(spec)
spec.loader.exec_module(endpoints)
spec = importlib.util.spec_from_file_location('local_launcher', ROOT / 'scripts/run_fusion_local60.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LocalInferenceTests(unittest.TestCase):
    def test_loopback_only(self):
        with patch.dict(os.environ, {'FUSION_LOCAL_ONLY': '1', 'FUSION_REMOTE_ONLY': '0'}):
            endpoints.require_local_endpoint('http://127.0.0.1:8110/v1')
            for url in ['https://opencode.ai/zen/go/v1', 'http://localhost.evil/v1', 'file:///tmp/model']:
                with self.assertRaises(RuntimeError):
                    endpoints.require_local_endpoint(url)

    def test_registry_rejects_remote_override(self):
        with patch.dict(os.environ, {'FUSION_LOCAL_ONLY': '1', 'FUSION_REMOTE_ONLY': '0',
                                   'VLLM_QWEN35_VL_URL': 'https://example.com/v1'}):
            with self.assertRaises(RuntimeError):
                endpoints.resolve('qwen35-vl')

    def test_conflicting_modes_rejected(self):
        with patch.dict(os.environ, {'FUSION_LOCAL_ONLY': '1', 'FUSION_REMOTE_ONLY': '1'}):
            with self.assertRaises(RuntimeError):
                endpoints.require_local_endpoint('http://127.0.0.1:8110/v1')

    def test_launcher_drops_credentials_and_api_budgets(self):
        with patch.dict(os.environ, {'OPENCODE_GO_API_KEY': 'not-a-real-key',
                                   'FUSION_TASK_SECONDS': '1200', 'OPENROUTER_API_KEY': 'test'}):
            env = launcher.environment()
        self.assertNotIn('OPENCODE_GO_API_KEY', env)
        self.assertNotIn('OPENROUTER_API_KEY', env)
        self.assertNotIn('FUSION_TASK_SECONDS', env)
        self.assertEqual(env['FUSION_REMOTE_ONLY'], '0')
        cmd = launcher.command(Path('/tmp/example'))
        for flag, value in [('--model', 'vllm_qwen35-vl'), ('--verifier_model', 'vllm_qwen35-27b'),
                            ('--max_steps', '100'), ('--max_tokens', '1500'), ('--num_envs', '1')]:
            self.assertEqual(cmd[cmd.index(flag) + 1], value)


if __name__ == '__main__':
    unittest.main()
