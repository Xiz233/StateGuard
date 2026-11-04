# StateGuard / OSWorld Training Data Audit

Date: 2026-09-21\
Audited repository: `/data/research/projects/StateGuard` (`feature/v10-natural`)\
Local mirror used for source inspection: `/home/researcher/Documents/Codex/2026-07-16/ban/StateGuard-v10-natural`\
Audited run: `/data/research/stateguard_runs/natural_failure_v10_canary_stateguard/osworld_v10_natural_canary_stateguard-stateguard`

## 中文结论摘要

当前输出适合做实验复盘，但**还不适合直接作为未来高质量训练集的唯一原始数据源**。对于正常完成的 GUI action，现有数据通常可以近似恢复 `Task + parsed history + screenshot S_t + parsed A_t + screenshot S_(t+1)`；但无法完整恢复模型当时真正看到的输入、原始输出/推理、OSWorld 实际执行回执、evaluator 条件级结果，以及所有非环境动作决策。

最关键的问题不是“字段不够多”，而是日志边界不完整：目前以成功完成一次 `env.step()` 为主要落盘时机。因此 finish、解析失败、API 重试、环境异常、被拒绝的 Grounder/Replanner 候选等高价值负样本会丢失，或者只剩 episode 汇总计数。配置中的 `save_model_responses: true` 也没有真正贯通 Executor、Guard、Grounder 和 Replanner。

真实 episode 核验结果：成功样本报告 13 步但只有 12 条 trajectory，缺失 finish 决策；repair 失败样本报告 45 步但只有 42 条 trajectory。三个抽查样本的截图均完整对应已有 trajectory 行，但 `structured_state`、`ui_tree`、`visible_text` 和 `active_app` 全部为空。

建议在继续大规模昂贵 rollout 前，至少先完成文末 8 项最小补丁：全逻辑事件流、逐模型调用原始记录、action execution receipt、完整 evaluator 结果、artifact manifest、逐事件 state before/after、统一 intervention 生命周期，以及真正接通 `save_model_responses`。旧数据仍有价值，可迁移为弱监督样本；已丢失的原始模型调用、finish 记录和原始 evaluator 细节无法离线补回。

## Executive conclusion

The current rollout format is useful for experiment analysis, but it is **not yet safe as the sole source for a future high-quality training corpus**.

For environment actions that complete normally, the system usually preserves enough data to approximate:

```text
Task + parsed history + screenshot S_t + parsed A_t + screenshot S_(t+1)
```

It does not preserve the complete model-visible input, raw model output, action execution status, evaluator details, or every logical decision. Logging is centered on a completed environment transition, not on every model invocation or decision. Finish proposals, parse failures, API retries, environment exceptions, rejected responses, grounding calls, and replanning inputs can therefore disappear or survive only as aggregate counters.

The most important conclusion is operational:

> Do not launch hundreds or thousands of additional expensive OSWorld episodes for training-data collection until the P0 fields in this document are recorded.

Existing episodes are still valuable. Their screenshots, parsed actions, state snapshots, parsed Guard results, contracts, and final scores can support partial transition verification, UNKNOWN analysis, and weak hindsight annotation. They cannot be made into a faithful record of model behavior after the missing raw inputs and outputs have already been discarded.

## Evidence inspected

Three real episodes were opened and checked, rather than inferring output from schemas:

| Episode | Outcome | Actual transition rows | Guard rows | Missing logical step rows | Size |
|---|---:|---:|---:|---|---:|
| `030eeff7...--stateguard--seed-20260908` | success, score 1.0 | 12 | 5 | step 13 | 6.0 MB |
| `3680a5ee...--stateguard--seed-20260908` | `max_steps`, score 0.0 | 50 | 30 | none | 14 MB |
| `4127319a...--stateguard--seed-20260908` | `repair_failed`, score 0.0 | 42 | 25 | steps 19, 22, 45 | 82 MB |

All three had paired `before` and `after` PNGs for every row in `trajectory.jsonl`. None had non-null `structured_state`, `ui_tree`, `visible_text`, or `active_app`. The run configuration used `require_a11y_tree: false`.

The successful episode reported `total_steps: 13` but only 12 trajectory rows. The missing row is the finish decision. The repair episode reported 45 steps but only 42 transition rows. This is direct evidence that `trajectory.jsonl` is not a complete sequence of logical runtime decisions.

## 1. Current Data Flow

### Runtime path

```text
task.json + task_graph.json + config_resolved.yaml
                  |
                  v
MLLMExecutor.act(observation, task_state, repair_context)
  - builds prompt from instruction, state, recent history and screenshot
  - calls model
  - parses ActionProposal
  - only aggregate calls/tokens/latency survive
                  |
                  v
EpisodeRunner
  - optional fault injection
  - resolves observability and checkpoint policy
  - converts parsed action to OSWorld action
                  |
                  v
OSWorldAdapter.step -> DesktopEnv.step
  - returns screenshot-centric Observation
  - action return tuple is folded into observation.metadata
                  |
                  v
StateGuard / adaptive verification at selected checkpoints
  - rule, contract and/or MLLM verification
  - UNKNOWN debt, reground, local replan, repair
  - parsed results mutate VerifiedTaskState
                  |
                  v
EpisodeLogger.log_step + TraceCollector.record_step
  - writes only after an environment action completes
  - writes parsed proposal/action/Guard result and screenshots
                  |
                  v
OSWorld evaluator at episode end
  - success and numeric score retained
  - evaluator details discarded by EpisodeRunner
```

