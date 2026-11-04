# StateGuard v9 修复与实验交接手册

更新时间：2026-09-04

## 1. 目标与结论

目标是把 StateGuard v9 的自适应验证用于真实 OSWorld episode：保持任务语义不变量，依据当前 UI 动态生成证据契约；证据不足时累计 verification debt；节点确实不可验证时只替换最小 DAG 区域，而不是重启整个任务。

首轮 36 episode 结果不能用于性能比较。36/36 均在 GUI 动作前以 `plan_revision_failed` 结束，`task_success_rate=0` 是框架失败，不是模型或 StateGuard 的任务成功率。结果位于：

`/data/research/stateguard_runs/poc_stability_v9/osworld_stability_v9-stateguard/summary.json`

本轮已修复两个系统性边界，并通过 218 项完整回归和新增 API smoke。真实单 episode smoke 使用独立目录，见第 6 节。

## 2. 服务器与环境

- SSH：`researcher@example-host`
- StateGuard：`/data/research/projects/StateGuard`
- OSWorld：`/data/research/projects/OSWorld-StateGuard`
- OSWorld Python：`/data/research/ui-mopd-repro/repos/OSWorld/.venv/bin/python`
- 单元测试 Python：`/data/research/projects/StateGuard/.venv-stateguard/bin/python`
- VM 镜像：`/data/research/ui-mopd-repro/repos/OSWorld/docker_vm_data/Ubuntu.qcow2`
- 模型配置：`/data/research/projects/StateGuard/configs/models.yaml`
- API 密钥：`/data/research/projects/StateGuard/.env.secrets`，不要提交或写入报告
- 实验包装脚本：`/data/research/stateguard_runs/run_smoke.sh`
- Git 分支：`feature/trust-trace-stateguard`
- 基线 commit：`4f75beb61882757fc4d3975562376fe701a49059`
- 当前 v9 是未提交工作树，正式比较前应审阅并提交，确保 `run_metadata.json` 能唯一追踪代码。

运行真实 OSWorld 时必须使用：

```bash
export PYTHONPATH=/data/research/projects/StateGuard:/data/research/projects/OSWorld-StateGuard
set -a
source /data/research/projects/StateGuard/.env.secrets
set +a
```

## 3. 当前方法与具体实现

### 3.1 不可变语义层

每个 TaskNode 持有 `SemanticGoal` 和 `VerificationIntent`。`SemanticGoal.invariant` 是成功语义，运行时不得由 Grounder、Guard 或 Replanner 改写。

- 数据结构：`/data/research/projects/StateGuard/stateguard/core/schema.py`
- DAG 状态机：`/data/research/projects/StateGuard/stateguard/core/task_state.py`
- 任务编译：`/data/research/projects/StateGuard/stateguard/compiler/task_compiler.py`
- 任务图：`/data/research/projects/StateGuard/configs/tasks/osworld/*.json`

### 3.2 自适应证据契约

`AdaptiveEvidenceContract` 把语义目标绑定到当前环境可用的截图、accessibility tree、结构化状态或外部持久化证据。契约允许更换证据源、verifier 和 UI anchor，但 `semantic_goal_ref`、`success_condition` 和 observable claim 必须与原 invariant 精确一致。

- 契约模型：`/data/research/projects/StateGuard/stateguard/verification/contracts.py`
- Grounder：`/data/research/projects/StateGuard/stateguard/verification/grounder.py`
- 契约校验：`/data/research/projects/StateGuard/stateguard/verification/validator.py`
- 生命周期与事件：`/data/research/projects/StateGuard/stateguard/verification/lifecycle.py`
- Verifier 注册：`/data/research/projects/StateGuard/stateguard/verification/registry.py`
- 环境能力：`/data/research/projects/StateGuard/stateguard/environment/capabilities.py`
- 控制器：`/data/research/projects/StateGuard/stateguard/runtime/adaptive_verification.py`

本轮修复后，MLLM 只返回 `evidence_sources`、`ui_anchor`、`fallback_strategy`、`confidence` 等 grounding hints。完整契约由本地 `_build_contract()` 从不可变 `SemanticGoal` 构造。模型输出中的伪造 `success_condition` 或 `semantic_goal_ref` 会被忽略。

模型把“目标暂时未显示”误报为 `ungroundable` 时，只要本地 capability graph 仍存在理论验证通道，就降级到确定性契约继续执行。只有模型和本地能力检查均认为无通道时，节点才进入不可验证流程。

### 3.3 Guard、unknown 与 verification debt

Guard 在 checkpoint 返回 `verified`、`contradicted` 或 `unknown`。`unknown` 不是未知动作，而是当前证据不足；它携带 `unknown_reason` 和 `evidence_gap`。连续 unknown 会先切换证据策略或重新 grounding，达到硬阈值后才标记节点不可验证。

