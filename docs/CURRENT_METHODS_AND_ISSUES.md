# StateGuard 当前方法、实现与问题分层报告

> 更新时间：2026-08-31\
> 服务器：`researcher@example-host`\
> 仓库：`/data/research/projects/StateGuard`\
> 分支：`feature/trust-trace-stateguard`\
> 当前提交：`e654b91`\
> 当前测试：`178 passed`\
> 最近实验：`osworld_stability_v8`

## 1. 汇报摘要

当前系统已经从“Executor 直接操作桌面”扩展为一套显式状态管理与故障恢复框架：任务先被表达为状态 DAG，Executor 在可执行前沿上提出 GUI 动作，Checkpoint Policy 决定何时调用 Guard，Guard 使用规则或多模态模型验证状态；发生矛盾时，系统定位故障根节点、失效其后代并发起最小范围修复。运行过程中还记录 execution trace、节点 trust、suspicion、repair budget 和 fault injection 指标。

目前的主要进展是**运行稳定性提升**：动作格式错误、`double_click` 解析失败和无限 repair 等基础设施问题已明显收敛。v8 三个小样本均无基础设施故障，前两个案例能够在无效策略耗尽后提前退出，不再全部跑满 50 步。

但当前尚未证明任务恢复能力。v8 的实际任务成功率为 **0/3**：两个案例以 `plan_revision_required` 终止，一个案例以 `max_steps` 终止。核心瓶颈已经由“系统能否稳定运行”变成“状态是否可验证、UNKNOWN 是否能收敛、计划修订是否能真正执行”。

需要特别区分：v8 报告中的 `gate_passed=true` 只表示 `infrastructure_failures=0`，**不表示任务成功，也不表示方法性能提升**。

## 2. 当前实验配置

### 2.1 模型与角色

| 角色 | 当前配置 | 用途 | 当前风险 |
|---|---|---|---|
| Executor | `executor_qwen`，模型及 URL 由 `EXECUTOR_MODEL`、`EXECUTOR_BASE_URL` 注入 | 读取截图和任务状态，产生下一步 GUI 动作 | 可能错误声明动作可观察性、重复宣称子目标完成、输出成本高 |
| Guard | OpenCode `qwen3.7-plus` | 判断 `verified / contradicted / unknown`，提供 fault root、fault type、verification target | 视觉识别、结构化证据和因果定位仍不稳定；API 延迟较高 |
| Task compiler | 同 Guard provider，但 PoC 中 `enabled_for_poc=false` | 自动生成状态 DAG | v8 未启用，当前任务图仍是 manual |

模型配置位于：

- `/data/research/projects/StateGuard/configs/models.yaml`
- 密钥通过环境变量注入，不应写入报告或仓库。

### 2.2 环境与运行参数

| 项目 | 当前值 |
|---|---|
| Benchmark | `OSWorld-Verified` |
| OSWorld | `/data/research/projects/OSWorld-StateGuard` |
| VM | `/data/research/ui-mopd-repro/repos/OSWorld/docker_vm_data/Ubuntu.qcow2` |
| Provider | Docker, headless |
| 最大步数 | 50 |
| 单故障最大 repair cycle | 3 |
| 单 repair cycle 最大动作数 | 20 |
| UNKNOWN 配置阈值 | 3 |
| Trace 上限 | 200 entries，保留最近 10 张图像 |
| Checkpoint | Hybrid，HIGH=2 步，MEDIUM=5 步，cooldown=2 |
| Task graph | Manual |
| Fault injection | Enabled |

完整配置：`/data/research/projects/StateGuard/configs/poc/osworld_stability_v8.yaml`。

## 3. 端到端运行流程