### Source locations

| Stage | Current implementation | What actually persists |
|---|---|---|
| Task/run setup | `experiments/poc/runner.py`, `run_experiment()` | resolved config, run metadata, task, graph |
| Executor | `stateguard/executor/mllm_executor.py`, `MLLMExecutor.act()` | parsed proposal for logged environment steps; aggregate usage |
| Model client | `stateguard/models/openai_compatible.py`, `openai_responses.py` | returns `ModelResponse.raw_response`, but callers do not persist it |
| Environment | `integrations/osworld/adapter.py`, `OSWorldAdapter.step()` | converted observation; no explicit execution receipt |
| Observation mapping | `integrations/osworld/observation_converter.py`, `convert_observation()` | screenshot and optional structured/UI/text/app fields |
| Guard | `stateguard/guard/backends/mllm_backend.py`, `MLLMBackend.verify()` | parsed `GuardResult` only when the enclosing transition is logged |
| Adaptive verification | `stateguard/verification/*` | final contract events, debt fields in trace, aggregate metrics |
| Replan | `stateguard/planning/runtime_replanner.py`; `EpisodeRunner.attempt_local_replan()` | accepted patch and runtime replacement mapping |
| Repair | `stateguard/runtime/episode_runner.py` | parsed repair request and repair-phase transitions |
| Trace | `stateguard/trace/collector.py` | one finalized trace row per completed environment transition |
| Episode output | `experiments/poc/logging.py`, `EpisodeLogger` | JSON/JSONL plus original PNG bytes |
| Evaluator | `integrations/osworld/adapter.py`, `evaluate()` | runner retains only `success` and `score` |

## 2. Current Field Inventory

Reliability terms:

- **High**: observed in real output and has clear semantics.
- **Medium**: present, but incomplete, inferred, aggregate, or dependent on a join.
- **Low**: declared by code/config but absent or null in actual v10 output.

### Run-level files

| File / field | Source | Type / real example | Every episode/step | Reliability | Training value |
|---|---|---|---|---|---|
| `run_metadata.json.git_commit` | `RunLogger` | string, `4f1bf4b...` | run | High | code provenance |
| `dirty_working_tree` | `RunLogger` | bool | run | High | reproducibility warning |
| `timestamp`, `hostname` | `RunLogger` | ISO time, host | run | High | provenance |
| `config_hash`, `task_manifest_hash` | `RunLogger` | hash | run | High | exact experiment identity |
| `mode`, `seed` | `RunLogger` | `stateguard`, `20260908` | run | High | grouping/reproduction |
| environment/provider/version | `RunLogger` | Docker, OSWorld-Verified, OSWorld commit | run | High | domain metadata |
| executor/guard provider and model | `RunLogger` | Qwen executor, Luna Guard | run | High | model attribution |
| `prompt_versions` | `RunLogger` | e.g. `phase2b: 1` | run | Medium | coarse prompt provenance; not exact prompt |
| DAG/verification policy | `RunLogger` | manual DAG, sparse policy | run | High | behavior context |
| `config_resolved.yaml` | runner | full resolved YAML | run | High | experiment reconstruction |
| `summary.json`, `results.csv` | `RunLogger.finish()` | aggregate metrics | run | High for counts | comparison, not example training |

### Episode task and outcome

| Field | Source | Type / real example | Every episode | Reliability | Training value |
|---|---|---|---|---|---|
| `task.json.task_id` | task manifest | UUID | yes | High | task identity |
| `instruction`, `application`, `category` | task manifest | strings | yes | High | model task input and strata |
| `task_config_path`, `source`, `proxy` | task manifest | paths/metadata | yes | Medium | replay and provenance |
| `evaluator` | task manifest | full evaluator spec, including expected/gold references | yes | High | annotation-only supervision; leakage risk |
| setup requirements | task manifest | structured object | yes | High | environment reconstruction |
| mode, seed, repetition | runner | scalar fields | yes | High | experiment grouping |
| `task_graph.json` | compiler/manifest | node list + graph | yes | High | DAG and dependency supervision |
| `result.json.status` | `EpisodeRunner` | `completed`, `max_steps`, `repair_failed`, etc. | yes | High | termination label |
| `success`, `environment_score` | final evaluator | bool + float | yes if evaluation runs | High but coarse | final outcome |
| evaluator details | adapter returns `EvaluationResult.details` | only task id currently | **not written** | None | local condition labels are lost |
| final `task_state` | runner | serialized nodes | yes | High for runtime state | milestone labels, subject to Guard errors |
| fault/injection fields | controlled experiments | lists, root metrics | conditional | High as annotation | synthetic-fault labels; never model input |
| aggregate verification/replan/repair metrics | runner | counts/rates | yes | High as aggregates | experiment analysis |
| `error` | runner | final error string/null | yes | Medium | final failure diagnosis only |

