# OSWorld Evaluator Supervision Audit

Date: 2026-09-21\
StateGuard repository: `/data/research/projects/StateGuard`\
OSWorld repository: `/data/research/projects/OSWorld-StateGuard`\
Real probe output: `/data/research/stateguard_runs/evaluator_audit_v1/results.json`

## 结论

OSWorld 原生 `DesktopEnv.evaluate()` 实际只返回一个 scalar。原始 StateGuard adapter 虽然定义了 `EvaluationResult.details`，但真实内容只有 `task_id`，不存在尚未保存的隐藏 condition 列表。多 evaluator task 的 component 结果在 OSWorld 内部临时计算后立即丢弃，而且 `and/or` 会短路。

本轮增加的 adapter-side component probe 不改变原生最终分数，而是在原生 evaluation 完成后逐项重新调用 getter、expected getter 和 metric，记录 component 名称、observed、expected、score、pass/fail、异常和 artifact 摘要。它把 details 从“只有 task id”提升为可用于弱监督的 top-level condition 记录，但仍不能直接提供 DAG milestone GT、动作级失败根因或 metric 内部每条 rule 的细粒度差异。

## A. Evaluator Data Flow

真实调用链如下：

```text
stateguard/runtime/episode_runner.py
  EpisodeRunner.run()
  -> env.evaluate(task_spec)
     |
     v
integrations/osworld/adapter.py
  OSWorldAdapter.evaluate()
  -> DesktopEnvBackend.evaluate()
     |
     v
/data/research/projects/OSWorld-StateGuard/desktop_env/desktop_env.py
  DesktopEnv.evaluate()
  1. execute evaluator.postconfig
  2. call result_getter(s)
  3. call expected_getter(s)
  4. call metric(s)
  5. combine by evaluator.conj (and/or)
  6. return one scalar
     |
     v
integrations/osworld/adapter.py
  EvaluationResult(success=score > 0, score=score, details=...)
     |
     v
EpisodeRunner -> result.json + evaluator_result.json
```

Task reset initializes evaluator functions in:

`/data/research/projects/OSWorld-StateGuard/desktop_env/desktop_env.py:379-414`

- `evaluator.func` resolves to `desktop_env.evaluators.metrics.*`.
- `evaluator.result[].type` resolves to `desktop_env.evaluators.getters.get_<type>`.
- `evaluator.expected[].type` resolves through the same getter namespace.
- `options` is passed to the metric.
- `conj` defaults to `and`.

Native scoring is implemented at `desktop_env.py:458-523`. For a list of metrics:

- `and`: the first exact `0.0` returns immediately;
- `or`: the first exact `1.0` returns immediately;
- only when not short-circuited are collected values averaged (`and`) or maximized (`or`).

Therefore native final score cannot be inverted into component results.

## B. Returned Fields

### Before this patch

The real adapter returned:

```json
{
  "success": false,
  "score": 0.0,
  "details": {"task_id": "..."}
}
```

The following were lost: metric name, individual condition result, observed value, expected value, getter exception, actual/gold artifact identity, and short-circuited components.

### After this patch

`EvaluationResult.details` now contains:

```json
{
  "task_id": "...",
  "raw_evaluator_output": 0.0,
  "conjunction": "and",
  "components": [
    {
      "index": 0,
      "metric": "compare_docx_tables",
      "conjunction": "and",
      "result_config": {"type": "vm_file", "path": "..."},
      "expected_config": {"type": "cloud_file", "path": "..."},
      "options": {},
      "observed": {
        "kind": "artifact",
        "path": "...",
        "byte_size": 9931,
        "sha256": "1b6253..."
      },
      "expected": {
        "kind": "artifact",
        "path": "...Gold.docx",
        "byte_size": 10782,
        "sha256": "9a429e..."
      },
      "score": 0.0,
      "passed": false,
      "exception": null
    }
  ]
}
```

`evaluator_result.json` also records evaluator exceptions independently of episode success.

### Real 5-task validation