```text
OSWorld observation
    -> Executor 读取截图、DAG 状态、历史/repair context
    -> ExecutorProposal
       (subgoal_id, intent, action, expected_effect,
        effect_observability, subgoal_done, is_finish)
    -> 动作规范化与 OSWorld action conversion
    -> 环境执行动作并返回 after observation
    -> CheckpointPolicy 判断是否需要验证
    -> Hybrid Guard
       -> 有结构化 predicate/expected_effect：优先 RuleBackend
       -> 规则无法决断：MLLMBackend
    -> VERIFIED / UNKNOWN / CONTRADICTED
       -> VERIFIED：节点写入 evidence，提升 trust
       -> UNKNOWN：请求补充验证；检测动作停滞或不可观察循环
       -> CONTRADICTED：因果定位、后代失效、最小 repair
    -> 所有 required 节点 VERIFIED 后才允许 FINISH
```

核心调度实现：`stateguard/runtime/episode_runner.py`。

## 4. 方法与实现

### 4.1 状态 DAG 任务表示

**方法**

将任务拆成 2-8 个语义状态节点，而不是 GUI 动作序列。每个节点包含：

- `node_id`
- `description`
- `dependencies`
- `expected_result_semantic`
- `evidence_mode`
- `required`
- 可选的 `structured_predicate`、`expected_effect`、`verify_action`

只有依赖已满足的节点进入 executable frontier。所有 required 节点都成为 `VERIFIED` 后，任务才可结束。

**实现**

- Schema：`stateguard/core/schema.py`
- DAG：`stateguard/core/dependency_graph.py`
- 编译：`stateguard/compiler/task_compiler.py`
- 自动 DAG prompt：`stateguard/planning/prompts.py`
- 自动 DAG parser：`stateguard/planning/parser.py`
- 当前手工任务图：`configs/tasks/osworld/*.json`

**当前效果**

DAG 提供了明确的状态边界、依赖传播和最小修复范围，是 StateGuard 的核心结构基础。

**当前问题**

- v8 使用 `task_graph.source=manual`，没有实际验证最新 Auto-DAG prompt 的效果。
- 手工 DAG 中仍存在“识别、理解、提取”一类内部认知节点，它们未必对应可见环境状态。
- `evidence_mode=structured` 不等于存在结构化验证能力。没有 `structured_predicate` 或环境 structured state 时，节点仍无法被验证。
- 当前没有运行时 DAG refinement；任务图一旦不可验证，只能终止。

### 4.2 Executor 输出契约

**方法**

Executor 每步必须返回结构化 proposal，包括目标节点、意图、动作、预期效果、完成信号和效果可观察性。可观察性分为：

- `visual`
- `structured`
- `persistence`
- `none`

**实现**

- Prompt：`stateguard/executor/mllm_executor.py`
- Parser：`stateguard/executor/parser.py`
- Proposal schema：`stateguard/core/schema.py`

**当前效果**

解析重试和严格 schema 能阻止大部分自由文本直接进入环境。v8 不再出现上一轮的 `executor_parse_failed`。

**当前问题**

- `effect_observability` 由 Executor 自报，存在语义误标风险。
- Executor 可能在没有证据时连续设置 `subgoal_done=true`。
- Executor 能更换动作形式来绕过“重复动作”检测，但验证目标实际上没有变化。
- 结构化 prompt 很长，叠加截图和历史后 token/延迟开销较大。

### 4.3 动作规范化与能力契约

**方法**

先将模型生成的动作规范化为系统支持的 canonical action，再交给 OSWorld adapter。系统还根据动作类型推断默认 effect observability。

**实现**

- `stateguard/core/action_capabilities.py`
- `stateguard/core/action_similarity.py`
- `integrations/osworld/action_converter.py`
- `stateguard/executor/parser.py`

最近的通用修复包括：

- 将 `double_click` 规范化为可执行动作。
- 统一动作等价性比较。
- 将动作效果渠道写入 trace。

**当前效果**

`bc2...no_effect--2` 在 v6 因 `double_click` 解析失败，v8 已不再出现该基础设施故障。

**当前问题**

- 动作“语法合法”不代表动作“对当前 UI 有效”。
- 坐标缩放、窗口位置变化和不可交互区域仍可能产生合法但无效的点击。
- capability contract 主要处理动作类型，尚不能判定动作能否为某个 DAG 节点产生所需证据。

### 4.4 显式任务状态机

**方法**

每个 DAG 节点在以下状态间转换：

