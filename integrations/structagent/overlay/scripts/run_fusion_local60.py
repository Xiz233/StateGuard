"""Run the fusion variant with the historical local main60 model/settings pair."""
import argparse
import base64
from collections import Counter
import datetime
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time
import urllib.request

REPO = Path(__file__).resolve().parents[1]
BASELINE = Path(os.environ.get('FUSION_BASELINE_RUN', 'baseline/main60'))
BASELINE_REPO = Path(os.environ.get('FUSION_BASELINE_REPO', 'baseline/StructAgent'))
sys.path.insert(0, str(REPO))
from lib_episode_budget import write_json


def environment():
    env = {k: os.environ[k] for k in ('HOME', 'USER', 'LOGNAME', 'PATH', 'LANG', 'LC_ALL') if k in os.environ}
    env.update(
        FUSION_LOCAL_ONLY='1', FUSION_REMOTE_ONLY='0', FUSION_PROGRESSIVE='1',
        VLLM_QWEN35_VL_URL='http://127.0.0.1:8110/v1',
        VLLM_QWEN35_27B_URL='http://127.0.0.1:8112/v1',
        QWEN35_THINKING='0', ENABLE_PLANNER_EXPERIENCE_MEMORY='0',
        ENABLE_VERIFIER_EXPERIENCE_MEMORY='0', MEMORY_TOP_K='10',
        PERCEIVER_ENABLED='1', ENABLE_FEASIBILITY_VERDICT='1',
        USE_FAILURE_ATTRIBUTION='1', ENABLE_STUCK_DIAGNOSIS_INJECTION='1',
        ENABLE_DONE_AUDITOR='1', WEB_DOM_INJECT='1', DISABLE_LEDGER='0',
        HF_HOME=os.environ.get('HF_HOME', str(Path.home() / '.cache/huggingface')),
        TMPDIR=os.environ.get('TMPDIR', '/tmp'),
        PYTHONPATH=str(REPO / 'vendor') + os.pathsep + str(REPO), PYTHONUNBUFFERED='1')
    return env


def command(root):
    return [sys.executable, 'scripts/run_structagent.py', '--provider_name', 'docker',
        '--headless', '--model', 'vllm_qwen35-vl', '--verifier_model', 'vllm_qwen35-27b',
        '--enable_done_auditor', '--done_auditor_model', 'vllm_qwen35-27b',
        '--done_auditor_max_per_task', '3', '--observation_type', 'screenshot',
        '--sleep_after_execution', '3', '--max_steps', '100', '--num_envs', '1',
        '--max_tokens', '1500', '--temperature', '0', '--top_p', '0.9',
        '--client_password', 'password', '--screen_width', '1920', '--screen_height', '1080',
        '--version_num', root.name, '--domain', 'all', '--test_config_base_dir', 'evaluation_examples',
        '--test_all_meta_path', str(root / 'selected_tasks.json'),
        '--result_dir', str(root / 'results'),
        '--path_to_vm', os.environ.get('OSWORLD_VM_PATH', str(REPO / 'docker_vm_data/Ubuntu.qcow2'))]


