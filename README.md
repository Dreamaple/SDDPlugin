# Speckit GUI（VSCode 插件）

Spec Kit 的可视化面板：全程图形界面完成 SDD（Spec-Driven Development）流程——初始化、工具环境识别/切换、工作流引导、进度可视化与澄清问答。

## 功能

- **环境检测与初始化向导**（US1）：自动识别项目 `.specify` 环境状态（未初始化/不完整/就绪）与已配置的 AI 工具；图形向导选择工具与脚本类型后复用官方 `specify` CLI 执行初始化；支持二次确认后切换工具环境（`specify integration install`）
- **工作流全景与下一步引导**（US2）：constitution → specify → clarify → plan → tasks → analyze → implement 阶段时间线，状态由磁盘产物推导；醒目「下一步」按钮触发对应 speckit 命令（聊天预填/剪贴板回退）；内置 spec/plan 人工评审关卡
- **进度可视化**（US3）：CLI 长操作逐行进度流 + 可取消（进程树终止）；任务阶段 N/M 复选框统计
- **澄清可视化**（US4）：解析 spec 中 `[NEEDS CLARIFICATION: …]` 标记为交互问题卡片（含建议选项表），点选或自定义答案后单事务写回 spec 并确保零残留

## 前置条件

- Node.js ≥ 20、npm ≥ 10；VSCode Desktop ≥ 1.99（或 Cursor 等兼容编辑器）
- 初始化/切换功能需官方 `specify` CLI（specify-cli，Python ≥ 3.11）：
  - `uvx --from git+https://github.com/github/spec-kit.git specify --help`，或
  - `pipx install specify-cli` / `pip install specify-cli`
  - 或在设置中指定 `speckitGui.specifyCliPath`
  - 未安装时：工作流/澄清等状态可视化仍可用（离线友好）

## 开发

```bash
npm install          # 安装依赖
npm run compile      # esbuild（扩展宿主）+ vite（Webview React）双端构建
npm run typecheck    # tsc 双工程类型检查
npm run lint         # eslint
npm test             # Vitest：tests/unit + tests/integration（61 用例）
npm run package      # vsce 打包 .vsix
```

F5 调试：启动 Extension Development Host（`.vscode/launch.json`），点击活动栏 Speckit 图标打开面板。

**交互式走查**：按 `specs/001-vscode-speckit-gui/quickstart.md` 场景 1–4 逐条验证（含 SC 预算）。

## 设置项

| 设置 | 默认 | 说明 |
|------|------|------|
| `speckitGui.specifyCliPath` | `""` | specify CLI 路径；留空在 PATH 查找 |
| `speckitGui.dispatchTransport` | `chat-open` | 命令触发传输：聊天预填 / 剪贴板回退 |
| `speckitGui.answerPrefix` | `**答案**: ` | 澄清答案写回前缀（可置空） |

## 架构速览

- `src/`：扩展宿主端（`core/` 纯逻辑推导、`init/` CLI 编排、`dispatch/` 命令触发、`panel/` Webview 宿主 + 文件监听、`state/` workspaceState）
- `webview-ui/`：React 18 + Vite 前端（单 JS 产物，CSP nonce 加载）
- `shared/protocol.ts`：宿主 ↔ Webview 消息协议单一事实源
- `tests/`：Vitest（`helpers/vscode-stub.ts` 提供可落盘的 vscode 桩）+ `fixtures/`（5 个样例项目 + `fake-specify` CLI 桩）
- 设计文档：`specs/001-vscode-speckit-gui/`（spec/plan/research/data-model/contracts/quickstart/tasks）

## 已知边界（v1）

- 仅支持单根工作区（multi-root 拒绝并提示）
- 插件不重新实现 spec/plan/tasks 生成逻辑——按钮触发命令，由 AI 代理执行实际生成
- 工具目录为静态快照（来自 `INTEGRATION_REGISTRY`），未知集成显示为「未知/自定义环境」
- Windows 下 `.cmd` 形式的 CLI 经 `cmd.exe /d /s /c` 包装执行（参数均来自受控常量，无注入面）