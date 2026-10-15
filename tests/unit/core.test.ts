// T022: 核心推导单元测试（fixtures 矩阵：environment/feature/workflow 派生）
import { describe, expect, it } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { detectEnvironment } from '../../src/core/environment';
import { parseToolCatalog } from '../../src/core/toolCatalog';
import {
  isConstitutionReady,
  resolveCurrentFeatureDir,
  scanFeatures,
} from '../../src/core/featureCatalog';
import { countTaskCheckboxes } from '../../src/core/taskProgress';
import { parseClarifications } from '../../src/core/clarify';
import { buildStages, deriveNextStep, detectStageAvailability } from '../../src/core/workflow';
import type { WorkspaceEnvironment } from '../../shared/protocol';

const FIX = (...p: string[]) => path.join(process.cwd(), 'tests', 'fixtures', ...p);

const catalog = parseToolCatalog(
  fs.readFileSync(path.join(process.cwd(), 'resources', 'tool-catalog.json'), 'utf-8'),
);
const labelFor = (id: string) => catalog.labelFor(id);

function readyEnv(partial: Partial<WorkspaceEnvironment> = {}): WorkspaceEnvironment {
  return {
    state: 'ready',
    isKnownIntegration: true,
    cliAvailable: true,
    hints: [],
    ...partial,
  };
}

describe('T022 环境检测（fixtures）', () => {
  it('uninitialized fixture → missing', async () => {
    const env = await detectEnvironment(FIX('uninitialized'), { cliAvailable: true, labelFor });
    expect(env.state).toBe('missing');
  });

  it('partial fixture → ready (claude/ps, ai_skills=false)', async () => {
    const env = await detectEnvironment(FIX('partial'), { cliAvailable: true, labelFor });
    expect(env.state).toBe('ready');
    expect(env.integrationId).toBe('claude');
    expect(env.integrationLabel).toBe('Claude Code');
    expect(env.script).toBe('ps');
    expect(env.aiSkills).toBe(false);
  });

  it('complete fixture → ready (copilot) + 宪法已填充', async () => {
    const env = await detectEnvironment(FIX('complete'), { cliAvailable: true, labelFor });
    expect(env.state).toBe('ready');
    expect(env.integrationId).toBe('copilot');
    expect(isConstitutionReady(FIX('complete'))).toBe(true);
    expect(isConstitutionReady(FIX('partial'))).toBe(false);
  });

  it('corrupt fixture → incomplete + hints', async () => {
    const env = await detectEnvironment(FIX('corrupt'), { cliAvailable: true, labelFor });
    expect(env.state).toBe('incomplete');
    expect(env.hints.some((h) => h.includes('无法解析'))).toBe(true);
  });
});

describe('T022 特性扫描与当前特性（partial fixture）', () => {
  it('扫描出 001-partial，产物齐全', async () => {
    const features = await scanFeatures(FIX('partial'));
    expect(features).toHaveLength(1);
    expect(features[0].dirName).toBe('001-partial');
    expect(features[0].name).toBe('partial');
    expect(features[0].artifacts.spec).toBeDefined();
    expect(features[0].artifacts.plan).toBeDefined();
    expect(features[0].artifacts.tasks).toBeDefined();
  });

  it('当前特性解析链：feature.json 候选 → statePreferred 覆盖', async () => {
    const root = FIX('partial');
    const features = await scanFeatures(root);
    expect(resolveCurrentFeatureDir(root, features)).toBe('001-partial');
    expect(resolveCurrentFeatureDir(root, features, '001-partial')).toBe('001-partial');
  });

  it('复选框统计：partial 3/7，complete 4/4（大写 X）', async () => {
    const partial = fs.readFileSync(FIX('partial', 'specs', '001-partial', 'tasks.md'), 'utf-8');
    expect(countTaskCheckboxes(partial)).toEqual({ done: 3, total: 7 });
    const complete = fs.readFileSync(FIX('complete', 'specs', '002-complete', 'tasks.md'), 'utf-8');
    expect(countTaskCheckboxes(complete)).toEqual({ done: 4, total: 4 });
  });
});

