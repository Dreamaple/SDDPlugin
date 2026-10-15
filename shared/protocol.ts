// T009: 宿主 ↔ Webview 共享协议（contracts/webview-protocol.md 的单一事实源）
// 双端共享导入；未识别的消息 type 必须被接收方忽略（前向兼容）。

// ---------- 数据模型（对齐 data-model.md） ----------

export type EnvState = 'missing' | 'incomplete' | 'ready';
export type ScriptType = 'sh' | 'ps' | 'py';

export interface WorkspaceEnvironment {
  state: EnvState;
  /** init-options.json 的 ai 字段（集成 id） */
  integrationId?: string;
  /** 工具目录命中的显示名；未命中显示「未知/自定义环境」 */
  integrationLabel?: string;
  isKnownIntegration: boolean;
  script?: ScriptType;
  speckitVersion?: string;
  /** init-options.json 的 ai_skills（skills 模式令牌推导） */
  aiSkills?: boolean;
  /** specify CLI 是否可发现（contracts/cli.md §1 解析链） */
  cliAvailable: boolean;
  /** incomplete 时的具体缺失说明 */
  hints: string[];
}

export interface FeatureArtifacts {
  /** 各产物 mtime（ms）；constitution 仅在「已填充」时存在 */
  constitution?: number;
  spec?: number;
  plan?: number;
  tasks?: number;
}

export interface Feature {
  dirName: string;
  number?: number;
  name: string;
  artifacts: FeatureArtifacts;
  isCurrent: boolean;
}

export type StageId =
  | 'constitution'
  | 'specify'
  | 'clarify'
  | 'plan'
  | 'tasks'
  | 'analyze'
  | 'implement';

export type StageState = 'not_started' | 'in_progress' | 'completed' | 'blocked_review' | 'error';
export type GateId = 'spec-review' | 'plan-review';

export interface WorkflowStage {
  id: StageId;
  order: number;
  label: string;
  optional: boolean;
  /** contracts/dispatch.md §1：skills 模式 /speckit-<name>，命令模式 /speckit.<name> */
  commandToken: string;
  /** 命令探测可用性；不可用则禁用按钮（不隐藏行） */
  available: boolean;
  state: StageState;
  gate?: GateId;
  /** tasks/implement 阶段的复选框统计 */
  taskStats?: { done: number; total: number };
}

export interface ClarificationOption {
  label: string;
  implication: string;
}

/** 受支持工具目录条目（与 resources/tool-catalog.json 对齐） */
export interface ToolCatalogEntry {
  id: string;
  label: string;
}

export interface ClarificationItem {
  id: string;
  question: string;
  context: string;
  options?: ClarificationOption[];
  answer?: string;
  status: 'open' | 'answered' | 'unparseable';
  /** 原始标记全文（写回替换的精确输入；协议增补字段） */
  rawMarker: string;
}

export interface Progress {
  /** null = 无操作进行中 */
  operation: 'init' | 'integration-install' | 'stage' | null;
  running: boolean;
  kind: 'determinate' | 'indeterminate';
  label: string;
  /** CLI 最近输出行（环形，≤10 行） */
  logTail: string[];
  taskStats?: { done: number; total: number };
  cancellable: boolean;
  result?: { outcome: 'success' | 'failure' | 'cancelled'; message: string };
}

export function idleProgress(): Progress {
  return {
    operation: null,
    running: false,
    kind: 'indeterminate',
    label: '',
    logTail: [],
    cancellable: false,
  };
}

// ---------- 快照 ----------

export interface Snapshot {
  workspaceRootLabel: string;
  multiRootBlocked: boolean;
  environment: WorkspaceEnvironment;
  /** 受支持工具目录（向导选择用，协议增补字段） */
  tools: ToolCatalogEntry[];
  features: Feature[];
  stages: WorkflowStage[];
  clarifications: ClarificationItem[];
  nextStep: { stageId: StageId; token: string } | null;
  reviewPending: GateId | null;
}

// ---------- 错误 ----------

export type ErrorCode =
  | 'cli-not-found'
  | 'cli-failed'
  | 'workspace-missing'
  | 'write-back-failed'
  | 'io-error';

export interface FriendlyError {
  code: ErrorCode;
  message: string;
  suggestion?: string;
  canRetry: boolean;
  /** 关联的上下文（如失败的 stageId / integrationId），供重试使用 */
  context?: Record<string, unknown>;
}

// ---------- 消息 ----------

export interface InitOptions {
  integrationId: string;
  script: ScriptType;
  force: boolean;
}

export type HostToWebview =
  | { type: 'stateUpdated'; snapshot: Snapshot }
  | { type: 'progressUpdated'; progress: Progress }
  | { type: 'errorRaised'; error: FriendlyError }
  | {
      type: 'commandResult';
      stageId: StageId;
      outcome: 'dispatched' | 'fallback-clipboard' | 'failed';
      token: string;
    };

export type WebviewToHost =
  | { type: 'ready' }
  | { type: 'refresh' }
  | { type: 'startInit'; options: InitOptions }
  | { type: 'switchIntegration'; integrationId: string; force: boolean }
  | { type: 'selectFeature'; dirName: string }
  | { type: 'dispatchStage'; stageId: StageId }
  | { type: 'confirmReview'; gateId: GateId }
  | { type: 'answerClarification'; id: string; answer: string }
  | { type: 'cancelOperation' }
  | { type: 'openLogs' };