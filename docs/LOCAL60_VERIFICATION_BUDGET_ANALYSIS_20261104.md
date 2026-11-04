# Local60 验证预算终止与 StructAgent 基线对比

审计日期：2026-11-04。仅分析既有数据，不修改运行代码，不重新执行任务。

## 核心结论

1. 本轮已结束全部 60 个任务：26 个原生评分满分、7 个零分、1 个部分分、26 个 verification_budget 终止且没有原生评分。不是此前的 24 个终止任务快照。
2. 与旧版相同 60 个 task ID 配对：23 个保持满分，3 个从零分变为满分，9 个从满分变为非满分。因此已确认满分率为 32/60 -> 26/60，即 53.33% -> 43.33%，下降 10 个百分点。
3. 3 个新增满分中，2 个是操作任务成功，1 个是 benchmark 对正确输出 FAIL 的不可行任务给予满分，不能写成新增 3 个 GUI 任务完成。
4. 终止任务不能统一称为误拦截。既有明显执行错误，也有证据读取缺口、验证解释失真，以及不可行任务的退出路径被预算中断。
5. 最明确的机制问题是：同一 outcome 的三次验证次数，会在修复的中间导航步骤被迅速耗尽。它不是“完整修复尝试三次仍然失败”的预算。

## 数据来源与口径

服务器新结果根目录：

`/data/research/fusion-runs/fusion_local60_20261103_01`

新任务结果前缀：

`/data/research/fusion-runs/fusion_local60_20261103_01/results/pyautogui/screenshot/vllm_qwen35-vl_planner_fusion_local60_20261103_01`

下文任务路径为此前缀加 `/<domain>/<完整 task ID>/`。主要检查 `traj.jsonl`、`runtime.log`、`progressive_verification/*.json`、`boundary_verify_debug/*.json`、`termination.json`、`result.txt` 和 task evaluator 定义。没有把模型的 reason 文本直接当成环境真值；重要争议结合实际 action 和结构化探针内容核对。

基线运行：`/data/research/structagent-repro/runs/main60_20261018_full`。

本地基线结果包：`/home/researcher/Downloads/StructAgent_main60_20261021/StructAgent_main60_analysis_light`。

本地新结果轻量副本：`/home/researcher/Documents/Codex/2026-07-16/ban/outputs/fusion_local60_20261103_01_audit`。

两个运行采用相同 60 个任务和本地 Qwen3.5-9B / 27B 模型组合，但不是随机重复、多种子消融；在线网页状态、相对日期和模型执行轨迹仍可能不同。下面是一次配对运行的观察差异，不是融合模块的因果增益估计。

## 完整结果对比

| 指标 | 旧 StructAgent | 本轮融合 |
|---|---:|---:|
| 选定任务 | 60 | 60 |
| 有原生评分 | 57 | 34 |
| score = 1 | 32 | 26 |
| score = 0 | 24 | 7 |
| 0 < score < 1 | 1 | 1 |
| 无原生评分 | 3 | 26 |
| 全部选定任务中的已确认满分率 | 53.33% | 43.33% |

不能用 26/34=76.47% 宣称整体成功率提升：34 是被验证机制筛选后才进入原生评分的子集。26 个终止任务的状态必须保留为未评分，而不是伪造原生 0 分或推测 1 分。

| 配对变化 | 数量 |
|---|---:|
| 旧满分 -> 新满分 | 23 |
| 旧零分 -> 新满分 | 3 |
| 旧满分 -> 新 verification_budget | 8 |
| 旧满分 -> 新零分 | 1 |
| 旧零分 -> 新零分 | 6 |
| 旧零分 -> 新 verification_budget | 15 |
| 旧未评分 -> 新 verification_budget | 3 |
| 旧部分分 -> 新部分分 | 1 |

部分分任务 `vlc/fba2c100-79e8-42df-ae74-b592418d54f4`：0.8510417343321308 -> 0.906492567397591，增加约 0.05545，但仍不是满分。

## 原先 24 个终止任务的逐项归类

分类是人工轨迹诊断，非新增 evaluator 标签，也不是对终止时原生得分的反事实预测。

- A：存在明显未完成步骤或错误操作。可以同时存在过早停止问题。
- B：证据链不足，现有材料不足以确定终态是否正确。
- C：验证解释有明显争议，属于疑似误拦截；并不等于证明任务已经完整成功。
- D：task evaluator 定义为 infeasible，需要单独审查可行性判断与 FAIL 退出路径。此信息只用于离线审计，绝不能注入代理输入。

