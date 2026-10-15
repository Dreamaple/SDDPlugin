# Contract: specify CLI 调用

**Feature**: `001-vscode-speckit-gui` | **Date**: 2026-10-15 | **Source**: research.md R3/R12 + `input/spec-kit-main`（specify-cli 1.2.1.dev0）

## 1. 调用来源解析（v0.4.0：内置源码直跑为推荐路径）

1. 设置 `speckitGui.specifyCliPath`（文件路径，非空且存在 → **直跑模式**，兼容旧流程/测试桩）
2. **内置源码 + uv**（推荐）：插件自带 specify-cli 源码副本（`resources/speckit-cli`，含 pyproject/src/templates/scripts/workflows/bundles/extensions），若已下载更新的 Release 副本（globalStorage/speckit-bundles/<tag>）则优先副本（版本比较取最新）；uvx 可发现 → `uvx --from <源码目录> specify ...`（bundled 模式）
3. PATH 上的 `specify`（兜底直跑，Windows 需同时尝试 `specify.cmd` / `specify.exe`）
4. 均不可用 → `errorRaised(cli-not-found)`：有内置源但缺 uv → uv 安装指引；全缺 → uv + specify CLI 双指引，附"重新检测"按钮

- bundled 模式首次运行 uvx 会构建隔离环境（从 PyPI 拉依赖并缓存，需网络；此后走缓存秒级）
- bundled 模式能力 = 全旗标（1.2.x 源码），免 `--help` 探测；direct 模式继续能力探测（parseInitCapabilities）
- 版本显示：bundled → 内置副本 pyproject `version`；direct → `specify --version` 解析

要求：Python ≥ 3.11 由 CLI 自身声明；插件不校验 Python，只校验 uv/CLI 可执行与调用退出码。v1 不自动安装 uv。

## 2. 调用契约

统一规则：
- `spawn`（**永不使用 shell**），UTF-8，cwd = 工作区根
- stdout/stderr 逐行捕获 → `Progress.logTail`（环形 ≤ 10 行）
- 取消：`CancellationToken` → 终止进程树（Windows `taskkill /T`，POSIX `kill(-pid)`）→ Progress 终态"已取消"
- 退出码 0 = 成功；非 0 = 失败（`cli-failed`，message 取 stderr 尾行摘要 + 友好映射，原始输出入 OutputChannel `Speckit GUI`）
- 超时：无输出 > 120s 视为疑似挂起 → 提示用户（不自动杀进程）

### init（全新初始化，2026-10-15 增强：覆盖官方完整旗标）
```text
specify init --here --integration <id> --script <ps|sh|py> [--force] --non-interactive
             [--preset=<id>] [--extension=<name>]… [--integration-options=<text>]
             [--ignore-agent-tools] [--allow-symlinks] [--trust-extension-urls] [--trust-integration]
```
- 参数由 `buildInitArgs()`（`src/init/initRunner.ts`，纯函数）构建；值型选项统一 `--flag=value` 形式，规避以 "-" 开头的值被解析为新旗标
- 前置校验：工作区未初始化或用户已确认覆盖（`force` 仅在用户二次确认后为 true，FR-004/FR-015）
- 高级选项默认关闭/留空：preset、extension（可重复）、integration-options、ignore-agent-tools、allow-symlinks、trust-extension-urls、trust-integration（后两项仅外部内容需要，UI 附警示）
- 成功后：重读 init-options.json 推送 `stateUpdated`；校验 `ai` == 请求值，不一致 → `errorRaised(cli-failed)`

### integration install（工具切换 / 追加安装）
```text
specify integration install <integrationId> [--script <ps|sh|py>] [--force]
```
- `--script` 省略时由 CLI 依 init-options.json / 平台默认；切换前宿主展示当前环境与影响提示（FR-004 二次确认）
- 成功后同 init 的回读校验

### 更新内置 Spec Kit（v0.4.0，替代 v0.3.0 的 specify upgrade 流程）
```text
GET https://api.github.com/repos/github/spec-kit/releases/latest     # 解析最新 tag
GET https://codeload.github.com/github/spec-kit/zip/refs/tags/<tag>  # 整仓源码 zip
```
- 下载进度为 determinate（ratio 0..1，可取消）；解压阶段不可取消
- zip-slip 防护：解压前逐条目校验解析路径位于目标目录内
- 解压目标：globalStorage/speckit-bundles/<tag>/（整仓快照，pyproject 在根，force-include 路径齐备）
- 校验：pyproject 存在且 version 可解析；成功后 invalidateCli → 下次调用走新副本
- 旧版 `specify upgrade` 流程废弃（机器 CLI 版本不再参与初始化）

### check / --version（环境诊断）
```text
specify check      # 检查必需工具（输出透传 OutputChannel，结果以通知摘要呈现）
specify --version  # 版本探测：specify 0.13.1.dev0 → 0.13.1.dev0（parseVersionText，版本显示与升级支持判定输入）
```

## 3. 错误映射表（友好文案，FR-011）

| 症状 | code | message 要点 | suggestion |
|------|------|--------------|------------|
| CLI 未发现 | `cli-not-found` | 未找到 specify CLI | 安装指引 + 重新检测 |
| init 目录冲突 | `cli-failed` | 当前目录已有冲突内容，需覆盖确认 | 提示勾选"强制覆盖"重试 |
| 网络失败 | `cli-failed` | 下载模板/集成失败，请检查网络 | 重试 |
| 集成 id 无效 | `cli-failed` | 所选工具不被当前 CLI 支持 | 升级 CLI / 换选工具 |
| 非 0 退出（其他） | `cli-failed` | 初始化失败：<stderr 摘要> | 重试 / 查看日志 |

所有原始 stderr/stdout 必须写入 OutputChannel，供"查看日志"动作打开（不进 UI）。