# StateGuard v9 — 问题交接手册

> 供下一位 agent 接手。目标：修复 v9 36 矩阵暴露的问题，为无 Guard baseline 对比与
> 正式实验做准备。所有实验文件在 `/data/research`；尽量不占系统盘。

## 1. 当前状态

- 分支：`feature/trust-trace-stateguard`
- 最近 commit：`d1bbb9e`（v9 矩阵报告）、`6f5fdbe`（evidence_gap parser 修复）、
  `0626423`（premature-finish 预算修复）、另有 `mark_suspicious` 幂等修复（已提交）
- 工作树：clean；**218 tests passed**
- 36-episode 矩阵：完成，结果在 `/data/research/stateguard_runs/poc_stability_v9_matrix/`
- 汇总脚本：`scripts/report_v9_matrix.py`
- 实验 wrapper：`/data/research/stateguard_runs/run_smoke.sh`（repo 外，保持工作树干净）
- 真实运行环境：
  ```bash
  export PYTHONPATH=/data/research/projects/StateGuard:/data/research/projects/OSWorld-StateGuard
  set -a; source /data/research/projects/StateGuard/.env.secrets; set +a
  /data/research/ui-mopd-repro/repos/OSWorld/.venv/bin/python scripts/run_poc_osworld.py ...
  ```

## 2. 36 矩阵结果（基线事实）

- fault 注入 21/21（100%）
- first_root_acc 5/21（24%）——earlier 定位正确：030eeff7→S2、4127319a→S2
- fault 恢复 7/21；clean success 4/15
- 终止分布：completed 11 / **guard_parse_failed 10** / **plan_revision_failed 5** /
  max_steps 5 / repair_failed 3 / executor_parse_failed 1 / environment_failed 1
- guard_calls 327、executor_calls 1171、contracts 137、unknown_checkpoints 167、
  local_replan 5（**success 0**）

结论：v9 的 trace+suspicion 让**因果定位 claim 有了证据**（Round 2.5 缺失），
但任务成功率被两件事压住：**executor premature finish**（Qwen3.7 Plus 不完成多步
GUI 动作）和**框架层失败**（15/36）。

## 3. 问题清单（按优先级）

### P1. guard_parse_failed —— 10/36 集（最严重）
**症状**：episode 以 `guard_parse_failed` 终止。
**具体错误**（`result.json.error`）：
- x4 `invalid evidence strategy: 'scroll' is not a valid EvidenceStrategy`
- x1 `'wait' is not a valid EvidenceStrategy`
- x1 `'Copying the URL via Ctrl+C ...' is not a valid EvidenceStrategy`
- x1 `'Scroll down through the document ...' is not a valid EvidenceStrategy`
- x1 `'Right-clicking on sheet tabs ...' is not a valid EvidenceStrategy`
- x1 `progress update must be verified with evidence`

**根因**：Guard 模型在 `evidence_gap` 的 `attempted_strategy`/`recommended_strategy`
字段返回自由文本（甚至 action 类型如 `scroll`/`wait`），而
`stateguard/guard/parser.py:140-141` 用 `EvidenceStrategy(value)` 严格构造，任何
非枚举值都抛 `ValueError` → `guard_parse_failed`。
**位置**：
- 解析：`stateguard/guard/parser.py`（`_parse_evidence_gap`，134-153 行）
- 枚举：`stateguard/verification/result.py:26`（`EvidenceStrategy`）
- prompt（模型为何返回自由文本）：`stateguard/guard/backends/mllm_backend.py`
**修复方向（选一）**：
1. **宽松解析**：`_parse_evidence_gap` 对无法映射的 strategy 字符串降级为
   `None` 或归一化（而不是抛异常），并在日志记录原始串；
2. **prompt 收紧**：给 `evidence_gap` 明确枚举白名单，禁止自由文本；
3. **fallback**：Guard 结果解析失败时降级为 `unknown`（fail-open），不终止 episode。
建议先做 1+3（低风险），再评估 2。

### P2. plan_revision_failed / replan_success=0 —— 5/36 集
**具体错误**（`result.json.error`）：
- x2 `local replan failed for S2: plan patch generation failed: 'trigger_node_id'`
  —— 模型 PlanPatch 缺 `trigger_node_id` 字段
- x1 `'manual' is not a valid ContractProvenance` —— 模型返回非法 provenance
- x2 `replacement_anchor must preserve the trigger node semantic invariant`
  —— replacement_anchor 语义与 trigger 节点不一致
