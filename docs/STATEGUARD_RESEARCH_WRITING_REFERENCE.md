# StateGuard 研究成果与论文写作参考

> 生成日期：2026-09-30\
> 服务器仓库：`/data/research/projects/StateGuard`\
> 本地同步仓库：`/home/researcher/Documents/Codex/2026-07-16/ban/StateGuard-v10-natural`\
> 当前分支快照：`feature/v10-natural-failure`\
> 用途：供 GPT、论文作者和后续 Agent 撰写技术报告、论文实验章节与项目总结。\
> 数据口径：本文只汇总已有代码、日志和报告中能够复核的结果。不同任务集、模型或实验协议的数据不做无条件横向比较。

2026-09-30 已重新连接实验服务器并直接复核仓库、summary、paired report 和测试。服务器当前结果树约 8.1 GB，最新完整实验仍是 2026-09-21 的 stabilization v1；当前没有实验进程运行。服务器完整回归为 **261 passed in 9.39s**。

## 1. 一句话定位

StateGuard 是面向 GUI Agent 的运行时状态验证与故障恢复框架。它不把 Executor 的“我做完了”直接当作任务进度，而是将任务表示成可验证状态 DAG，在关键检查点独立收集证据、判断状态、追踪验证债务，并通过局部 repair 或 DAG replan 恢复执行。

当前工作最扎实的贡献不是声称已经超过完整 OSWorld SOTA，而是：

1. 建立了从 `动作 -> 状态证据 -> 验证 -> 故障定位 -> 修复/重规划 -> 最终评测` 的闭环；
2. 在保持 3/3 clean task 成功的同时，将 Guard 调用从 22 次降至 13 次，减少 **40.9%**；
3. 在受控故障实验中取得最高 **4/6（66.7%）** 的任务恢复率，并在 36-episode 矩阵中恢复 **7/21（33.3%）** 的故障任务；
4. 将早期 `0/5` 的可用 local replan 推进到稳定性实验中 3 次实际介入，其中 2 次出现在最终成功 episode；
5. 建成 training-ready、append-only 的完整取证链，4 个 canary 全部通过完整性检查，12-episode 稳定性实验中 11/12 通过严格完整性检查；
6. 将所有 73 个 UNKNOWN 都连接到终局 hindsight resolution，首次形成可直接研究 `UNKNOWN -> 补证 -> 结果` 的训练数据链；
7. 把 OSWorld 原本只有 scalar score 的评测结果扩展为可保存 top-level evaluator component 的弱监督记录。

## 2. 证据等级与引用规则

为了避免把机制测试包装成 benchmark 提升，建议报告中采用以下等级。

| 等级 | 数据来源 | 可以支持的结论 | 不应支持的结论 |
|---|---|---|---|
| A | 真实 OSWorld、自然失败、无注入 | 真实任务成功、UNKNOWN、成本、系统稳定性 | 未配对时不能宣称优于 Executor-only |
| B | 真实 OSWorld、声明式故障注入 | 检测、定位、恢复、进度保留能力 | 不能等同完整 OSWorld success rate |
| C | Fake backend / deterministic canary | 控制流、repair、日志和完整性正确 | 不能作为真实 GUI 性能 |
| D | 单元测试、离线 replay、审计 | 工程可靠性、接口与数据契约 | 不能作为任务完成能力 |

下文所有数字都标注其所属协议。论文主结果应优先使用 A/B；C/D 放在系统验证或附录。

## 3. 系统架构

### 3.1 端到端流程

```text
Task instruction + OSWorld observation
  -> Task compiler / manual graph
  -> semantic state DAG + executable frontier
  -> Executor proposes one atomic GUI action
  -> OSWorld executes action and returns observation
  -> CheckpointPolicy decides whether verification is needed
  -> AdaptiveEvidenceContract selects evidence source/verifier
  -> StateGuard returns VERIFIED / UNKNOWN / CONTRADICTED
       VERIFIED     -> commit evidence and advance state
       UNKNOWN      -> accumulate verification debt, reground/retry/replan
       CONTRADICTED -> causal localization, invalidate affected descendants,
                       create minimal RepairRequest
  -> completion gate only allows finish after required state is verified
  -> OSWorld evaluator produces final benchmark score
  -> training-ready logger joins every decision, call, artifact and outcome
```

### 3.2 任务状态与 DAG

核心思想是将 GUI 任务拆成语义状态，而不是固定点击序列。每个节点保存依赖、成功语义、证据模式、验证契约和运行状态。Executor 只能操作当前 executable frontier；上游故障会使受影响的下游节点变为 `STALE`，未受影响的已验证进度得到保留。

关键实现：

- `stateguard/core/schema.py`：TaskNode、ActionProposal、RepairRequest 等核心 schema；
- `stateguard/core/dependency_graph.py`：DAG、依赖关系和 executable frontier；
- `stateguard/core/task_state.py`：显式状态机和原子更新；
- `stateguard/planning/auto_dag.py`：模型生成语义 DAG；
- `stateguard/compiler/validator.py`：任务图合法性验证。

12-task Auto-DAG 审计中，12/12 graph 在首次生成后通过验证。该结果证明 schema 和生成约束稳定，但不能单独证明生成 DAG 的语义质量优于人工 DAG。

### 3.3 Executor

Executor 接收当前截图、frontier、task state、动作历史和 repair context，输出结构化 proposal：目标节点、意图、原子动作、预期效果、可观察性、`subgoal_done` 和 `is_finish`。

关键实现：

- `stateguard/executor/mllm_executor.py`：多模态请求、frontier guidance、重试；
- `stateguard/executor/parser.py`：动作与 finish proposal 解析、字段归一化；
- `stateguard/core/action_capabilities.py`：动作能力与 effect observability；
- `integrations/osworld/action_converter.py`：通用动作转 OSWorld/PyAutoGUI 动作。

v10 对模型/API failure 做了正常 episode 终止分类，避免单个调用异常中止整批实验。动作执行还会保存 proposed、parsed、backend-converted action、耗时、异常和环境 metadata。

### 3.4 Checkpoint 与 Guard

Guard 不再对每个原子动作都调用。CheckpointPolicy 组合三类触发：

- 强制检查：subgoal completion、finish、repair revalidation、stagnation；
- 风险检查：高风险节点更频繁，中风险节点较稀疏，低风险节点按需；
- cooldown：阻止同节点无信息增益的密集复查。

关键实现：

- `stateguard/runtime/checkpoint_policy.py`：dense/sparse/hybrid 调度与节点风险；
- `stateguard/guard/state_guard.py`：统一 Guard 入口；
- `stateguard/guard/backends/rule_backend.py`：结构化规则验证；
- `stateguard/guard/backends/mllm_backend.py`：视觉/语义验证；
- `stateguard/guard/backends/hybrid_backend.py`：规则优先、MLLM 回退；
- `stateguard/guard/parser.py`：Guard structured output 归一化。

### 3.5 Adaptive Verification 与 UNKNOWN

UNKNOWN 的语义不是“未知动作”，而是“当前证据无法支持 VERIFIED 或 CONTRADICTED”。系统为每个节点维护 AdaptiveEvidenceContract 和 verification debt，记录尝试过的 source、verifier、evidence signature 和信息增益。

关键实现：

- `stateguard/verification/contracts.py`：证据契约；
- `stateguard/verification/grounder.py`：证据源选择和 reground；
- `stateguard/runtime/adaptive_verification.py`：契约生命周期与 source switch；
- `stateguard/runtime/verification_debt.py`：UNKNOWN 债务和升级动作；
- `stateguard/verification/unknowns.py`：标准化 UNKNOWN taxonomy；
- `stateguard/verification/evidence_signature.py`：证据去重与信息增益判断。

当前 taxonomy 包括 evidence insufficient、verification target unclear、hidden/persistent state、contract unverifiable、Guard capability insufficient、environment/state missing 等类别。

### 3.6 Repair 与 local replan

StateGuard 明确区分两类恢复：

- **State repair**：世界状态与预期矛盾，定位 causal root，保留无关进度并修复受影响状态；
- **Plan repair / replan**：语义目标仍成立，但现有节点、证据契约或局部计划不可执行/不可验证，替换有限 DAG 子图。

关键实现：

- `stateguard/guard/localization.py`：故障根定位；
- `stateguard/guard/repair.py`：失效传播与 RepairRequest；
- `stateguard/runtime/repair_loop.py`：repair phase 和预算；
- `stateguard/planning/runtime_replanner.py`：模型生成局部 PlanPatch；
- `stateguard/planning/patch_validator.py`：循环、语义、可达性和 protected progress 检查；
- `stateguard/runtime/episode_runner.py`：repair/replan 运行时编排。

v10 修复了 replan 后 node ID cache、active repair root、contract、debt 和 budget 状态残留问题，并将多操作 task-state update 改为 shadow-copy 原子提交。

### 3.7 Training-ready logging

新日志层采用 dual-write，不破坏旧的 `trajectory.jsonl`、`guard_events.jsonl`、`execution_trace.jsonl`，同时新增：

