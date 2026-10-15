# Implementation Plan: VSCode Speckit 可视化插件

**Branch**: `001-vscode-speckit-gui` | **Date**: 2026-10-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-vscode-speckit-gui/spec.md`

## Summary

构建一个 VSCode 扩展（ Speckit 可视化面板 ），为 Spec Kit 提供全程图形界面：环境状态检测与初始化向导（复用官方 `specify` CLI）、AI 工具环境识别与切换、工作流阶段可视化（状态推导自磁盘产物）与"下一步"按钮触发 speckit 命令、长操作进度与取消、以及澄清标记（[NEEDS CLARIFICATION]）的交互式问答与写回。技术形态：TypeScript 扩展宿主 + React/Vite Webview 面板，文件监听驱动状态刷新，workspaceState 持久化最小界面状态。

> **术语约定**：面向用户的 UI 文案使用「工具环境」；代码、类型与契约文档统一使用 `integration`（集成）。

## Technical Context

**Language/Version**: TypeScript 5.x（strict）；扩展宿主运行于 VSCode Extension Host（Node.js ≥ 18）；`engines.vscode`: `^1.99.0`

**Primary Dependencies**: VSCode Extension API（WebviewPanel、FileSystemWatcher、workspaceState、Terminal/Chat 命令）；Webview 前端 React 18 + Vite；扩展端打包 esbuild；测试 Vitest + @vscode/test-electron。外部进程：官方 `specify` CLI（specify-cli，Python ≥3.11，经 uv/pipx/pip 安装）

**Storage**: 无数据库。只读消费工作区文件（`.specify/`、`specs/`、`tasks.md` 等）；插件自身仅写：澄清答案写回 spec 文档、`workspaceState` 中的最小 UI 状态

**Testing**: Vitest（单元：核心推导/解析逻辑）+ @vscode/test-electron（集成：面板、命令、watcher 冒烟）；fixture 样例项目 + `fake-specify` CLI 桩

**Target Platform**: VSCode Desktop 1.99+（Windows / macOS / Linux）；对 Cursor 等 VSCode 系编辑器尽力兼容（命令触发走抽象传输层）

**Project Type**: 编辑器扩展（VSCode extension，Activity Bar Webview 面板 + 状态栏项）

**Performance Goals**: 面板冷启动首屏 < 1s；环境检测 < 500ms；产物变化 → 面板更新 < 1s；满足 SC-002（5s 内显示环境与阶段）与 SC-006（无 >5s 无反馈）

**Constraints**: 单工作区根目录（multi-root 不支持）；初始化/切换依赖外部 `specify` CLI 可用（缺失时给出安装指引，不自动安装）；Webview 仅加载本地资源（严格 CSP）；v1 无遥测；不重新实现 spec/plan/tasks 生成逻辑（按钮触发 AI 代理执行）

**Scale/Scope**: 1 个 Webview 面板 + 1 个状态栏项；7 个核心工作流阶段（constitution/specify/clarify/plan/tasks/analyze/implement）+ 评审关卡；40+ 受支持工具目录（静态快照）；15 条 FR

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` 当前为**未填充的模板**（全部为占位符，无已批准原则、无治理条款），因此本特性无可执行的宪法门禁。

- 结论（Phase 0 前）：**PASS（N/A）** — 无需 justification，无需 Complexity Tracking 记录
- **复检结论（Phase 1 设计后）：PASS（N/A）** — 宪法仍未被填充；设计期间产生的外部依赖决策（复用官方 `specify` CLI、React/Vite Webview、外部 AI 代理执行生成）未引入违反任何既记录原则的结构；若宪法在实现期间被正式批准，须回到本计划复核（尤其"复用 CLI 而非自研初始化"与"不重新实现生成逻辑"两条架构边界）

## Project Structure

### Documentation (this feature)