按主要问题分组，原 24 个为 A=14、B=4、C=2、D=4。新增两个 VS Code 终止任务后为 A=15、B=4、C=2、D=5。类别存在次要交叉，不能把 C 的两个候选直接加到成功数。

| Domain / Task ID | 类别 | 轨迹依据及限制 |
|---|---|---|
| chrome / 2888b4e6-5b47-4b57-8bf5-c73827890774 | B | step 30 曾显示 L 和 Sales & Discounts，但不能确定 50% 条件；step 31 页面变为 about:blank/Loading。混合网页加载与具体折扣证据缺口，不足以判为已经完成。 |
| chrome / da46d875-6b82-4681-9284-653b0c7ae241 | A | step 22/25/27 在日期、时间列表反复滚动；没有确认目标 10:15 被选中。验证理由又混入尚未进入的姓名、邮箱阶段，存在验收范围扩张。 |
| chrome / 6c4c23a1-42a4-43cc-9db1-2f86ff3738cc | A | 出发地仍为 SIN，不是 SEA。但 step 13/14/15 三次验证跨越“返回表单、打开起点下拉框”，尚未执行修复计划后面的输入和选择 SEA 就被终止。 |
| gimp / f4aec372-4fb0-4df5-a52b-79e0e2a5d6ce | A | 点击菜单和画布未产生目标选区；最终使用 Crop、整画布选中，三角形位置仍不对。验收还把后续居中要求混入 triangle_selected 子目标。 |
| gimp / d16c99dc-2a1e-46f2-b350-d97c86c85c15 | A | step 5/7/9 仍停在 Scale Image 而非目标图层缩放，显示高度 947 而不是 512；不能因返回 UNKNOWN 就当成纯证据缺口。 |
| libreoffice_calc / aa3a8974-2e85-438b-b29e-a64df44deb4b | A | 早期两次 DONE 没有 PDF 证据；后续停在 PDF Options 中滚动，未完成目标页缩放和导出流程。探针也缺少页样式与导出产物信息。 |
| libreoffice_calc / 04d9aeaf-7bed-4024-bedb-e10e6f00eb7f | A | step 24 实际输入 =(Sheet1.B2-Sheet1.B1)/Sheet1.B1，引用表头；结构与画面报告 #VALUE!，此前年份列也曾写成 2..6。 |
| libreoffice_impress / a669ef01-ded5-4099-9ea9-25e99b569840 | C | 常规验证 step 8 判对齐且无 bullet；渐进验证说仍有 bullet、嵌套。结构记录 p5 (title) 且后续缩进变化，不支持单凭自然语言断言其仍嵌套。但真实左右缩进数值未记录，不能确认最终正确。 |
| libreoffice_impress / 358aa0a7-6677-453f-ae35-e440f004c31e | C | UNO 已执行全体字体设置；探针列出的 31 个 txt/title 都为 Liberation Sans Narrow。验证却把 Slide 17 的 pic 图形属性当成文本框反例。另有 8 张 slide 未展示，所以仍有覆盖缺口，不能证明全部 28 页和保存状态均正确。 |
| libreoffice_writer / 0810415c-bde4-4443-9047-d5f70165a697 | A | 结构探针显示第一正文段 lh=200，第二正文段 lh=100，确有未完成。最终截图判断又误称两个都未改变，不能照抄模型最终 reason。 |
| libreoffice_writer / 0e47de2a-32e0-456c-a366-8c607ef7a9d2 | B | step 4..7 调用 op_page_numbers(bottom_left)，但探针只列正文、不列页脚。之后 GUI 出现 Delete footer?，可能把已有页脚再次切换。缺 footer 字段、页码锚点和保存状态，不能确认是否先完成后被破坏。 |
| libreoffice_writer / bb8ccc78-479f-4a2f-a71e-d565e439436b | D | 实时协作任务原生为 infeasible；旧版第 12 步输出 FAIL 得 1。新版第 4/5/6 步核验不存在的协作完成态，先被预算中断，没有走到正确的不可行退出。 |
| libreoffice_writer / adf5e2c3-64c7-4644-b7b6-d2f0167927e7 | A | 引用条目有部分进展，但目标第四段的数字交叉引用没有完成，后续滚动和菜单操作未提供完成证据。 |
| multi_apps / 7ff48d5b-2df2-49da-b500-a5150ffc7f18 | A | 搜索结果是 24 相关影视内容，而非福田自助设备地址；中文输入/搜索执行路径有问题，后续文档亦未完成。 |
| multi_apps / 3680a5ee-6870-426a-a997-eba929a0d25c | A | 多次脚本只读 A1，或调用不可靠的 ODF 对象接口；step 10 把 with 复合语句放在分号之后，存在明确语法问题。还加入未被任务要求的删除源文件。CSV 内容和打开 Calc 均未证明；并有 stdout 缺失。 |
| multi_apps / ee9a3c83-f437-4879-8918-be5efbb9fac7 | B | 多次转换和 ls；step 19 检查目标 CSV，但验证输入没有命令输出。命令也存在运行风险，不能因为执行过转换就断定产物存在。 |
| multi_apps / e8172110-ec08-421b-a6f5-842e6451911f | A | 已处理部分图像，后续仅创建/打开 extract_char.py 并点击编辑区，没有写入所需脚本内容。 |
| os / 5812b315-e7bd-4265-b51f-863c02174c28 | A | 创建用户命令通过 pyautogui 输入时焦点仍在 Impress，命令落入错误应用，非成功执行系统操作。 |
| os / a462a795-fdc7-4b23-b689-e8b6df786b78 | D | 原生为 infeasible，用户还明确要求不能切换时停止。验证继续追求 switched_to_charles。轨迹中的小写 charles 与任务 Charles 不可混为一谈，需精确账号检查后作可行性判断。 |
| os / 4783cc41-c03c-4e1b-89b4-50658f642bd5 | D | 用户只给未绑定的 $sourceDir/$targetDir；代理自行选择目录，原生为 infeasible。问题是缺少前提识别，而非仅缺一个 ls 截图。 |
| os / 37887e8c-da15-4192-923c-08fa390a176d | B | 多次 find/gzip 和 ls 没有结构化 stdout、文件集合前后态；无法确认压缩结果。另有 -mtime +30 与任务 30 days ago 的解释偏差风险，不能写成“其实成功”。 |
| thunderbird / a1af9f1c-50d5-4bc3-a51e-4d9b425ff638 | D | 原生为 infeasible；SMTP 与账户窗口反复切换，最终为空白账户字段。需要评估约束可满足性，而不是无限要求账户完成态。 |
| vlc / 215dfd39-f493-4bc3-a027-8a97d72c61bf | A | 最后仍在 Preferences 导航，未观察到目标开关被实际切换；验证在定位设置期间消耗预算。 |
| vlc / 8ba5ae7a-5ae5-4eab-9fcc-5dd4fe3abf89 | A | 实际命令修改 record_directory，但原生检查读取 input-record-path；这不是单纯缺截图。GUI 又一直在 Interface 标签而非目标配置区域。需同时解决配置语义和独立读取。 |

