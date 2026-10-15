// T030: 集成测试——面板编排冒烟（US1）
// 说明：通过 vitest 的 vscode 桩（tests/helpers/vscode-stub.ts）在 Node 内驱动
// InitRunner 真实编排 + fake-specify CLI 桩；完整 Extension Host 冒烟（@vscode/test-electron）
// 需交互环境，由 quickstart.md F5 场景人工执行（T031）。
import { afterAll, beforeEach, describe, expect, it } from 'vitest';
import { execFileSync } from 'node:child_process';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { InitRunner, INSTALL_GUIDANCE } from '../../src/init/initRunner';
import { findSpecifyInPath } from '../../src/init/cli';
import { detectEnvironment } from '../../src/core/environment';
import { parseToolCatalog } from '../../src/core/toolCatalog';
import type { FriendlyError, Progress } from '../../shared/protocol';

const FIX = (...p: string[]) => path.join(process.cwd(), 'tests', 'fixtures', ...p);
const catalog = parseToolCatalog(
  fs.readFileSync(path.join(process.cwd(), 'resources', 'tool-catalog.json'), 'utf-8'),
);

const tempRoots: string[] = [];

function makeRoot(from: 'uninitialized' | 'partial' | 'corrupt'): string {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-panel-'));
  fs.cpSync(FIX(from), tmp, { recursive: true });
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
    builtinSrcDir: () => path.join(os.tmpdir(), 'spk-no-builtin-xyz'),
    bundleStorageDir: () => path.join(root, '.spk-bundles'),
    allowPathFallback: false,
    onProgress: (p) => progresses.push(p),
    onDone: () => undefined,
    onError: (e) => errors.push(e),
  });
  return { runner, errors, progresses };
}

beforeEach(() => {
  delete (globalThis as Record<string, unknown>).__SPK_CONFIG;
});

afterAll(() => {
  for (const dir of tempRoots) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

describe('T030 initRunner × fake-specify（US1 集成）', () => {
  it('PATH 发现：空 PATH → 不可发现；含 specify 桩 → 可发现（win32 命名为 specify.cmd）', () => {
    expect(findSpecifyInPath('', 'win32')).toBeUndefined();
    // findSpecifyInPath 查找 specify/specify.cmd；将 fake-specify 复制为规范命名
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-path-'));
    const srcJs = path.join(process.cwd(), 'tests', 'fixtures', 'fake-specify', 'fake-specify.js');
    fs.copyFileSync(srcJs, path.join(tmp, 'specify.cmd.mjs'));
    fs.copyFileSync(srcJs, path.join(tmp, 'specify'));
    fs.chmodSync(path.join(tmp, 'specify'), 0o755);
    if (process.platform === 'win32') {
      fs.copyFileSync(srcJs, path.join(tmp, 'specify.cmd'));
      const shim = ['@echo off', `node "${path.join(tmp, 'specify.cmd.mjs')}" %*`, 'exit /b %ERRORLEVEL%'].join('\r\n');
      fs.writeFileSync(path.join(tmp, 'specify.cmd'), shim);
    }
    try {
      const found = findSpecifyInPath(tmp + path.delimiter, process.platform);
      expect(found).toBeDefined();
      expect(found?.startsWith(tmp)).toBe(true);
    } finally {
      fs.rmSync(tmp, { recursive: true, force: true });
    }
  });

  it('cli 不可用 → startInit 回报 cli-not-found + 安装指引（FR-011）', async () => {
    (globalThis as Record<string, unknown>).__SPK_CONFIG = {
      specifyCliPath: path.join(os.tmpdir(), 'no-such-specify-xyz'),
    };
    const root = makeRoot('uninitialized');
    const { runner, errors } = makeRunner(root);
    await runner.startInit({ integrationId: 'claude', script: 'ps', force: true });
    expect(errors).toHaveLength(1);
    expect(errors[0].code).toBe('cli-not-found');
    expect(errors[0].suggestion).toBe(INSTALL_GUIDANCE);
    expect(errors[0].canRetry).toBe(true);
  });

  it('fake-specify init 成功 → init-options.json 写入 ai=claude → 环境 ready（场景 1b）', async () => {
    const stubCmd = path.join(process.cwd(), 'tests', 'fixtures', 'fake-specify', 'fake-specify.cmd');
    const stubSh = path.join(process.cwd(), 'tests', 'fixtures', 'fake-specify', 'fake-specify.sh');
    const cliPath = process.platform === 'win32' ? stubCmd : stubSh;
    if (process.platform !== 'win32') {
      fs.chmodSync(stubSh, 0o755);
    }
    (globalThis as Record<string, unknown>).__SPK_CONFIG = { specifyCliPath: cliPath };

    const root = makeRoot('uninitialized');
    const { runner, errors } = makeRunner(root);
    await runner.startInit({ integrationId: 'claude', script: 'ps', force: true });
    expect(errors).toHaveLength(0);

    const env = await detectEnvironment(root, { cliAvailable: true, labelFor: catalog.labelFor });
    expect(env.state).toBe('ready');
    expect(env.integrationId).toBe('claude');
    expect(env.integrationLabel).toBe('Claude Code');
    expect(env.speckitVersion).toBe('1.0.0-fake');
  });

  it('corrupt fixture → incomplete（场景 1f 容错）', async () => {
    const root = makeRoot('corrupt');
    const env = await detectEnvironment(root, { cliAvailable: true, labelFor: catalog.labelFor });
    expect(env.state).toBe('incomplete');
    expect(env.hints.join(' ')).toContain('无法解析');
  });

  it('unsupported integration id → cli-failed（不经 CLI 即拦截）', async () => {
    const root = makeRoot('uninitialized');
    const { runner, errors } = makeRunner(root);
    await runner.startInit({ integrationId: 'no-such-tool', script: 'ps', force: true });
    expect(errors).toHaveLength(1);
    expect(errors[0].code).toBe('cli-failed');
    expect(errors[0].message).toContain('no-such-tool');
  });

  it('fake-specify check 子命令可运行（环境诊断）', () => {
    const js = path.join(process.cwd(), 'tests', 'fixtures', 'fake-specify', 'fake-specify.js');
    const out = execFileSync(process.execPath, [js, 'check'], { encoding: 'utf-8' });
    expect(out).toContain('all tools ok');
  });
});