# StateGuard v3 — Trust + Trace + Suspicion 交接手册

> 供下一位 coding agent 实现 v3（Execution Trace Memory + State Trust Management
> + Suspicion Lifecycle + Causal Diagnosis + Minimal Repair）使用。不重写 core。

## 0. 当前状态（交接起点）

- 分支：`feature/hybrid-verification`
- HEAD commit：`a682983`（工作树干净，**149 tests passed**）
- 历史 commit：`13dc1a2`（hybrid 核心）→ `cf3fda3`（certified_clean+replay）→
  `def7e81`（consistency fail-open 修复）→ `d154230`（总结）→ `a682983`（fault 报告）
- Round 2.5 结论：**REVISE**。overhead 已解决（Guard calls 22→13），clean 3/3，
  但 **causal localization 弱（earlier replay 1/6，hybrid fault 定位 0/6）**，恢复 3/6 < sparse 4/6。

### v3 起点要求（Phase 0）
```bash
cd /data/research/projects/StateGuard
git status            # 应为 clean
git log -1 --oneline  # a682983
.venv-stateguard/bin/pytest -q   # 149 passed
git checkout -b feature/trust-trace-stateguard
```
记录 base commit 到 `/data/research/stateguard_runs/round2_5/`（沿用 round2_5 目录）。

---

## 1. 代码地图（v3 各 Phase 的落点）

### Phase 1 — Execution Trace Memory（新增 `stateguard/trace/`）
- **新增**：`stateguard/trace/{__init__,models,collector,storage,summarizer}.py`
  - `ExecutionTraceEntry`：step_id, timestamp, active_node_id, executor_intent, action(type/args),
    expected_effect, observation_before/after_summary, state_before/after (node status snapshot),
    checkpoint_reason, trust_snapshot
- **插入点**（只读 hook，不改 Executor）：
  - 在 `stateguard/runtime/episode_runner.py`：executor 产出 proposal 后 + `env.step()` 返回 after 后，
    各调一次 `trace_collector.record_step(...)`
  - 参考现有每步数据来源：`experiments/poc/logging.py::EpisodeLogger.log_step`（trajectory.jsonl 已含
    proposal/executed_action/obs_before/obs_after/guard_result——Trace 可对齐这些字段）
- **已有轻量版**：`stateguard/runtime/history.py::ActionHistory`（limit=10，供 prompt 用 recent()）。
  Trace 是它的超集/替代，不要破坏 history。
- **存储**：`trace.storage` 落盘可复用 `RunLogger.write`（`experiments/poc/logging.py`），
  max_entries=200、keep_recent_images=10 放 config。

### Phase 2-4 — Trust Management + Suspicion Lifecycle + Trust Score
- **`stateguard/core/schema.py`**：
  - `NodeStatus` enum 增加 `SUSPICIOUS = "suspicious"`（在 VERIFIED 与 FAILED 之间）
  - `TaskNode` 增加 `trust_score: float = 1.0`
- **`stateguard/core/task_state.py`**：
  - `_ALLOWED` 转移表增加合法边：`VERIFIED -> SUSPICIOUS`、`SUSPICIOUS -> FAILED/ACTIVE/STALE`
  - 新增 `mark_suspicious(node_id)`（可带 reason/step 记录）
- **`stateguard/runtime/checkpoint_policy.py`**：当前 `evaluate()` 已返回
  `CheckpointDecision(should_verify, reason, target_node, checkpoint_kind)`；suspicion 弱矛盾信号可在此产生
- **`stateguard/runtime/episode_runner.py`**：把当前的 blunt consistency fail-open（在
  `stateguard/guard/state_guard.py` 的 model-contradicted 分支）替换为 suspicion 生命周期——
  弱矛盾 → SUSPICIOUS（trust -= 0.2）；满足条件 A(subgoal_done 且状态仍假)/B(finish 未决)/
  C(依赖阻塞) 之一才 → FAILED（trust=0）

### Phase 5-7 — Guard Causal Diagnosis（两阶段）+ prompt + trace replay
- **现有基础（不要重写）**：
  - `stateguard/guard/localization.py::causal_root()` 已经是 Python 端"最早祖先"选择
    （规则：直接矛盾 → 最早非 VERIFIED → 观察节点）。Stage 2 的 per-candidate YES/NO 可喂给它或新函数。
  - `stateguard/guard/state_guard.py::verify_transition` 的 model-verdict 分支（~line 66-90）是改造点
  - `stateguard/guard/backends/mllm_backend.py` 已含 `causal_chain` + `causal_policy` + consistency_policy；
    新 prompt 在此 diff
- **两阶段**：
  1. Python 生成 candidate = `graph.ancestors(active) + [active]`（runner 里已有此逻辑）
  2. Guard 逐个输出 `{"S1":"YES","S2":"NO",...}`（信任判断），Python 选最早 NO 为 root
- **`causal_trace_window()`**：新函数，输入 failed node + ancestors + DAG，输出相关 transition 子集
  （Trace 提供），不要给 Guard 全量 history
- **离线 replay 复用**：`scripts/replay_earlier_root.py`、`scripts/replay_earlier_batch.py`
  （当前对 108 矩阵 earlier 集重放，目标 **First Root Accuracy >= 4/6**，当前 1/6）

### Phase 8-9 — Repair Pipeline + Budget 分离
- **`stateguard/guard/repair.py`**：`propagate_failure`（root→FAILED, descendants→STALE）、
  `build_repair_request`（preserve/reverify）——保持，加 repair phase 标注
