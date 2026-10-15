# Contract: 宿主 ↔ Webview 消息协议

**Feature**: `001-vscode-speckit-gui` | **Date**: 2026-10-15

宿主端（Extension Host）与 Webview（React）之间的唯一通信通道：`webview.postMessage(msg)` 下行、`acquireVsCodeApi().postMessage(msg)` 上行。消息类型定义于 `shared/protocol.ts`，两端共享导入（单一事实源）。所有消息含 `type` 判别字段；未识别 type 必须被接收方忽略（前向兼容）。

## 下行（宿主 → Webview）

### `stateUpdated`
全量状态快照（watcher 防抖 300ms 或本地操作后推送）。

```ts
{
  type: "stateUpdated",
  snapshot: {
    environment: WorkspaceEnvironment;          // data-model §1
    features: Feature[];                        // data-model §3（含 isCurrent）
    stages: WorkflowStage[];                    // data-model §4（含派生 state）
    clarifications: ClarificationItem[];        // data-model §5（当前特性）
    nextStep: { stageId: string; token: string } | null;
    reviewPending: { gateId: "spec-review" | "plan-review" } | null;
  }
}
```

### `progressUpdated`
进度事件流（运行期间高频，终态必达一次）。

```ts
{ type: "progressUpdated", progress: Progress }        // data-model §6
```

### `errorRaised`
友好错误（含建议操作；原始堆栈只进 OutputChannel，永不下发）。

```ts
{
  type: "errorRaised",
  error: {
    code: "cli-not-found" | "cli-failed" | "workspace-missing" | "write-back-failed" | "io-error";
    message: string;              // 友好文案
    suggestion?: string;          // 建议操作（重试/安装指引/查看日志）
    canRetry: boolean;
  }
}
```

### `commandResult`
阶段触发（dispatch）结果回执。

```ts
{ type: "commandResult", stageId: string; outcome: "dispatched" | "fallback-clipboard" | "failed"; token: string }
```

## 上行（Webview → 宿主）

### `ready` / `refresh`
```ts
{ type: "ready" }      // Webview 加载完成，宿主应推首帧 stateUpdated
{ type: "refresh" }    // 用户点击刷新，宿主立即重推 stateUpdated
```

### `startInit`
```ts
{
  type: "startInit",
  options: {
    integrationId: string;          // 必填，来自 tool-catalog
    script: "sh" | "ps" | "py";     // 必填（向导默认：Windows→ps，其他→sh）
    force: boolean;                 // 用户已见覆盖警告后的确认值
    // —— 高级选项（默认关闭/留空，对齐 specify init 完整旗标）——
    preset?: string;                // --preset=<id>
    extensions?: string[];          // --extension=<name>（可重复）
    integrationOptions?: string;    // --integration-options=<text>
    ignoreAgentTools?: boolean;     // --ignore-agent-tools
    allowSymlinks?: boolean;        // --allow-symlinks
    trustExtensionUrls?: boolean;   // --trust-extension-urls
    trustIntegration?: boolean;     // --trust-integration
  }
}
```

### `switchIntegration`
```ts
{ type: "switchIntegration", integrationId: string; force: boolean }   // force 语义同上（二次确认后）
```

### `selectFeature`
```ts
{ type: "selectFeature", dirName: string }
```

### `dispatchStage`
```ts
{ type: "dispatchStage", stageId: string }        // 触发"下一步"/阶段按钮
```

### `confirmReview`
```ts
{ type: "confirmReview", gateId: "spec-review" | "plan-review" }
```

### `answerClarification`
```ts
{ type: "answerClarification", id: string; answer: string }   // 宿主执行写回；成功后经 stateUpdated 反映
```

### `cancelOperation`
```ts
{ type: "cancelOperation" }    // 取消当前 cancellable 的 Progress
```

### `upgradeSpeckit`（v0.3.0）
```ts
{ type: "upgradeSpeckit" }    // 升级 Spec Kit CLI；宿主做版本感知（旧版 0.x 无 upgrade 命令 → 回报手动升级指引）
```

## 交互时序（关键）

1. 面板创建 → Webview 加载 → `ready` → 宿主 `stateUpdated`（首帧 ≤ 1s）
2. 磁盘产物变化 → watcher → 防抖 → `stateUpdated`（≤ 1s）
3. `startInit` → 宿主校验 + `progressUpdated(running)` 流 → `stateUpdated(environment=ready)` + `progressUpdated(终态)`；失败 → `progressUpdated(失败终态)` + `errorRaised(canRetry=true)`
4. `dispatchStage` → `commandResult` → `stateUpdated`（阶段转 in_progress）
5. `answerClarification` → 写回（单事务） → 重扫 → `stateUpdated`（无残留标记）

## 校验规则

- `startInit`/`switchIntegration` 的 `integrationId` 必须命中 tool-catalog，否则宿主回 `errorRaised(write-back-failed… code=cli-failed)` 并忽略
- `answerClarification` 的 `id` 必须命中当前 clarifications，否则忽略
- 宿主在任何上行消息处理前验证工作区单根；multi-root → `errorRaised(workspace-missing)`