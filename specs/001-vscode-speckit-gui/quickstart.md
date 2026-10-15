# Quickstart: 验证指南

**Feature**: `001-vscode-speckit-gui` | **Date**: 2026-10-15

可运行的验证场景，逐条对应 spec.md 用户故事与验收场景。实现细节见 `tasks.md`（/speckit-tasks 产出）；数据与协议契约见 [data-model.md](./data-model.md) 与 [contracts/](./contracts/)。

## 前置条件

- Node.js ≥ 20、npm ≥ 10；VSCode Desktop ≥ 1.99（或 Cursor 等兼容编辑器）
- 本地指定 CLI 二选一（真实验证用）：
  - `uvx --from git+https://github.com/github/spec-kit.git specify --help` 可运行，或
  - `pipx install specify-cli` 后 PATH 上有 `specify`
- 无 CLI 时：场景 1a/1c/3a 可改用 `tests/fixtures/fake-specify/` 桩（设置 `speckitGui.specifyCliPath` 指向桩脚本）

## 构建与运行

```text
npm install          # 安装依赖
npm run compile      # esbuild + vite 双端构建（产物 dist/）
npm run lint         # eslint
npm test             # Vitest 单元 + @vscode/test-electron 集成
```

调试运行：F5（`.vscode/launch.json`）启动 Extension Development Host。

## 场景 1：初始化与工具环境识别（US1）

| # | 步骤 | 预期 |
|---|------|------|
| 1a | 打开 `tests/fixtures/uninitialized/`（空项目），点击状态栏 Speckit 图标 | 面板显示"未初始化"+ 醒目初始化按钮；不超 1s |
| 1b | 走向导：选 `claude`、脚本 `ps`、确认执行 | 进度指示持续更新；成功后显示"已初始化 · Claude Agent"，`.specify/init-options.json` 的 `ai=claude` |
| 1c | 场景 1b 重复于 `tests/fixtures/uninitialized/` 但拔掉 CLI（清空 `speckitGui.specifyCliPath` 且 PATH 无 specify） | `cli-not-found` 友好提示 + 安装指引 + 重试入口；无原始堆栈 |
| 1d | 打开本仓库根（已初始化 cursor-agent） | 5s 内显示"Cursor Agent · ps · 0.13.1.dev0"（SC-002） |
| 1e | 已初始化项目：切换工具 `copilot`，拒绝确认 | 无任何写盘；再操作并二次确认 | `specify integration install` 执行，面板显示 Copilot |
| 1f | 打开 `tests/fixtures/corrupt/`（init-options.json 损坏） | "环境不完整"提示 + 修复/重新初始化引导，不崩溃 |

## 场景 2：工作流与下一步按钮（US2）

| # | 步骤 | 预期 |
|---|------|------|
| 2a | 打开 `tests/fixtures/partial/`（仅 spec.md + plan.md） | constitution/specify/clarify 显示已完成，plan 高亮或 awaiting review；tasks 起为未开始 |
| 2b | 观察下一步按钮 | 文案指向下一建议阶段（如"下一步：运行 /speckit-tasks"） |
| 2c | 点击下一步按钮 | 2s 内聊天窗口打开且输入框预填 `/speckit-tasks`（或剪贴板回退通知）；tasks 转"进行中" |
| 2d | 磁盘新建 `tasks.md`（含 5 个复选框） | ≤ 1s 后 tasks 阶段自动转"已完成"，按钮前移（SC-008） |
| 2e | fixture 含 spec/plan 已完成且关卡未确认 | 显示评审确认卡；确认后按钮指向 tasks |
| 2f | `specs/` 含多特性，切换当前特性 | 工作流/澄清视图切换到新特性；重启 VSCode 后仍记住选择 |

## 场景 3：进度可视化（US3）

| # | 步骤 | 预期 |
|---|------|------|
| 3a | 执行一次 init（或桩脚本 sleep 10s） | 全程有进度指示+最新日志行，无 >5s 完全静止 |
| 3b | `tests/fixtures/partial/` 的 tasks.md 预置 3/7 勾选 | 任务进度显示"3/7 已完成" |
| 3c | 3a 完成后 | 终态"成功"摘要替换进度；失败路径显示原因+重试 |
| 3d | init 进行中点击取消 | 进程终止，界面回到可操作状态，进度显示"已取消" |

## 场景 4：澄清可视化（US4）

| # | 步骤 | 预期 |
|---|------|------|
| 4a | 打开 `tests/fixtures/clarify/`（spec.md 含 2 个 `[NEEDS CLARIFICATION: …]`，其中一个邻近选项表） | 澄清面板出现 2 张卡片；选项表卡片含建议选项+影响说明 |
| 4b | 卡片 1 点选选项 A，卡片 2 输入自定义答案，提交 | spec.md 中两标记分别替换为答案；重扫残留 0（`rg "\[NEEDS CLARIFICATION" specs/` 无命中） |
| 4c | 全部回答后 | 面板显示"无待澄清项"，下一步按钮指向 plan |
| 4d | 未作答关闭面板再打开 | 未答卡片仍在（数据源自磁盘） |

## 边界抽检

- `corrupt/` fixture 在工作流视图下各阶段不显示 error 崩溃态，给出环境修复引导
- 外部编辑器并发修改 spec.md（另一编辑器写入）→ 面板 ≤ 1s 反映
- 未知 `ai` 值（手改 init-options.json 为 `"ai":"no-such-tool"`）→ 显示"未知/自定义环境"，工作流视图仍可用

## 验收对照

- SC-001 ↔ 场景 1a+1b 全程计时 < 3 分钟、零命令行输入
- SC-002/SC-003 ↔ 场景 1d + 2a（10 状态样例矩阵见 `tests/fixtures/`）
- SC-004 ↔ 场景 2b/2c
- SC-005 ↔ 场景 4b（残留 0）
- SC-006 ↔ 场景 3a
- SC-008 ↔ 场景 2d + 边界抽检
- SC-007（用户满意度）↔ 试点调研，不属本 quickstart 自动验证范围