```text
PENDING -> ACTIVE -> EXECUTED -> VERIFIED
                         |          |
                         v          v
                    SUSPICIOUS <- VERIFIED
                         |
                         v
                       FAILED -> ACTIVE

下游已完成节点在上游失效后可变为 STALE -> ACTIVE
```

`VERIFIED` 必须附带 evidence。非法状态转换直接抛错，从而防止运行时静默污染状态。

**实现**

- `stateguard/core/task_state.py`
- `stateguard/core/schema.py`

**当前效果**

该机制能区分“动作执行过”与“状态已经得到证明”，并支持保留未受故障影响的进度。

**当前问题**

- `EXECUTED` 节点可以长时间停留并连续 UNKNOWN，目前没有通用的节点级验证债务上限。
- trust 的更新是固定增减值，尚未校准为概率或可靠性估计。
- SUSPICIOUS 生命周期主要由矛盾触发，对“持续无法验证”覆盖不足。

### 4.5 Hybrid Checkpoint Policy

**方法**

为了降低每步调用 Guard 的成本，使用三层 checkpoint：

1. 强制检查：`subgoal_done`、`finish`、repair revalidation、stagnation。
2. 风险检查：高风险节点每 2 步、中风险节点每 5 步检查。
3. Cooldown：同一节点周期检查间隔至少 2 步。

节点风险依据 persistence 和下游节点数量确定。

**实现**

- `stateguard/runtime/checkpoint_policy.py`
- 调度入口：`stateguard/runtime/episode_runner.py`

**已知历史效果**

Round 2.5 clean smoke 中，Hybrid 保持 clean `3/3`，Guard calls 从 dense 的 22 降至 13，降低约 41%。

**当前问题**

- Executor 每步都宣称 `subgoal_done` 时，Hybrid 会退化为几乎每步验证。
- c7 案例产生 49 个 completion checkpoints，既昂贵又没有新增证据。
- 风险按 DAG 拓扑启发式计算，不考虑真实 UI 难度、证据可用性和模型不确定性。
- Checkpoint 决策关注“何时验证”，没有充分解决“用什么证据验证”。

### 4.6 Hybrid Guard：规则优先、MLLM 回退

**方法**

如果节点定义了 `structured_predicate` 或 `expected_effect`，先调用 RuleBackend；规则无法决断时回退到 MLLM。MLLM 返回：

- `judgement`
- `progress_updates`
- `fault_root`
- `fault_type`
- `verification_target`
- `reason`

**实现**

- `stateguard/guard/backends/hybrid_backend.py`
- `stateguard/guard/backends/rule_backend.py`
- `stateguard/guard/backends/mllm_backend.py`
- `stateguard/guard/state_guard.py`
- `stateguard/guard/parser.py`

**当前效果**

规则验证在存在真实结构化状态时更确定；视觉和语义任务可以通过 MLLM 覆盖。

**当前问题**

- c7 的 S1 虽声明 `structured`，但没有 predicate，RuleBackend 无法工作，只能回退 MLLM。
- MLLM 无法从截图证明内部提取结果，因此连续 49 次 UNKNOWN。
- 部分 UNKNOWN 的 `reason` 为空，只重复同一个 `verification_target`，反馈信息不足。
- 早期实验中 Guard 容易将最先看见的下游异常误判为根因。
- Guard 对截图裁切、细小文字、应用内部状态和持久化状态的观察能力有限。

### 4.7 Execution Trace Memory 与历史上下文

**方法**

每一步记录动作前后 observation 摘要、任务状态、active node、intent、action、expected effect、effect observability、checkpoint 和 trust snapshot。Guard 因果诊断只应读取相关 trace window，而不是全部历史。

**实现**

- `stateguard/trace/models.py`
- `stateguard/trace/collector.py`
- `stateguard/trace/storage.py`
- `stateguard/trace/summarizer.py`
- 轻量 prompt 历史：`stateguard/runtime/history.py`

每个 episode 的落盘文件包括：

- `execution_trace.jsonl`
- `executor_events.jsonl`
- `guard_events.jsonl`
- `trajectory.jsonl`
- `result.json`

