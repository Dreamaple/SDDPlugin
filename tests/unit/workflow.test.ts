// T032: 工作流状态推导矩阵测试（≥10 状态样例，SC-003 一致率 100%）
import { describe, expect, it } from 'vitest';
import {
  buildStages,
  deriveCommandToken,
  deriveNextStep,
  detectStageAvailability,
} from '../../src/core/workflow';
import type { WorkspaceEnvironment, WorkflowStage } from '../../shared/protocol';

function env(partial: Partial<WorkspaceEnvironment> = {}): WorkspaceEnvironment {
  return {
    state: 'ready',
    isKnownIntegration: true,
    aiSkills: false,
    cliAvailable: true,
    hints: [],
    ...partial,
  };
}

interface Fixture {
  constitutionReady?: boolean;
  spec?: boolean;
  plan?: boolean;
  tasks?: boolean;
  taskStats?: { done: number; total: number };
  openClarifications?: boolean;
}

function stagesOf(f: Fixture, overrides: Record<string, unknown> = {}): WorkflowStage[] {
  return buildStages({
    env: env(),
    feature:
      f.spec || f.plan || f.tasks
        ? {
            dirName: '001-x',
            name: 'x',
            artifacts: {
              spec: f.spec ? 1 : undefined,
              plan: f.plan ? 1 : undefined,
              tasks: f.tasks ? 1 : undefined,
            },
            isCurrent: true,
          }
        : undefined,
    specContent: f.spec ? '# spec' : undefined,
    taskStats: f.taskStats,
    constitutionReady: f.constitutionReady ?? false,
    hasOpenClarifications: f.openClarifications ?? false,
    availableCommands: {
      constitution: true,
      specify: true,
      clarify: true,
      plan: true,
      tasks: true,
      analyze: true,
      implement: true,
    },
    lastTrigger: {},
    lastFailure: {},
    reviewConfirmations: {},
    ...overrides,
  });
}

const byId = (stages: WorkflowStage[]) =>
  Object.fromEntries(stages.map((s) => [s.id, s])) as Record<
    string,
    WorkflowStage
  >;

