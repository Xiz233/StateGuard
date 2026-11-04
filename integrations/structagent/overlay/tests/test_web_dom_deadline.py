import importlib.util
import pathlib
import subprocess
import sys
import time
import unittest

path = pathlib.Path(__file__).resolve().parents[1] / 'mm_agents/structagent/utils/web_dom.py'
spec = importlib.util.spec_from_file_location('web_dom', path)
web_dom = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web_dom)


class ProbeTests(unittest.TestCase):
    def test_success(self):
        self.assertEqual(web_dom._run_probe([sys.executable, '-c', 'print("[]")'], 5), [])

    def test_failure(self):
        with self.assertRaises(RuntimeError):
            web_dom._run_probe([sys.executable, '-c', 'raise RuntimeError("broken")'], 5)

    def test_timeout_including_child(self):
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            web_dom._run_probe([sys.executable, '-c',
                'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); time.sleep(60)'], 0.3)
        self.assertLess(time.monotonic() - started, 5)

    def test_invalid_json(self):
        with self.assertRaises(ValueError):
            web_dom._run_probe([sys.executable, '-c', 'print("invalid")'], 5)


if __name__ == '__main__':
    unittest.main()
