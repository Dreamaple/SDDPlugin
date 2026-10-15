// T023: 环境检测边界测试（US1：missing/incomplete/ready/未知 ai/ai_skills）
import { describe, expect, it } from 'vitest';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { detectEnvironment } from '../../src/core/environment';

const FIX = (...p: string[]) => path.join(process.cwd(), 'tests', 'fixtures', ...p);

describe('T023 环境检测边界', () => {
  it('不存在的根 → missing', async () => {
    const env = await detectEnvironment(path.join(os.tmpdir(), 'speckit-gui-no-such-root-xyz'), {
      cliAvailable: false,
    });
    expect(env.state).toBe('missing');
    expect(env.cliAvailable).toBe(false);
  });

  it('.specify 存在但 init-options.json 缺失 → incomplete + 缺失 hint', async () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-env-'));
    fs.mkdirSync(path.join(tmp, '.specify'));
    const env = await detectEnvironment(tmp, { cliAvailable: false });
    expect(env.state).toBe('incomplete');
    expect(env.hints.some((h) => h.includes('缺少 .specify/init-options.json'))).toBe(true);
  });

  it('损坏 JSON → incomplete + 无法解析 hint（corrupt fixture）', async () => {
    const env = await detectEnvironment(FIX('corrupt'), { cliAvailable: false });
    expect(env.state).toBe('incomplete');
    expect(env.hints.join(' ')).toContain('无法解析');
  });

  it('ai 为空字符串 → incomplete', async () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-env-'));
    fs.mkdirSync(path.join(tmp, '.specify'));
    fs.writeFileSync(path.join(tmp, '.specify', 'init-options.json'), '{"ai": ""}');
    const env = await detectEnvironment(tmp, { cliAvailable: false });
    expect(env.state).toBe('incomplete');
  });

  it('未知 ai 值 → ready 且 isKnownIntegration=false（未知/自定义环境）', async () => {
    const env = await detectEnvironment(FIX('partial'), {
      cliAvailable: true,
      labelFor: () => undefined,
    });
    expect(env.state).toBe('ready');
    expect(env.isKnownIntegration).toBe(false);
  });

  it('ai_skills=true 透传（skills 模式令牌）', async () => {
    const env = await detectEnvironment(FIX('clarify'), { cliAvailable: true });
    expect(env.aiSkills).toBe(true);
  });

  it('script 非 sh/ps/py → undefined', async () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-env-'));
    fs.mkdirSync(path.join(tmp, '.specify'));
    fs.writeFileSync(
      path.join(tmp, '.specify', 'init-options.json'),
      '{"ai":"claude","script":"fish"}',
    );
    const env = await detectEnvironment(tmp, { cliAvailable: true });
    expect(env.state).toBe('ready');
    expect(env.script).toBeUndefined();
  });
});