- `events.jsonl`：所有 logical event，包括 finish、parse/API failure、retry 和环境异常；
- `model_calls.jsonl`：Executor/Guard/Grounder/Replanner 的精确 request、图片引用、raw/parsed response、错误、重试、模型、延迟和 usage；
- `artifact_manifest.jsonl`：相对路径、SHA256、role、尺寸、字节数和 producer ID；
- `interventions.jsonl`：decision、execution、immediate result、hindsight outcome；
- `unknown_resolutions.jsonl`：UNKNOWN 的 PENDING 到 VALID/FAILED/UNRESOLVED；
- `evaluator_result.json`：完整 final score、details、component probe 和异常。

关键实现：

- `stateguard/training_logging.py`：`TrainingReadyLogger`、`RecordingModelClient`；
- `experiments/poc/logging.py`：新旧格式 dual-write；
- `scripts/check_training_ready_episode.py`：跨 event/call/action/artifact/evaluator 的完整性检查；
- `scripts/analyze_stabilization.py`：稳定性统计。

## 4. 可使用的实验结果总表

### 4.1 结果概览

| 实验 | 协议 | 样本 | 最值得引用的结果 | 证据等级 |
|---|---|---:|---|---|
| Round 2 clean A/B/C | 真实 OSWorld clean | 3 tasks x 3 settings | sparse 保持 3/3 成功，Guard calls 22 -> 13（-40.9%） | A，小样本 |
| Round 2 sparse fault smoke | 真实 OSWorld + 注入故障 | 6 | 4/6 recovery（66.7%），1/6 root localization | B |
| Round 2.5 hybrid fault smoke | 真实 OSWorld + 注入故障 | 6 | 3/6 recovery，clean 3/3，开销仍比 dense 低 41% | B |
| v8 frozen baseline | 真实 OSWorld + 注入故障 | 3 | 0/3 success，0 useful contradiction/repair | B，历史基线 |
| v9 stability matrix | 真实 OSWorld clean/fault | 36 | injection 21/21；recovery 7/21；clean 4/15；root 5/21 | A/B |
| Training logging canary | 3 real + 1 deterministic | 4 | 4/4 integrity PASS；真实任务 1/3；fault canary 1/1 recovered | A/C |
| Stabilization v1 | 真实 OSWorld mixed tasks | 12 | 2/12 success；354 model calls；true schema/semantic failure 2.8%；73/73 UNKNOWN 有终局记录 | A |
| v10 natural paired canary | 同任务/seed Executor-only vs StateGuard | 4 pairs | 0 rescued、1 preserved、1 regression、2 unresolved；paired delta -25pp | A，严格 paired |
| Evaluator audit | 真实 OSWorld initial states | 5 task types | 成功恢复 top-level evaluator component weak supervision | D/系统审计 |

### 4.2 效率提升：Guard 调用减少 40.9%

Round 2 在 Chrome、file、Writer 三个 clean task 上比较 dense 与 sparse：

| 设置 | Guard calls | Clean success |
|---|---:|---:|
| Dense A | 22 | 3/3 |
| Sparse B | 13 | 3/3 |
| Auto-DAG sparse C | 35 | 2/3 |

Sparse B 相比 dense A 少 9 次 Guard 调用，即 **40.9% reduction**，且样本内 clean success 没有下降。这是目前最清晰、最适合放进摘要或主表的效率结果。

推荐写法：

> On a three-task clean OSWorld smoke set, sparse state-level verification reduced Guard invocations by 40.9% (22 to 13) while preserving all successful task outcomes (3/3).

限定：样本只有 3 个任务，不应扩写成完整 OSWorld 上的平均节省。

### 4.3 故障恢复与定位

Round 2 sparse fault smoke：

- fault injection validity：6/6；
- task recovery：4/6（66.7%）；
- correct first-root localization：1/6；
- 两个失败分别是 file wrong-value 和 Writer earlier-corruption。

Round 2.5 hybrid fault smoke：

- fault injection validity：6/6；
- task recovery：3/6（50.0%）；
- localization：0/6；
- clean task success：3/3；
- clean Guard calls：13，仍比 dense 少约 41%。

v9 36-episode stability matrix：

- 21/21 fault successfully injected（100%）；
- 7/21 fault episodes recovered（33.3%）；
- 5/21 first root correct（23.8%）；
- 4/15 clean episodes succeeded（26.7%）；
- earlier-state-corruption 的可用案例中有 2 个成功定位早期根节点；
- 327 Guard calls、1,171 Executor calls、137 contracts、167 UNKNOWN checkpoints。

可以合理强调：StateGuard 已在多类真实 GUI 故障中展示“检测后恢复”的可行性；但 causal localization 仍明显弱于 recovery，恢复有时来自 Executor 自纠，而不是 Guard 准确定位。

### 4.4 从 v8 到 v9/v10 的框架进步

冻结的 v8 三案例结果：