新增任务：

| Domain / Task ID | 类别 | 轨迹依据及限制 |
|---|---|---|
| vs_code / c6bf789c-ba3a-4209-971d-b63abf0ab733 | A | step 8..10 在设置 UI/JSON 切换，未写入 files.exclude。仍属未完成，同时三次验证过快耗尽。 |
| vs_code / 7c4cc09e-7a92-40dd-8338-b2286535c4ed | D | task evaluator 为 infeasible，旧版满分。新版把 displayLanguage 写入 settings.json，出现无效 JSON，并把 backspace 当字符串输入；既有执行错误，也未正确识别不可行退出路径。 |

## 关键机制证据

### 1. 修复还没做完，验证预算已用完

Delta 任务 `chrome/6c4c23a1-42a4-43cc-9db1-2f86ff3738cc`：

- `runtime.log` step 13 明确生成四步修复：Modify -> 打开 origin -> 输入 SEA -> 选择 SEA。
- step 14 已成功回到搜索表单，是修复进展，但 departure_set_to_sea 尚未满足，于是消耗第二次验证。
- step 15 打开机场下拉框，仍是正常中间步骤；第三次验证失败后整任务终止，来不及输入 SEA。
- 不能称此时任务已完成；但“未完成”不能推出“应当立刻终止”。这是修复调度和验收时机的问题。

对应审计文件：`135cb1043fbe4af4aeb27e39c5724801.json`、`444b34450ff2425cbb13ad4aff500705.json`、`fc2c2bb379144bb08c40e5df60620389.json`。

26 个终止任务的最后 attempt 全为 3；23 个 trigger 为 boundary_insufficient，3 个为 task_done。最终 judgement 为 17 unknown、9 contradicted。这些任务共保存 126 个渐进验证阶段结果（static 87、retrospection 28、probe 11），debt_action 全为 normal。因此不能描述成“StateGuard 检测到验证债务恶化才停止”；当前主要是硬计数触发。

### 2. 已有结构化证据被误读，且覆盖不完整