### `trajectory.jsonl`

One row is written only after `env.step()` and subsequent logic reach `EpisodeLogger.log_step()`.

| Field | Source | Type / real example | Every logged transition | Reliability | Training value |
|---|---|---|---|---|---|
| `step` | runner loop | integer | yes | High | join key inside episode |
| timestamp | none | absent | no | None | ordering/duration unavailable here |
| `task_state_before` | `VerifiedTaskState.serialize()` | full node map | yes | High | state supervision |
| `executor_proposal` | parsed `ActionProposal` | id, intent, expected effect, action, observability, done/finish | yes | High for parsed form | policy/verification input |
| raw executor prompt/response/reasoning | model response | absent | no | None | irrecoverable model behavior |
| `injected_fault`, `failure_exposure` | injector | object/null | yes | High | controlled annotation only |
| `executed_action` | runner | generic action after injection, before OSWorld conversion | yes | Medium | executed intent; not exact backend command |
| backend-converted action | `convert_action()` | absent | no | None | exact OSWorld command lost |
| action execution success/exception/duration | backend | absent | no | None | separates policy/parser/environment failures |
| `execution_phase`, `repair_phase`, `repair_cycle_id` | runner | strings/id/null | yes | High | repair sequence slicing |
| `observation_before/after` | `Observation.to_dict()` | object | yes | High for screenshot, low for optional state | transition pair |
| `guard_result` | parsed Guard output | object/null | checkpoint only | High for parsed result | verifier labels/evidence |
| `state_updates` | Guard result | list | checkpoint only | High | milestone changes |
| `repair_context` | active repair/request | object/null | yes | Medium | repair conditioning |
| `interventions` | current transition events | list | yes | Medium | incomplete intervention record |

`task_state_after` is not explicitly stored here. It can often be recovered from the next row's `task_state_before`, or from `execution_trace.jsonl`, but not reliably for the final row or for decisions occurring between logged environment actions.

### Observation and screenshots

| Field | Code support | Real v10 output | Reliability | Training value |
|---|---|---|---|---|
| pre-action screenshot | PNG bytes saved as `screenshots/step_NNN_before.png` | present for every trajectory row | High | primary visual state `S_t` |
| post-action screenshot | `step_NNN_after.png` | present for every trajectory row | High | primary visual state `S_(t+1)` |
| JSON screenshot path | absolute server path | present | High on original server; not portable | image join |
| image uniqueness | episode directory + step + role | no overwrite observed | High | stable identity in place |
| resolution/compression | raw backend PNG bytes | 1920x1080 PNG in inspected data | High | no logger-side resize/re-encode |
| content hash/dimensions/byte size | not recorded | absent | None | dedupe/integrity missing |
| Guard image role | Guard receives before+after | no separate mapping | Medium | infer by transition join only |
| reground image | used transiently | not separately identified | Low | grounder training unavailable |
| structured state | supported | null in all inspected rows | Low | currently unavailable |
| accessibility/UI tree | supported | null; disabled in config | Low | currently unavailable |
| OCR/visible text | supported | null | Low | currently unavailable |
| active app/window | supported | null | Low | currently unavailable |
| cursor/focus | no dedicated field | absent | None | cannot distinguish focus failures |
| transition metadata | reward/done/info/instruction | present inside metadata when backend supplies it | Medium | environment hints, not normalized |

Screenshots dominate storage. The inspected episodes used 6 MB, 14 MB, and 82 MB respectively; JSON and model text are comparatively small. Consecutive `before` and prior `after` screenshots are often duplicates, but both are stored.

### `executor_events.jsonl`

| Field | Source | Presence | Reliability | Value |
|---|---|---|---|---|
| `step` | runner | logged transitions only | High | join key |
| `proposal` | parsed executor output | logged transitions only | High | parsed policy output |
| exact model input/history/image IDs | executor | absent | None | cannot reproduce input |
| raw response/reasoning | model client | absent | None | cannot train parser/reasoning or audit failure |
| parse attempt/retry/error | executor | absent | None | parser failures conflated with episode failure |
| model/latency/tokens per call | model client | absent | None | per-example filtering/cost unavailable |

Finish proposals are not written because the finish branch exits or `continue`s before `log_step()`.

### `guard_events.jsonl`

Actual parsed fields include:

| Field group | Fields | Presence / reliability | Training value |
|---|---|---|---|
| judgement | `judgement`, `approved` | checkpoint rows; High | VALID/FAILED/UNKNOWN proxy |
| explanation | `reason`, `unknown_reason` | usually present; Medium-High | diagnostic text |
| evidence gap | `missing_evidence`, `available_evidence`, `unavailable_evidence`, attempted/recommended strategy, source-switch flags | often present on UNKNOWN; Medium | UNKNOWN taxonomy and next action |
| progress | `progress_updates`, `state_updates` | conditional; High after parser filtering | task-state supervision |
| failure | `fault_root`, `fault_type` | contradictions only; Medium | node-level localization |
| repair | parsed repair object | conditional | repair proposal |
| target | `verification_target` | conditional | verification objective |
| contract | `active_contract_id` | conditional | join to contract history |