- **`stateguard/runtime/repair_loop.py`**：`RepairBudget` 目前只按 fault_root 限 cycle（默认3）。
  增加 `max_actions_per_cycle`（默认20）独立预算
- **`stateguard/runtime/episode_runner.py`**：repair 时记录 phase（RESTORE_ROOT / VERIFY_DESCENDANTS /
  REPAIR_INVALID_DESCENDANTS）到 history/log，不重跑整条轨迹
- **config**：`experiments/poc/config.py` 是通用 loader；在各 smoke config yaml 加
  ```yaml
  repair: {max_cycles: 3, max_actions_per_cycle: 20}
  ```
- **ablation**：budget x1 / x1.5 / x2，判断 repair 失败是 method 还是 budget 限制
- **已知案**：File WRONG_VALUE 定位对（S1, acc=1.0）但 34 个 repair action 4 cycle 耗尽仍失败——
  见 `/data/research/stateguard_runs/round2_5/file_wrong_value_forensic.md`

### Phase 10 — Finish 信号
- 已在 `stateguard/runtime/episode_runner.py`：`premature_finish_count` + 规则反馈已实现
  （finish 被拒 ≥3 次给 executor 结构化提示，不调 Guard）。verify_finish 保持 rule-based。

### Phase 11 — Fault 校准
- **现有**：`configs/poc/selected_tasks_ready.yaml`（12 tasks 带 faults）、
  `configs/faults/osworld/*.yaml`（24 specs）、`experiments/poc/manifest_validation.py`、
  `scripts/validate_fault_manifest.py`
- **待办**：7 个无真实 trajectory 任务先跑 clean trajectory catalog（用
  `configs/poc/osworld_sparse_smoke_b.yaml` = manual+frontier+sparse、faults disabled），
  记录真实 action_type，改 fault trigger 为 semantic（subgoal+action_type+occurrence），
  目标 injection validity >=95%（当前 stateguard 0.667）
- 输出：`/data/research/stateguard_runs/round2_5/clean_trajectory_catalog.json`

### Phase 12 — Evaluation
- Offline replay：`scripts/replay_earlier_batch.py`（>=4/6）
- Smoke：`configs/poc/osworld_sparse_smoke_{a,b,h}.yaml` + 新建 Trust+Trace 配置；
  输出对比 `scripts/compare_smoke.py`
- Round 3 108：`configs/poc/osworld_poc.yaml`（12 tasks × 3 scenarios × 3 modes）、
  `scripts/run_poc_matrix.py`（--resume）

---

## 2. 关键集成点 / 坑

1. **`_ALLOWED` 转移表**（task_state.py）是硬门：加 SUSPICIOUS 必须同步改这里，否则 `mark_suspicious` 抛 IllegalTransitionError。
2. **consistency fail-open 是当前定位弱的主因**：在 `state_guard.py` model-contradicted 分支
   （`if checkpoint_kind == "consistency" and root == node.node_id: return UNKNOWN`）——
   v3 的 suspicion 生命周期应替代这个 blunt 逻辑，但保留其防假矛盾的作用（用 suspicion+confirm 替代直接降级）。
3. **Hybrid 三层**在 `checkpoint_policy.py`：Layer A 强制 / Layer B causal-risk(HIGH 2步,MEDIUM 5步) / Layer C cooldown(2步)。NodeRisk 已实现。
4. **Guard 已收到 causal_chain**（mllm_backend），但 Qwen3.7 仍输出 first-visible-contradiction —— 两阶段 YES/NO 判断是主攻方向。
5. **metrics 计分**在 `experiments/poc/metrics.py::episode_metrics`（affected_set_f1 等）；新增字段要同步 `experiments/poc/logging.py::RunLogger.summarize` 与 `EpisodeResult`（episode_runner.py）。
6. **执行环境**：真实 run 必须用 OSWorld venv
   ```bash
   PYTHONPATH=/data/research/projects/StateGuard:/data/research/projects/OSWorld-StateGuard
   /data/research/ui-mopd-repro/repos/OSWorld/.venv/bin/python scripts/run_poc_osworld.py ...
   ```
   帮助脚本：`/data/research/stateguard_runs/run_smoke.sh`（repo 外，保持工作树干净）。
7. **Guard API 波动**：qwen3.7-plus 偶发 503；跑前先 curl 探测（.env.secrets 有 key）。

---

## 3. 必须新增的测试（v3）

- Trace：`test_trace_records_every_action`、`test_trace_contains_state_transition`、
  `test_trace_window_selection`
- Suspicion：`test_verified_to_suspicious`、`test_suspicious_requires_confirmation`、
  `test_suspicious_not_immediate_repair`
- Diagnosis：`test_candidate_root_generation`、`test_earliest_failed_ancestor_selection`、
  `test_downstream_failure_not_root`
- Repair：`test_restore_then_revalidate`、`test_keep_valid_descendants`、
  `test_repair_budget_logging`
- 现有测试全部保持 PASS（149 + 新 = 目标）

---

## 4. 最终交付清单（v3）

1. 修改/新增文件列表
2. Trace schema
3. Suspicious lifecycle 图
4. Trust score 规则
5. Guard prompt diff
6. Candidate root diagnosis 逻辑
7. Repair pipeline 变化
8. 新测试结果
9. Earlier corruption replay accuracy（>=4/6 才 GO）
10. Smoke 对比（Sparse/Hybrid/Trust+Trace）
11. Round 3 GO 判定 + frozen config + commit SHA