字体任务 `libreoffice_impress/358aa0a7-6677-453f-ae35-e440f004c31e`：

- 实际操作代码多次执行 `op_impress_set_font(scope='all', name='Liberation Sans Narrow')`。
- step 12/14/16 的结构文本展示前 20/28 张幻灯片，列出的 31 个 txt/title 均为目标字体。
- 验证引用的 Slide 17 反例实际为 `[3] pic 'Google Shape;237;p17' ... Liberation Sans 18pt`，不是探针标识的文本框。
- 验证还错误要求一定经 Master Slide UI 执行修改，把“最终状态成立”变成“必须按指定方式操作”。
- 但探针明确写有 `(+ 8 more slides not shown)`，并不能证明未展示内容和磁盘保存。正确处理是补全覆盖、核对实际文本 runs，而不是无条件接受，也不是重跑同一修改。

审计文件：`45bcce8d34bf460c8bd475f4a68e91c9.json`、`78170f6868344eb39f58d13a5990df27.json`、`b7d7db15f58e4e8d809c7a256ec03ff6.json`。

缩进任务 `a669ef01` 也存在常规验证与渐进验证冲突，但目前保存的文本布局不足以判定完整结果，应补 `ParaLeftMargin`、`ParaFirstLineIndent`、`NumberingLevel`、`NumberingIsNumber` 等可比属性，而不是仅比较字符串前面的空格。

### 3. 结构化执行回执没有进入渐进验证

`audit()` 只从 trajectory 提取 action 文本，截取前 1200 字符；复杂 UNO wrapper 的真正修改语句往往位于后半段。因此验证器会说“只是连接脚本”，尽管完整 action 里确实有修改语句。

此外，它没有把现有 `_last_cli_run_output` 的 stdout/stderr/returncode 接入。渐进验证常见输入只有终端截图，导致执行了 ls 却看不到输出。`lib_run_single.py` 已有把该回执放入 HTML 步骤记录的逻辑，说明应接通已有来源，而非另造一套执行器。

允许的文件 probe 仅为任务文字中原样出现的 `/home/user/...` 绝对路径及少量元数据。`~/Desktop/output.csv`、通过操作发现的产物、`/tmp/test_files`、隐藏应用配置目录都可能不满足当前规则。解决时应建立任务授权的路径来源和最小读取范围，不应开放任意 shell 或读取 evaluator/gold。

## 三个新增满分案例

| 任务 | 基线 -> 本轮 | 可支持的结论 |
|---|---|---|
| thunderbird/10a730d5-d414-4b40-b479-684bed1ae522，完整深色主题 | 0 -> 1 | 旧版在 Settings 选 Theme 后 DONE，原生 0；本轮进入 Add-ons Themes，step 8/11 渐进验证 UNKNOWN，step 12 点击启用，最终看到 Dark 的 Disable 按钮，step 13 DONE、原生 1。能观察到验证参与，但不能用单次配对证明没有它就一定失败。 |
| vlc/9195653c-f4aa-453d-aa95-787f6ccfaae9，最大音量 200% | 0 -> 1 | 旧版跑到 step 100 未完成；本轮 step 28 DONE，最终静态验证看到 Maximum Volume displayed=200。渐进模块仅出现最终 verified，没有 UNKNOWN->补证->修复链，不能把它当成渐进修复的成功案例。 |
| vs_code/dcbe20e8-647f-4f1d-8696-f1c5bbb570e3，设置照片背景 | 0 -> 1 | 该任务 evaluator 为 infeasible；旧版错误 DONE，新版 step 47 输出 FAIL 后原生 1。是正确不可行判断，不是成功设置背景，更不是 Markdown 预览任务。 |

所以，26 个满分里 3 个为旧版未成功任务，占 11.54%；其余 23 个原来也满分。任务定义为 infeasible 的满分数由 3 降为 2；其余操作任务的满分数由 29 降为 24。

## 九个退步任务

旧版 score=1，本轮 verification_budget：

1. gimp/d16c99dc-2a1e-46f2-b350-d97c86c85c15
2. libreoffice_impress/358aa0a7-6677-453f-ae35-e440f004c31e
3. libreoffice_writer/0e47de2a-32e0-456c-a366-8c607ef7a9d2
4. libreoffice_writer/bb8ccc78-479f-4a2f-a71e-d565e439436b
5. multi_apps/3680a5ee-6870-426a-a997-eba929a0d25c
6. vlc/8ba5ae7a-5ae5-4eab-9fcc-5dd4fe3abf89
7. vs_code/c6bf789c-ba3a-4209-971d-b63abf0ab733
8. vs_code/7c4cc09e-7a92-40dd-8338-b2286535c4ed

