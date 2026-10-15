# Research: VSCode Speckit 可视化插件

**Feature**: `001-vscode-speckit-gui` | **Date**: 2026-10-15 | **Input**: plan.md Technical Context

> 所有未知项均通过直接检视本仓库内嵌的 Spec Kit 源码（`input/spec-kit-main`，specify-cli 1.2.1.dev0）与当前项目 `.specify/` 实例解决，无需外部研究任务。

## R1 插件 UI 形态

**Decision**: 单一 Activity Bar 图标 → Webview Panel 作为主界面（向导/工作流/澄清/进度四视图），辅以一个状态栏项显示环境状态摘要（点击打开面板）。

**Rationale**: 规范要求"友好的图形界面"——阶段时间线、澄清卡片、进度指示均为富交互组件，Webview 是唯一能承载的形态；状态栏提供 SC-002 要求的快速可见性。保持一个 UI 面，避免双 UI（TreeView+Webview）维护成本。

**Alternatives considered**:
- 原生 TreeView + QuickPick：无自定义卡片/时间线样式，澄清选项表格无法呈现 → 拒绝
- 仅状态栏 + 通知：交互能力不足 → 拒绝
- 双 UI（TreeView 导航 + Webview 详情）：v1 范围内收益低 → 拒绝

## R2 Webview 前端技术

**Decision**: React 18 + Vite 构建 Webview 前端（单 JS + 单 CSS 产物，经 `webview.asWebviewUri` 注入，严格 CSP）；扩展宿主端用 esbuild 打包。

**Rationale**: 卡片、步骤条、表单向导等组件用 React 产出效率最高且类型安全（与宿主共享 `shared/protocol.ts` 类型）；Vite 构建快、HMR 便于开发。`@vscode/webview-ui-toolkit` 已停止维护，不采用。

**Alternatives considered**:
- 原生 vanilla TS + 手写 DOM：组件复杂度（澄清卡片列表、状态机视图）下可维护性差 → 拒绝
- Svelte：包体更小，但生态与 AI 实现熟悉度低于 React → 拒绝

## R3 初始化机制：复用官方 CLI

**Decision**: 插件不自行生成 `.specify` 内容；以子进程方式调用官方 `specify` CLI：
- 初始化：`specify init --here --integration <id> --script <ps|sh|py> --force --non-interactive`
- 工具安装/切换：`specify integration install <id> [--script <...>] [--force]`
- 环境自检：`specify check`

**Rationale**: 源码证实 `specify init`（`command_init.py`）支持上述旗标；`--non-interactive --force` 保证脚本化执行不挂起（typer.confirm 无 TTY 时会中断）。自研初始化会与官方模板/集成体系漂移，违反 spec 假设"复用官方初始化能力"。

**Alternatives considered**:
- TypeScript 重新实现 init（拼装 .specify）：实现成本高、随 Spec Kit 版本漂移 → 拒绝
- 通过 MCP server 调用 spec-kit：引入常驻进程与认证复杂度，超出 v1 → 拒绝

## R4 受支持工具目录

**Decision**: 以静态快照 JSON（`resources/tool-catalog.json`）内置工具目录，条目取自 `specify_cli/integrations/__init__.py` 的 `INTEGRATION_REGISTRY`（40+ 集成：claude、copilot、cursor-agent、codex、gemini、opencode、kilocode、qwen、zed…），字段 `{id, label}`。随插件版本人工更新。

**Rationale**: 目录仅用于向导选择与显示标签，无需运行时拉取 registry 源码；静态快照零依赖、离线可用（离线场景仅保证可视化可用的假设一致）。未知/自定义环境显示为"未知/自定义"（FR/Edge Case 已覆盖）。

**Alternatives considered**: 运行时解析 CLI 源码/网络拉取 catalog → 依赖网络与解析脆弱 → 拒绝

## R5 环境检测与完整性判定

**Decision**: 检测规则（详见 contracts/artifacts.md）：
1. `.specify/` 不存在 → `missing`
2. `.specify/` 存在但 `init-options.json` 缺失/不可解析 → `incomplete`（引导修复/重新初始化）
3. `init-options.json` 可解析 → `ready`；工具 = `ai` 字段（本工作区实例验证：`{"ai":"cursor-agent","script":"ps","speckit_version":"0.13.1.dev0",...}`）；辅证：`.specify/integrations/<id>.manifest.json` 存在性、集成命令目录（如 `.cursor/skills/`、`.claude/skills/`、`.github/prompts/`）
4. `ai` 值不在工具目录中 → 显示"未知/自定义环境"，允许用户手动指定