```text
specs/001-vscode-speckit-gui/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   ├── webview-protocol.md   # 宿主 ↔ Webview 消息协议
│   ├── artifacts.md          # 磁盘工件契约（检测/解析/写回规则）
│   ├── cli.md                # specify CLI 调用契约
│   └── dispatch.md           # speckit 命令触发契约
├── checklists/
│   └── requirements.md  # 规范质量清单
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
.vscode/                    # launch/tasks 调试配置
src/                        # 扩展宿主端（Node.js / Extension Host）
├── extension.ts            # 激活入口：命令注册、状态栏、面板生命周期
├── core/
│   ├── environment.ts      # 环境检测：init-options.json、集成 manifest、完整性判定
│   ├── toolCatalog.ts      # 受支持工具目录（加载 resources/tool-catalog.json）
│   ├── featureCatalog.ts   # specs/ 特性扫描、当前特性选择（默认最近修改）
│   ├── workflow.ts         # 阶段模型、产物→状态推导、评审关卡
│   ├── clarify.ts          # [NEEDS CLARIFICATION] 标记解析与写回
│   └── taskProgress.ts     # tasks.md 复选框 N/M 统计
├── init/
│   ├── cli.ts              # specify CLI 进程封装：spawn（无 shell）、输出流、取消
│   └── initRunner.ts       # 初始化 / integration install 编排与友好错误映射
├── dispatch/
│   ├── dispatcher.ts       # 阶段→命令→调用令牌（按集成与 ai_skills 模式）
│   └── transports.ts       # 传输层：chat-open / 剪贴板回退
├── panel/
│   ├── panel.ts            # WebviewPanel：CSP、资源加载、消息路由
│   └── watcher.ts          # FileSystemWatcher（.specify/**、specs/**）→ 防抖刷新
└── state/
    └── store.ts            # workspaceState 读写（当前特性、评审确认）

shared/
└── protocol.ts             # 宿主 ↔ Webview 消息协议共享类型（两端 import）

webview-ui/                 # Webview 前端（React 18 + Vite）
├── src/
│   ├── App.tsx             # 视图路由：向导 / 工作流 / 澄清 / 进度
│   ├── views/
│   │   ├── WizardView.tsx      # 初始化向导（US1）
│   │   ├── CliMissingView.tsx  # CLI 未安装引导（US1）
│   │   ├── WorkflowView.tsx    # 阶段时间线 + 下一步按钮（US2）
│   │   ├── ClarifyView.tsx     # 澄清问题卡片（US4）
│   │   └── ProgressView.tsx    # 进度指示与 N/M（US3）
│   ├── components/
│   │   ├── ErrorSurface.tsx    # 全局错误/提示呈现（FR-011）
│   │   └── FeatureSwitcher.tsx # 特性切换下拉（FR-012）
│   └── ...（状态管理、消息总线 hook）
└── vite.config.ts

resources/
└── tool-catalog.json       # 受支持 AI 工具目录（源自 specify_cli INTEGRATION_REGISTRY 快照）

tests/
├── unit/                   # Vitest 单元测试（core/、clarify、workflow、taskProgress）
├── integration/            # @vscode/test-electron 集成测试
└── fixtures/               # 样例项目：uninitialized / partial / complete / corrupt
    └── fake-specify/       # CLI 桩（模拟 init/install 输出与退出码）

package.json               # 插件清单（contributes: viewsContainers/views/commands/configuration）
esbuild.js                 # 扩展端打包脚本
tsconfig.json
```

**Structure Decision**: 采用单一 VSCode 扩展项目（根目录即扩展根）：`src/` 为扩展宿主端（状态推导、CLI 编排、面板宿主），`webview-ui/` 为 Webview 前端（React+Vite 独立构建产物注入 Webview），`shared/protocol.ts` 保证两端消息类型一致。测试与 fixture 独立成 `tests/` 树。不引入 monorepo/多包结构——单一扩展无需拆包。

## Complexity Tracking

> 无宪法违规，本节留空。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |