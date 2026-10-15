# Contract: specify CLI 调用

**Feature**: `001-vscode-speckit-gui` | **Date**: 2026-10-15 | **Source**: research.md R3/R12 + `input/spec-kit-main`（specify-cli 1.2.1.dev0）

## 1. 可执行发现（解析顺序）

1. 设置 `speckitGui.specifyCliPath`（文件路径，非空时直接使用，存在性校验失败 → `cli-not-found`）
2. PATH 上的 `specify`（Windows 需同时尝试 `specify.cmd` / `specify.exe`，经 `which`/`where` 语义探测）
3. 均不可用 → 环境面板进入"需要安装"态：`errorRaised(cli-not-found, suggestion=安装指引)`，安装指引文案：
   `uvx --from git+https://github.com/github/spec-kit.git specify --help` 或 `pipx install specify-cli` 或 `pip install specify-cli`，并附"重新检测"按钮

要求：Python ≥ 3.11 由 CLI 自身声明；插件不校验 Python，只校验 CLI 可执行与调用退出码。v1 **不自动安装**。

## 2. 调用契约

统一规则：
- `spawn`（**永不使用 shell**），UTF-8，cwd = 工作区根
- stdout/stderr 逐行捕获 → `Progress.logTail`（环形 ≤ 10 行）
- 取消：`CancellationToken` → 终止进程树（Windows `taskkill /T`，POSIX `kill(-pid)`）→ Progress 终态"已取消"
- 退出码 0 = 成功；非 0 = 失败（`cli-failed`，message 取 stderr 尾行摘要 + 友好映射，原始输出入 OutputChannel `Speckit GUI`）
- 超时：无输出 > 120s 视为疑似挂起 → 提示用户（不自动杀进程）

### init（全新初始化）
```text
specify init --here --integration <integrationId> --script <ps|sh|py> --force --non-interactive
```
- 前置校验：工作区未初始化或用户已确认覆盖（`force` 仅在用户二次确认后为 true，FR-004/FR-015）
- 成功后：重读 init-options.json 推送 `stateUpdated`；校验 `ai` == 请求值，不一致 → `errorRaised(cli-failed)`

### integration install（工具切换 / 追加安装）
```text
specify integration install <integrationId> [--script <ps|sh|py>] [--force]
```
- `--script` 省略时由 CLI 依 init-options.json / 平台默认；切换前宿主展示当前环境与影响提示（FR-004 二次确认）
- 成功后同 init 的回读校验

### check（自检）
```text
specify check
```
- 用于"环境诊断"动作（可选按钮）；输出透传至 OutputChannel，结果以通知摘要呈现

## 3. 错误映射表（友好文案，FR-011）

| 症状 | code | message 要点 | suggestion |
|------|------|--------------|------------|
| CLI 未发现 | `cli-not-found` | 未找到 specify CLI | 安装指引 + 重新检测 |
| init 目录冲突 | `cli-failed` | 当前目录已有冲突内容，需覆盖确认 | 提示勾选"强制覆盖"重试 |
| 网络失败 | `cli-failed` | 下载模板/集成失败，请检查网络 | 重试 |
| 集成 id 无效 | `cli-failed` | 所选工具不被当前 CLI 支持 | 升级 CLI / 换选工具 |
| 非 0 退出（其他） | `cli-failed` | 初始化失败：<stderr 摘要> | 重试 / 查看日志 |

所有原始 stderr/stdout 必须写入 OutputChannel，供"查看日志"动作打开（不进 UI）。