def preflight():
    from PIL import Image, ImageDraw
    manifest = json.loads((REPO / 'evaluation_examples/main60.json').read_text())
    if manifest != json.loads((BASELINE / 'main60.json').read_text()):
        raise ValueError('Task selection differs from the historical main60')
    pairs = [(domain, tid) for domain, tids in manifest.items() for tid in tids]
    if len(pairs) != 60 or len(set(pairs)) != 60:
        raise ValueError('Expected exactly 60 unique tasks')
    task_hashes = {}
    for domain, tid in pairs:
        rel = Path('evaluation_examples/examples') / domain / (tid + '.json')
        raw = (REPO / rel).read_bytes()
        if raw != (BASELINE_REPO / rel).read_bytes():
            raise ValueError('Task config differs from baseline repo: ' + str(rel))
        task_hashes[str(rel)] = hashlib.sha256(raw).hexdigest()
    image = Image.new('RGB', (480, 100), 'white')
    ImageDraw.Draw(image).text((30, 35), 'LOCAL MODEL READY', fill='black')
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    data_url = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
    models = []
    for port, model in [(8110, 'Qwen/Qwen3.5-9B'), (8112, 'Qwen/Qwen3.5-27B')]:
        url = f'http://127.0.0.1:{port}/v1'
        with urllib.request.urlopen(url + '/models', timeout=15) as response:
            inventory = json.load(response)
        if model not in [entry['id'] for entry in inventory['data']]:
            raise ValueError('Unexpected model on port ' + str(port))
        payload = {'model': model, 'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': 'Transcribe the text in this image. Reply only with that text.'},
            {'type': 'image_url', 'image_url': {'url': data_url}}]}],
            'max_tokens': 128, 'temperature': 0,
            'chat_template_kwargs': {'enable_thinking': False}}
        request = urllib.request.Request(url + '/chat/completions',
            data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.load(response)
        text = result['choices'][0]['message'].get('content') or ''
        if 'LOCAL MODEL READY' not in text.upper():
            raise ValueError('Local vision smoke failed: ' + model + ': ' + text)
        models.append({'model': model, 'url': url, 'inventory': inventory,
                       'vision_response': text, 'latency_seconds': time.monotonic() - started,
                       'usage': result.get('usage')})
    return manifest, {'models': models, 'task_sha256': task_hashes,
        'manifest_sha256': hashlib.sha256((BASELINE / 'main60.json').read_bytes()).hexdigest()}


def summarize(root, manifest):
    episodes = []
    for domain, tids in manifest.items():
        for tid in tids:
            row = {'domain': domain, 'task': tid, 'status': 'not_started'}
            directories = list((root / 'results').glob(f'**/{domain}/{tid}'))
            if directories:
                p = directories[0]
                row.update(status='incomplete', path=str(p))
                if (p / 'termination.json').exists():
                    row.update(status='terminated', termination=json.loads((p / 'termination.json').read_text()))
                if (p / 'result.txt').exists():
                    row.update(status='scored', score=float((p / 'result.txt').read_text()))
            episodes.append(row)
    counts = dict(Counter(row['status'] for row in episodes))
    summary = {'episodes': episodes, 'counts': counts,
               'successes': sum(row.get('score') == 1.0 for row in episodes)}
    write_json(root / 'summary.json', summary)
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args()
    root = Path(args.run_dir).resolve()
    manifest, checks = preflight()
    if args.preflight_only:
        print(json.dumps(checks, indent=2))
        return
    root.parent.mkdir(parents=True, exist_ok=True)
    lock = (root.parent / 'fusion_evaluation.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    root.mkdir(exist_ok=False)
    env = environment()
    env['FUSION_RUN_DIR'] = str(root)
    cmd = command(root)
    write_json(root / 'selected_tasks.json', manifest)
    write_json(root / 'preflight.json', checks)
    write_json(root / 'run_config.json', {'manifest': manifest, 'command': cmd,
        'baseline_run': str(BASELINE), 'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'environment': env, 'task_seconds': None, 'task_api_attempts': None,
        'differences_from_baseline': ['StateGuard/VAGEN progressive verification enabled; replaces legacy task DONE auditor',
            'Verification stops preserved and queue advances; existing artifacts never overwritten',
            'Local-only endpoint enforcement; no external inference credentials loaded']})
    sources = [p for folder in ['mm_agents', 'scripts', 'vendor', 'tests']
               for p in (REPO / folder).rglob('*.py')]
    sources += [REPO / 'lib_run_single.py', REPO / 'lib_episode_budget.py']
    write_json(root / 'source_manifest.json', {str(p.relative_to(REPO)):
        hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    with tarfile.open(root / 'source_snapshot.tar.gz', 'w:gz') as archive:
        for p in sources:
            archive.add(p, arcname=str(p.relative_to(REPO)))
    with (root / 'launcher.log').open('w') as log:
        result = subprocess.run(cmd, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
    counts = summarize(root, manifest)
    finished = counts.get('scored', 0) + counts.get('terminated', 0)
    write_json(root / 'exit_status.json', {'returncode': result.returncode, 'finished': finished,
                                         'complete': finished == 60, 'counts': counts})
    sys.exit(0 if result.returncode == 0 and finished == 60 else 2)


if __name__ == '__main__':
    main()
