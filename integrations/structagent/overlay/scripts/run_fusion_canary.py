"""Bounded remote evaluation; expansion to main60 requires explicit --full60."""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import fcntl
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib_episode_budget import write_json


def load_key(path):
    values = []
    for line in Path(path).read_text().splitlines():
        if re.match(r'^(?:export\s+)?OPENCODE_GO_API_KEY\s*=', line):
            value = re.sub(r'^(?:export\s+)?OPENCODE_GO_API_KEY\s*=\s*', '', line)
            words = shlex.split(value, comments=True)
            if len(words) != 1 or not words[0] or words[0] != words[0].strip():
                raise ValueError('Invalid key assignment; value withheld')
            values.append(words[0])
    if len(values) != 1:
        raise ValueError('Expected exactly one OPENCODE_GO_API_KEY assignment')
    return values[0]


def summarize(root, manifest):
    spec = importlib.util.spec_from_file_location('remote_client',
        Path(__file__).resolve().parents[1] / 'mm_agents/structagent/utils/opencode_client.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    summary = module.usage_summary(root)
    episodes = []
    for domain, tasks in manifest.items():
        for task in tasks:
            paths = list((root / 'results').glob(f'**/{domain}/{task}'))
            item = {'domain': domain, 'task': task, 'status': 'not_started'}
            if paths:
                directory = paths[0]
                score = directory / 'result.txt'
                item.update(path=str(directory), status='completed' if score.exists() else 'incomplete')
                if score.exists():
                    item['score'] = float(score.read_text().strip())
                terminal = directory / 'termination.json'
                if terminal.exists():
                    item['termination'] = json.loads(terminal.read_text())
                    if not score.exists():
                        item['status'] = 'terminated'
                trace = directory / 'traj.jsonl'
                rows = [json.loads(line) for line in trace.read_text().splitlines() if line.strip()] if trace.exists() else []
                item['trajectory_entries'] = len(rows)
                item['errors'] = [row['Error'] for row in rows if 'Error' in row]
                audits = [json.loads(p.read_text()) for p in directory.glob('progressive_verification/*.json')]
                item['progressive_verdicts'] = [a['result']['judgement'] for a in audits]
                item['stages'] = [e['stage'] for a in audits for e in a['events'] if 'raw' in e]
            episodes.append(item)
    summary['episodes'] = episodes
    summary['completed'] = sum(e['status'] == 'completed' for e in episodes)
    summary['terminated'] = sum(e['status'] == 'terminated' for e in episodes)
    summary['finished'] = summary['completed'] + summary['terminated']
    summary['termination_reasons'] = {}
    for episode in episodes:
        if 'termination' in episode:
            reason = episode['termination']['reason']
            summary['termination_reasons'][reason] = summary['termination_reasons'].get(reason, 0) + 1
    summary['all_requests_have_receipts'] = all(
        p.with_name(p.name.replace('.request.json', '.response.json')).exists()
        for p in (root / 'model_calls').glob('*.request.json'))
    # Go's full monthly allowance is currently $60-equivalent, not a dollar bill.
    summary['monthly_percentage_points_estimate'] = summary['allowance'] / 60 * 100
    (root / 'summary.json').write_text(json.dumps(summary, indent=2))
    return summary


def incomplete_manifest(previous):
    previous = Path(previous)
    if not (previous / 'exit_status.json').exists():
        raise ValueError('Previous run has not exited; refusing concurrent VM use')
    manifest = json.loads((previous / 'run_config.json').read_text())['manifest']
    result = {}
    for domain, tasks in manifest.items():
        remaining = [task for task in tasks if not list(
            (previous / 'results').glob(f'**/{domain}/{task}/result.txt')) and not list(
            (previous / 'results').glob(f'**/{domain}/{task}/termination.json'))]
        if remaining:
            result[domain] = remaining
    return result


def close_previous_over_budget(previous, max_calls):
    """Annotate an exited, interrupted task using actual prior API receipts.

    This is retrospective bookkeeping, not a fabricated runtime termination or score.
    """
    previous = Path(previous).resolve()
    if not (previous / 'exit_status.json').exists():
        raise ValueError('Previous run is still active')
    counts = {}
    for path in (previous / 'model_calls').glob('*.response.json'):
        directory = json.loads(path.read_text()).get('task_result_dir')
        if directory:
            counts[directory] = counts.get(directory, 0) + 1
    for directory, count in counts.items():
        directory = Path(directory).resolve()
        if not directory.is_relative_to(previous / 'results'):
            raise ValueError('Task directory is outside the parent run')
        if count >= max_calls and not (directory / 'result.txt').exists() and not (directory / 'termination.json').exists():
            write_json(directory / 'termination.json', {
                'status': 'terminated', 'reason': 'task_call_budget',
                'enforcement': 'retrospective_at_user_requested_resume',
                'observed_api_receipts': count, 'new_max_api_attempts': max_calls,
                'native_score_available': False, 'original_artifacts_preserved': True})


def validate_selection(manifest, full60=False, rerun=False):
    pairs = [(domain, task) for domain, tasks in manifest.items() for task in tasks]
    count = len(pairs)
    if len(set(pairs)) != count:
        raise ValueError('Duplicate task in evaluation manifest')
    if full60:
        valid = 1 <= count <= 60 if rerun else count == 60
    else:
        valid = 1 <= count <= 3
    if not valid:
        raise ValueError('Invalid selection; more than 3 tasks requires explicit --full60')
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--secrets', default=os.environ.get('STATEGUARD_SECRETS_FILE', '.env.secrets'))
    parser.add_argument('--max-allowance', type=float)
    parser.add_argument('--max-calls', type=int)
    parser.add_argument('--max-steps', type=int)
    parser.add_argument('--task-seconds', type=float, default=1200)
    parser.add_argument('--task-calls', type=int, default=80)
    parser.add_argument('--close-previous-over-budget', action='store_true')
    parser.add_argument('--full60', action='store_true', help='Run the original main60 manifest')
    parser.add_argument('--summarize-only', action='store_true')
    parser.add_argument('--rerun-incomplete-from')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    root = Path(args.run_dir).resolve()
    manifest_path = repo / ('evaluation_examples/main60.json' if args.full60
                            else 'experiments/fusion/canary3.json')
    manifest = json.loads(manifest_path.read_text())
    if args.summarize_only:
        manifest = json.loads((root / 'run_config.json').read_text())['manifest']
        print(json.dumps(summarize(root, manifest), indent=2))
        return
    if args.rerun_incomplete_from:
        if args.close_previous_over_budget:
            close_previous_over_budget(args.rerun_incomplete_from, args.task_calls)
        manifest = incomplete_manifest(args.rerun_incomplete_from)
    expected = validate_selection(manifest, args.full60, bool(args.rerun_incomplete_from))
    max_calls = args.max_calls if args.max_calls is not None else (6000 if args.full60 else 450)
    max_steps = args.max_steps if args.max_steps is not None else (100 if args.full60 else 60)
    max_allowance = args.max_allowance if args.max_allowance is not None else (6.0 if args.full60 else 1.0)
    if min(max_calls, max_steps, max_allowance, args.task_calls, args.task_seconds) <= 0:
        raise ValueError('Budgets must be positive')
    key = load_key(args.secrets)
    root.parent.mkdir(parents=True, exist_ok=True)
    # Hold this descriptor for the whole run, including child shutdown/summary.
    run_lock = (root.parent / 'fusion_evaluation.lock').open('a')
    try:
        fcntl.flock(run_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('Another fusion evaluation owns the VM lock') from None
    root.mkdir(parents=True, exist_ok=False)
    manifest_path = root / 'selected_tasks.json'
    manifest_path.write_text(json.dumps(manifest, indent=2))
    (repo / 'logs').mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(OPENCODE_GO_API_KEY=key,
        OPENCODE_MODEL='qwen3.7-plus', FUSION_REMOTE_ONLY='1', FUSION_PROGRESSIVE='1',
        FUSION_RUN_DIR=str(root), FUSION_MAX_CALLS=str(max_calls), FUSION_MAX_ALLOWANCE=str(max_allowance),
        FUSION_API_MAX_ATTEMPTS='3', FUSION_API_TIMEOUT='180',
        FUSION_TASK_SECONDS=str(args.task_seconds), FUSION_TASK_CALLS=str(args.task_calls),
        ENABLE_PLANNER_EXPERIENCE_MEMORY='0', ENABLE_VERIFIER_EXPERIENCE_MEMORY='0',
        PERCEIVER_ENABLED='1', ENABLE_FEASIBILITY_VERDICT='1', USE_FAILURE_ATTRIBUTION='1',
        ENABLE_STUCK_DIAGNOSIS_INJECTION='1', ENABLE_DONE_AUDITOR='1', WEB_DOM_INJECT='1',
        HF_HOME=os.environ.get('HF_HOME', str(Path.home() / '.cache/huggingface')),
        TMPDIR=os.environ.get('TMPDIR', '/tmp'),
        PYTHONPATH=str(repo / 'vendor') + os.pathsep + str(repo), PYTHONUNBUFFERED='1')
    command = [sys.executable, 'scripts/run_structagent.py', '--provider_name', 'docker',
        '--headless', '--num_envs', '1', '--max_steps', str(max_steps), '--max_tokens', '8192',
        '--model', 'qwen3.7-plus', '--verifier_model', 'qwen3.7-plus',
        '--enable_done_auditor', '--done_auditor_model', 'qwen3.7-plus',
        '--done_auditor_max_per_task', '3', '--observation_type', 'screenshot',
        '--sleep_after_execution', '3', '--client_password', 'password',
        '--screen_width', '1920', '--screen_height', '1080',
        '--version_num', root.name, '--test_config_base_dir', 'evaluation_examples',
        '--test_all_meta_path', str(manifest_path), '--result_dir', str(root / 'results'),
        '--path_to_vm', os.environ.get('OSWORLD_VM_PATH', str(repo / 'docker_vm_data/Ubuntu.qcow2'))]
    files = [p for directory in ('mm_agents', 'scripts', 'vendor', 'experiments/fusion')
             for p in (repo / directory).rglob('*') if p.suffix in ('.py', '.json', '.sh')]
    files.extend([repo / 'lib_episode_budget.py', repo / 'lib_run_single.py'])
    (root / 'source_manifest.json').write_text(json.dumps({str(p.relative_to(repo)):
        hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, indent=2))
    (root / 'run_config.json').write_text(json.dumps({'manifest': manifest, 'command': command,
        'max_calls': max_calls, 'max_allowance': max_allowance, 'max_steps': max_steps,
        'full60': args.full60,
        'task_seconds': args.task_seconds, 'task_api_attempts': args.task_calls,
        'model': env['OPENCODE_MODEL'], 'parent_run': args.rerun_incomplete_from,
        'api_max_attempts': 3, 'api_timeout_seconds': 180,
        'started_at': datetime.datetime.now().isoformat()}, indent=2))
    with (root / 'launcher.log').open('w') as log:
        result = subprocess.run(command, env=env, cwd=repo, stdout=log, stderr=subprocess.STDOUT)
    summary = summarize(root, manifest)
    code = 0 if result.returncode == 0 and summary['finished'] == expected else 2
    (root / 'exit_status.json').write_text(json.dumps({'returncode': result.returncode,
        'complete': summary['finished'] == expected, 'scored': summary['completed'],
        'terminated': summary['terminated'], 'exit_code': code}))
    print(json.dumps(summary, indent=2))
    sys.exit(code)


if __name__ == '__main__':
    main()