- task success：0/3；
- 两个 `plan_revision_required`，一个 `max_steps`；
- useful contradiction/repair：0；
- 最坏案例产生 49 次 UNKNOWN 后仍跑满 50 步。

v9 开始能够完成完整 fault pipeline：21 个注入故障中恢复 7 个，并正确定位 5 个 first root。虽然任务集不完全等价，不能把 `0% -> 33%` 当成严格 paired uplift，但它可以作为系统能力从“没有恢复轨迹”到“出现可量化恢复轨迹”的版本演进证据。

v9 早期矩阵中的主要框架失败：

- `guard_parse_failed`：10/36（27.8% episodes）；
- `plan_revision_failed`：5/36（13.9% episodes）；
- local replan：5 次触发，0 次成功应用。

Stabilization v1 的 12 episodes 中：

- 没有 episode 以 `guard_parse_failed` 或 `plan_revision_failed` 终止；
- 3 次 replan 被记录并进入完整 intervention lifecycle；
- 2 次 replan 出现在最终成功的 `d53ff5ee...` episode，1 次出现在失败 episode；
- 不能据此证明 replan 的因果 uplift，但已证明 replan 从“协议层 0/5 可用”进入真实运行路径。

这是一个有利但诚实的版本进步口径：**框架失败显著收敛，性能瓶颈转移到证据质量和 Agent 能力。**

### 4.5 Structured output 稳定性

旧 canary 将 71 个事件统称为 parse failure。重新审计发现：

- 12 个 schema missing-field；
- 55 个 blocked-action policy rejection；
- 1 个 frontier policy rejection；
- 3 个 replanner semantic validation failure。

Stabilization v1 的 354 次 model calls 中：

- true schema/semantic failures：10（2.8%）；
- missing-field：6（1.7%）；
- invalid-value：1（0.3%）；
- replanner semantic validation：3（0.8%）；
- blocked-action policy rejection：46（13.0%），已与 parse failure 分离；
- provider retry：1（0.3%）；
- domain retry intervention：10（2.8%）。

最稳妥的贡献表述不是“parse failure 从 71 降到 10”，因为分母和旧标签口径不同，而是：

> After separating policy rejection from true structured-output errors, only 10 of 354 model calls (2.8%) exhibited schema or semantic validation failures in the stabilization run.

### 4.6 UNKNOWN lifecycle 与预算控制

Training logging canary 的 37 个真实 UNKNOWN 全部可以追踪到后续事件。Stabilization v1 进一步为 73/73 UNKNOWN 写入终局 resolution：

| Resolution | 数量 | 占比 |
|---|---:|---:|
| VALID by later state | 12 | 16.4% |
| VALID by final evaluator | 2 | 2.7% |
| UNRESOLVED by episode hindsight | 59 | 80.8% |
| Missing outcome | 0 | 0% |

这意味着 **100% UNKNOWN lifecycle coverage**，可用于构造 `UNKNOWN -> evidence acquisition -> hindsight outcome` 数据。需要同时承认 59/73 最终未解决，当前 Guard 的证据使用能力仍是主要瓶颈。

预算机制将失控循环转化为显式终止：12 个 stabilization episodes 中有 9 个以 `unknown_budget_exhausted` 结束。它降低了无界成本，但当前阈值和 source-switch 机制尚未带来较高成功率。

### 4.7 Training-ready 数据完整性

Training logging canary 覆盖 3 个真实 OSWorld episode 和 1 个 deterministic fault episode：

- 4/4 episode integrity PASS；
- 163 logical events；
- 186 model calls；
- 77 environment transitions；
- 450 artifact manifest rows；
- 所有 screenshot 的文件、SHA256 和 byte size 一致；
- successful real episode 和 controlled-fault episode 均保留 finish decision；
- fault canary 形成 contradiction、repair request、repair execution、finish 和 evaluator PASS 的完整闭环；
- 当时 regression suite：256 passed。

Stabilization v1：

- 1,172 events；
- 354 model calls；
- 185 environment steps；
- 994 artifact rows；
- 107 MB run size；
- 11/12 episodes 通过严格 integrity check；
- 唯一失败是 evaluator hindsight 将 `max_steps` 改成 completed 后缺少显式 finish event，其余 request/response/action/state/artifact/evaluator join 通过。

该结果支持的论文贡献是“可恢复的训练数据基础设施”，而不是任务准确率提升。

### 4.8 OSWorld evaluator 弱监督

审计证明 OSWorld 原生 `DesktopEnv.evaluate()` 只返回 scalar；此前 `EvaluationResult.details` 实际只有 `task_id`。新增 component probe 在不改变 native final score 的前提下，逐项保存：

- metric/component 名称；
- result getter 和 expected getter 配置；
- observed/expected 摘要；
- component score 和 pass/fail；
- artifact path、SHA256、byte size；
- exception；
- conjunction 和 raw evaluator output。