All tasks were reset and evaluated through the real Docker OSWorld backend. They were intentionally evaluated at their initial state, so score 0 is expected; the purpose was to inspect actual outputs.

| Type / task | Native score | Component output | Eval time |
|---|---:|---|---:|
| Chrome `030eeff7...` | 0.0 | `exact_match`: observed `false`, expected `true`, FAIL | 27.8 s |
| multi-app/file `3680a5ee...` | 0.0 | terminal-use condition FAIL; CSV artifact condition FAIL because output missing | 22.4 s |
| OS/terminal `4127319a...` | 0.0 | terminal output missing expected `54`, FAIL | 2.7 s |
| Writer `66399b0d...` | 0.0 | `compare_docx_tables`, actual and gold paths/sizes/SHA256 recorded, FAIL | 2.4 s |
| Calc/PDF `aa3a8974...` | 0.0 | one-page condition FAIL; PDF comparison condition FAIL, gold hash recorded | 48.1 s |

The multi-app and Calc examples prove that a scalar `0.0` can hide multiple independently useful conditions. They also confirm native short-circuit behavior: the adapter probe had to evaluate the later components explicitly.

### What is and is not returned

| Information | Native OSWorld | Component probe |
|---|---|---|
| evaluator component name | internal only | YES |
| component pass/fail | discarded | YES, top-level component |
| partial numeric score | final aggregate only | YES, if metric returns graded value |
| expected value/rule | task config only | YES, annotation metadata |
| observed value | transient | YES when getter returns serializable data |
| result artifact path/hash/size | path transient | YES for local files |
| gold/reference path/hash/size | config/cache transient | YES for local cached files |
| field/content diff | usually internal or absent | NO, unless metric itself returns it |
| multiple evaluator results | discarded/short-circuited | YES, all top-level components probed |
| evaluator exception | often converted to 0 for missing files | YES when an exception escapes a component |
| raw evaluator output | scalar | YES, scalar retained |

Many getters represent “missing artifact” as `None` or log a 404 rather than raising. In those cases the component correctly has score 0, but `exception` may remain null. Consumers must distinguish `observed: null` from a valid observed value.

## C. Supervision Capability Matrix

| Capability | Rating | Reason |
|---|---|---|
| final task success | **YES** | native score and success are authoritative benchmark outcome |
| partial success | **PARTIAL** | top-level component scores are available after probing; many metrics are binary and native aggregation short-circuits |
| condition-level success | **PARTIAL** | top-level evaluator components are captured; nested rules inside one metric remain collapsed |
| milestone supervision | **NO** direct / **PARTIAL** weak | evaluator components describe final invariants, not StateGuard DAG milestones; some can be mapped heuristically |
| artifact correctness | **YES/PARTIAL** | file-based metrics compare actual and gold; only scalar correctness is exposed, not always the detailed diff |
| observed vs expected difference | **PARTIAL** | values/artifact identities are saved; field-, cell-, paragraph- or style-level diff is generally absent |
| failure localization | **PARTIAL** | identifies failed final condition, not earliest faulty action or dependency |
| progress tracking | **PARTIAL** with probes | repeated safe component probes can show condition changes; native API has no timeline |
| intermediate evaluation | **PARTIAL** | technically callable, but postconfig and cost make native `evaluate()` unsafe at arbitrary checkpoints |

## D. Task-Type Differences

### Browser and settings

State getters commonly return a string, URL, preference object or parsed page data. These are relatively cheap and useful as condition GT. Some tasks have evaluation `postconfig` that injects JavaScript, blurs focus, kills Chrome, relaunches it and waits. The tested Do Not Track evaluator took 27.8 seconds and modified application state during evaluation.

### OS / terminal / app-state

Getters run a VM command or read terminal output. They can expose a concrete observed string and expected include/exclude rules. This is good final-condition supervision, but an empty terminal getter does not explain whether the command was never run, ran in the wrong terminal, or the output was later cleared.

### Multi-app and file-system tasks

These often combine process/app-state checks with output artifact comparison. They provide the strongest top-level condition decomposition. Missing files may be represented as `None`, and `and` short-circuiting previously hid later artifact conditions.