**Rationale**: `init-options.json` 是 init 的权威写入物（单一事实源）；目录佐证仅在权威文件缺失时用于 `incomplete` 判定提示。与 SC-003 的产物一致率要求一致。

**Alternatives considered**: 仅靠集成目录探测（`register_commands` 的 detect_dir 逻辑同样依赖目录，但 init-options 更直接）→ 拒绝作为主判定

## R6 工作流阶段模型与状态推导

**Decision**: 内置静态阶段目录（id、顺序、产物判定规则、可触发命令）：
constitution → specify → clarify → plan → tasks → analyze → implement（analyze 为可选阶段，命令不可用时隐藏/禁用）。状态推导规则：

- `not_started`：产物不存在
- `in_progress`：用户已触发且产物未满足（触发记录存 workspaceState）
- `completed`：产物满足判定（spec.md 存在；plan.md 存在；tasks.md 存在；implement = tasks.md 全部复选框勾选）
- `blocked_review`：阶段产物满足但内置评审关卡未确认（spec 后、plan 后两处，对齐 `.specify/workflows/speckit/workflow.yml` 的 review-spec / review-plan gate），确认后转为 completed
- `error`：上次触发执行失败（CLI 退出非 0 或产物校验失败）
- clarify 为可选阶段：spec 无待澄清标记时显示"已完成（无需澄清）"

**Rationale**: 状态完全由磁盘产物推导（SC-003 一致率 100% 的来源），不信任会话内存；评审关卡与项目实际安装的 workflow（specify → review → plan → review → tasks → implement）对齐。阶段集合可被项目 `.specify` 中可用命令增强（假设条款）。

**Alternatives considered**: 解析 `.specify/workflows/workflow.yml` 动态建模：引入 YAML 依赖且各项目工作流差异大 → v1 拒绝，留作后续增强

## R7 speckit 命令触发（Dispatcher）

**Decision**: 阶段触发 = `Dispatcher` 生成"调用令牌"并经传输层发送：
- 令牌规则：`ai_skills: true`（skills 模式）→ `/speckit-<name>`（如 `/speckit-plan`）；命令模式 → `/speckit.<name>`。依据：skills 模式下命令以 SKILL.md 形态安装（`.cursor/skills/speckit-plan/SKILL.md` 即实例）
- 传输层 A（chat-open）：执行编辑器命令 `workbench.action.chat.open`，预填令牌文本，将焦点交给用户发送
- 传输层 B（clipboard 回退）：复制令牌 + 打开聊天/通知提示粘贴发送
- 传输层可在设置中覆盖；两插件目标环境（Copilot chat / Cursor）均先走 A，失败回退 B

**Rationale**: 规范假设"插件触发命令，内容由 AI 代理生成"——VSCode 无统一跨厂商的"执行代理命令"API，预填聊天输入是兼容面最广且用户保持掌控的机制；SC-004 的 2s 触发预算指令牌送达（打开聊天/复制完成），而非代理执行完成。

**Alternatives considered**:
- 扩展内自建终端运行 CLI 工作流引擎（`specify workflow run`）：工作流引擎由代理而非终端驱动，产品语义不符 → 拒绝
- 直接调用 Copilot Chat 扩展私有 API：私有面不稳定 → 拒绝

## R8 澄清标记解析与写回

**Decision**:
- 语法：`[NEEDS CLARIFICATION: <问题>]`（正则 `/\[NEEDS CLARIFICATION:\s*([^\]]+)\]/g`）；若标记下方/邻近存在选项表（`| Option | Answer |` 形态），解析为建议选项
- 写回：确认答案后，将标记整体替换为答案文本（`<问题> → <答案>` 语义保留于替换行 `**答案**: <答案>` 前缀可由用户在设置关闭），编辑通过 `TextEditor.edit` 单次事务执行，避免并发写
- 无法解析的标记（空问题、未闭合）→ `unparseable`，面板说明原因，跳过不阻塞（Edge Case）

**Rationale**: 与 `/speckit-clarify` 的编码约定一致（答案编码回 spec）；单事务替换保证 SC-005"替换残留为 0"可验证（写回后重扫标记数）。