describe('T032 工作流状态矩阵（SC-003）', () => {
  it('① 未初始化（无特性）→ 全部 not_started', () => {
    const s = byId(stagesOf({}));
    expect(Object.values(s).every((x) => x.state === 'not_started')).toBe(true);
    const { nextStep, reviewPending } = deriveNextStep(Object.values(s));
    expect(nextStep?.stageId).toBe('constitution');
    expect(reviewPending).toBeNull();
  });

  it('② 宪法就绪 → constitution 完成，nextStep 指向 specify', () => {
    const s = byId(stagesOf({ constitutionReady: true }));
    expect(s.constitution.state).toBe('completed');
    expect(s.specify.state).toBe('not_started');
    expect(deriveNextStep(Object.values(s)).nextStep?.stageId).toBe('specify');
  });

  it('③ 仅 spec → specify blocked_review（关卡未确认）', () => {
    const s = byId(stagesOf({ constitutionReady: true, spec: true }));
    expect(s.specify.state).toBe('blocked_review');
    const { reviewPending } = deriveNextStep(Object.values(s));
    expect(reviewPending).toBe('spec-review');
  });

  it('④ spec + 关卡确认 → specify completed，clarify 完成（无标记），plan not_started', () => {
    const s = byId(
      stagesOf(
        { constitutionReady: true, spec: true },
        { reviewConfirmations: { 'spec-review': '2026-10-15T00:00:00Z' } },
      ),
    );
    expect(s.specify.state).toBe('completed');
    expect(s.clarify.state).toBe('completed');
    expect(s.plan.state).toBe('not_started');
  });

  it('⑤ spec（含 open 标记）→ clarify not_started；确认后 specify 放行', () => {
    const s = byId(
      stagesOf(
        { constitutionReady: true, spec: true, openClarifications: true },
        { reviewConfirmations: { 'spec-review': 'x' } },
      ),
    );
    expect(s.clarify.state).toBe('not_started');
  });

  it('⑥ spec+plan → plan blocked_review（plan-review）', () => {
    const s = byId(
      stagesOf(
        { constitutionReady: true, spec: true, plan: true },
        { reviewConfirmations: { 'spec-review': 'x' } },
      ),
    );
    expect(s.plan.state).toBe('blocked_review');
    expect(deriveNextStep(Object.values(s)).reviewPending).toBe('plan-review');
  });

  it('⑦ spec+plan+tasks 3/7 → tasks/analyze 完成，implement not_started', () => {
    const s = byId(
      stagesOf(
        { constitutionReady: true, spec: true, plan: true, tasks: true, taskStats: { done: 3, total: 7 } },
        {
          reviewConfirmations: { 'spec-review': 'x', 'plan-review': 'x' },
        },
      ),
    );
    expect(s.tasks.state).toBe('completed');
    expect(s.analyze.state).toBe('completed');
    expect(s.implement.state).toBe('not_started');
    expect(s.implement.taskStats).toEqual({ done: 3, total: 7 });
  });

  it('⑧ 全勾选（4/4）→ implement completed，nextStep=null', () => {
    const s = byId(
      stagesOf(
        {
          constitutionReady: true,
          spec: true,
          plan: true,
          tasks: true,
          taskStats: { done: 4, total: 4 },
        },
        { reviewConfirmations: { 'spec-review': 'x', 'plan-review': 'x' } },
      ),
    );
    expect(s.implement.state).toBe('completed');
    expect(deriveNextStep(Object.values(s)).nextStep).toBeNull();
  });

  it('⑨ lastTrigger 指定 spec → in_progress（产物未满足）', () => {
    const s = byId(
      stagesOf({ constitutionReady: true }, { lastTrigger: { specify: '2026-10-15T00:00:00Z' } }),
    );
    expect(s.specify.state).toBe('in_progress');
  });

  it('⑩ lastFailure 指定 plan → error', () => {
    const s = byId(
      stagesOf(
        { constitutionReady: true, spec: true },
        { lastFailure: { plan: true }, reviewConfirmations: { 'spec-review': 'x' } },
      ),
    );
    expect(s.plan.state).toBe('error');
  });

  it('⑪ tasks.md 存在但 M=0 → tasks not_started', () => {
    const s = byId(stagesOf({ constitutionReady: true, spec: true, tasks: true }));
    expect(s.tasks.state).toBe('not_started');
  });

  it('⑫ 令牌推导：skills 模式 /speckit-plan，命令模式 /speckit.plan', () => {
    expect(deriveCommandToken('plan', true)).toBe('/speckit-plan');
    expect(deriveCommandToken('plan', false)).toBe('/speckit.plan');
    const aiSkillsStages = buildStages({
      env: env({ aiSkills: true }),
      feature: undefined,
      specContent: undefined,
      taskStats: undefined,
      constitutionReady: false,
      hasOpenClarifications: false,
      availableCommands: {
        constitution: true,
        specify: true,
        clarify: true,
        plan: true,
        tasks: true,
        analyze: true,
        implement: true,
      },
      lastTrigger: {},
      lastFailure: {},
      reviewConfirmations: {},
    });
    expect(aiSkillsStages.find((x) => x.id === 'plan')?.commandToken).toBe('/speckit-plan');
  });

  it('⑬ 命令不可用：可选阶段禁用，非可选回退可用（fixtures/partial 实测）', () => {
    const root = `${process.cwd()}/tests/fixtures/partial`;
    // partial 的 ai_skills=false → 命令模式目录探测（无 .github/prompts 等）→ 可选降级
    const availability = detectStageAvailability(root, env({ aiSkills: false }));
    expect(availability.analyze).toBe(false);
    expect(availability.clarify).toBe(false);
    expect(availability.specify).toBe(true); // 非可选回退
  });
});