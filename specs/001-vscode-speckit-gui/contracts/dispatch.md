# Contract: speckit 命令触发（Dispatch）

**Feature**: `001-vscode-speckit-gui` | **Date**: 2026-10-15 | **Source**: research.md R7

## 1. 阶段 → 命令映射

| 阶段 id | 命令基名 | skills 模式令牌（`ai_skills: true`） | 命令模式令牌 |
|---------|----------|--------------------------------------|--------------|
| constitution | constitution | `/speckit-constitution` | `/speckit.constitution` |
| specify | specify | `/speckit-specify` | `/speckit.specify` |
| clarify | clarify | `/speckit-clarify` | `/speckit.clarify` |
| plan | plan | `/speckit-plan` | `/speckit.plan` |
| tasks | tasks | `/speckit-tasks` | `/speckit.tasks` |
| analyze | analyze | `/speckit-analyze` | `/speckit.analyze` |
| implement | implement | `/speckit-implement` | `/speckit.implement` |

令牌模式判定：`.specify/init-options.json` 的 `ai_skills === true` → skills 令牌；否则命令模式令牌。未初始化工作区无令牌可发（按钮禁用）。

## 2. 传输层

### Transport A：chat-open（默认）
执行编辑器命令 `workbench.action.chat.open`，参数预填 `<token> `（含尾随空格），焦点交给用户确认发送。
- 目标：Copilot Chat（VSCode）与 Cursor 的 AI 聊天均接受该编辑器命令或等效实现；插件不做厂商探测，仅负责"打开聊天并预填令牌"
- 结果：成功 → `commandResult(dispatched)`

### Transport B：clipboard（回退/显式选择）
复制令牌到剪贴板 + 信息通知"已复制 <token>，请粘贴到 AI 聊天发送" + "打开聊天"按钮（再次尝试 A）。
- 触发条件：A 执行抛错（命令不存在/被拒）或设置 `speckitGui.dispatchTransport = "clipboard"`
- 结果：`commandResult(fallback-clipboard)`

### 失败
两种传输均失败（如剪贴板权限拒绝）→ `commandResult(failed)` + `errorRaised`；阶段状态不转 in_progress。

## 3. 触发语义

- `dispatchStage(stageId)` 成功（dispatched 或 fallback-clipboard）→ 记录 `lastStageTrigger[stageId]` → 该阶段视图状态转 `in_progress`（产物满足规则优先于该记录）
- SC-004 的"2 秒内触发"以令牌送达（聊天打开/复制完成）计，**不含** AI 代理执行时间
- implement 阶段特殊文案：按钮"下一步：运行 /speckit-implement"始终可点，但 tasks 阶段未完成时提示确认（防误触）

## 4. 评审关卡（FR-014）

- 关卡集合：`spec-review`（specify 完成后）、`plan-review`（plan 完成后）
- 关卡未确认 → 面板在阶段列表与"下一步"位置显示评审确认卡（"已生成 spec，请评审后继续" + 确认按钮），确认写入 `reviewConfirmations` 后放行下一阶段
- 关卡确认**不**自动触发下一阶段；放行后用户仍以"下一步"按钮显式推进（保持用户掌控）