旧版 score=1，本轮 score=0：`multi_apps/e135df7c-7687-4ac0-a5f0-76b74438b53e`，电子表格转换 HTML 并在浏览器查看。

不能把这 9 个都归因于 Guard：其中有明确 actor 错误，也有 verifier 误读和可行性退出冲突，需要不同修复。

## 通用修复优先级

### P0 调整验证与修复的时间尺度

区分 action 执行回执、局部里程碑、完整 outcome 和整个任务四种边界。导航到设置页、打开下拉框不应立刻按最终 outcome 计一次失败。修复计划的中间步骤允许 pending；计划结束、显式完成声明或出现真正反证时再验收。

将“验证调用预算”与“完整修复周期预算”分开；仅在相关属性有可证明进展时更新停滞计数。保留总调用和墙钟上限，避免无限延长，不能只把 3 改成更大的常数。

### P0 停止也要形成可评分终态

verification_budget 触发时先记录终止原因、最终观测与产物快照，然后在安全条件下运行一次原生 evaluator，分别保存 native_score、termination_reason、agent_completion_claim。不能把预算耗尽伪装成 agent FAIL，也不能利用 evaluator 反馈指导本次代理重试。

当前异常在正常评价路径之前中止，所以这轮 26 个无法凭日志补出真实分数；VM 已顺序 reset，更不能把当前 VM 当作每个历史任务的终态。

### P1 接通有类型的独立证据

将任务绑定的 CLI 回执、浏览器 DOM/URL/表单值、Office 目标属性和覆盖范围接入 progressive。执行回执必须包含来源、时间、关联 action ID；actor 自己 print('PASS') 不是成功证明。

Office probe 显式区分文本、图片、母版、页脚和磁盘文件；覆盖不完整时按目标分页或聚合读取。对 `all text boxes` 输出扫描数量、未覆盖对象和异常项，而不是把长文档整体交给模型猜。

### P1 约束验收范围和证据解释

子目标只核验其原始后置条件；不得用后续姓名输入、最终居中、必须通过特定 GUI 等额外要求卡住前置步骤。对可精确比较的类型、字体、缩进和值优先确定性比较，模型负责解释无法直接比较的部分。

保留完整 action 与回执引用；可给模型简洁的领域操作摘要，但不能仅截取 wrapper 前 1200 字符再让它判断实际执行过什么。

### P1 为不可行性保留独立退出路径

在任务前提缺失、账号不存在或功能不支持时，允许基于环境证据进行可行性复核，满足条件后返回有理由的 FAIL。该路径应能在普通 verification_budget 用完之前执行。不可直接读取 task evaluator 的 infeasible 标签决定 FAIL。

### 验证修复效果的最小实验

先重跑按原因分层的少量任务：Delta 多步导航、Impress 字体、Writer 页脚、ODS 转换、Writer 不可行协作，并保留一个成功主题任务作为回归。比较修复周期是否完整、结构化证据是否被引用、终止时原生评分是否总能落盘，再决定是否重复全部 60 个。此处只是建议，本次没有启动重跑。

## 对应实现路径

服务器仓库：`/data/research/projects/StructAgent-fusion`。以下是相对此根目录的路径。

- `mm_agents/structagent/loop.py:820`：常规 boundary verifier 未通过后调用 recover_pending。
- `mm_agents/structagent/core/final_audit/progressive.py:77`：recover_pending，恢复 outcome 或抛出 EpisodeStopped。
- `mm_agents/structagent/core/final_audit/progressive.py:129`：allowed_path，当前 probe 路径限制。
- `mm_agents/structagent/core/final_audit/progressive.py:146`：audit，scope 计数、三阶段验证、证据指纹、债务更新和停止逻辑。
- `lib_run_single.py:509`：已有 CLI 执行回执进入 HTML 步骤记录的逻辑。
- `lib_run_single.py:570`：正常流程的原生 evaluator 调用。
- `lib_episode_budget.py`：EpisodeStopped 捕获、termination.json 与下一任务恢复。
- `desktop_env/evaluators/metrics/vlc.py:140`：录制路径检查，读取 input-record-path。
- `evaluation_examples/examples/<domain>/<task ID>.json`：任务要求和 evaluator 定义，仅用于离线分析标注。

本地与服务器的 progressive.py、loop.py SHA256 已核对相同。本次仅新增这份报告并下载分析用文本证据，没有修改、提交或推送运行代码。