真实验证覆盖 5 类任务：Chrome、multi-app/file、terminal、Writer、Calc/PDF。单次评测耗时约 2.4 至 48.1 秒。该信息可作为 final-state top-level weak supervision，但不能直接提供 cell/paragraph 内部差异、动作级 failure root 或 DAG milestone ground truth。

### 4.9 严格 paired natural-failure canary

服务器已经存在 4 组同任务、同 seed 的 v10 Executor-only vs StateGuard canary。这是目前最接近因果性能比较的数据：

| Pair outcome | 数量 |
|---|---:|
| RESCUED | 0 |
| PRESERVED | 1 |
| REGRESSION | 1 |
| UNRESOLVED | 2 |

聚合结果：Executor-only 为 2/4 success、116 steps、116 model calls；StateGuard 为 1/4 success、158 steps、380 model calls。natural-failure rescue rate 为 0%，regression rate 为 50%，net rescue 为 -1，paired success delta 为 -25 percentage points。

StateGuard 路径产生 109 Guard calls、77 UNKNOWN、2 repair cycles 和 5/5 applied local replans，但 evidence-source switch 仍为 0。唯一 regression 是 terminal 类任务 `4127319a...`：baseline 7 步成功，StateGuard 45 步后 `repair_failed`。另外两个 baseline failure 虽触发 local replan，仍未恢复。

该负结果不能作为性能贡献，但它是有价值的诊断成果：严格 paired protocol 揭示了 Guard 的高 UNKNOWN、错误干预和额外成本，并证明当前系统能够计算真实 net rescue，而不是只报告 intervention count。

## 5. 与 baseline 和论文结果的正确比较方式

### 5.1 当前可成立的内部 baseline 对比

| 指标 | Baseline | StateGuard 改进结果 | 建议结论 |
|---|---:|---:|---|
| Clean Guard calls | dense 22 | sparse 13 | -40.9%，clean 3/3 不变 |
| v8 useful recovery | 0/3 | v9 7/21；sparse smoke 4/6 | 能力从无恢复轨迹发展为可量化恢复，非严格 paired |
| v9 early local replan | 0/5 applied | stabilization 3 interventions | replan 已进入真实运行路径，尚无因果 uplift |
| v9 guard parse terminal failures | 10/36 episodes | stabilization 0/12 terminations | 框架稳定性明显改善，协议不同 |
| UNKNOWN outcome coverage | 后续结果不完整 | 73/73 terminal resolution | 100% lifecycle 可追踪 |
| evaluator details | task ID + scalar | top-level components + artifacts | 弱监督信息显著增加 |
| model response persistence | aggregate only | 4 roles exact request/response | 可复现性和训练可用性提升 |

需要单独列出严格 paired 反例：v10 canary 中 StateGuard success 为 1/4，低于 Executor-only 的 2/4。任何对 task success 的正向宣传都必须等待修复后扩大 paired 样本，不能用非配对 v9 数据覆盖该结果。

服务器还存在一个 36 vs 36 的 v9 aggregate：StateGuard 11/36，executor baseline 3/36。这个表面上是 +22.2pp / 3.67x，但两者 seed 和 Executor provider 不同，且 fault exposure validity 也不同。因此只能列作历史观察，不能作为 StateGuard 的 baseline uplift。

### 5.2 与 UI-MOPD Table 2 的关系

UI-MOPD Table 2 报告的是完整 benchmark/protocol 下的 task success，例如 Qwen3-VL-8B-Thinking 在 OSWorld 的 33.9%。当前 StateGuard 数字主要来自 3、6、12 或 36 episode 的诊断子集，并且模型、任务选择、步数、DAG 和 fault protocol 不同。因此：

- **不能**直接声称 StateGuard 的 66.7% recovery 超过 UI-MOPD 的 33.9% OSWorld success；
- **不能**把 stabilization 的 16.7% 与论文 33.9% 当作模型能力比较；
- 可以说当前研究关注的是正交问题：在同一个 imperfect Executor 上，通过 runtime verification/rescue 改善失败恢复和数据可追踪性；
- 真正论文级性能对比需要同任务、同 seed、同 Executor、同 step budget 的 executor-only vs StateGuard paired experiment。

### 5.3 最值得补跑的主实验

v10 已经定义并在 4-pair canary 上执行严格 paired natural-failure protocol：

```text
RESCUED    = baseline fail, StateGuard success
PRESERVED  = baseline success, StateGuard success
REGRESSION = baseline success, StateGuard fail
UNRESOLVED = baseline fail, StateGuard fail

rescue_rate          = RESCUED / (RESCUED + UNRESOLVED)
regression_rate      = REGRESSION / (REGRESSION + PRESERVED)
net_rescue           = RESCUED - REGRESSION
paired_success_delta = (SG successes - baseline successes) / pairs
```

