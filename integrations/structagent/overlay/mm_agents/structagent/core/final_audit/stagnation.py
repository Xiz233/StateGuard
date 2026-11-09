"""Optional local stagnation scoring before progressive milestone verification."""

from collections import deque
from functools import lru_cache
import json
import logging
import os
from pathlib import Path
import re
from time import perf_counter
import unicodedata


logger = logging.getLogger(__name__)
CONTROL_ROLES = (
    'check-box', 'radio-button', 'entry', 'combo-box', 'spin-button',
    'table-cell', 'list-item', 'page-tab', 'document-web', 'document-text',
    'terminal', 'label', 'push-button', 'section', 'static',
)
ROLE_PRIORITY = {role: index for index, role in enumerate(CONTROL_ROLES)}


def control_rows(a11y):
    rows = set()
    for line in a11y.splitlines():
        line = ''.join(char for char in line if unicodedata.category(char) != 'Cf')
        if re.match(r'^(?:label|text)\t(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+.*\d{1,2}[:∶]\d{2}', line):
            continue
        parts = re.sub(r' - Memory usage - [\d.]+ [MG]B', '', line).strip().split('\t')
        if len(parts) >= 3:
            parts[-1] = ','.join(flag for flag in parts[-1].split(',') if flag != 'focused')
        row = '\t'.join(parts)
        if row and not row.startswith('tag\ttext'):
            rows.add(row)
    return rows


def recent_observations(history, current, step):
    frames = {frame.step_idx: frame.a11y for frame in history
              if frame.step_idx < step and frame.a11y}
    if current is None or current.step_idx != step or not current.a11y:
        return []
    frames[step] = current.a11y
    rows_by_step = [(index, control_rows(frames[index])) for index in sorted(frames)[-3:]]
    if not rows_by_step[-1][1]:
        return []
    common = set.intersection(*(rows for _, rows in rows_by_step))
    observations = []
    for index, rows in rows_by_step:
        changed = rows - common
        ordered = sorted(changed or rows, key=lambda row: (
            ROLE_PRIORITY.get(row.split('\t', 1)[0], len(CONTROL_ROLES)), row))
        if not changed:
            ordered = ordered[:12]
        observations.append({'step': index, 'text': '\n'.join(ordered)[:2000]})
    return observations


def recent_actions(path):
    actions = deque(maxlen=8)
    with path.open(encoding='utf-8') as trajectory:
        for line in trajectory:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            index, action = row.get('step_num'), row.get('action')
            if type(index) is int and isinstance(action, str) and action:
                block = f'Step {index}:\nAction: {action}'
                actions.append({'step': index, 'text': block[:700], 'truncated': len(block) > 700})
    return list(actions)


def encode_window(tokenizer, instruction, actions, observations, proposal=None):
    def tokens(text):
        return tokenizer.encode(text, add_special_tokens=False)

    ids = tokens('TASK: ' + instruction)[:256]
    ids += tokens('\nEXECUTED ACTIONS BEFORE CURRENT: ' + json.dumps(actions, ensure_ascii=False))[-640:]
    ids += tokens('\nPROPOSED, NOT EXECUTED: ' + json.dumps(proposal, ensure_ascii=False))[:192]
    for observation in observations[-3:]:
        ids += tokens(f"\nOBSERVATION BEFORE ACTION {observation['step']}:\n{observation['text']}")[:300]
    return tokenizer.build_inputs_with_special_tokens(ids)


class StagnationScorer:
    def __init__(self, model_dir, head_path):
        import numpy as np
        import torch
        from transformers import AutoModel, AutoTokenizer

        with np.load(head_path, allow_pickle=False) as head:
            self.mean = head['embedding_mean']
            self.projection = head['projection']
            self.scale = head['projection_scale']
            self.beta = head['beta']
        if (self.projection.ndim != 2 or self.mean.shape != self.projection.shape[:1]
                or self.scale.shape != self.projection.shape[1:]
                or self.beta.shape != (self.scale.size + 1,)
                or any(not np.isfinite(array).all() for array in (
                    self.mean, self.projection, self.scale, self.beta))
                or np.any(self.scale <= 0)):
            raise ValueError('Expected a finite embedding-only PCA/logistic head')
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
        self.model = AutoModel.from_pretrained(
            model_dir, local_files_only=True, attn_implementation='sdpa',
            reference_compile=False,
        ).eval()
        if self.model.config.hidden_size != self.mean.size:
            raise ValueError('The encoder hidden size does not match the fitted head')

    def score_embedding(self, embedding):
        import numpy as np

        projected = (embedding - self.mean) @ self.projection / self.scale
        logit = projected @ self.beta[:-1] + self.beta[-1]
        if not np.isfinite(logit):
            raise ValueError('Non-finite stagnation logit')
        return float(1 / (1 + np.exp(-np.clip(logit, -35, 35))))

    def score(self, instruction, actions, observations, proposal=None):
        tokens = encode_window(self.tokenizer, instruction, actions, observations, proposal)
        with self.torch.inference_mode():
            inputs = self.torch.tensor([tokens])
            hidden = self.model(input_ids=inputs, attention_mask=self.torch.ones_like(inputs)).last_hidden_state
            embedding = hidden.float().mean(dim=1)[0].numpy()
        return self.score_embedding(embedding)


@lru_cache(maxsize=1)
def load_scorer(model_dir, head_path):
    return StagnationScorer(model_dir, head_path)


def record_shadow_score(agent, step, outcomes, history, current):
    """Log a score from existing observations. Verifier and ledger stay independent."""
    started = perf_counter()
    record = {'step': step, 'outcome_ids': sorted(outcome.id for outcome in outcomes)}
    try:
        results = Path(agent._results_dir)
        observations = recent_observations(history, current, step)
        trajectory = results / 'traj.jsonl'
        actions = recent_actions(trajectory) if trajectory.is_file() else []
        if len(observations) < 2 or not actions:
            record['status'] = 'insufficient_history'
        else:
            model = Path(os.environ['FUSION_STAGNATION_MODEL_DIR']).expanduser().resolve(strict=True)
            head = Path(os.environ['FUSION_STAGNATION_HEAD']).expanduser().resolve(strict=True)
            scorer = load_scorer(model, head)
            instruction = getattr(agent, '_raw_instruction', None) or agent.instruction or ''
            record.update(status='scored', p_stagnant=scorer.score(instruction, actions, observations),
                          observation_steps=[obs['step'] for obs in observations], action_count=len(actions))
    except Exception as exc:
        record.update(status='unavailable', error_type=type(exc).__name__)
    record['elapsed_ms'] = round(1000 * (perf_counter() - started), 1)
    try:
        with (Path(agent._results_dir) / 'stagnation_shadow.jsonl').open('a', encoding='utf-8') as log:
            log.write(json.dumps(record, ensure_ascii=False) + '\n')
    except (AttributeError, OSError, TypeError) as exc:
        logger.warning('Could not write stagnation shadow log (%s)', type(exc).__name__)
