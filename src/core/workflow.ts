// T015: 工作流阶段模型、产物→状态推导、评审关卡、下一步指针（data-model.md §4）
import type {
  Feature,
  GateId,
  StageId,
  StageState,
  WorkflowStage,
  WorkspaceEnvironment,
} from '../../shared/protocol';
import type { TaskStats } from './taskProgress';

export const STAGE_ORDER: StageId[] = [
  'constitution',
  'specify',
  'clarify',
  'plan',
  'tasks',
  'analyze',
  'implement',
];

const STAGE_LABELS: Record<StageId, string> = {
  constitution: '宪法',
  specify: '规范',
  clarify: '澄清',
  plan: '方案',
  tasks: '任务',
  analyze: '分析',
  implement: '实现',
};

/** analyze/clarify 为可选阶段；命令不可用时禁用按钮（不隐藏行） */
const OPTIONAL_STAGES: ReadonlySet<StageId> = new Set(['clarify', 'analyze']);

/** 阶段后的人工评审关卡（对齐 .specify/workflows/speckit/workflow.yml 的 review gates） */
const STAGE_GATES: Partial<Record<StageId, GateId>> = {
  specify: 'spec-review',
  plan: 'plan-review',
};

// ---------- 命令令牌（contracts/dispatch.md §1） ----------

/** 阶段 → 命令基名 */
export function stageCommandBase(stage: StageId): string {
  return stage;
}

/** 调用令牌：skills 模式（ai_skills=true）→ /speckit-<name>；命令模式 → /speckit.<name> */
export function deriveCommandToken(stage: StageId, aiSkills: boolean): string {
  const base = stageCommandBase(stage);
  return aiSkills ? `/speckit-${base}` : `/speckit.${base}`;
}

// ---------- 命令可用性探测（contracts/artifacts.md §1 可用命令探测） ----------

import * as fs from 'node:fs';
import * as path from 'node:path';

const SKILLS_DIRS = ['.cursor/skills', '.claude/skills', '.agents/skills', '.github/skills'];
const COMMAND_DIRS = [
  '.github/prompts',
  '.claude/commands',
  '.codex/prompts',
  '.gemini/commands',
  '.opencode/command',
];

function dirHasEntryWithPrefix(root: string, dir: string, prefixes: string[]): boolean {
  const abs = path.join(root, dir);
  try {
    const entries = fs.readdirSync(abs);
    return entries.some((e) => prefixes.some((p) => e.startsWith(p)));
  } catch {
    return false;
  }
}

/**
 * 探测各阶段命令可用性。探测失败的非可选阶段回退为可用（自定义集成布局下保持 UI 可用），
 * 可选阶段（clarify/analyze）探测失败则禁用。
 */
export function detectStageAvailability(
  root: string,
  env: WorkspaceEnvironment,
): Record<StageId, boolean> {
  const result = {} as Record<StageId, boolean>;
  const prefixesFor = (stage: StageId): string[] =>
    env.aiSkills ? [`speckit-${stage}`] : [`speckit.${stage}`, `speckit-${stage}`];
  const dirs = env.aiSkills ? SKILLS_DIRS : COMMAND_DIRS;

  for (const stage of STAGE_ORDER) {
    const optional = OPTIONAL_STAGES.has(stage);
    let detected = false;
    for (const dir of dirs) {
      if (dirHasEntryWithPrefix(root, dir, prefixesFor(stage))) {
        detected = true;
        break;
      }
    }
    // 非可选阶段探测失败 → 回退可用（contracts 允许：探测仅影响 optional 降级）
    result[stage] = detected || !optional;
  }
  return result;
}

// ---------- 状态推导 ----------

export interface BuildStagesInput {
  env: WorkspaceEnvironment;
  feature: Feature | undefined;
  /** 当前特性 spec 文本（clarify 阶段判定） */
  specContent: string | undefined;
  /** 当前特性 tasks.md 复选框统计 */
  taskStats: TaskStats | undefined;
  constitutionReady: boolean;
  hasOpenClarifications: boolean;
  availableCommands: Record<StageId, boolean>;
  /** workspaceState.lastStageTrigger（stageId → ISO 时间） */
  lastTrigger: Record<string, string>;
  /** 运行时最近触发失败记录（不持久化） */
  lastFailure: Partial<Record<StageId, boolean>>;
  /** workspaceState.reviewConfirmations */
  reviewConfirmations: Partial<Record<GateId, string>>;
}

function deriveState(
  stage: StageId,
  input: BuildStagesInput,
  completed: boolean,
): StageState {
  if (completed) {
    const gate = STAGE_GATES[stage];
    if (gate && !input.reviewConfirmations[gate]) {
      return 'blocked_review';
    }
    return 'completed';
  }
  if (input.lastFailure[stage]) {
    return 'error';
  }
  if (input.lastTrigger[stage]) {
    return 'in_progress';
  }
  return 'not_started';
}

/** 构建有序工作流阶段列表（含状态机、关卡、nextStep） */
export function buildStages(input: BuildStagesInput): WorkflowStage[] {
  const { env, feature, taskStats } = input;
  const aiSkills = env.aiSkills === true;
  const specExists = Boolean(feature?.artifacts.spec);
  const planExists = Boolean(feature?.artifacts.plan);
  const tasksExists = Boolean(feature?.artifacts.tasks);

  const stages: WorkflowStage[] = STAGE_ORDER.map((stage, idx) => {
    const optional = OPTIONAL_STAGES.has(stage);
    const base: WorkflowStage = {
      id: stage,
      order: idx + 1,
      label: STAGE_LABELS[stage],
      optional,
      commandToken: deriveCommandToken(stage, aiSkills),
      available: input.availableCommands[stage] ?? !optional,
      state: 'not_started',
      gate: STAGE_GATES[stage],
    };

    let completed = false;
    switch (stage) {
      case 'constitution':
        completed = input.constitutionReady;
        break;
      case 'specify':
        completed = specExists;
        break;
      case 'clarify':
        // 无未答标记 → 已完成（无需澄清）；unparseable 不阻塞
        completed = specExists && !input.hasOpenClarifications;
        break;
      case 'plan':
        completed = planExists;
        break;
      case 'tasks':
        completed = tasksExists && (taskStats?.total ?? 0) > 0;
        break;
      case 'analyze':
        completed = tasksExists && (taskStats?.total ?? 0) > 0;
        break;
      case 'implement':
        completed =
          tasksExists &&
          taskStats !== undefined &&
          taskStats.total > 0 &&
          taskStats.done === taskStats.total;
        break;
    }
    base.state = deriveState(stage, input, completed);
    if (stage === 'tasks' || stage === 'implement') {
      base.taskStats = taskStats;
    }
    return base;
  });

  return stages;
}

/** 当前建议阶段：第一个非 completed 的阶段；若为 blocked_review → reviewPending 为其关卡 */
export function deriveNextStep(stages: WorkflowStage[]): {
  nextStep: { stageId: StageId; token: string } | null;
  reviewPending: GateId | null;
} {
  for (const stage of stages) {
    if (stage.state !== 'completed') {
      return {
        nextStep: { stageId: stage.id, token: stage.commandToken },
        reviewPending: stage.state === 'blocked_review' ? (stage.gate ?? null) : null,
      };
    }
  }
  return { nextStep: null, reviewPending: null };
}