实现位于 `docs/V10_NATURAL_FAILURE_DESIGN.md`、`experiments/poc/natural_failures.py` 和 `scripts/report_natural_failure.py`。当前 canary 是负结果，必须先降低 UNKNOWN/错误干预并在相同 4 pairs 上达到 `net_rescue >= 0`，随后才能扩大样本并声称 StateGuard 对自然失败产生净提升。

## 6. 可写成论文贡献的内容

### C1. State-centric runtime verification

不同于仅检查动作格式或让 Agent 自我反思，StateGuard 将任务完成定义为 DAG 中 required semantic states 的独立证据闭包。Executor 决定如何操作，Guard 决定状态是否真正成立。

### C2. Cost-aware sparse/hybrid checking

CheckpointPolicy 根据 completion、stagnation、repair 和 causal risk 选择检查时机。小规模真实 OSWorld clean 测试表明，Guard 调用减少 40.9%，成功结果保持 3/3。

### C3. Evidence debt instead of UNKNOWN-as-failure

UNKNOWN 不被强制转换为 FAILED。系统记录缺失证据、已尝试 source/verifier、信息增益和 debt，并通过 bounded reground/retry/replan 升级处理。73/73 UNKNOWN 获得可连接的 hindsight outcome。

### C4. Causal repair and protected progress

发生 contradiction 时，系统定位 earliest plausible root，失效受影响 descendants，并保留 verified/protected progress。RepairRequest 和 PlanPatch 分离世界状态错误与计划/证据错误。

### C5. Validated local DAG replanning

Replanner 只接收 bounded local context，输出局部 patch；本地 validator 强制语义不变量、无环、required-node 可达和 protected progress。v10 还对 node identity、contract、debt 和 budget 做一致性迁移。

### C6. Training-ready provenance

系统以稳定 ID 连接 logical event、model call、image artifact、action receipt、state delta、intervention 和 evaluator outcome。该设计允许事后重建 `state_before -> decision -> action -> state_after -> judgement -> hindsight`，并减少未来训练数据中不可恢复的信息损失。

### C7. Evaluator-derived weak supervision

在 OSWorld scalar evaluator 之上进行不改变 benchmark score 的 component probe，恢复 observed/expected、top-level pass/fail 和 artifact identity，为 final-state condition supervision 提供可用起点。

## 7. 当前主要问题

### 7.1 方法/模型层

1. UNKNOWN 仍占主导。Stabilization 中 Guard UNKNOWN 73 次，UNKNOWN rate 79.3%，9/12 episode 因 UNKNOWN budget 终止。
2. taxonomy 塌缩。71/73 live UNKNOWN 被分到 evidence insufficient，无法细致区分 Guard 能力不足、contract 不可验证和环境状态缺失。
3. source switching 尚未被证明。该批次 `evidence_source_switch_count=0`、`contract_revision_count=0`。
4. contradiction 和 repair 数据不足。Stabilization 没有自然 contradiction/repair cycle，失败分布过于单一。
5. first-root localization 仍弱。v9 为 5/21，早期 replay 曾只有 1/6；下游首次可见矛盾容易被误判为根因。
6. Executor 仍是主要性能瓶颈之一，包括 premature finish、GUI wandering、长序列操作失败和结构化输出错误。

### 7.2 控制流层

1. 一个成功 episode 由 final evaluator 从 max-steps 改为 completed，但没有显式 evaluator-derived finish event。
2. 一条 replan 路径曾让 consecutive UNKNOWN 达到 7，超过配置上限 6；budget termination 必须优先于 replan continuation。
3. 当前 replan 介入与成功 episode 相关，但没有 matched counterfactual，不能证明因果提升。

### 7.3 评测层

1. component probe 是 final-only，且部分 getter/metric 会改变环境或花费数十秒。
2. top-level component 仍可能把多个 cell、paragraph 或 rule 聚合在一个 metric 内。
3. evaluator gold、reference file 和 expected value 只能作为 annotation，绝不能放入在线 Guard input，否则会产生 benchmark leakage。

### 7.4 实验层

1. 当前最强效率结果只有 3 个 clean tasks；恢复结果最多 21 个 fault episodes。
2. 已有 4-pair canary，但结果为净回归；尚缺修复后的中等规模 paired natural-failure 主表。
3. 不同历史轮次使用过不同模型、prompt、checkpoint policy 和 task subset，只适合作为版本演进，不适合作为严格 ablation。
4. Stabilization v1 当前是 NO-GO for 100+ rollout，原因是 finish invariant、budget precedence、failure diversity 和 source switching 尚未全部通过。

