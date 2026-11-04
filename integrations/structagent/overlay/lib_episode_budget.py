"""Episode-local control flow that cannot be swallowed by model/parser retries."""
import json
import signal
import time
import traceback
from contextlib import nullcontext
from pathlib import Path


class EpisodeStopped(BaseException):
    """Only the task boundary catches this; it never means benchmark FAIL."""

    def __init__(self, reason, **details):
        super().__init__(reason)
        self.reason = reason
        self.details = details


class EpisodeBudget:
    def __init__(self, seconds, max_calls):
        if seconds <= 0 or max_calls <= 0:
            raise ValueError('Episode limits must be positive')
        self.seconds = seconds
        self.max_calls = max_calls
        self.calls = 0
        self.started = time.monotonic()

    def check(self):
        if time.monotonic() - self.started >= self.seconds:
            raise EpisodeStopped('task_time_budget')

    def reserve_call(self):
        self.check()
        if self.calls >= self.max_calls:
            raise EpisodeStopped('task_call_budget')
        self.calls += 1

    def remaining(self):
        self.check()
        return max(0.001, self.seconds - (time.monotonic() - self.started))

    def _alarm(self, signum, frame):
        raise EpisodeStopped('task_time_budget')

    def __enter__(self):
        self.started = time.monotonic()
        self.previous_handler = signal.getsignal(signal.SIGALRM)
        self.previous_timer = signal.getitimer(signal.ITIMER_REAL)
        if self.previous_timer[0]:
            raise RuntimeError('Episode deadline conflicts with an existing alarm')
        signal.signal(signal.SIGALRM, self._alarm)
        signal.setitimer(signal.ITIMER_REAL, self.seconds)
        return self

    def __exit__(self, *args):
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, self.previous_handler)

    def snapshot(self):
        return {'elapsed_seconds': time.monotonic() - self.started,
                'api_attempts': self.calls, 'max_seconds': self.seconds,
                'max_api_attempts': self.max_calls}


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2))
    temporary.replace(path)


def run_episode(agent, directory, callback, cleanup, seconds, max_calls, cleanup_seconds=20):
    """End one episode on a limit/error and allow the queue to advance.

    Limits cover reset, inference, environment operations and final evaluation.
    Failed cleanup has its own 20-second ceiling and does not block the queue.
    """
    directory = Path(directory)
    # Local baseline-matched runs have no wall-time/API cap, but still need
    # the same termination receipt and queue advance for verification stops.
    if (seconds is None) != (max_calls is None):
        raise ValueError('Provide both budget limits or neither')
    budget = EpisodeBudget(seconds, max_calls) if seconds is not None else None
    started = time.monotonic()
    def snapshot():
        return budget.snapshot() if budget is not None else {
            'elapsed_seconds': time.monotonic() - started, 'api_attempts': None,
            'max_seconds': None, 'max_api_attempts': None}
    agent._fusion_episode_budget = budget
    reason = None
    details = {}
    try:
        with budget if budget is not None else nullcontext():
            callback()
        if not (directory / 'result.txt').exists():
            reason = 'evaluator_no_score'
    except EpisodeStopped as exc:
        reason, details = exc.reason, exc.details
    except Exception as exc:
        reason = 'episode_exception'
        details = {'error': f'{type(exc).__name__}: {exc}', 'traceback': traceback.format_exc()}
    finally:
        agent._fusion_episode_budget = None
    if reason is None:
        write_json(directory / 'episode_budget.json', snapshot())
        return True
    record = {'status': 'terminated', 'reason': reason, 'details': details,
              'ended_at_unix': time.time(), 'budget': snapshot(),
              'native_score_available': (directory / 'result.txt').exists()}
    write_json(directory / 'termination.json', record)
    with (directory / 'traj.jsonl').open('a') as stream:
        stream.write(json.dumps({'event': 'episode_terminated', **record}) + '\n')
    try:
        with EpisodeBudget(cleanup_seconds, 1):
            cleanup()
    except (EpisodeStopped, Exception) as exc:
        record['cleanup_error'] = f'{type(exc).__name__}: {exc}'
        write_json(directory / 'termination.json', record)
    return False
