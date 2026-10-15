# Data Model: VSCode Speckit 可视化插件

**Feature**: `001-vscode-speckit-gui` | **Date**: 2026-10-15 | **Source**: spec.md Key Entities + contracts/artifacts.md

> 本插件为只读消费者 + 少量写回（澄清答案、workspaceState）。除 `ClarificationItem.answer` 外，所有实体均为**派生状态**（从磁盘产物推导），不落地持久化。

## 1. WorkspaceEnvironment（工作区环境）

工作区 Speckit 环境的检测结果，派生自 `.specify/` 内容。

| 字段 | 类型 | 说明 |
|------|------|------|
| `state` | `missing \| incomplete \| ready` | 未初始化 / 不完整 / 就绪 |
| `integrationId` | `string \| undefined` | 已配置的 AI 工具 id（取自 init-options.json `ai`） |
| `integrationLabel` | `string \| undefined` | 显示名（查 tool-catalog；未命中 → "未知/自定义环境"） |
| `isKnownIntegration` | `boolean` | `ai` 是否命中内置目录 |
| `script` | `"sh" \| "ps" \| "py" \| undefined` | 脚本类型 |
| `speckitVersion` | `string \| undefined` | init-options.json `speckit_version` |
| `cliAvailable` | `boolean` | `specify` CLI 是否可发现（R12 解析链） |
| `hints` | `string[]` | `incomplete` 时的具体缺失说明（如"init-options.json 缺失或损坏"） |

**派生/验证规则**：
- `.specify/` 目录不存在 → `state=missing`（其余字段空）
- `.specify/init-options.json` 缺失、JSON 解析失败或无 `ai` 字段 → `state=incomplete`，`hints` 给出缺失项
- 可解析 → `state=ready`；`integrationId = ai`；`script = script`；`speckitVersion = speckit_version`
- 辅证（仅用于 incomplete 提示）：`.specify/integrations/<id>.manifest.json`、集成命令目录存在性

**状态迁移**：`missing → ready`（init 成功）；`ready → ready`（integration install 成功，integrationId 变化）；任意 → `incomplete`（关键文件被删/损坏，watcher 触发重判）。

## 2. ToolCatalogEntry（工具目录条目）

静态目录 `resources/tool-catalog.json` 的条目。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `string` | 集成键（= INTEGRATION_REGISTRY 键，如 `claude`、`copilot`、`cursor-agent`） |
| `label` | `string` | 显示名（如 "GitHub Copilot"、"Cursor Agent"） |

**约束**：`id` 唯一、小写；目录 ≥ 40 条（R4）；初始化向导与切换列表均由它渲染；`ai` 未命中目录时环境显示"未知/自定义"（不阻塞工作流视图）。

## 3. Feature（特性）

`specs/` 下一个特性目录的推进状态。

| 字段 | 类型 | 说明 |
|------|------|------|
| `dirName` | `string` | 目录名（`NNN-short-name` 形态，如 `001-vscode-speckit-gui`） |
| `number` | `number \| undefined` | 目录名前缀 `NNN`（解析失败为 undefined，不阻塞） |
| `name` | `string` | 去前缀的可读名 |
| `artifacts` | `object` | 各产物存在性与 mtime：`constitution?`（readiness）、`spec?`、`plan?`、`tasks?` |
| `isCurrent` | `boolean` | 是否为当前特性（UI 选择） |
| `specBody` | `string`（瞬时） | 澄清解析输入（仅在解析时读取，不入 store） |

**派生/验证规则**：
- 扫描 `specs/*/` 仅取目录；`constitution` 产物判定 = `.specify/memory/constitution.md` 存在且**非未填充模板**（不含 `PRINCIPLE_1_NAME` 占位符）
- 当前特性默认 = 目录 mtime 最新；用户显式选择后以 `workspaceState.activeFeatureDir` 为准（FR-012/FR-013）
- `.specify/feature.json` 存在时，其 `feature_directory` 作为初始当前特性候选

## 4. WorkflowStage（工作流阶段）