Missing for every real Guard call:

- exact serialized prompt/context and exact history window;
- explicit image IDs/hashes used by that call;
- raw response and reasoning content;
- parser attempts, rejected outputs and normalization before/after;
- backend identity (rule, MLLM, hybrid) per decision;
- model/version, latency and token usage per call;
- calibrated confidence;
- suspected **root step** (only a node id may be present);
- direct dependency violation field;
- explicit link from recommendation to the intervention that was executed;
- finish-verification calls that do not reach transition logging.

### `execution_trace.jsonl`

| Field group | Fields | Coverage | Reliability / value |
|---|---|---|---|
| identity/time | `step_id`, UTC `timestamp`, `active_node_id` | completed environment transitions | High |
| intent/action | executor intent, proposed action, executed generic action, expected effect, observability | same | High for parsed data |
| observations | before/after summaries | same | Medium; summaries omit screenshot path |
| state | full `state_before`, `state_after`, trust snapshot | same | High; best current state supervision source |
| checkpoint | reason, kind, Guard judgement | checkpoints | High |
| contracts/evidence | contract id/version, sources available/used, verifier id | conditional | Medium; no full call input |
| UNKNOWN debt | information gain, unknown reason, verification debt | conditional | Medium-High |
| phase/done | execution phase, subgoal done | same | High |

The trace collector keeps pending entries in memory until a transition completes. An exception can leave the pending decision unpersisted. `TraceStorage` also keeps only its configured last `max_entries` if an episode exceeds that limit.

### Adaptive verification, replan, repair

| File | Actual fields | What is missing |
|---|---|---|
| `contract_events.jsonl` | node, old/new contract IDs, trigger, previous reason, semantic/evidence/verifier changes, accepted/rejection, step | complete old/new contract payload, grounding prompt/response, candidate contracts, call usage |
| `plan_patch_events.jsonl` | step, problem node, accepted patch, preserved nodes, replacement mapping, active repair | replan request, exact before graph, raw response, rejected attempts, exception event, per-call usage, later outcome |
| `repair_events.jsonl` | step and parsed repair: root, type, goal, preserve/stale/reverify nodes, confidence, cycle id | triggering evidence bundle, raw response, action list as a first-class cycle, completion/outcome label |
| trajectory intervention list | repair request, finish rejection, verification request on associated logged transitions | unified decision-before/executed/result/outcome lifecycle; finish-only events can be lost |
| `result.json` metrics | debt/source switch/contract/replan/repair counts and rates | event-level causal links |

Local replan “success” currently means the patch was generated, validated, and applied. It does **not** mean the task or repaired node later succeeded. This metric must not be used as an intervention outcome label without hindsight derivation.

### Model usage

`model_usage.json` contains aggregate calls, tokens, latency, parser counters, and verification calls by role. It does not contain one record per call. In inspected Luna episodes, token counts can be zero because provider usage fields do not always match the parser's expected schema. Thus aggregate token values are not a reliable per-sample quality or cost signal.

The configuration contains `evaluation.save_model_responses: true`, but the runner does not wire this flag into Executor, Guard, Grounder, or Replanner persistence. Auto-DAG generation is the exception: it can write `dag_generation_raw_response.json`.

## Can the current output recover `S_t -> A_t -> S_(t+1)`?

**For a normally completed GUI action: partially.**

- `S_t`: pre-action screenshot and runtime task state exist.
- `A_t`: parsed executor proposal and generic action passed toward the adapter exist.
- `S_(t+1)`: post-action screenshot and trace `state_after` exist.

What is missing is the exact model input/output, exact backend-converted action, an execution receipt, action duration, exception, active window/focus, and nonvisual state. A pixel-identical screenshot therefore cannot distinguish “valid action with no visible effect,” “wrong focus,” “backend ignored the action,” and “execution failed.”

**For the complete decision sequence: no.** Finish decisions, failed parses, failed model calls, failed environment calls, and some adaptive decisions have no row.

## 3. Training Readiness Matrix