**当前效果**

Trace 已能还原 c7 在 S1 上连续 49 次 UNKNOWN 的过程，并区分动作停滞和节点失败。

**当前问题**

- Trace 已记录，但运行策略对 trace 中“验证目标长期不变”的利用不足。
- observation summary 不能替代精确的结构化 UI 状态。
- 大量截图和模型响应导致存储、token 与分析成本增长。

### 4.8 Trust 与 Suspicion 生命周期

**方法**

弱矛盾不立即触发 repair，而是将节点标记为 `SUSPICIOUS` 并降低 trust；后续强证据才确认 FAILED。该方法用于替换 Round 2.5 中过于粗暴的 consistency fail-open。

**实现**

- 状态与 trust：`stateguard/core/task_state.py`
- Guard 更新：`stateguard/guard/state_guard.py`
- Trace trust snapshot：`stateguard/trace/*`

**当前效果**

降低了进行中节点被一次弱视觉矛盾误判后立刻 repair 的概率。

**当前问题**

- trust score 目前是启发式分值，没有经过实验校准。
- UNKNOWN 不等价于 contradiction，因此 49 次 UNKNOWN 不会自然降低到 FAILED。
- suspicion 的确认策略与 checkpoint 类型仍较粗，可能漏掉真实 active-node 故障。

### 4.9 因果故障定位

**方法**

候选根节点为 `ancestors(active) + active`。规则定位优先选择：

1. 环境直接否定 expected result 的最早节点；
2. 最早未 VERIFIED 的候选节点；
3. 当前观察到矛盾的节点。

MLLM 两阶段诊断可对候选节点分别输出可信/不可信判断，再由 Python 选择最早不可信节点。

**实现**

- `stateguard/guard/localization.py`
- `stateguard/guard/state_guard.py`
- `stateguard/guard/backends/mllm_backend.py`
- 离线 replay：`scripts/replay_earlier_root.py`、`scripts/replay_earlier_batch.py`

**历史结果**

- Round 2.5 earlier-root replay：`1/6`。
- Hybrid fault smoke 定位：`0/6`，低于 sparse 的 `2/6`。

**当前问题**

- 当 Guard 从未输出 CONTRADICTED 时，因果定位模块没有触发机会。
- expected result 多为自然语言，规则端无法稳定判断是否被环境否定。
- MLLM 容易选择视觉上最明显的下游异常，而不是最早故障根。
- v8 三案例均没有形成有效 root prediction，当前无法声称定位性能提升。

### 4.10 故障传播与最小修复

**方法**

一旦确认 fault root：

- root 标记为 `FAILED`；
- 已执行或已验证的 descendants 标记为 `STALE`；
- 不受影响的 VERIFIED 节点加入 `preserve_nodes`；
- 只恢复 root，并重新验证实际失效的 descendants；
- 不重新执行整条任务。

**实现**

- `stateguard/guard/repair.py`
- `stateguard/runtime/repair_loop.py`
- `stateguard/runtime/episode_runner.py`

Repair phase 被区分为：

- `RESTORE_ROOT`
- `VERIFY_DESCENDANTS`
- `REPAIR_INVALID_DESCENDANTS`

**当前效果**

修复范围由 DAG descendants 确定，不依赖模型自由生成受影响集合，理论上能保留无关进度。

**当前问题**

- v8 没有 contradiction，因此 repair 完全没有启动；这不是 repair 已成功，而是系统没有获得触发 repair 的证据。
- 历史 File WRONG_VALUE 虽正确定位 S1，但执行 34 个 repair actions、4 个 cycles 后仍失败。
- Executor 可能在 repair 中重复同类无效动作。
- 当前 minimal repair 只能修复已有 DAG 节点，无法修复“节点本身不可验证”的计划缺陷。

### 4.11 Repair Budget 与收敛控制

**方法**

分别限制：

- 每个 fault root 的 repair cycle 数；
- 每个 repair cycle 的动作数。

重复无效果动作先作为 action-level stagnation 处理，不立即把整个节点判为失败。

**实现**

