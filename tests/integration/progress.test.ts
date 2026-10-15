// T045: 集成测试——进度流与取消（US3）
// fake-specify 慢速运行 → onProgress 事件流持续更新；取消 → 进程树终止 + cancelled 终态
import { afterAll, beforeEach, describe, expect, it } from 'vitest';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { InitRunner } from '../../src/init/initRunner';
import { parseToolCatalog } from '../../src/core/toolCatalog';
import type { FriendlyError, Progress } from '../../shared/protocol';

const FIX = (...p: string[]) => path.join(process.cwd(), 'tests', 'fixtures', ...p);
const catalog = parseToolCatalog(
  fs.readFileSync(path.join(process.cwd(), 'resources', 'tool-catalog.json'), 'utf-8'),
);

const tempRoots: string[] = [];
const savedEnv: Record<string, string | undefined> = {};

function makeRoot(): string {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-progress-'));
  fs.cpSync(FIX('uninitialized'), tmp, { recursive: true });
  tempRoots.push(tmp);
  return tmp;
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
});

afterAll(() => {
  // Windows 下被终止的子进程可能短暂持有目录句柄——清理失败忽略（OS 会回收临时目录）
  for (const dir of tempRoots) {
    try {
      fs.rmSync(dir, { recursive: true, force: true });
    } catch {
      /* ignore EPERM */
    }
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

function stubCliPath(): string {
  const stubCmd = path.join(process.cwd(), 'tests', 'fixtures', 'fake-specify', 'fake-specify.cmd');
  const stubSh = path.join(process.cwd(), 'tests', 'fixtures', 'fake-specify', 'fake-specify.sh');
  if (process.platform !== 'win32') {
    fs.chmodSync(stubSh, 0o755);
  }
  return process.platform === 'win32' ? stubCmd : stubSh;
}

describe('T045 进度与取消（US3 集成）', () => {
  it('慢速 init → 进度事件流持续更新（logTail 增长，场景 3a）', async () => {
    process.env.FAKE_SPECIFY_DELAY = '60';
    process.env.FAKE_SPECIFY_LINES = '6';
    (globalThis as Record<string, unknown>).__SPK_CONFIG = { specifyCliPath: stubCliPath() };

    const root = makeRoot();
    const { runner, progresses, errors } = makeRunner(root);
    await runner.startInit({ integrationId: 'claude', script: 'ps', force: true });

    expect(errors).toHaveLength(0);
    // 初始 running + ≥6 行输出事件 → 事件流持续
    expect(progresses.length).toBeGreaterThanOrEqual(7);
    expect(progresses[0].running).toBe(true);
    expect(progresses[0].cancellable).toBe(true);
    const last = progresses[progresses.length - 1];
    expect(last.running).toBe(false);
    expect(last.result?.outcome).toBe('success');
    expect(last.logTail.length).toBeLessThanOrEqual(10);
  }, 20000);

  it('取消运行中的 init → cancelled 终态（场景 3d）', async () => {
    process.env.FAKE_SPECIFY_DELAY = '300';
    process.env.FAKE_SPECIFY_LINES = '40';
    (globalThis as Record<string, unknown>).__SPK_CONFIG = { specifyCliPath: stubCliPath() };

    const root = makeRoot();
    const { runner, progresses } = makeRunner(root);
    const done = runner.startInit({ integrationId: 'gemini', script: 'sh', force: true });
    // 等待若干事件后取消
    await new Promise((r) => setTimeout(r, 600));
    expect(progresses.length).toBeGreaterThan(0);
    runner.cancel();
    await done;

    const last = progresses[progresses.length - 1];
    expect(last.result?.outcome).toBe('cancelled');
    // 进程被杀 → 未落盘 init-options.json
    expect(fs.existsSync(path.join(root, '.specify', 'init-options.json'))).toBe(false);
  }, 30000);
});