- Guard 主逻辑：`/data/research/projects/StateGuard/stateguard/guard/state_guard.py`
- MLLM backend：`/data/research/projects/StateGuard/stateguard/guard/backends/mllm_backend.py`
- 输出解析：`/data/research/projects/StateGuard/stateguard/guard/parser.py`
- debt 状态机：`/data/research/projects/StateGuard/stateguard/runtime/verification_debt.py`
- checkpoint 策略：`/data/research/projects/StateGuard/stateguard/runtime/checkpoint_policy.py`

### 3.4 Trace 与故障定位

每次动作、观察和验证结果进入 trust trace。Trace Analyzer 用它定位最早可疑根节点、影响集合及可保留进度，为 repair/replan 提供边界。

- Trace 数据：`/data/research/projects/StateGuard/stateguard/trace/models.py`
- 收集器：`/data/research/projects/StateGuard/stateguard/trace/collector.py`
- 分析器：`/data/research/projects/StateGuard/stateguard/trace/analyzer.py`
- Episode 总编排：`/data/research/projects/StateGuard/stateguard/runtime/episode_runner.py`

### 3.5 局部 DAG 重规划

`MLLMPlanPatchProvider` 只生成最小 `PlanPatch`；`validate_plan_patch()` 在内存副本上检查节点存在性、依赖、环、可达性、契约能力和已验证节点不可变性，全部通过后原子替换。

- Patch 数据与兼容解析：`/data/research/projects/StateGuard/stateguard/planning/plan_patch.py`
- Replanner 与 schema/retry：`/data/research/projects/StateGuard/stateguard/planning/runtime_replanner.py`
- Patch 校验和原子应用：`/data/research/projects/StateGuard/stateguard/planning/patch_validator.py`

本轮明确了两类节点：`protected_verified_nodes` 必须字节级不变；`preserved_node_ids` 必须保留语义和字段，但允许把依赖从旧节点重连到 `replacement_anchor`。解析器还兼容 `plan_patch`/`patch` 包装、字段别名以及列表形式的 dependency rewrites。

此外，`replacement_anchor` 的 semantic invariant 必须与原 trigger node 精确一致。这样允许新建中间步骤，但不允许通过改写出口语义来降低任务要求。

## 4. 首轮失败的分层诊断

首轮汇总：36 episodes、44 steps、101 model calls、422609 tokens、43 次 contract validation failure、44 次 local replan、8 次 patch 通过，但没有任何 trajectory、Guard verification 或有效 fault injection。

### L0 实验有效性

- 所有 episode 都在动作前失败。
- `0%` 不能与论文 Table 2 或此前版本比较。
- `state_preservation_rate=1.0` 也没有意义，因为没有进度可破坏。

### L1 Grounder 协议

- 旧实现要求模型重写完整 `AdaptiveEvidenceContract`。
- 模型漏字段、改变 claim、给出环境不支持的 source/verifier，导致 43 次校验失败。
- 模型还把“当前看不见目标”误当成永久不可验证。
- 已修复：模型只提供 grounding hints，本地绑定完整语义；可行通道存在时忽略错误的 `ungroundable`。

### L2 Replanner 输出协议

- 出现缺少 `trigger_node_id`、缺少 `replacement_anchor`、返回顶层 list、返回 request 字段 `ancestor_boundary`、dependency rewrites 类型错误。
- 已修复：严格 response schema、包装/别名归一化、列表 rewrites 归一化、带解析错误的有限重试。

### L3 Patch 语义

- 14 个主要失败为 `protected node S2 was modified`。
- 根因是旧校验器把待执行的 preserved downstream node 也当成字节级 immutable，但替换上游节点必然需要更新它的 dependencies。
- 已修复：verified 才字节级 immutable；preserved 节点仅允许 dependencies 改变。

### L4 真实 UI 与 verifier

- 首轮没有到达该层，尚不能证明视觉 Guard、unknown debt、repair 和局部 replan 在真实 episode 中有效。
- accessibility tree 并非所有 OSWorld 状态都稳定提供，当前配置 `require_a11y_tree: false`，视觉路径仍是主要 fallback。
- Qwen3.7-plus 同时承担 executor、grounder、guard、replanner，延迟和错误具有相关性；后续应分开统计各角色调用。

### L5 基准与论文比较

