"""Explicit remote-only routing with bounded requests and audit records."""
import json
import os
import time
import uuid
import urllib.request
import urllib.error
import http.client
from pathlib import Path
from types import SimpleNamespace
from lib_episode_budget import EpisodeStopped


class RemoteRunStopped(SystemExit):
    """Stop the worker through legacy broad Exception handlers; cleanup still runs."""


def usage_summary(root):
    summary = {'calls': 0, 'errors': 0, 'tokens': 0, 'allowance': 0.0,
               'missing_allowance': 0, 'billing_sources': [], 'retries': 0,
               'unaccounted_failed_attempts': 0}
    for path in (Path(root) / 'model_calls').glob('*.response.json'):
        record = json.loads(path.read_text())
        summary['calls'] += 1
        summary['errors'] += int('error' in record)
        summary['retries'] += int(record.get('attempt', 1) > 1)
        summary['unaccounted_failed_attempts'] += int('error' in record and not record.get('response'))
        response = record.get('response', {})
        usage = response.get('usage', {})
        summary['tokens'] += usage.get('total_tokens', 0)
        billing = usage.get('opencode', {})
        if response:
            if not isinstance(billing.get('allowance'), (int, float)):
                summary['missing_allowance'] += 1
            else:
                summary['allowance'] += billing['allowance']
            source = billing.get('billing_source', 'unknown')
            if source not in summary['billing_sources']:
                summary['billing_sources'].append(source)
    return summary


def stop(root, reason):
    (root / 'STOP.json').write_text(json.dumps({'reason': reason, 'time': time.time()}))
    raise RemoteRunStopped(reason)


class RemoteClient:
    """OpenAI-shaped adapter for the actor's otherwise independent call path."""

    base_url = 'https://opencode.ai/zen/go/v1'

    def __init__(self, owner):
        self.owner = owner
        self.chat = self.completions = self

    def create(self, **payload):
        content = generate(payload, self.owner)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def generate(payload, owner):
    logical_id = uuid.uuid4().hex
    max_attempts = max(1, min(int(os.environ.get('FUSION_API_MAX_ATTEMPTS', '3')), 5))
    for attempt in range(1, max_attempts + 1):
        try:
            return _generate_once(payload, owner, logical_id, attempt, max_attempts)
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                http.client.RemoteDisconnected, http.client.IncompleteRead) as exc:
            if not retryable(exc) or attempt == max_attempts:
                raise
            time.sleep(retry_delay(exc, attempt))


def retryable(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (408, 500, 502, 503, 504)
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError,
                            http.client.RemoteDisconnected, http.client.IncompleteRead))


def retry_delay(exc, attempt):
    delay = min(2 ** attempt, 30)
    if isinstance(exc, urllib.error.HTTPError):
        try:
            delay = max(delay, float(exc.headers.get('Retry-After', 0)))
        except (ValueError, TypeError, AttributeError):
            pass
    return min(delay, 30)


def _generate_once(payload, owner, logical_id, attempt, max_attempts):
    root = Path(os.environ['FUSION_RUN_DIR'])
    calls = root / 'model_calls'
    calls.mkdir(parents=True, exist_ok=True)
    # A single worker is required for this run-wide call budget.
    if (root / 'STOP.json').exists():
        raise RemoteRunStopped('Run has a persistent STOP marker')
    if sum(1 for _ in calls.glob('*.request.json')) >= int(os.environ.get('FUSION_MAX_CALLS', '450')):
        stop(root, 'Remote model call budget exhausted')
    totals = usage_summary(root)
    if totals['allowance'] >= float(os.environ.get('FUSION_MAX_ALLOWANCE', '1.0')):
        stop(root, 'Go allowance budget exhausted (last request can overshoot)')
    if totals['missing_allowance'] or any(s != 'go' for s in totals['billing_sources']):
        stop(root, 'Cannot verify Go allowance accounting; refusing paid fallback')
    key = os.environ.get('OPENCODE_GO_API_KEY')
    if not key:
        raise RuntimeError('OPENCODE_GO_API_KEY is missing; no local fallback')
    body = dict(model=os.environ.get('OPENCODE_MODEL', 'qwen3.7-plus'),
                messages=payload['messages'], temperature=payload.get('temperature', 0),
                max_tokens=min(max(payload.get('max_tokens', owner.max_tokens), 4096), 8192))
    budget = getattr(owner, '_fusion_episode_budget', None)
    if budget is not None:
        budget.reserve_call()
    call_id = uuid.uuid4().hex
    owner._fusion_last_call_id = call_id
    (calls / f'{call_id}.request.json').write_text(json.dumps(body))
    start = time.monotonic()
    record = {'call_id': call_id, 'logical_call_id': logical_id, 'attempt': attempt,
              'max_attempts': max_attempts, 'requested_role_model': payload.get('model'),
              'task_result_dir': getattr(owner, '_results_dir', None)}
    try:
        request = urllib.request.Request('https://opencode.ai/zen/go/v1/chat/completions',
            data=json.dumps(body).encode(), headers={
                'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                'User-Agent': 'StateGuard-OSWorld-Research/1.0',
                'x-opencode-session': root.name})
        timeout = max(1, min(float(os.environ.get('FUSION_API_TIMEOUT', '180')), 240))
        if budget is not None:
            timeout = min(timeout, budget.remaining())
        record['timeout_seconds'] = timeout
        with urllib.request.urlopen(request, timeout=timeout) as response:
            record['response'] = json.load(response)
        text = record['response']['choices'][0]['message']['content']
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Empty model response')
        return text
    except EpisodeStopped as exc:
        record['error'] = str(exc)
        record['termination_reason'] = exc.reason
        record['will_retry'] = False
        raise
    except Exception as exc:
        record['error'] = f'{type(exc).__name__}: {exc}'
        record['retryable'] = retryable(exc)
        record['will_retry'] = retryable(exc) and attempt < max_attempts
        if record['will_retry']:
            record['retry_delay_seconds'] = retry_delay(exc, attempt)
        if isinstance(exc, urllib.error.HTTPError):
            record['http_status'] = exc.code
        if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 429):
            stop(root, f'OpenCode HTTP {exc.code}; manual review required')
        raise
    finally:
        record['latency_seconds'] = time.monotonic() - start
        path = calls / f'{call_id}.response.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(record))
        temporary.replace(path)