- `stateguard/runtime/repair_loop.py`
- `stateguard/runtime/episode_runner.py`
- 配置：`repair.max_cycles=3`、`repair.max_actions_per_cycle=20`

**当前效果**

v8 没有出现 repair budget exhaustion，也没有无限 repair。

**当前问题**

- “没有预算耗尽”可能只是因为 repair 没有触发，不能作为恢复成功证据。
- 达到预算后当前只能 `repair_failed`，没有升级为全局策略重规划。
- 预算阈值仍是经验值，尚无成本-成功率曲线支持。

### 4.12 UNKNOWN、动作停滞与计划修订

**方法**

当前存在三类控制：

1. 对 `none/persistence` 等不支持直接 no-effect 判断的动作累计 nonvisual UNKNOWN。
2. 对等价动作且 observation 未变化的情况累计 action stagnation。
3. 多种 observable action strategy 被阻塞后返回 `plan_revision_required`。

**实现**

- `stateguard/runtime/episode_runner.py`
- `stateguard/core/action_similarity.py`
- `stateguard/runtime/observation_similarity.py`

**当前效果**

- `wrong_target` 在 16 步提前返回 `plan_revision_required`。
- `no_effect` 在 20 步提前返回 `plan_revision_required`。
- 相比全部跑满 50 步，系统能更早识别部分无效策略。

**当前问题**

- `plan_revision_required` 只是终止信号，并未调用 planner 生成和应用新 DAG。
- c7 的动作不断变化且标记为 `structured`，绕过等价动作和 nonvisual 检测。
- 系统没有按“同一节点、同一 verification target 连续 UNKNOWN”累计 verification debt。
- UNKNOWN 的计数可能因为动作变化而重置，即使语义上没有任何新证据。

### 4.13 Finish 规则

**方法**

只有所有 required 节点 VERIFIED 时才允许结束。Executor 提前 finish 会被拒绝；连续三次提前结束后，系统给出未验证节点列表，不额外调用 Guard。

**实现**

- `stateguard/core/task_state.py::can_finish`
- `stateguard/guard/state_guard.py::verify_finish`
- `stateguard/runtime/episode_runner.py`

**当前效果**

能够防止 Executor 仅凭自身声明完成任务。

**当前问题**

- 如果 DAG 节点天然不可验证，严格 finish 规则会把任务永久锁住。
- 当前缺少“验证条件有缺陷，应重写节点”这一中间分支。

### 4.14 Fault Injection 与评测

**方法**

在语义节点和动作条件满足时注入 `wrong_target`、`wrong_value`、`no_effect` 等故障，记录 injection、exposure、detection、root prediction、repair 和最终环境分数。

**实现**

- `experiments/poc/faults.py`
- `configs/faults/osworld/*.yaml`
- `experiments/poc/metrics.py`
- `experiments/poc/logging.py`
- `scripts/run_poc_matrix.py`

**当前问题**

- 如果任务无法推进到触发位置，fault 可能根本没有注入或暴露。c7 v8 中 `fault_injected_step=null`。
- 这时 root accuracy、repair rate 等指标为 0 或空，不能用于评价 Guard 的故障恢复能力。
- 小样本三案例不能代表完整 OSWorld 分布。

## 5. v8 实验结果

报告路径：`/data/research/stateguard_runs/round3/stability_v8.json`。

| Fault case | Status | Success | Steps | Executor calls | Guard calls | UNKNOWN | Suspicious | Contradictions | Repairs |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `8b1...wrong_target--2` | `plan_revision_required` | 0 | 16 | 36 | 9 | 9 | 3 | 0 | 0 |
| `bc2...no_effect--2` | `plan_revision_required` | 0 | 20 | 32 | 14 | 12 | 4 | 0 | 0 |
| `c7...wrong_value--1` | `max_steps` | 0 | 50 | 98 | 49 | 49 | 0 | 0 | 0 |

汇总结论：

- `infrastructure_failures=0`
- 当前基础设施 gate：PASS
- 实际任务成功率：`0/3`
- 有效 contradiction：`0`
- 有效 repair：`0`
- 不能据此声称恢复性能优于论文或 baseline

