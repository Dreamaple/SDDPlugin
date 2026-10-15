# Contract: 磁盘工件（检测 / 解析 / 写回规则）

**Feature**: `001-vscode-speckit-gui` | **Date**: 2026-10-15

插件对工作区文件的全部读写契约。路径均相对工作区根。所有解析必须容错：单个文件损坏只降级相关状态（hints/error），不得令面板崩溃（FR-011）。

## 1. 只读工件

### `.specify/init-options.json`（环境权威源）
JSON 对象，字段：`ai`（集成 id，必读）、`script`、`here`、`ai_skills`、`feature_numbering`、`integration`、`speckit_version`。
- 判定：文件存在 + JSON 可解析 + `ai` 为非空字符串 → `ready`；否则 `.specify` 存在时 → `incomplete`
- 工作区验证样例（本仓库）：`{"ai":"cursor-agent","ai_skills":true,"feature_numbering":"sequential","here":true,"integration":"cursor-agent","script":"ps","speckit_version":"0.13.1.dev0"}`

### `.specify/feature.json`
`{"feature_directory": "specs/NNN-name"}` —— 当前特性初始候选；不可解析则忽略。

### `.specify/memory/constitution.md`
宪法就绪判定：文件存在且内容**不含**未填充占位符（检测子串 `PRINCIPLE_1_NAME` 或 `[PROJECT_NAME]`）。含占位符 → constitution 阶段 `not_started`。

### `specs/<dir>/`
- 目录名匹配 `^(\d{3})-(.+)$` 才计入特性列表（不匹配的目录忽略）
- `spec.md` → specify 产物；`plan.md` → plan 产物；`tasks.md` → tasks 产物
- `.specify/integrations/<id>.manifest.json` 与集成命令目录（`.cursor/skills/`、`.claude/skills/`、`.github/prompts/` 等）仅作 incomplete 辅证

### 可用命令探测（阶段可选性）
- skills 模式（`ai_skills === true`）：`.cursor/skills/speckit-<name>/SKILL.md` 或项目集成对应的 skills 目录存在
- 命令模式：集成命令目录下存在 `speckit.<name>*` 文件
- 探测失败的命令对应阶段标记 optional 并禁用按钮（不隐藏行）

## 2. 写回工件（插件唯一的 spec 文件写入）

### 澄清答案写回
- 标记语法：`[NEEDS CLARIFICATION: <问题文本>]`；解析正则 `/\[NEEDS CLARIFICATION:\s*([^\]]+)\]/g`
- 建议选项（可选增强）：标记邻近（下方 ≤ 30 行内）存在表格头含 `Option` 与 `Answer` 的 markdown 表格 → 行首列为 `label`，其余列为 `implication`
- 写回格式：标记整体替换为 `**答案**: <answer>`（`speckitGui.answerPrefix` 设置可改为空串/自定义前缀）
- 执行：`TextEditor` 单次 `edit` 事务（若文件未打开则先以不可见编辑器打开）；写回后立即重扫，残留同类标记计数为 0 才计成功（SC-005）
- 冲突：写回前校验文件 mtime 与解析时一致；不一致 → 重新解析后重试一次，仍冲突 → `errorRaised(write-back-failed, canRetry=true)`

### tasks.md 复选框统计（只读解析）
- 完成数 N = 匹配 `^\s*[-*] \[[xX]\]` 的行数；总数 M = 匹配 `^\s*[-*] \[[ xX]\]` 的行数
- 未见 tasks.md 或 M=0 → 无 taskStats（进度退化为活动指示）

## 3. 阶段产物判定规则（artifactRule）

| 阶段 | 判定（= completed） | 备注 |
|------|---------------------|------|
| constitution | 宪法就绪（§1 规则） | 未填模板 = not_started |
| specify | 当前特性 `spec.md` 存在 | |
| clarify | spec 无未答标记（含 unparseable 视为已尽审） | spec 无标记 → "已完成（无需澄清）" |
| plan | 当前特性 `plan.md` 存在 | |
| tasks | 当前特性 `tasks.md` 存在且 M > 0 | |
| analyze | 同 tasks（可选阶段；命令可用才显示） | |
| implement | tasks.md 全部复选框已勾（N = M，M > 0） | |

## 4. 时序与监听范围

- Watcher 模式：`.specify/**/*`、`specs/**/*`；创建/删除/修改均触发防抖 300ms 全量重推
- 自写忽略窗口：澄清写回后 1s 内的该文件 watcher 事件不触发重推（防回环；期间状态由写回路径主动推送）
- 一致性要求：任何时刻面板显示的状态必须能在 ≤ 1s 内由磁盘产物重新推导得出（SC-003/SC-008 的实现基础）