**根因**：Replanner 输出协议仍不可靠。`validate_plan_patch` 的语义不变量检查
（`stateguard/planning/patch_validator.py:65-69`）在模型生成的 replacement_anchor
与原 trigger 的 `SemanticGoal.invariant` 不完全一致时拒绝；provenance 枚举
（`stateguard/verification/contracts.py:35`）与模型输出不匹配；缺字段。
**位置**：
- replanner：`stateguard/planning/runtime_replanner.py`
- patch 数据：`stateguard/planning/plan_patch.py`（trigger_node_id 在 :69）
- 校验：`stateguard/planning/patch_validator.py`
- 语义不变量：`SemanticGoal.invariant`（`stateguard/core/schema.py`）
**修复方向**：收敛 replanner response schema（缺失字段重试/默认）、
provenance 归一化、语义比较用可容差的匹配（允许等价描述而非字节级）。
注意：`replan_success=0` 说明即使局部 replan 触发也从没成功应用——这是核心能力缺口。

### P3. Executor premature finish —— max_steps 5 + clean 成功率低
**症状**：executor（Qwen3.7 Plus）完成 1 次点击后反复 `is_finish=true`，不完成
多步 GUI 动作（如 DNT toggle 需"点击+确认对话框"）；clean 4/15。
**位置**：`stateguard/runtime/episode_runner.py`（finish 块，~522-574 行）——
已实现 `premature_finish_count` 规则反馈（不给 RepairBudget 增加 cycle）。
**判断**：这是 executor 能力问题（已知风险，handoff §4.L4），不是 StateGuard 诊断
失败。**除非换 executor（如 Qwen3-VL-32B 视觉模型，见 configs 旧配置 executor_qwen），
否则任务成功率上不去**。若坚持 Qwen3.7 Plus，可在 finish 被拒 ≥N 次后强制引导
回到未完成节点（当前已做，但模型不遵从）。

### P4. 磁盘（已处理，需长期注意）
- 系统盘 `/` 曾 100% 满 → 清 `~/.cache/uv`（17.5G）后 81%。
- **今后实验文件一律放 `/data/research`**（stateguard_runs 已在 /data，4.4T）。
- 不要往系统盘写大文件；`/tmp` 用完即清。
- 检查残留：`du -sh ~/.cache ~/.npm ~/.cursor-server /var/log/journal`（多为预存，勿乱删）。

### P5. 已修复的 3 个运行时崩溃（记录，勿回归）
1. `evidence_gap` 含 null 列表 → `tuple(None)` 崩溃。修复：`value.get(k) or ()`（parser.py）。
2. premature-finish repair 消耗 causal RepairBudget → repair_failed。修复：premature_finish
   不进 repair 循环，只给规则反馈（episode_runner.py）。
3. `mark_suspicious` 对已 SUSPICIOUS 节点重复 transition → IllegalTransitionError。
   修复：幂等（`task_state.py` 的 `mark_suspicious`，已 SUSPICIOUS 时只更新 reason/trust）。

## 4. 验证方式

- 单元：`cd /data/research/projects/StateGuard && .venv-stateguard/bin/pytest -q`（应 218 passed）
- 单集冒烟：`run_smoke.sh --config configs/poc/osworld_v9_fix_smoke.yaml --mode stateguard \
  --task 030eeff7-b492-4218-b312-701ec99ee0cc --scenario clean --allow-dirty`
- canary：`run_smoke.sh --config configs/poc/osworld_v9_canary.yaml --mode stateguard \
  --task 030eeff7-... --scenario <clean|wrong_target_id|earlier_id> --allow-dirty`
- 36 矩阵：`run_smoke.sh --config configs/poc/osworld_v9_matrix.yaml --mode stateguard --allow-dirty --resume`
- 汇总：`scripts/report_v9_matrix.py`

## 5. 下一步（建议顺序）

1. 修 P1（guard_parse_failed fail-open + 宽松策略解析）——收益最大，直接消除 10/36 框架失败。
2. 修 P2（replanner schema/语义容差），目标 replan_success>0。
3. 跑 executor_only 无 Guard baseline（`osworld_poc.yaml` 的 executor_only mode），
   得到任务成功率基准，才能判断 StateGuard 提升是否真实。
4. 修完 P1/P2 后重跑 36 矩阵，再与 baseline 对比。
5. （可选）评估切换 executor 到 Qwen3-VL-32B（`executor_qwen` provider）能否解决 premature finish。

## 6. 最终交付目标

- guard_parse_failed → 0
- plan_revision_failed → 0，replan_success > 0
- 与无 Guard baseline 对齐后可比较：clean success / fault recovery /
  first-root accuracy / 额外调用 / 延迟
- 不要用框架失败 episode 计算提升

## 7. 2026-09-06 修复进展

### 7.1 已实现并提交

核心修复 commit：`5b27154`（`fix v9 guard and replanner recovery paths`）。

实验流水线 commit：`d37c743`（`add gated v9 comparison pipeline`）。

