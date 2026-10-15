// v0.3.0 集成测试——CLI 版本解析 + 升级编排（specify upgrade / 旧版降级指引）
import { afterAll, beforeEach, describe, expect, it } from 'vitest';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { InitRunner, UPGRADE_GUIDANCE } from '../../src/init/initRunner';
import { parseVersionText } from '../../src/init/cli';
import { parseToolCatalog } from '../../src/core/toolCatalog';
import type { FriendlyError, Progress } from '../../shared/protocol';

const FIX = (...p: string[]) => path.join(process.cwd(), 'tests', 'fixtures', ...p);
const catalog = parseToolCatalog(
  fs.readFileSync(path.join(process.cwd(), 'resources', 'tool-catalog.json'), 'utf-8'),
);

const tempRoots: string[] = [];
const savedEnv: Record<string, string | undefined> = {};

function makeRoot(): string {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-upgrade-'));
  fs.cpSync(FIX('uninitialized'), tmp, { recursive: true });
  tempRoots.push(tmp);
  return tmp;
}

function stubCliPath(): string {
  const stubCmd = path.join(process.cwd(), 'tests', 'fixtures', 'fake-specify', 'fake-specify.cmd');
  const stubSh = path.join(process.cwd(), 'tests', 'fixtures', 'fake-specify', 'fake-specify.sh');
  if (process.platform !== 'win32') {
    fs.chmodSync(stubSh, 0o755);
  }
  return process.platform === 'win32' ? stubCmd : stubSh;
}

function makeRunner(root: string) {
  const errors: FriendlyError[] = [];
  const progresses: Progress[] = [];
  const channel = { appendLine: (_: string) => undefined, show: () => undefined } as never;
  const runner = new InitRunner({
    getRoot: () => root,
    catalog,
    output: channel,
    onProgress: (p) => progresses.push(p),
    onDone: () => undefined,
    onError: (e) => errors.push(e),
  });
  return { runner, errors, progresses };
}

beforeEach(() => {
  delete (globalThis as Record<string, unknown>).__SPK_CONFIG;
  for (const k of ['FAKE_SPECIFY_DELAY', 'FAKE_SPECIFY_LINES', 'FAKE_SPECIFY_EXIT']) {
    savedEnv[k] = process.env[k];
  }
  process.env.FAKE_SPECIFY_DELAY = '0';
  process.env.FAKE_SPECIFY_LINES = '2';
});

afterAll(() => {
  for (const dir of tempRoots) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
  for (const [k, v] of Object.entries(savedEnv)) {
    if (v === undefined) {
      delete process.env[k];
    } else {
      process.env[k] = v;
    }
  }
  delete (globalThis as Record<string, unknown>).__SPK_CONFIG;
});

describe('CLI 版本解析（parseVersionText）', () => {
  it('"specify 0.13.1.dev0" → 0.13.1.dev0', () => {
    expect(parseVersionText('specify 0.13.1.dev0')).toBe('0.13.1.dev0');
  });
  it('"specify v1.2.3" → 1.2.3（v 前缀剥离）', () => {
    expect(parseVersionText('specify v1.2.3')).toBe('1.2.3');
  });
  it('多行输出取首个匹配（含 "version" 字样）', () => {
    expect(parseVersionText('banner...\nspecify version 1.0.0\nmore')).toBe('1.0.0');
  });
  it('无版本信息 → undefined', () => {
    expect(parseVersionText('nothing here')).toBeUndefined();
  });
});

describe('升级编排（specify upgrade）', () => {
  it('fake-specify upgrade 成功 → success 终态、无错误（v0.3.0 场景）', async () => {
    process.env.FAKE_SPECIFY_EXIT = '0';
    (globalThis as Record<string, unknown>).__SPK_CONFIG = { specifyCliPath: stubCliPath() };
    const root = makeRoot();
    const { runner, errors, progresses } = makeRunner(root);
    await runner.upgradeSpeckit();
    expect(errors).toHaveLength(0);
    const last = progresses[progresses.length - 1];
    expect(last.result?.outcome).toBe('success');
    expect(last.result?.message).toContain('已升级');
  }, 20000);

  it('fake-specify upgrade 失败 → 升级失败 + 友好映射（含 stderr 尾行）', async () => {
    process.env.FAKE_SPECIFY_EXIT = '1';
    (globalThis as Record<string, unknown>).__SPK_CONFIG = { specifyCliPath: stubCliPath() };
    const root = makeRoot();
    const { runner, errors, progresses } = makeRunner(root);
    await runner.upgradeSpeckit();
    expect(errors).toHaveLength(1);
    expect(errors[0].code).toBe('cli-failed');
    expect(errors[0].message).toContain('升级失败');
    expect(errors[0].suggestion).toBeDefined();
    const last = progresses[progresses.length - 1];
    expect(last.result?.outcome).toBe('failure');
    expect(last.result?.message).toContain('升级');
  }, 20000);

  it('升级中不可取消（cancellable=false，安装器中断风险）', async () => {
    process.env.FAKE_SPECIFY_EXIT = '0';
    (globalThis as Record<string, unknown>).__SPK_CONFIG = { specifyCliPath: stubCliPath() };
    const root = makeRoot();
    const { runner, progresses } = makeRunner(root);
    await runner.upgradeSpeckit();
    const running = progresses.filter((p) => p.running);
    expect(running.length).toBeGreaterThan(0);
    expect(running.every((p) => p.cancellable === false)).toBe(true);
  }, 20000);

  it('UPGRADE_GUIDANCE 提及 uv/pipx 手动升级路径（旧版 CLI 降级场景）', () => {
    expect(UPGRADE_GUIDANCE).toContain('uv tool upgrade');
    expect(UPGRADE_GUIDANCE).toContain('pipx upgrade');
  });
});