| Training task | Rating | Reason |
|---|---|---|
| transition validity | **PARTIAL** | paired screenshots + parsed actions exist for successful environment calls; execution receipts, raw inputs/outputs and some transitions are missing |
| suspicious detection | **PARTIAL** | state/trace records suspicious statuses, trust and counts; first event/reason is not consistently a first-class event |
| failure detection | **PARTIAL** | contradictions and final score exist; evaluator condition details and unlabeled environment failures do not |
| UNKNOWN diagnosis | **PARTIAL** | reasons and structured evidence gaps are often strong; exact evidence bundle, raw reasoning and complete later resolution chain are absent |
| failure localization | **PARTIAL** | node root and trace history exist; earliest root step and authoritative local failure condition do not |
| task-state verification | **PARTIAL** | full before/after runtime state exists for logged transitions, but is Guard-derived and logical steps are missing |
| dependency corruption | **PARTIAL** | graph, statuses, stale/fail updates exist; no authoritative per-edge corruption label or evaluator decomposition |
| progress preservation | **PARTIAL** | final preservation metrics and state snapshots exist; natural failures lack ground truth and per-intervention preservation outcomes |
| intervention selection | **NOT READY** | recommendation, execution and outcome are scattered; rejected alternatives and complete intervention lifecycle are missing |
| repair learning | **PARTIAL** | repair request and repair-phase actions can be grouped; no complete input, raw proposal, per-cycle outcome or negative candidates |
| hindsight relabeling | **PARTIAL** | visual transitions can be relabeled approximately; evaluator details, raw model context and missing decisions cannot be recovered |

No category is marked READY because every intended task needs either complete model-visible inputs, a reliable outcome/evidence label, or complete event coverage. Current data can support exploratory or weakly supervised datasets, not a canonical training corpus without qualifications.

## UNKNOWN audit

Current UNKNOWN records are substantially better than a bare status. Real rows included a natural-language reason, `unknown_reason`, missing/available/unavailable evidence, attempted and recommended strategy, whether a new source is required, and whether the same contract applies.

However, the taxonomy is incomplete in practice:

- screenshot ambiguity and missing UI-tree/structured state are described in prose rather than guaranteed normalized codes;
- `attempted_strategy` can be null or normalized from a free-form raw value;
- environment unavailable, verifier unsupported, specification insufficient, model uncertainty, and action-effect unobservable are not guaranteed mutually exclusive categories;
- the exact evidence images and exact prompt used are inferred by step rather than bound by immutable IDs;
- later continue/reground/replan/repair events are spread across trace, contract, patch and result files;
- no field closes an UNKNOWN with `resolved_as = valid|failed|genuinely_unknown` and supporting evidence.

Existing UNKNOWNs can be heuristically relabeled by joining later task-state changes, contradictions, contract events, patches and final outcome. They cannot be authoritatively relabeled in many final-failure episodes because the final evaluator exposes only 0/1 and screenshots may not reveal persistence or hidden application state.

## Natural-failure usability

A failed episode can currently yield a weak sequence such as:

```text
logged transition -> Guard judgement -> runtime node status -> eventual episode score
```

It cannot reliably yield the desired authoritative sequence:

```text
VALID -> first SUSPICIOUS -> first CONFIRMED FAILURE -> DOWNSTREAM
```

The reasons are:

1. `first suspicious` is a runtime state mutation/debt consequence, while `first confirmed failure` is a Guard contradiction/root prediction. They are not emitted into one normalized event stream.
2. `guard_first_detection_step` is derived from `root_predictions`; it is not necessarily the earliest corrupted transition.
3. A `fault_root` is a DAG node, not a transition step.
4. Final evaluator condition details are dropped, so downstream/local condition failures cannot be grounded authoritatively.
5. Intermediate evaluator snapshots are not run or saved.
6. Missing logical rows prevent a complete timeline.

Partial milestone success remains recoverable from `execution_trace.state_after` and final `task_state`, but these are system beliefs, not independent ground truth.

## Leakage and metadata separation

`task.json` currently mixes three classes of information:

| Class | Examples | Rule for future datasets |
|---|---|---|
| `model_input` | instruction, model-visible history, screenshot, task state supplied to model, active repair context | safe only if it was actually passed at that time |
| `annotation_metadata` | full evaluator definition, expected/gold artifact references, synthetic fault specification, hidden setup facts | never feed at inference; use only to derive labels |
| `outcome_metadata` | final score/success, later Guard decisions, future screenshots, termination reason | hindsight labels only; never enter causal model input |

The current runtime does not appear to pass the evaluator definition into Executor or Guard prompts; it passes instruction, runtime state, observations and contexts. Nevertheless, a naive dataset builder that joins all of `task.json` would leak evaluator/gold information. Schema v1 must enforce this boundary structurally.

## 4. Missing Critical Fields

### P0: irrecoverable if not captured at runtime

1. **One append-only event for every logical decision and model invocation**, including finish, parse failure, API failure, retry and environment exception.
2. **Exact model request**: rendered messages, image artifact IDs in order, response schema, provider/model, prompt version and generation settings.
3. **Raw model response per attempt**, including reasoning when returned, parsed value, parse error and retry relationship.
4. **Execution receipt**: parsed action, backend-converted action, start/end time, success, exception, and raw environment return metadata.
5. **Final evaluator details**, including each evaluator component/condition, raw score, produced artifact references and evaluator exception.
6. **Immutable evidence manifest** with content hash, role, MIME type, dimensions, byte size, relative path and producer call/event.
7. **Complete intervention lifecycle**: proposed decision, selected decision, execution started/completed, result, and hindsight outcome.
8. **Grounding/replan/repair raw calls**, including requests, candidate/rejected outputs and accepted normalized output.

### P1: materially improves training quality