服务器工作树在提交后为 clean，完整回归为 `230 passed`。

P1 Guard 修复：

- `stateguard/guard/parser.py`
  - 对 `scroll`、`wait`、URL copy、自由文本导航等 strategy 做通用归一化。
  - 无法归一化的 strategy 降级为 `None`，原始文本保存在 `raw_*_strategy`。
  - evidence list 接受字符串、列表和空值，不再出现 `tuple(string)` 拆字符。
- `stateguard/guard/backends/mllm_backend.py`
  - 非法 progress update 被丢弃并写入 reason，不再终止 episode。
  - Guard JSON 重试耗尽后返回 `unknown/verifier_inconclusive`，由 verification debt
    决定后续动作，不再产生 `guard_parse_failed`。

P2 Replanner 修复：

- `stateguard/planning/runtime_replanner.py`
  - 本地绑定 `trigger_node_id` 和最小 `replace_nodes`。
  - 缺失 anchor 时从新节点 DAG 的唯一 sink 推导。
  - replacement anchor 的 `SemanticGoal`、`VerificationIntent` 和 contract success
    condition 强制继承原 problem node。
  - 清除 `manual` 等模型生成的非法 provenance 和 TaskNode 未知字段。
  - 依据 environment capabilities 生成可验证的 provisional contract。
  - 模型连续无法生成 `new_nodes` 时，生成确定性的、语义不变的 retry boundary，
    防止 local replan 因协议漂移直接失败。
- `stateguard/planning/patch_validator.py`
  - 继续使用精确 invariant 校验；语义等价问题通过本地绑定解决，不放宽安全门槛。

指标与汇总修复：

- `stateguard/runtime/episode_runner.py`：新增四项 episode 指标。
- `experiments/poc/logging.py`：支持新指标，并在 `--resume` 时累计读取全部 episode
  的 `result.json`。旧矩阵 summary 已从错误的 12 episodes 恢复为 36 episodes。
- `experiments/poc/metrics.py`：clean false intervention 仅统计错误 repair 请求；正常的
  finish rejection 和 verification request 不再算 false positive。
- `scripts/report_v9_matrix.py`：支持 `--base`，并报告四项新容错指标。

四项新增验收指标：

- `guard_parse_fail_open_count`
- `guard_strategy_normalization_count`
- `guard_progress_update_drop_count`
- `replanner_fallback_count`

对应回归测试：

- `tests/test_mllm_guard_parser.py`
- `tests/test_mllm_runtime_prompts.py`
- `tests/test_runtime_replanner_normalization.py`
- `tests/test_cumulative_results.py`
- `tests/test_false_intervention_certified_clean.py`

### 7.2 当前 canary

配置：`configs/poc/osworld_v9_recovery_canary.yaml`

启动器：`scripts/run_v9_recovery_canary.sh`

输出目录：`/data/research/stateguard_runs/poc_stability_v9_recovery_canary`

该 canary 顺序重跑三类历史失败：

1. `c7c1e4c3... clean`：旧错误为非法 progress update。
2. `aad10cd7... wrong_value`：旧错误为非法 `manual` provenance。
3. `8b1ce5f2... earlier_state_corruption`：旧错误为缺 `trigger_node_id`。

监控：

```bash
cat /data/research/stateguard_runs/poc_stability_v9_recovery_canary/canary_status.txt
tail -n 100 /data/research/stateguard_runs/poc_stability_v9_recovery_canary/canary.log
find /data/research/stateguard_runs/poc_stability_v9_recovery_canary -name result.json -print
```

### 7.3 门控正式流水线

脚本：`scripts/run_v9_postfix_pipeline.sh`

状态目录：`/data/research/stateguard_runs/v9_postfix_pipeline`

流水线等待 canary 完成，并检查：结果数为 3、无框架失败、每例至少生成一个 adaptive
contract、所有触发的 local replan 都成功。通过后依次执行：

1. StateGuard 36-case：`configs/poc/osworld_v9_fixed_matrix.yaml`
2. 同 executor 的无 Guard baseline：`configs/poc/osworld_v9_executor_baseline.yaml`

两者均使用本地 `Qwen3-VL-32B-Instruct` 作为 executor。服务为
`http://127.0.0.1:8032/v1`，Guard/Grounder/Replanner 继续使用 qwen3.7-plus。

监控：

```bash
cat /data/research/stateguard_runs/v9_postfix_pipeline/status.txt
tail -n 100 /data/research/stateguard_runs/v9_postfix_pipeline/pipeline.log
pgrep -af 'run_v9_postfix_pipeline|run_poc_osworld'
```

若 canary 不达标，流水线写入 `state=canary_failed` 并停止，不会消耗完整矩阵资源。