静态目录中的阶段定义 + 运行时状态。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `string` | `constitution \| specify \| clarify \| plan \| tasks \| analyze \| implement` |
| `order` | `number` | 展示顺序（1..7） |
| `optional` | `boolean` | analyze/clarify 为可选（命令缺失或产物条件不适用时降级显示） |
| `commandToken` | `string` | 调用令牌：skills 模式 `/speckit-<name>`，命令模式 `/speckit.<name>` |
| `artifactRule` | `string` | 完成判定规则（见 contracts/artifacts.md §3） |
| `gate` | `"spec-review" \| "plan-review" \| undefined` | 阶段完成后挂起的人工评审关卡 |
| `state` | 派生 | `not_started \| in_progress \| completed \| blocked_review \| error` |

**状态迁移（有限状态机）**：

```text
not_started ──dispatch──▶ in_progress ──artifact满足──▶ blocked_review(有gate) ──用户确认──▶ completed
                              │                              │
                              ├──执行失败──▶ error ──重试──▶ in_progress
                              └──无gate──▶ completed
completed(当前最高阶段) ──nextStep指向──▶ 下一阶段 not_started
```

- `in_progress` 判定 = `workspaceState.lastStageTrigger[id]` 记录存在且产物未满足；产物一旦满足立即按规则转 `blocked_review`/`completed`（不信任触发记录）
- `error` 判定 = 最近一次触发的 CLI/校验失败结果；仅可经重试离开
- 关卡 `spec-review` 挂在 specify 之后、`plan-review` 挂在 plan 之后（对齐 workflow.yml 的 review-spec / review-plan gate）
- 当前建议阶段 = 第一个非 completed（或 blocked_review  awaiting 确认）的阶段；"下一步"按钮指向它（SC-004）

## 5. ClarificationItem（澄清问题）

当前特性 spec 文档中一个待澄清标记的解析结果。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `string` | 稳定 id = `file#序号`（按出现顺序） |
| `question` | `string` | 标记内的问题文本 |
| `context` | `string` | 标记所在行前后各 1 行的摘录 |
| `options` | `{label, implication}[] \| undefined` | 邻近选项表解析结果 |
| `answer` | `string \| undefined` | 用户答案（写回后） |
| `status` | `open \| answered \| unparseable` | 状态 |

**约束/迁移**：
- 解析正则与写回格式见 contracts/artifacts.md §4；`open → answered`（写回成功，重扫无该标记）；解析失败 → `unparseable`（面板说明，跳过）
- 面板未作答关闭，状态保留（瞬时推导自磁盘，天然保留，US4-4）；全部 answered 后面板显示"无待澄清项"

## 6. Progress（进度）

一次长操作的运行时进度（不持久化，仅存在于操作生命周期）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `operation` | `"init" \| "integration-install" \| "stage"` | 操作类型 |
| `kind` | `"determinate" \| "indeterminate"` | 已知/未知步数 |
| `label` | `string` | 当前操作名（如"正在初始化 claude 环境…"） |
| `logTail` | `string[]` | CLI 最近输出行（环形，≤ 10 行） |
| `taskStats` | `{done, total} \| undefined` | tasks.md 复选框统计（stage=tasks/implement 时） |
| `cancellable` | `boolean` | 仅插件发起的 CLI 操作为 true |
| `result` | `{outcome: "success" \| "failure", message} \| undefined` | 终态摘要 |

**迁移**：`running(kind/label/logTail/taskStats 持续更新) → completed(result=success) | failed(result=failure)`；`cancellable && cancel → failed(result="已取消")`。约束：running 期间不得出现 >5s 无任何事件（SC-006，watcher 心跳/日志行即可满足）。

## 7. UiState（界面状态）

持久化到 `workspaceState` 的最小状态。

| 键 | 类型 | 说明 |
|----|------|------|
| `activeFeatureDir` | `string \| undefined` | 当前特性目录名 |
| `reviewConfirmations` | `Record<gateId, iso时间>` | spec-review / plan-review 确认记录 |
| `lastStageTrigger` | `Record<stageId, iso时间>` | 最近阶段触发记录（in_progress 判定输入） |

**约束**：仅此三项入持久化；面板视图选择等纯瞬态不入盘。

## 实体关系

```text
WorkspaceEnvironment 1 ─── 0..1 Feature(当前) ─── 1..* WorkflowStage
                                   │
                                   └── 0..* ClarificationItem（来自 specBody）
ToolCatalogEntry * ──提供 label──▶ WorkspaceEnvironment / 向导
Progress 0..1 ──附着于──▶ 正在进行的操作（init / install / stage dispatch）
UiState ──▶ WorkspaceState 持久化（activeFeatureDir / reviewConfirmations / lastStageTrigger）
```