1. Explicit `task_state_before` and `task_state_after` for every logical event, plus a normalized state delta.
2. Normalized suspicious/failure timeline: `last_verified_step`, `first_suspicious_step`, `first_confirmed_failure_step`, root node and root step kept separate.
3. Stable UNKNOWN taxonomy and explicit resolution records linked to later evidence.
4. Accessibility tree, active window/application, focused element and cursor state where OSWorld exposes them.
5. Contract snapshots, not only old/new IDs, for every accepted or rejected grounding event.
6. Per-call tokens, latency, status code, retry count and parser/normalizer changes.
7. Repair-cycle and replan outcome records tied to affected nodes and final evaluator conditions.
8. Relative artifact paths plus content-addressed IDs to make datasets portable.

### P2: analysis and debugging

1. Screenshot deduplication links (`same_as_artifact_id`) and optional perceptual hashes.
2. Host resource/VM health snapshots and network/API timing breakdown.
3. Explicit code locations/config keys that produced each event schema version.
4. Optional OCR text and compact UI-tree diffs as processed artifacts.
5. Human annotation history and label agreement metadata.

## 5. StateGuard Training-Ready Episode Schema v1

The recommended representation is an episode manifest plus append-only events and content-addressed artifacts. Labels remain optional and versioned so raw rollout evidence is never overwritten.

```json
{
  "schema_version": "stateguard.training_episode.v1",
  "episode": {
    "episode_id": "task_uuid--stateguard--seed-20260908",
    "task_id": "task_uuid",
    "model_input": {
      "instruction": "...",
      "application": "chrome"
    },
    "annotation_metadata": {
      "evaluator_definition_ref": "annotations/evaluator.json",
      "fault_spec_ref": null,
      "task_config_ref": "raw/task_config.json"
    },
    "environment": {
      "benchmark": "OSWorld-Verified",
      "provider": "docker",
      "osworld_git_commit": "...",
      "screen": {"width": 1920, "height": 1080},
      "seed": 20260908
    },
    "models": {
      "executor": {"provider": "...", "model": "...", "prompt_version": "..."},
      "guard": {"provider": "...", "model": "...", "prompt_version": "..."},
      "grounder": {"provider": "...", "model": "..."},
      "replanner": {"provider": "...", "model": "..."}
    },
    "final_outcome": {
      "status": "task_failed",
      "success": false,
      "score": 0.0,
      "termination_reason": "max_steps",
      "evaluator_call_id": "eval-0001"
    }
  },
  "artifacts": {
    "img-sha256-abc": {
      "relative_path": "raw/artifacts/ab/abc.png",
      "sha256": "abc...",
      "mime_type": "image/png",
      "width": 1920,
      "height": 1080,
      "bytes": 925431,
      "role": "post_action_screenshot",
      "producer_event_id": "evt-0008"
    }
  },
  "events": [
    {
      "event_id": "evt-0007",
      "sequence_id": 7,
      "step_id": 3,
      "timestamp_start": "2026-09-21T01:02:03.000Z",
      "timestamp_end": "2026-09-21T01:02:08.000Z",
      "event_type": "environment_transition",
      "phase": "normal",
      "model_input": {
        "observation_before": {
          "screenshot_id": "img-sha256-before",
          "accessibility_tree_id": null,
          "structured_state": null,
          "active_window": null,
          "focused_element": null
        },
        "task_state_before": {"nodes": {}},
        "history_event_ids": ["evt-0001", "evt-0004"],
        "repair_context": null
      },
      "executor": {
        "call_id": "call-executor-0003",
        "request_ref": "raw/model_calls/call-executor-0003.request.json",
        "response_ref": "raw/model_calls/call-executor-0003.response.json",
        "raw_text": "{...}",
        "reasoning": null,
        "parsed_proposal": {"subgoal_id": "S1", "action": {"type": "click"}},
        "parse_status": "ok",
        "parse_attempt": 1
      },
      "execution": {
        "planned_action": {"type": "click", "x": 420, "y": 310},
        "backend_action": {"script": "pyautogui.click(806, 335)"},
        "success": true,
        "exception": null,
        "duration_seconds": 1.23,
        "raw_result_ref": "raw/environment/evt-0007.result.json"
      },
      "observation_after": {
        "screenshot_id": "img-sha256-abc",
        "accessibility_tree_id": null,
        "structured_state": null,
        "active_window": null,
        "focused_element": null
      },
      "guard": {
        "invoked": true,
        "call_id": "call-guard-0002",
        "backend": "mllm",
        "request_ref": "raw/model_calls/call-guard-0002.request.json",
        "response_ref": "raw/model_calls/call-guard-0002.response.json",
        "evidence_artifact_ids": ["img-sha256-before", "img-sha256-abc"],
        "judgement": "unknown",
        "confidence": null,
        "reason": "...",
        "unknown_reason": "need_more_evidence",
        "evidence_gap": {"missing_evidence": ["..."]},
        "suspected_root_node": null,
        "suspected_root_step": null,
        "recommendation": "reground"
      },
      "task_state": {
        "before": {"nodes": {}},
        "after": {"nodes": {}},
        "delta": {
          "newly_achieved": [],
          "preserved": ["S0"],
          "broken": [],
          "suspicious": ["S1"],
          "unknown": ["S1"]
        }
      },
      "intervention": {
        "decision_id": "decision-0002",
        "proposed": "reground",
        "selected": "reground",
        "executed": true,
        "result_event_id": "evt-0009",
        "immediate_result": "contract_revised",
        "hindsight_outcome": null
      },
      "annotation": {
        "transition_label": null,
        "failure_type": null,
        "annotation_source": null,
        "annotation_confidence": null,
        "label_version": null
      }
    }
  ],
  "model_calls": [
    {
      "call_id": "call-guard-0002",
      "role": "guard",
      "provider": "opencode",
      "model": "gpt-5.6-luna",
      "started_at": "...",
      "latency_seconds": 20.1,
      "usage": {"prompt_tokens": 0, "completion_tokens": 0},
      "attempt": 1,
      "status": "ok",
      "request_ref": "raw/model_calls/call-guard-0002.request.json",
      "response_ref": "raw/model_calls/call-guard-0002.response.json"
    }
  ],
  "evaluator_calls": [
    {
      "call_id": "eval-0001",
      "phase": "final",
      "score": 0.0,
      "success": false,
      "condition_results": [],
      "raw_details_ref": "annotations/evaluator_result.json",
      "exception": null
    }
  ]
}
```