### LibreOffice Writer/document

File getters retrieve the produced document and gold document. Metrics such as `compare_docx_tables` return a scalar. The probe preserves both artifact identities, but the metric does not expose which table dimensions/cells/styles differed. The tested evaluator's postconfig activated Writer and sent Ctrl+S, so native intermediate evaluation is state-changing.

### Calc/spreadsheet/PDF

Tasks can combine page-count rules with visual/document comparison. Actual/gold files are available when produced, but a missing output creates repeated VM transfer failures and high latency. The tested initial-state evaluation took 48.1 seconds.

Evaluator supervision quality is therefore task- and metric-dependent. A single global “evaluator details available” flag would be misleading.

## E. Leakage Risk

The following are **annotation_metadata** and must never be inserted into Executor or Guard model input:

- `evaluator.func`, `conj`, `options`;
- expected rules, target strings and hidden state queries;
- gold/reference URLs, paths, file names, hashes and downloaded content;
- postconfig commands;
- native and component scores, pass/fail and future evaluator exceptions;
- actual artifact content collected after the action when constructing a causal pre-action input;
- any later checkpoint or final evaluator result used for hindsight relabeling.

Safe runtime model input remains the information the model actually saw: task instruction, current/past permitted observations, task-state belief, action history and explicit repair/verification context. Store evaluator data under outcome/annotation namespaces, not next to model-visible task fields without a boundary.

## Intermediate Evaluation Assessment

Calling native `DesktopEnv.evaluate()` at checkpoints is not generally safe:

1. It always executes task-specific `postconfig` first.
2. Postconfig can activate windows, save documents, inject JavaScript, kill/relaunch applications and sleep.
3. File getters copy artifacts to the host/cache and cloud getters download gold files.
4. Metrics can be expensive; real samples ranged from 2.4 to 48.1 seconds after reset.
5. Some tasks assume a final persisted file or final active UI state.

A lower-cost intermediate probe is possible only after classifying evaluator components as read-only. VM command-line preference checks and some getters are suitable; Writer save postconfig and browser relaunch are not. The current probe should therefore be used at final evaluation by default, not blindly at every Guard checkpoint.

For progress weak ground truth, add a future allowlist such as:

```text
probe_safety = read_only | host_copy_only | state_mutating | unknown
```

Only `read_only` and carefully reviewed `host_copy_only` components should run mid-episode.

## F. Recommendation

### 1. Is `EvaluationResult.details` worth saving completely?

**Yes.** Before this patch it contained almost nothing, but the adapter can recover top-level component supervision at low implementation cost. The data is especially valuable for multi-condition and artifact tasks. Full details, exceptions and artifact identities are now persisted in `evaluator_result.json` and `result.json`.

### 2. Can it directly serve as StateGuard condition/milestone ground truth?

**Condition GT: partially. Milestone GT: no.**

- A component result is strong final-condition supervision when its getter/metric is reliable.
- It is not the earliest failure step, action success, causal root or DAG milestone.
- Metrics that contain multiple internal rules still expose only one scalar.
- A final artifact failure cannot tell when the corruption occurred.

Use component results as hindsight annotation/outcome metadata, not as direct online Guard input and not as unquestioned transition labels.

### 3. What minimum additional instrumentation is still needed?

1. Keep the implemented top-level component probe and artifact hashing.
2. Mark each component's probe safety and side effects before enabling intermediate evaluation.
3. For high-value metrics, optionally expose structured internal rule results (cell/range, paragraph/table, URL field, preference key) instead of only a scalar.
4. Copy/hash actual evaluator artifacts into the episode artifact store so cache cleanup cannot invalidate references.
5. Link evaluator component results to StateGuard nodes through a separate annotation mapping, never by injecting evaluator rules into prompts.
6. If intermediate progress is needed, run only read-only component probes at sparse checkpoints and record their runtime/side effects.

The current patch is enough to stop losing final top-level condition evidence. It is not enough to turn OSWorld evaluators into a universal milestone oracle.