describe('T022 工作流推导（fixtures 级）', () => {
  it('partial：宪法未填→not_started；specify 完成→blocked_review（关卡未确认）；implement 未开始', async () => {
    const root = FIX('partial');
    const env = await detectEnvironment(root, { cliAvailable: true, labelFor });
    const features = await scanFeatures(root);
    const feature = features[0];
    const spec = fs.readFileSync(FIX('partial', 'specs', '001-partial', 'spec.md'), 'utf-8');
    const clar = parseClarifications(spec);
    const stats = countTaskCheckboxes(
      fs.readFileSync(FIX('partial', 'specs', '001-partial', 'tasks.md'), 'utf-8'),
    );
    const stages = buildStages({
      env,
      feature,
      specContent: spec,
      taskStats: stats,
      constitutionReady: isConstitutionReady(root),
      hasOpenClarifications: clar.some((c) => c.status === 'open'),
      availableCommands: detectStageAvailability(root, env),
      lastTrigger: {},
      lastFailure: {},
      reviewConfirmations: {},
    });
    const byId = Object.fromEntries(stages.map((s) => [s.id, s]));
    expect(byId.constitution.state).toBe('not_started');
    expect(byId.specify.state).toBe('blocked_review');
    expect(byId.clarify.state).toBe('completed'); // 无澄清标记
    expect(byId.plan.state).toBe('blocked_review');
    expect(byId.tasks.state).toBe('completed');
    expect(byId.tasks.taskStats).toEqual({ done: 3, total: 7 });
    expect(byId.implement.state).toBe('not_started');
  });

  it('complete：全部完成，nextStep=null', async () => {
    const root = FIX('complete');
    const env = await detectEnvironment(root, { cliAvailable: true, labelFor });
    const features = await scanFeatures(root);
    const feature = features[0];
    const spec = fs.readFileSync(FIX('complete', 'specs', '002-complete', 'spec.md'), 'utf-8');
    const stages = buildStages({
      env,
      feature,
      specContent: spec,
      taskStats: countTaskCheckboxes(
        fs.readFileSync(FIX('complete', 'specs', '002-complete', 'tasks.md'), 'utf-8'),
      ),
      constitutionReady: true,
      hasOpenClarifications: false,
      availableCommands: detectStageAvailability(root, env),
      lastTrigger: {},
      lastFailure: {},
      // 关卡已确认（complete 场景：评审通过后全部完成）
      reviewConfirmations: { 'spec-review': 'x', 'plan-review': 'x' },
    });
    expect(stages.every((s) => s.state === 'completed')).toBe(true);
    expect(deriveNextStep(stages).nextStep).toBeNull();
  });
});

describe('T022 澄清解析（clarify fixture）', () => {
  it('2 个标记：#1 含 A/B/C 选项，#2 无选项', async () => {
    const spec = fs.readFileSync(FIX('clarify', 'specs', '003-clarify', 'spec.md'), 'utf-8');
    const items = parseClarifications(spec);
    expect(items).toHaveLength(2);
    expect(items[0].status).toBe('open');
    expect(items[0].options?.map((o) => o.label)).toEqual(['A', 'B', 'C']);
    expect(items[1].status).toBe('open');
    expect(items[1].options).toBeUndefined();
    expect(items.every((i) => i.rawMarker.startsWith('[NEEDS CLARIFICATION:'))).toBe(true);
  });

  it('ready 环境（未知 ai 值）→ isKnownIntegration=false', async () => {
    const env = await detectEnvironment(FIX('partial'), {
      cliAvailable: true,
      labelFor: () => undefined,
    });
    expect(env.state).toBe('ready');
    expect(env.isKnownIntegration).toBe(false);
  });

  it('readyEnv helper sanity', () => {
    expect(readyEnv().state).toBe('ready');
  });
});