### 5.1 c7 的具体失败链

任务图 S1 为：识别教授姓名和主页链接，产生结构化列表。

实际链路为：

1. S1 声明 `evidence_mode=structured`。
2. S1 没有 `structured_predicate`，环境也没有提供对应 structured state。
3. Executor 从第 2 步开始反复声明 S1 完成，并不断更换点击、复制等动作。
4. Guard 每次要求确认同一份教授与 URL 列表，但无法从截图证明该内部结果。
5. 49 次 Guard judgement 全部为 UNKNOWN。
6. 因动作不断变化，action equivalence stagnation 没有达到终止条件。
7. 因动作被标记为 `structured`，nonvisual UNKNOWN 分支没有触发。
8. Episode 在第 50 步以 `max_steps` 结束，故障尚未注入。

该案例说明当前需要的是**节点级 verification debt**，而不是继续增加针对某个动作的规则。

## 6. 问题分层

### L0：实验结论与指标层

| 问题 | 影响 | 严重度 |
|---|---|---|
| `gate_passed` 仅代表无基础设施失败 | 容易误报方法成功 | 高 |
| v8 task success 为 0/3 | 尚无恢复性能证据 | 高 |
| 三案例样本过小 | 无法外推完整 benchmark | 高 |
| fault 未注入时 root/repair 指标没有意义 | 混淆规划失败与 Guard 失败 | 高 |
| 尚未与同模型、同任务、同预算 baseline 做严格对照 | 无法判断净提升 | 高 |

### L1：环境与基础设施层

| 问题 | 影响 | 当前状态 |
|---|---|---|
| Docker/VM reset 和 GUI settle 存在延迟 | 单次实验耗时长 | 可运行但昂贵 |
| Guard API 可能 503 或高延迟 | 长实验不稳定 | 有 retry，未根治 |
| Headless GUI 和截图是主要观察渠道 | 细小文本与隐式状态难验证 | 持续存在 |
| Accessibility tree 未启用 | 丢失结构化 UI 证据 | v8 为 `false` |

### L2：模型与接口层

| 问题 | 影响 | 证据 |
|---|---|---|
| Executor 自报 observability 不可靠 | 可绕过收敛机制 | c7 49 次 structured UNKNOWN |
| Executor 过早声明 `subgoal_done` | Hybrid 退化为密集验证 | c7 49 checkpoints |
| Guard UNKNOWN 反馈信息弱 | Executor 无法形成新策略 | verification target 长期不变 |
| 模型调用 token/延迟高 | 小样本成本已很大 | c7 Executor/Guard 调用 98/49 |

### L3：动作执行层

| 问题 | 影响 | 当前状态 |
|---|---|---|
| 模型动作格式不统一 | 可能 parse failure | canonicalization 已显著缓解 |
| 语法合法动作可能无 UI 效果 | 产生 no-effect 循环 | 仍存在 |
| 坐标与窗口状态敏感 | 点击错误区域 | 仍存在 |
| 更换动作形式可绕过重复检测 | 语义循环不收敛 | c7 已发生 |

### L4：观察与证据层

| 问题 | 影响 | 严重度 |
|---|---|---|
| evidence mode 与真实 verifier 不绑定 | 节点看似可验证，实际不可验证 | 高 |
| structured node 缺 predicate | RuleBackend 无法决断 | 高 |
| persistence 需要额外检查，不可由截图完全证明 | 容易 UNKNOWN 或误判 | 高 |
| 视觉截图无法证明私有推理结果 | 认知型 DAG 节点永久 UNKNOWN | 高 |

### L5：规划与 DAG 层

| 问题 | 影响 | 严重度 |
|---|---|---|
| v8 仍使用 manual DAG | 最新规划约束未进入真实实验 | 高 |
| DAG 含不可观察认知节点 | 阻塞整个 frontier | 高 |
| 节点缺可执行 verifier contract | Guard 只能回退 MLLM | 高 |
| 无运行时局部重规划 | `plan_revision_required` 直接终止 | 高 |

### L6：Checkpoint 与运行时控制层