## 8. 建议论文表格

### Table A：Verification efficiency

| Method | Tasks | Success | Guard calls | Relative calls |
|---|---:|---:|---:|---:|
| Dense verification | 3 | 3/3 | 22 | 100% |
| Sparse verification | 3 | 3/3 | 13 | 59.1% |
| Hybrid verification | 3 | 3/3 | 13 | 59.1% |

Caption 建议明确这是 clean smoke subset。

### Table B：Controlled fault capability

| Version | Faults | Injection valid | Recovery | First-root accuracy |
|---|---:|---:|---:|---:|
| Round 2 sparse | 6 | 6/6 | 4/6 | 1/6 |
| Round 2.5 hybrid | 6 | 6/6 | 3/6 | 0/6 |
| v9 matrix | 21 | 21/21 | 7/21 | 5/21 |

注意这些版本的 task mix/policy 不完全一致，主文应避免将三行解释为单调版本提升。

### Table C：Data integrity and observability

| Metric | Logging canary | Stabilization v1 |
|---|---:|---:|
| Episodes | 4 | 12 |
| Integrity pass | 4/4 | 11/12 |
| Logical events | 163 | 1,172 |
| Model calls | 186 | 354 |
| Environment transitions | 77 | 185 |
| Artifact rows | 450 | 994 |
| UNKNOWN with traceable outcome | 37/37 later trace | 73/73 terminal resolution |

### Table D：Structured-output robustness

| Outcome | Count | Share of 354 calls |
|---|---:|---:|
| True schema/semantic failure | 10 | 2.8% |
| Blocked-action policy rejection | 46 | 13.0% |
| Frontier policy rejection | 3 | 0.8% |
| Provider retry | 1 | 0.3% |

## 9. 可直接使用的摘要素材

下面这段可作为写作起点，但正式论文应在 paired v10 结果完成后替换性能句：

> We introduce StateGuard, a runtime verification and recovery framework for GUI agents that separates action generation from state acceptance. StateGuard represents tasks as semantic state DAGs, verifies high-value transitions under adaptive evidence contracts, accumulates verification debt for inconclusive observations, and applies bounded state repair or validated local replanning while preserving unaffected progress. On a three-task OSWorld clean subset, sparse state-level verification reduced Guard calls by 40.9% without reducing observed task success. Across controlled-fault evaluations, the system recovered up to 4 of 6 injected failures, while a broader 36-episode matrix yielded 100% valid fault injection, 7/21 recovery, and 5/21 first-root localization. We further contribute an append-only provenance layer that joins model calls, screenshots, actions, state deltas, interventions, and evaluator outcomes; all 73 UNKNOWN decisions in a 12-episode stabilization run received terminal hindsight records, and true structured-output failures accounted for 2.8% of 354 model calls.

中文概括：

> StateGuard 将 GUI Agent 的“动作执行”与“状态验收”解耦，通过语义状态 DAG、自适应证据契约、验证债务、因果修复和局部重规划构建运行时安全网。在小规模真实 OSWorld clean 测试中，该方法将 Guard 调用降低 40.9% 且保持 3/3 成功；受控故障测试中最高恢复 4/6。系统还建立了可训练的完整取证链，在 12-episode 稳定性实验中记录 1,172 个逻辑事件，并为 73/73 UNKNOWN 建立终局追踪。

## 10. 不应写入论文的夸大表述

以下说法目前没有证据支持：

- “StateGuard 超过 UI-MOPD 或 Qwen3-VL-8B-Thinking 的 33.9% OSWorld 准确率”；
- “replan 显著提升任务成功率”；
- “StateGuard 在完整 OSWorld 上达到 66.7%”；
- “UNKNOWN 已经被解决”；73 个中只有 14 个最终转为 VALID，59 个仍未解决；
- “evaluator 提供 cell/paragraph-level ground truth”；当前只恢复 top-level components；
- “source switching 已有效工作”；当前批次实际切换次数为 0；
- “已安全开始无监控 100+ rollout”；最新 stabilization gate 仍为 NO-GO。

可以积极表述为：框架已经把不可见、不可追踪的失败变成结构化、有限预算、可做 hindsight analysis 的数据；核心性能提升还需要 matched paired study 证明。

## 11. 服务器结果与代码路径索引

### 11.1 主要实验结果