- 当前 12 个任务及故障矩阵是 StateGuard 稳定性 PoC，不等同于 UI-MOPD 论文 Table 2 的完整 OSWorld/MobileWorld protocol。
- 必须先得到有效 clean baseline，再比较带 Guard 的任务成功率、恢复率、额外调用和延迟。
- 未匹配任务集、镜像、模型权重、推理模板和 evaluator 前，不应声称超过论文的 33.9%/35.8%/38.2% 等结果。

## 5. 已完成验证

```text
targeted regression: 24 passed
full regression: 218 passed
real qwen3.7-plus Grounder API smoke: groundable=True, source=screenshot, valid=True
```

关键测试：

- `/data/research/projects/StateGuard/tests/test_adaptive_verification_v9.py`
- `/data/research/projects/StateGuard/tests/test_plan_patch.py`
- `/data/research/projects/StateGuard/tests/test_verification_runtime.py`

完整回归命令：

```bash
cd /data/research/projects/StateGuard
.venv-stateguard/bin/pytest -q
```

## 6. 真实 smoke 与结果目录

独立 smoke 配置：

`/data/research/projects/StateGuard/configs/poc/osworld_v9_fix_smoke.yaml`

任务：Chrome Do Not Track clean episode，task id `030eeff7-b492-4218-b312-701ec99ee0cc`。

输出：

`/data/research/stateguard_runs/poc_stability_v9_fix_smoke/osworld_v9_fix_smoke-stateguard`

日志：

`/data/research/stateguard_runs/poc_stability_v9_fix_smoke/launcher.log`

启动命令：

```bash
cd /data/research/projects/StateGuard
/data/research/stateguard_runs/run_smoke.sh \
  --config configs/poc/osworld_v9_fix_smoke.yaml \
  --models configs/models.yaml \
  --mode stateguard \
  --task 030eeff7-b492-4218-b312-701ec99ee0cc \
  --scenario clean \
  --allow-dirty
```

检查进度：

```bash
pgrep -af 'run_poc_osworld.py.*osworld_v9_fix_smoke'
tail -n 100 /data/research/stateguard_runs/poc_stability_v9_fix_smoke/launcher.log
find /data/research/stateguard_runs/poc_stability_v9_fix_smoke -type f | sort
```

判定 smoke 有效的最低条件：episode 中出现 `trajectory.jsonl`/步骤截图，`contracts_generated > 0`，且不再在 step 0 以 `plan_revision_failed` 结束。任务本身成功不是框架 smoke 的唯一通过条件。

截至交接时，该 smoke 仍在运行，已完成 6 步并保存 12 张前后截图。它生成了 `S1-c1` 和 `S2-c1` 自适应契约，真实执行 click/type/hotkey；Guard 在 step 2 和 step 4 返回证据不足，在 step 5 验证 S1，并在 step 6 验证 S2。这证明 Grounder、Executor、checkpoint、unknown 处理和 Guard 已形成真实 UI 闭环，并跨过首轮“动作前全部失败”的阻塞点。尚未生成最终 `result.json`，因此不能宣称整个任务成功。

## 7. 下一步顺序

1. 等待单任务 smoke 完成，检查 trajectory、contract events、Guard 输出和 evaluator。
2. 若仍在动作前失败，优先修协议/状态机，不运行 36 episode。
3. 若已进入动作循环，选择一个 clean、一个 immediate fault、一个 delayed fault，形成 3-case canary。
4. canary 均产生有效 trajectory 后，再用新输出目录重跑 36 episode。
5. 分别报告 clean task success、fault injection validity、recovery success、unknown 分布、replan 成功率、模型调用和延迟。
6. 最后再与无 Guard baseline 和论文 protocol 对齐，不能用框架无效 episode 计算提升。

## 8. 尚存风险

- 真实 single-episode smoke 尚需最终确认；单元测试不能替代 GUI 运行。
- MLLM Replanner 虽能被稳定解析，生成的新节点语义是否足够好仍依赖模型，需要真实 fault canary。
- Grounder 的确定性 fallback 保证可执行性，不保证当前截图已经含有目标证据；Guard 仍需区分“尚未导航到目标”和“动作无效”。
- `max_grounding_attempts` 当前跨调用计数，并非在一次 `ensure_contract()` 内自动连试；失败后由 episode policy 决定 re-ground/replan。
- OpenCode API 延迟较高，首轮 101 调用累计约 4395 秒；大矩阵前应确认调用并发和费用。
- 工作树为 dirty；未经提交的正式结果可复现性较弱。

## 9. 代码同步说明

本轮修改已同时写入服务器 `/data/research/projects/StateGuard` 与本地副本：

`/home/researcher/Documents/Codex/2026-07-16/ban/StateGuard-v9-adaptive`

后续以服务器为实验真源。再次从本地 `scp` 前先比较 `git status` 与文件哈希，避免覆盖服务器侧新增修改。