Recommended storage layers:

```text
episode/
  episode.json                 # manifest and references
  events.jsonl                 # append-only causal timeline
  raw/
    artifacts/                 # screenshots, UI trees, produced files
    model_calls/               # exact requests and raw responses
    environment/               # action receipts/raw returns
  processed/
    observation_summaries.jsonl
    state_deltas.jsonl
  annotations/
    evaluator.json
    evaluator_result.json
    labels-v1.jsonl
```

Raw data is immutable. Processed features and labels are regenerable and versioned.

## 6. Required Code Changes

| File / class / function | Current behavior | Required change |
|---|---|---|
| `stateguard/models/base.py::ModelResponse` | response object has raw response but no stable call identity/request | add `call_id`, request envelope, attempts, timestamps/status; preserve provider raw payload |
| `stateguard/models/openai_compatible.py::generate()` and `openai_responses.py::generate()` | returns response to caller | emit or return a complete serializable call record for every attempt, including failures |
| `stateguard/executor/mllm_executor.py::MLLMExecutor.act()` | aggregates usage and returns parsed proposal | expose call records, rendered messages, image refs, raw text, parse attempts/errors |
| `stateguard/guard/backends/mllm_backend.py::MLLMBackend.verify()` and `diagnose_candidates()` | builds rich prompt transiently; retains parsed result and aggregates | persist exact prompt, image refs, candidate chain, raw attempts, parser changes and final parsed output |
| `stateguard/verification/grounder.py::MLLMGroundingProvider.ground()` | transient grounding request/response | persist request, old contract snapshot, candidates, raw response and accepted contract |
| `stateguard/planning/runtime_replanner.py::MLLMPlanPatchProvider.replan()` | returns accepted patch | persist `LocalReplanRequest`, all attempts, parse/validation errors and raw responses |
| `stateguard/runtime/episode_runner.py::run()` | finish/parse/model/env failures can exit before step logging | create a decision event before model/action execution and finalize it on every branch/exception |
| `EpisodeRunner.attempt_local_replan()` | logs only an accepted patch; exceptions become final error | log requested/attempted/rejected/applied events and later outcome links |
| `EpisodeRunner.handle_adaptive_result()` / intervention branches | mutates state and counters | write normalized decision and intervention lifecycle events |
| `integrations/osworld/action_converter.py::convert_action()` and `OSWorldAdapter.step()` | converted action is transient | return/log backend action plus execution timestamps, success, exception and raw result metadata |
| `integrations/osworld/observation_converter.py::convert_observation()` | supports optional fields but actual config leaves them null | retain active app/window/focus/UI tree when available; record capability and missing reason |
| `integrations/osworld/adapter.py::EvaluationResult` + `EpisodeRunner.run()` final evaluate block | `details` exists but runner drops it | persist complete evaluator result and per-condition details; catch/log evaluator exceptions |
| `experiments/poc/logging.py::EpisodeLogger` | several separate files, action-transition-centered | add schema version, artifact manifest, model-call writer and append-only event writer; keep legacy files |
| `EpisodeLogger._observation()` | writes PNG and absolute path | add relative path, SHA-256, dimensions, bytes, role and dedupe link |
| `experiments/poc/runner.py::run_experiment()` | `save_model_responses` is not connected | pass explicit logging policy/callback to all model-backed components and record whether each channel is enabled |
| `stateguard/trace/storage.py::TraceStorage` | rewrites a bounded recent window | append durable events or flush evicted entries; do not silently lose long-episode history |

The cleanest implementation is a small `EventSink`/`ModelCallRecorder` interface injected into components. It avoids coupling model clients to filesystem paths while ensuring every caller records the same envelope.