| 问题 | 影响 | 严重度 |
|---|---|---|
| completion checkpoint 受 Executor 声明驱动 | 可被错误的 done 信号放大 | 高 |
| UNKNOWN 主要按动作累计 | 无法发现语义不变但动作变化的循环 | 高 |
| 没有 node-level verification debt | c7 跑满 50 步 | 高 |
| max steps 是最终兜底，不是恢复策略 | 浪费 API 与环境时间 | 中 |

### L7：Guard 判定层

| 问题 | 影响 | 严重度 |
|---|---|---|
| 无证据时只能 UNKNOWN | repair 无法触发 | 高 |
| 早期因果定位准确率低 | 修复错误根节点 | 高 |
| 弱矛盾与真实故障难区分 | false repair 或漏检 | 高 |
| visual/structured/persistence 证据边界不清 | judgement 不稳定 | 高 |

### L8：Trust 与 Suspicion 层

| 问题 | 影响 | 严重度 |
|---|---|---|
| trust 增减规则未校准 | 分值解释有限 | 中 |
| 连续 UNKNOWN 不形成 verification debt | 信任状态无法反映长期不可证 | 高 |
| suspicion 依赖 contradiction/特定 stagnation | 覆盖范围不足 | 高 |

### L9：Repair 与重规划层

| 问题 | 影响 | 严重度 |
|---|---|---|
| 无 contradiction 就无 repair | UNKNOWN 主导时系统不恢复 | 高 |
| repair 只能修状态，不能修 DAG contract | 不可验证节点无法解决 | 高 |
| plan revision 未真正实现 | 前两案例提前失败而非恢复 | 高 |
| 预算耗尽后缺少升级策略 | 只能 `repair_failed` | 中 |

### L10：故障注入与评测有效性层

| 问题 | 影响 | 严重度 |
|---|---|---|
| 前置规划失败会阻止 fault injection | 无法测试 Guard 核心主张 | 高 |
| 触发条件依赖实际轨迹 | 模型策略改变后可能失效 | 高 |
| 环境分数、status、root accuracy 可能互相矛盾 | 汇总解释困难 | 中 |

### L11：测试覆盖层

当前 `178 passed`，主要覆盖 parser、状态转换、checkpoint、repair budget、trace 和 mock runtime。

仍缺少：

- 同一节点、不同动作、同一 verification target 的 UNKNOWN debt 测试；
- 运行时 DAG 局部替换和状态保留测试；
- accessibility/structured evidence 的真实 OSWorld 集成测试；
- plan revision 后继续执行直至成功的端到端测试；
- 基础设施 gate、行为 gate、任务成功 gate 的独立测试。

## 7. 根因关系图

```text
手工 DAG 含认知型 structured 节点
        +
没有 structured_predicate / a11y / external verifier
        |
        v
Guard 无法获得正反证据 -> UNKNOWN
        |
        +-> 不触发 causal diagnosis
        +-> 不触发 repair
        +-> fault injection 位置无法到达
        |
        v
Executor 继续更换动作并反复 subgoal_done
        |
        +-> completion checkpoint 几乎每步触发
        +-> 动作级重复检测被绕过
        +-> structured 标记绕过 nonvisual UNKNOWN 分支
        |
        v
大量模型调用 -> max_steps -> task success = 0
```

## 8. 下一步方案与验收标准

### P0：节点级 Verification Debt

实现与动作类型无关的节点级累计：

- 同一 node 连续 UNKNOWN 即累计；
- verification target 语义不变时加速累计；
- 只有 VERIFIED、CONTRADICTED 或真实 progress evidence 才清零；
- 软阈值要求更换证据策略；
- 硬阈值触发局部 DAG revision。

验收：c7 不再达到 `max_steps`，同一节点连续 UNKNOWN 不超过配置上限。

### P0：真正执行 DAG 局部重规划

将 `plan_revision_required` 从终止状态升级为运行时事件：

- 保留 unaffected VERIFIED nodes；
- 替换不可验证节点及必要下游；
- 新节点必须绑定 concrete evidence contract；
- 验证新 DAG 的依赖、可达性和 verifier availability；
- 在同一 episode 中继续执行。

