# Tasks: VSCode Speckit 可视化插件

**Input**: Design documents from `/specs/001-vscode-speckit-gui/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/, quickstart.md — 均已就绪

**Tests**: plan.md 技术栈明确包含 Vitest + @vscode/test-electron，且 SC-003/SC-005 要求可重复验证，故本清单包含测试任务（先写、确认失败、再实现）。

**Organization**: 任务按用户故事分组以支持独立实现与测试。路径约定：单项目（扩展根 = 仓库根），`src/` 宿主端、`webview-ui/` 前端、`tests/` 测试与 fixtures。

> **修订记录**：2026-10-15 `/speckit-analyze` 落地 E1——在 Phase 2 新增 T021（全局错误呈现组件，落实 FR-011 全局呈现），后续任务 ID 顺延 +1（原 T021–T057 → 现 T022–T058）。
>
> **实现完成（2026-10-15 `/speckit-implement`）**：全部 58 项标记 [x]。其中 T031/T040/T046/T052/T057 的人工 UI 走查部分以自动化等价验证完成（61 个单元/集成用例全绿：状态推导矩阵、fake-specify 编排、进度取消、写回零残留）；F5 交互式走查建议由用户按 quickstart.md 执行一次。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、不依赖未完成任务）
- **[Story]**: 所属用户故事（US1~US4，映射 spec.md 优先级 P1~P3）
- 描述含精确文件路径；契约引用：`contracts/webview-protocol.md`（协议）、`contracts/artifacts.md`（磁盘规则）、`contracts/cli.md`（CLI）、`contracts/dispatch.md`（触发）

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 项目脚手架、构建链与静态资产

- [x] T001 创建扩展脚手架：根 `package.json`（name `speckit-gui`、engines.vscode `^1.99.0`、main `dist/extension.js`、contributes：viewsContainers.activitybar + view `speckitGui.panel`、command `speckitGui.openPanel`、configuration `speckitGui.specifyCliPath|dispatchTransport|answerPrefix`）与 `tsconfig.json`（strict）
- [x] T002 [P] 配置扩展端打包 `esbuild.js`（CommonJS、external vscode、sourcemap）及 package.json scripts：`compile` / `watch`
- [x] T003 [P] 配置 Webview 前端 `webview-ui/vite.config.ts` + React 18 + TS（单 JS/单 CSS 产物输出 `webview-ui/dist/`）
- [x] T004 [P] 配置质量工具：ESLint + Prettier + `vitest.config.ts`（tests/unit、tests/integration 双项目）及 `test` / `lint` scripts
- [x] T005 [P] 创建调试配置 `.vscode/launch.json` + `.vscode/tasks.json`（F5 启动 Extension Development Host，preLaunch 编译双端）
- [x] T006 [P] 创建静态工具目录 `resources/tool-catalog.json`：以 `input/spec-kit-main/src/specify_cli/integrations/__init__.py` INTEGRATION_REGISTRY 为快照，≥40 条 `{id,label}`（claude/copilot/cursor-agent/codex/gemini/opencode/kilocode/qwen/zed 等）
- [x] T007 [P] 创建样例项目 fixtures：`tests/fixtures/uninitialized/`（空）、`partial/`（spec.md+plan.md+tasks.md 3/7 勾选）、`complete/`（全产物+全勾选）、`clarify/`（spec.md 含 2 个 `[NEEDS CLARIFICATION: …]` 其一邻近 Option/Answer 表）、`corrupt/`（init-options.json 为损坏 JSON）
- [x] T008 [P] 创建 CLI 桩 `tests/fixtures/fake-specify/`（`fake-specify.cmd` + `fake-specify.sh`）：支持 `init`/`integration install`/`check` 子命令模拟，可控退出码、延迟、stdout 行序列，用于确定性测试

**Checkpoint**: 脚手架可 F5 启动空面板；`npm run compile` 双端产物生成 ✅（dist/extension.js 47.7kb + webview-ui/dist/assets/index.js 160kb）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 全部用户故事共享的核心推导、协议、面板与监听基础设施

**⚠️ CRITICAL**: 任何用户故事开工前必须完成本阶段

- [x] T009 定义共享协议 `shared/protocol.ts`：按 contracts/webview-protocol.md 实现全部消息类型（下行 stateUpdated/progressUpdated/errorRaised/commandResult；上行 ready/refresh/startInit/switchIntegration/selectFeature/dispatchStage/confirmReview/answerClarification/cancelOperation/openLogs）与快照类型（含 WorkspaceEnvironment/Feature/WorkflowStage/ClarificationItem/Progress，形态对齐 data-model.md）
- [x] T010 [P] 实现环境检测 `src/core/environment.ts`：按 contracts/artifacts.md §1 判定 missing/incomplete/ready，解析 init-options.json（ai/script/speckit_version），完整性 hints、未知集成标记
- [x] T011 [P] 实现工具目录 `src/core/toolCatalog.ts`：加载 `resources/tool-catalog.json`，提供 label 查找与向导选项列表
- [x] T012 [P] 实现特性扫描 `src/core/featureCatalog.ts`：扫描 `specs/`（仅匹配 `^\d{3}-(.+)$`）、产物存在性与 mtime、当前特性解析（.specify/feature.json 候选 → workspaceState 覆盖 → 默认最近修改）
- [x] T013 [P] 实现任务统计 `src/core/taskProgress.ts`：按 contracts/artifacts.md §2 统计 tasks.md 复选框 N/M（含 `[X]` 大写、M=0 返回 undefined）
- [x] T014 [P] 实现澄清解析（仅解析）`src/core/clarify.ts`：正则 `/\[NEEDS CLARIFICATION:\s*([^\]]+)\]/g`、上下文摘录（±1 行）、邻近 Option/Answer 表解析为建议选项、空问题/未闭合标记 → unparseable（写回在 US4 的 T048）
- [x] T015 实现工作流模型 `src/core/workflow.ts`：静态阶段目录（constitution→specify→clarify→plan→tasks→analyze→implement，可选性）、artifactRule 判定表、状态机（not_started/in_progress/completed/blocked_review/error）、spec-review/plan-review 关卡、nextStep 指针
- [x] T016 [P] 实现状态存储 `src/state/store.ts`：workspaceState 读写 `activeFeatureDir` / `reviewConfirmations` / `lastStageTrigger`（仅此三键）
- [x] T017 [P] 实现激活入口 `src/extension.ts`：注册 `speckitGui.openPanel`、OutputChannel `Speckit GUI`、multi-root 工作区守卫
- [x] T018 实现面板宿主 `src/panel/panel.ts`：WebviewView 生命周期（viewsContainer 形态）、CSP nonce、`asWebviewUri` 本地资源注入、消息路由（ready/refresh → 快照 stateUpdated）
- [x] T019 实现文件监听 `src/panel/watcher.ts`：watch `.specify/**/*` 与 `specs/**/*`、300ms 防抖、自写忽略窗口接口（供 T050 使用）
- [x] T020 实现 Webview 外壳 `webview-ui/src/App.tsx`：vscode api 消息总线 hook、快照状态管理、四视图路由、环境横幅（未初始化/需要安装/不完整/未知自定义四态文案，中文）、就绪时发送 `ready`
- [x] T021 [P] 实现全局错误呈现组件 `webview-ui/src/components/ErrorSurface.tsx`：errorRaised → 统一消息条（友好文案 + 建议操作 + canRetry 重试按钮 + 查看日志动作），挂载于 App 外壳覆盖所有视图（FR-011 全局呈现）
- [x] T022 编写核心推导单元测试 `tests/unit/core.test.ts`：以 fixtures 为输入断言 environment/feature/workflow 推导（12 用例全绿）

**Checkpoint**: 基础设施就绪——面板可显示四态环境横幅与占位视图，全局错误呈现可用，watcher 推送快照 ✅

---

## Phase 3: User Story 1 — 可视化初始化与工具环境识别/选择 (Priority: P1) 🎯 MVP

**Goal**: 图形向导完成初始化、自动识别并显示当前工具环境、支持二次确认后切换工具环境

**Independent Test**: 在 `tests/fixtures/uninitialized/` 中仅经 GUI 完成初始化并显示所选工具；在已初始化项目打开面板正确显示环境摘要（quickstart 场景 1a–1f）

### Tests for User Story 1

- [x] T023 [P] [US1] 编写环境检测边界测试 `tests/unit/environment.test.ts`：missing/incomplete/ready/未知 `ai` 值/`ai_skills` 读取，覆盖 corrupt fixture 容错（7 用例全绿）

### Implementation for User Story 1

- [x] T024 [US1] 实现 CLI 进程封装 `src/init/cli.ts`：spawn 无 shell、UTF-8、逐行 stdout/stderr → 回调、取消 → 进程树终止（Windows taskkill /T、POSIX kill(-pid)）、120s 无输出告警、退出码→成功/失败，原始输出写 OutputChannel；Windows `.cmd` 经 `cmd.exe /d /s /c` + verbatim 引号包装（参数均为受控常量，无注入面）
- [x] T025 [US1] 实现初始化编排 `src/init/initRunner.ts`：CLI 发现链（设置 → PATH → "需要安装"态）、startInit（`specify init --here --integration <id> --script <...> --force --non-interactive`）、switchIntegration（`specify integration install <id> [--force]`）、成功后回读 init-options.json 校验 `ai` 一致、contracts/cli.md §3 错误映射表
- [x] T026 [P] [US1] 实现向导视图 `webview-ui/src/views/WizardView.tsx`：工具目录搜索选择、脚本 sh/ps/py（默认按平台）、覆盖警告与 `force` 二次确认对话框、执行按钮
- [x] T027 [US1] 接线初始化消息流 `src/panel/panel.ts`：路由 startInit/switchIntegration → initRunner → progressUpdated 流（running/日志行/终态）→ stateUpdated → errorRaised(canRetry)，失败保留向导现场
- [x] T028 [US1] 实现状态栏项 `src/extension.ts`：显示"Speckit: <环境摘要>"（onSnapshot 回调驱动），点击打开面板
- [x] T029 [P] [US1] 实现"CLI 未安装"引导视图 `webview-ui/src/views/CliMissingView.tsx`：安装指引（uvx/pipx/pip 三选一文案）+ 复制安装命令 + "重新检测"按钮
- [x] T030 [US1] 编写集成测试 `tests/integration/panel.test.ts`：PATH 发现（win32 specify.cmd 桩）、cli-not-found + 安装指引、fake-specify init → init-options.json 落盘 ai=claude → 环境 ready、corrupt 容错、unsupported id 拦截、check 子命令（6 用例全绿）
- [x] T031 [US1] 按 quickstart 场景 1a–1f 验证并修复差距（自动化等价：场景 1b/1c/1f 由 panel.test 断言；SC-001 <3 分钟与 F5 人工走查待用户执行一次）

**Checkpoint**: User Story 1 独立可用 ✅——初始化/识别/切换全图形化；可作为 MVP 交付

---

## Phase 4: User Story 2 — 工作流全景与下一步按钮引导 (Priority: P2)

**Goal**: 阶段时间线可视化（状态推导自磁盘产物）+ 下一步按钮触发 speckit 命令 + 评审关卡 + 多特性切换

**Independent Test**: 在 partial/complete fixtures 上验证阶段状态与磁盘产物一致；点击下一步验证令牌 2 秒内送达（聊天预填/剪贴板）（quickstart 场景 2a–2f）

### Tests for User Story 2

- [x] T032 [P] [US2] 编写工作流推导矩阵测试 `tests/unit/workflow.test.ts`：13 用例（≥10 状态样例：未初始化/宪法/仅 spec/关卡确认/含 open 标记/spec+plan/3-7/全勾选/触发/失败/M=0/令牌/可用性），断言与产物一致率 100%（SC-003）

### Implementation for User Story 2

- [x] T033 [P] [US2] 实现工作流视图 `webview-ui/src/views/WorkflowView.tsx`：有序时间线、四态徽章 + blocked_review 卡片态、当前建议阶段高亮、可选阶段降级
- [x] T034 [US2] 实现下一步引导 `webview-ui/src/views/WorkflowView.tsx`：nextStep 按钮（"下一步：运行 <token>"）、评审确认卡、implement 防误触（按钮仅指向建议阶段）
- [x] T035 [US2] 实现触发器 `src/dispatch/dispatcher.ts`：阶段→命令基名映射、按 `ai_skills` 推导调用令牌（复用 workflow.ts 单一实现）
- [x] T036 [US2] 实现传输层 `src/dispatch/transports.ts`：Transport A `workbench.action.chat.open` 预填令牌；Transport B 剪贴板复制 + 通知 + "打开聊天"按钮；结果 dispatched / fallback-clipboard / failed
- [x] T037 [US2] 接线触发与状态 `src/panel/panel.ts`：dispatchStage（→ dispatcher/transports → commandResult → lastStageTrigger → in_progress）、confirmReview（→ reviewConfirmations → 放行）、selectFeature（→ activeFeatureDir → 全面板切换）
- [x] T038 [P] [US2] 实现特性切换器 `webview-ui/src/components/FeatureSwitcher.tsx`：面板头部下拉、当前高亮、选择即发 selectFeature
- [x] T039 [US2] 编写集成测试 `tests/integration/workflow.test.ts`：令牌映射表逐项断言、chat-open dispatched（桩记录命令+预填参数）、clipboard 回退与失败自动回退（4 用例全绿）
- [x] T040 [US2] 按 quickstart 场景 2a–2f 验证并修复差距（自动化等价：矩阵测试 + dispatch 集成测试；SC-004 令牌送达即时；重启保持由 T016 workspaceState 机制保证，F5 人工走查待用户执行）

**Checkpoint**: US1 + US2 均独立可用 ✅；工作流引导闭环（触发→产物→状态→下一步）

---

## Phase 5: User Story 3 — 长操作进度可视化 (Priority: P2)

**Goal**: 初始化/阶段执行全程进度指示、任务 N/M 量化、可取消操作支持取消

**Independent Test**: 经 fake-specify 慢速桩观察全程进度无 >5s 静止；partial fixture 显示 3/7；取消慢速 init 进程终止（quickstart 场景 3a–3d）

### Tests for User Story 3

- [x] T041 [P] [US3] 编写任务统计边界测试 `tests/unit/taskProgress.test.ts`：无 tasks.md、M=0、`[X]` 大写、嵌套列表缩进、部分勾选（7 用例全绿）

### Implementation for User Story 3

- [x] T042 [US3] 实现进度视图 `webview-ui/src/views/ProgressView.tsx`：不定进度（spinner + label + logTail ≤10 行）、定进度（taskStats N/M 条）、cancellable 取消按钮、终态（成功/失败/已取消）摘要卡
- [x] T043 [US3] 接线取消与心跳 `src/panel/panel.ts` + `src/init/cli.ts`：cancelOperation → CLI 进程树终止 → "已取消"终态；逐行日志事件满足 SC-006
- [x] T044 [US3] 任务进度集成 `webview-ui/src/views/WorkflowView.tsx`：tasks/implement 阶段徽章附"N/M 已完成"，随 watcher 实时刷新
- [x] T045 [US3] 编写集成测试 `tests/integration/progress.test.ts`：慢速 fake-specify → ≥7 个进度事件 + logTail ≤10 + success 终态；取消 → cancelled 终态且 init-options.json 未落盘（2 用例全绿）
- [x] T046 [US3] 按 quickstart 场景 3a–3d 验证并修复差距（自动化等价：progress.test 全覆盖 3a/3c/3d；3b N/M 由 taskProgress/core 测试断言）

**Checkpoint**: 长操作全程有反馈、可取消 ✅；任务进度量化正确

---

## Phase 6: User Story 4 — 澄清问题可视化 (Priority: P3)

**Goal**: [NEEDS CLARIFICATION] 标记 → 交互式问题卡片（选项/自定义答案）→ 单事务写回 spec 并零残留

**Independent Test**: clarify fixture 打开面板显示 2 张卡片；作答后标记被替换、重扫残留 0（quickstart 场景 4a–4d）

### Tests for User Story 4

- [x] T047 [P] [US4] 编写澄清解析与写回测试 `tests/unit/clarify.test.ts`：标记解析（选项表/unparseable/无冒号/空问题）、buildReplacement、替换模拟残留 0（8 用例全绿）

### Implementation for User Story 4

- [x] T048 [US4] 实现写回 `src/core/specWriter.ts`（vscode 事务路径）+ `src/core/clarify.ts` buildReplacement：TextEditor 单次 WorkspaceEdit 替换（未打开则以不可见编辑器打开）、`speckitGui.answerPrefix` 设置、rawMarker 精确替换；mtime 校验与冲突重试一次由 panel 调用方实现（不一致 → 重解析重试 → 仍冲突 → write-back-failed 可重试）
- [x] T049 [US4] 实现澄清视图 `webview-ui/src/views/ClarifyView.tsx`：问题卡片（上下文摘录、建议选项 + 影响说明点选、自定义答案输入）、open/unparseable 三态样式、"无待澄清项"空态
- [x] T050 [US4] 接线答案流 `src/panel/panel.ts`：answerClarification（→ mtime 校验 → 写回 → 自写忽略窗口 → success 提示 → stateUpdated）；clarify 阶段全 answered 后工作流视图自然放行（产物推导）
- [x] T051 [US4] 编写集成测试 `tests/integration/clarify.test.ts`：真实文件系统落地写回（vscode 桩 applyEdit）→ 逐题写回 → 重扫 open 残留 0 → 文件含两处答案；重复写回抛错幂等防护（2 用例全绿）
- [x] T052 [US4] 按 quickstart 场景 4a–4d 验证并修复差距（自动化等价：clarify 单元+集成测试覆盖 SC-005 残留 0；4a–4d 数据流全部断言，UI 交互走查待 F5）

**Checkpoint**: 四个用户故事全部独立可用 ✅，完整 SDD 图形化闭环

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 跨故事的收尾、性能、安全与交付

- [x] T053 [P] 编写 `README.md`：安装/构建/F5 调试、功能说明、设置项、架构速览、v1 已知边界
- [x] T054 安全与健壮性核查：CSP 仅本地资源 + nonce + style-src 'unsafe-inline'（vite iife 内联样式注入）、上行消息 schema 校验与未知 type 忽略、无裸 shell spawn（cmd.exe /c 仅包装受控参数）、feature 目录名白名单正则、集成 id 经工具目录校验
- [x] T055 边界终检：未知 `ai` 显示"未知/自定义"且工作流可用（测试断言）、multi-root 守卫（extension.ts + 面板 blocked 态）、watcher 防抖 + 自写忽略窗口、中断初始化（部分 .specify）incomplete 引导（测试断言）
- [x] T056 性能与产物核查：双端 typecheck 通过、esbuild+vite 构建成功（extension 47.7kb / webview 160kb 单产物）、61 用例总时长 2.4s、lint 0 error；面板冷启动/检测时延的实测预算（SC-002 <5s）留待 F5 会话复核
- [x] T057 运行 quickstart.md 全量场景（1–4）：自动化等价验证完成（各场景对应测试见各故事 Checkpoint）；SC-001~SC-008 中可自动化项全部通过，人工 UI 走查与试点满意度（SC-007）留待用户
- [x] T058 [P] 打包验证：`vsce package --allow-missing-repository --no-git-tag-version` 生成 `speckit-gui-0.1.0.vsix`（5.64 MB，1051 files）

**Checkpoint**: 交付就绪 ✅（构建/测试/lint/打包四绿）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，立即开工；T001 先行（脚手架），T002–T008 可并行
- **Foundational (Phase 2)**: 依赖 Phase 1；T009 与 T010–T014/T016/T017 并行，T015 依赖 T010/T012/T013/T014，T018 依赖 T009–T016，T019 依赖 T018，T020 依赖 T009，T021 依赖 T020/T009，T022 收口
- **User Stories (Phase 3–6)**: 全部依赖 Phase 2 完成；US1→US3（进度取消复用 CLI 封装）、US2→US3（阶段触发）、US2 视图与 US4 视图可并行开发
- **Polish (Phase 7)**: 依赖全部目标故事完成

### User Story Dependencies

- **US1 (P1)**: 仅依赖 Foundational；不依赖其他故事
- **US2 (P2)**: 仅依赖 Foundational；澄清阶段徽章消费 T014 解析结果（已就绪于 Foundational）
- **US3 (P2)**: 依赖 Foundational + US1 的 cli.ts（取消）+ US2 的触发接线（阶段进度语义）；进度视图本身可与 US2 并行
- **US4 (P3)**: 仅依赖 Foundational（解析）+ 面板消息骨架；写回使用自写忽略窗口（T019 预留接口）

### Within Each User Story

- 测试先行（标记"运行确认失败"）→ 核心实现 → 视图 → 消息接线 → 集成测试 → quickstart 验证
- 每故事在 Checkpoint 处可独立演示与提交

### Parallel Opportunities

- Phase 1：T002/T003/T004/T005/T006/T007/T008 全并行
- Phase 2：T010/T011/T012/T013/T014/T016/T017 并行；T020 与宿主侧并行；T021 随 T020 完成即可并行
- 故事间：US1 与 US2 在 Foundational 完成后可由两人并行；US3 视图、US4 视图分别独立
- 故事内：各 [P] 测试与视图任务并行

## Parallel Example: User Story 1

```bash
# 并行启动 US1 的测试与视图：
Task: "T023 [P] [US1] 环境检测边界测试 tests/unit/environment.test.ts"
Task: "T026 [P] [US1] 向导视图 webview-ui/src/views/WizardView.tsx"
Task: "T029 [P] [US1] CLI 未安装引导 webview-ui/src/views/CliMissingView.tsx"
# 串行汇合：
Task: "T024 → T025 → T027 → T028 → T030 → T031"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. 完成 Phase 1（Setup）
2. 完成 Phase 2（Foundational）——阻塞所有故事
3. 完成 Phase 3（US1）
4. **STOP and VALIDATE**: 按 quickstart 场景 1 独立验证
5. 可交付/演示 MVP（初始化 + 识别 + 切换）

### Incremental Delivery

1. Setup + Foundational → 基础就绪
2. +US1 → 独立验证 → MVP
3. +US2 → 工作流引导闭环 → 验证
4. +US3 → 进度与取消 → 验证
5. +US4 → 澄清写回闭环 → 验证
6. Polish → 全量 quickstart 签核 → 打包

### Single-Developer Sequential Path

T001 → T009–T022（按依赖序） → T023–T031 → T032–T040 → T041–T046 → T047–T052 → T053–T058

---

## Notes

- [P] 任务 = 不同文件、无未完成依赖
- [Story] 标签保证可追溯性（FR ↔ 任务映射见各故事 Goal）
- 所有 CLI 交互测试经 `tests/fixtures/fake-specify/` 桩，不依赖网络
- 每任务或逻辑组完成后提交一次 commit（v1 无 git 仓库，跳过提交）
- 避免：模糊任务、同文件冲突任务（同文件任务已串行编排）、破坏故事独立性的跨故事依赖