- v8 baseline：`/data/research/stateguard_runs/round3/stability_v8.json`
- v8 episodes：`/data/research/stateguard_runs/poc_stability_v8/osworld_stability_v8-stateguard/episodes`
- Auto-DAG audit：`/data/research/stateguard_runs/auto_dag_audit/`
- v9 recovery canary：`/data/research/stateguard_runs/poc_stability_v9_recovery_canary`
- v10 paired canary report：`/data/research/stateguard_runs/natural_failure_v10_pipeline/canary_report.json`
- training logging canary：`/data/research/stateguard_runs/training_logging_v1_canary/`
- training logging episodes：`/data/research/stateguard_runs/training_logging_v1_canary/osworld_training_logging_canary-stateguard/episodes`
- evaluator audit：`/data/research/stateguard_runs/evaluator_audit_v1/results.json`
- stabilization root：`/data/research/stateguard_runs/stabilization_v1/`
- stabilization summary：`/data/research/stateguard_runs/stabilization_v1/stability_report.partial.json`
- stabilization integrity：`/data/research/stateguard_runs/stabilization_v1/integrity_report.json`
- stabilization baseline audit：`/data/research/stateguard_runs/stabilization_v1/baseline_audit.json`
- stabilization episodes：`/data/research/stateguard_runs/stabilization_v1/osworld_stabilization_v1-stateguard/episodes`

### 11.2 v10 paired natural-failure 预留目录

- `/data/research/stateguard_runs/natural_failure_v10_canary_executor`
- `/data/research/stateguard_runs/natural_failure_v10_canary_stateguard`
- `/data/research/stateguard_runs/natural_failure_v10_executor`
- `/data/research/stateguard_runs/natural_failure_v10_stateguard`
- `/data/research/stateguard_runs/natural_failure_v10_pipeline`

### 11.3 主要文档

- `docs/ROUND2_SUMMARY.md`：sparse 与 Auto-DAG 结果；
- `docs/ROUND25_SUMMARY.md`、`docs/ROUND25_FAULT_REPORT.md`：hybrid clean/fault；
- `docs/V8_BASELINE.md`：冻结基线；
- `docs/V9_MATRIX_REPORT.md`：36-episode 矩阵；
- `docs/V9_ADAPTIVE_VERIFICATION.md`：v9 方法；
- `docs/V10_NATURAL_FAILURE_DESIGN.md`：paired natural-failure 设计；
- `docs/V10_CODE_AUDIT.md`：v10 bug audit；
- `docs/TRAINING_DATA_AUDIT.md`：旧日志缺口；
- `docs/TRAINING_READY_LOGGING_REPORT.md`：日志补丁和 canary；
- `docs/OSWORLD_EVALUATOR_AUDIT.md`：evaluator 真实输出；
- `docs/STABILIZATION_PHASE_V1.md`：stabilization 实现；
- `docs/STABILIZATION_V1_RESULTS.md`：12-episode 结果与 Go/No-Go。

## 12. 复现与核验建议

在引用任何数字前，建议执行：

```bash
cd /data/research/projects/StateGuard

# 回归测试
.venv-stateguard/bin/pytest -q

# 稳定性结果汇总
.venv-stateguard/bin/python scripts/analyze_stabilization.py \
  /data/research/stateguard_runs/stabilization_v1/osworld_stabilization_v1-stateguard/episodes

# 单 episode training-ready integrity
.venv-stateguard/bin/python scripts/check_training_ready_episode.py \
  /data/research/stateguard_runs/stabilization_v1/osworld_stabilization_v1-stateguard/episodes/<episode-id>
```

当前本地工作树包含尚未提交的 training logging、evaluator probe 和 stabilization 改动。发布 GitHub 前应先在服务器恢复连接后重跑完整测试、检查 secret 和大文件，再拆成至少两个清晰 commit：

1. `training-ready logging and evaluator supervision`；
2. `stabilization budgets, UNKNOWN taxonomy and resolution lifecycle`。

## 13. 当前结论

StateGuard 已经形成一套功能完整、可审计的 GUI Agent runtime verification 原型。最可信的成果是 verification efficiency、故障恢复可行性、框架失败收敛和训练数据可追踪性：clean smoke 上 Guard 开销下降 40.9%，受控故障最高恢复 66.7%，真实稳定性运行中 structured-output failure 仅占 model calls 的 2.8%，所有 73 个 UNKNOWN 都有终局记录。

同时，当前数据不仅不足以声称完整 OSWorld accuracy 超过 baseline，4-pair 严格 canary 还显示 `paired_success_delta=-25pp`。下一篇主结果必须来自修复后的扩大 paired experiment，并报告 rescue rate、regression rate、net rescue、额外调用/延迟以及 UNKNOWN/repair/replan 机制分解。现阶段最准确也最有说服力的叙事是：**StateGuard 已经把 GUI Agent 的不可控失败转化为可验证、可限额、可诊断和可训练的数据闭环；它在受控故障中展示了恢复能力，但自然失败上的净任务收益尚未实现。**