验收：前两个案例不再以 `plan_revision_required` 作为终态。

### P0：Evidence Contract Validation

在任务开始前校验：

- `structured` 必须有 predicate、structured state source 或明确工具；
- `persistence` 必须有 verify action/API；
- `visual` 必须描述截图中可观察的具体状态；
- 私有推理、识别、理解类节点拒绝进入 DAG。

验收：c7 当前 S1 在运行前被拒绝或重写，而不是第 50 步才失败。

### P1：评测门槛拆分

报告至少输出：

- `infrastructure_gate_passed`
- `behavior_gate_passed`
- `task_success_rate`
- `fault_injection_validity`
- `guard_detection_rate_given_exposure`
- `repair_success_rate_given_detection`

验收：不再用单个 `gate_passed` 表达整个实验结论。

### P1：v9 三案例回归

通过标准：

- infrastructure failures = 0；
- `max_steps` = 0；
- terminal `plan_revision_required` = 0；
- repair budget exhaustion = 0；
- 三个 fault 均成功注入并暴露；
- 至少出现可评价的 detection/root/repair 轨迹；
- 任务成功率必须高于 v8 的 0/3。

### P2：扩大实验与论文对比

只有 v9 小样本通过后才运行跨任务长实验。对比时必须固定：

- 同一 Executor 模型；
- 同一 OSWorld task subset；
- 同一最大步数与环境 reset；
- 同一 fault manifest；
- 同一 API/推理预算统计口径。

最终同时报告任务成功率、故障恢复率、Guard 调用数、token、延迟、误干预率和 root accuracy，不能只比较单个成功率。

## 9. 当前可复用文件索引

### 代码

- Runtime：`/data/research/projects/StateGuard/stateguard/runtime/episode_runner.py`
- Checkpoint：`/data/research/projects/StateGuard/stateguard/runtime/checkpoint_policy.py`
- State machine：`/data/research/projects/StateGuard/stateguard/core/task_state.py`
- Action contract：`/data/research/projects/StateGuard/stateguard/core/action_capabilities.py`
- Guard：`/data/research/projects/StateGuard/stateguard/guard/state_guard.py`
- Localization：`/data/research/projects/StateGuard/stateguard/guard/localization.py`
- Repair：`/data/research/projects/StateGuard/stateguard/guard/repair.py`
- Trace：`/data/research/projects/StateGuard/stateguard/trace/`
- Auto-DAG prompt：`/data/research/projects/StateGuard/stateguard/planning/prompts.py`

### 文档

- v3 交接：`/data/research/projects/StateGuard/docs/V3_HANDOFF.md`
- 架构：`/data/research/projects/StateGuard/docs/ARCHITECTURE.md`
- Round 2.5：`/data/research/projects/StateGuard/docs/ROUND25_SUMMARY.md`
- Fault report：`/data/research/projects/StateGuard/docs/ROUND25_FAULT_REPORT.md`

### v8 结果

- 汇总：`/data/research/stateguard_runs/round3/stability_v8.json`
- 状态：`/data/research/stateguard_runs/round3/stability_v8_status.txt`
- 日志：`/data/research/stateguard_runs/round3/stability_v8.log`
- Episodes：`/data/research/stateguard_runs/poc_stability_v8/osworld_stability_v8-stateguard/episodes`

## 10. 当前阶段结论

StateGuard 当前已经具备较完整的工程骨架：显式 DAG、verified state、hybrid checkpoint、规则/MLLM Guard、trace、trust/suspicion、因果定位、最小 repair 和预算控制。最近通用修复有效减少了 parser failure、repair 失控和部分无限动作循环。

但当前结果仍应判定为 **REVISE**，而不是 GO。最严重的问题不再是某个 GUI 动作写错，而是证据契约、节点级 UNKNOWN 收敛和运行时重规划没有闭环。下一阶段应优先解决这三个系统性问题，再扩大实验规模；否则只会用更多 API 调用重复产生无法评价的 UNKNOWN 轨迹。