**Alternatives considered**: 引入 markdown AST 库做位置映射：依赖重、对单行标记收益低 → 拒绝

## R9 进度与取消

**Decision**:
- CLI 操作（init / integration install）：`spawn`（无 shell）逐行捕获 stdout/stderr → 进度事件流（不定进度=活动指示+最新日志行）；`CancellationToken` → 终止子进程树 → 界面回到可操作状态（FR-015）
- 阶段执行（AI 代理在插件外部工作）：插件无法直接观测代理内部，进度 = 阶段状态 + tasks.md 复选框统计（`- [x]` 计 N、`- [ ]`/`- [ ]` 未勾选计 M，watcher 触发重算）+ 活动指示（in_progress 状态）
- 终态：成功/失败摘要替换进度指示（US3-3）

**Rationale**: FR-007 的"N/M"唯一可靠数据源是 tasks.md 复选框；代理执行不可取消（不在插件进程内），取消能力限定于插件自身发起的 CLI 操作，符合"在支持的范围内可取消"。

**Alternatives considered**: 轮询代理扩展状态 API（无公开稳定接口）→ 拒绝

## R10 文件监听与刷新

**Decision**: `FileSystemWatcher` 监听 `.specify/**`、`specs/**`（创建/修改/删除）+ 配置节 `speckitGui.refresh`；事件防抖 300ms 后全量重推状态快照到 Webview。插件自身写 spec（澄清写回）时设置"忽略窗口"避免回环。

**Rationale**: FR-010/SC-008 要求外部修改自动反映；快照式推送（而非增量 diff）实现简单且与"不缓存过期状态"边界一致。

**Alternatives considered**: 仅手动刷新按钮：不满足 SC-008 → 拒绝；增量 diff：复杂度高收益小 → 拒绝

## R11 持久化

**Decision**: `workspaceState` 存储：`activeFeatureDir`（当前特性）、`reviewConfirmations`（关卡确认）、`lastStageTrigger`（最近触发记录）。全局设置走 `contributes.configuration`（`speckitGui.specifyCliPath`、`speckitGui.dispatchTransport`、`speckitGui.answerPrefix`）。

**Rationale**: FR-013 仅要求"最小界面状态"；workspaceState 按工作区隔离，天然支持多项目不同状态。

**Alternatives considered**: 全局 settings 存 UI 状态（会跨项目串味）→ 拒绝

## R12 CLI 发现与错误引导

**Decision**: CLI 解析顺序：设置 `speckitGui.specifyCliPath` → PATH 上的 `specify`（Windows 下含 `specify.cmd`）→ 均不可用时进入"需要安装"态：面板展示安装指引（uv / pipx / pip 任一：如 `uvx --from git+https://github.com/github/spec-kit.git specify --help` 或 `pipx install specify-cli`）与"重新检测"按钮。所有 CLI 错误映射为友好文案（原因 + 建议操作），原始堆栈仅入输出日志（OutputChannel）。

**Rationale**: FR-011/Edge Case 要求；v1 不自动安装依赖（避免静默网络副作用），与假设"需要网络安装工具"一致。

**Alternatives considered**: 插件内置 CLI 打包（捆绑 Python 运行时不现实）→ 拒绝

## R13 测试策略

**Decision**: Vitest 覆盖 `core/` 纯逻辑（检测、阶段推导、澄清解析/替换、N/M 统计）——以 `tests/fixtures/` 样例项目为输入断言状态；@vscode/test-electron 冒烟（激活、面板打开、命令注册）；CLI 交互以 `tests/fixtures/fake-specify/` 桩脚本（可控输出与退出码）验证编排与取消。手工验收按 quickstart.md 场景执行。

**Rationale**: 状态推导是正确性核心（SC-003/SC-004），纯逻辑可测性最高；桩 CLI 使 init 编排可确定性测试（不依赖网络）。

**Alternatives considered**: 仅端到端手工测试（不可回归）→ 拒绝；Mocha（@vscode 默认脚手架）：Vitest 生态与 TS 体验更好 → 拒绝

## 结论

所有 NEEDS CLARIFICATION 已解决；无遗留未知项。关键外部依赖：官方 `specify` CLI ≥ 与项目 `.specify` 兼容的版本（本工作区实例 `speckit_version: 0.13.1.dev0` / CLI 源码 1.2.1.dev0）。