## 7. Migration Plan

### Phase 0: freeze and document legacy

- Declare current output as `legacy-v0`.
- Record the audit's repository commit and run paths.
- Do not rewrite existing evidence in place.

### Phase 1: dual-write

- Keep all current files unchanged for dashboards and experiment scripts.
- Add `schema_version`, `events.jsonl`, `artifact_manifest.jsonl`, `model_calls.jsonl`, and `evaluator_result.json`.
- Use stable event/call/artifact IDs to join legacy rows to v1 records.
- Validate that legacy metrics computed from v1 match existing summaries.

### Phase 2: legacy converter

Create `scripts/migrate_training_episode_v0_to_v1.py` that:

- reads task, graph, trajectory, trace, Guard, contracts, patches, repairs and result;
- builds v1 transition events for existing trajectory rows;
- hashes and inventories screenshots without copying when possible;
- explicitly marks unavailable fields with `availability: "not_recorded_legacy"` rather than inventing values;
- derives tentative state deltas and UNKNOWN outcome links as `annotation_source: "heuristic_v0_migration"`;
- emits a migration report with row gaps and unresolved joins.

### Phase 3: training views

- Generate Dataset A-D views only from v1 events.
- Keep model inputs, annotations and future outcomes in separate namespaces.
- Version all derived labels and retain annotator/model provenance.

### Phase 4: retire legacy writers

After parity tests and at least one canary run, make v1 canonical. Legacy JSONL may then be generated as a compatibility view rather than independently written.

### Recoverability of old experiments

**Recoverable**

- task instruction, task/evaluator specification, graph/dependencies;
- parsed action proposal and generic executed action for logged transitions;
- paired screenshots for logged transitions;
- parsed Guard judgement/reason/evidence gap for logged Guard checkpoints;
- runtime state before/after through trajectory + trace joins;
- accepted contracts, patches, repairs and aggregate final outcome;
- screenshot hashes, dimensions, relative dataset paths and deduplication metadata.

**Partially recoverable**

- `task_state_after` for trajectory rows, by joining trace/next row;
- first suspicious/confirmed/downstream sequence, by heuristic state/event analysis;
- UNKNOWN later outcome, when later visual/state evidence is decisive;
- intervention outcome, using later state and final score as weak hindsight labels;
- exact history content, approximately reconstructed from prior parsed rows;
- evaluator rerun only if the exact final VM/artifact state still exists, which normal reset usually invalidates.

**Irrecoverable**

- exact model prompts as sent, raw responses/reasoning, rejected attempts and parse errors;
- per-call model usage/latency/status/retry chain;
- finish proposals and finish Guard calls not logged as transitions;
- decisions lost before environment-step completion;
- exact backend-converted action and action execution exceptions/duration;
- evaluator per-condition result from the original final state;
- transient grounder/replanner candidate outputs and rejected contracts/patches;
- UI tree, focus, active window, structured state or OCR that the backend did not collect;
- authoritative earliest failure step when neither evidence nor evaluator decomposition captured it.

## Storage-cost assessment

- Screenshots are the dominant cost by a wide margin. Raw model requests/responses and event JSON are normally small relative to 1920x1080 PNG sequences.
- Preserve model text in full. The storage saved by dropping it is negligible compared with the loss of training provenance.
- Enable accessibility trees when technically stable, but store them as compressed content-addressed artifacts and optionally record diffs. Repeated full trees can otherwise become material.
- Deduplicate identical screenshots by SHA-256 while retaining logical before/after references. This preserves semantics without duplicate bytes.
- Keep original images; derive resized/training-ready images under `processed/`.
- Add retention controls only for debug duplicates, never for causal raw evidence.

## 8. Minimal Patch Recommendation

If only a small patch is allowed before the next large run, implement these eight changes:

1. Add an append-only `events.jsonl` row at the start and end of **every** logical step, including finish, parse/model failure and environment exception.
2. Persist every model call's exact messages, ordered image artifact IDs, raw response, parsed response, parse error, provider/model, attempt, latency and usage.
3. Write an explicit execution receipt containing planned action, backend-converted action, success/exception, raw return metadata and duration.
4. Persist `evaluation.details` and evaluator exceptions in `evaluator_result.json`; retain condition-level results whenever OSWorld exposes them.
5. Add an artifact manifest with relative path, SHA-256, role, dimensions, byte size and producing event/call for every screenshot or UI-tree artifact.
6. Write `task_state_before`, `task_state_after`, and normalized delta for every event, including finish and adaptive-only events.
7. Normalize interventions into `decision -> execution -> immediate result -> hindsight outcome`, with stable IDs linking reground/retry/replan/repair.
8. Wire `evaluation.save_model_responses` into all model-backed components and test that turning it on creates non-empty Executor, Guard, Grounder and Replanner call records.

These changes are small compared with another OSWorld rollout campaign and protect the fields that cannot be reconstructed later. Label generation, confidence calibration, OCR, and full training exporters can wait; raw evidence capture cannot.
