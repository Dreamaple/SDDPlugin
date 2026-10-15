// T025: 初始化/切换编排（contracts/cli.md §1/§2/§3）
// - CLI 发现链：设置 speckitGui.specifyCliPath → PATH → 「需要安装」态
// - init: specify init --here --integration <id> --script <ps|sh|py> [--force] --non-interactive
// - switch: specify integration install <id> [--force]
// - 成功后回读 init-options.json 校验 ai 一致；错误友好映射
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';
import type { FriendlyError, InitOptions, Progress } from '../../shared/protocol';
import { idleProgress } from '../../shared/protocol';
import type { ToolCatalog } from '../core/toolCatalog';
import { findSpecifyInPath, runSpecify, type CliRunHandle } from './cli';

export const INSTALL_GUIDANCE =
  'uvx --from git+https://github.com/github/spec-kit.git specify --help  ' +
  '或  pipx install specify-cli  或  pip install specify-cli';

export interface RunnerDeps {
  getRoot(): string;
  catalog: ToolCatalog;
  output: vscode.OutputChannel;
  onProgress(progress: Progress): void;
  onDone(): void;
  onError(error: FriendlyError): void;
}

interface ProgressRing {
  label: string;
  logTail: string[];
}

const RING_MAX = 10;

/**
 * 构建 `specify init` 参数（纯函数，可测试；contracts/cli.md §2）。
 * 值型选项统一使用 `--flag=value` 形式（避免以 "-" 开头的值被解析为新旗标）。
 */
export function buildInitArgs(o: InitOptions): string[] {
  const args = ['init', '--here', '--integration', o.integrationId, '--script', o.script];
  if (o.force) {
    args.push('--force');
  }
  const preset = o.preset?.trim();
  if (preset) {
    args.push(`--preset=${preset}`);
  }
  for (const ext of o.extensions ?? []) {
    const t = ext.trim();
    if (t) {
      args.push(`--extension=${t}`);
    }
  }
  const io = o.integrationOptions?.trim();
  if (io) {
    args.push(`--integration-options=${io}`);
  }
  if (o.ignoreAgentTools) {
    args.push('--ignore-agent-tools');
  }
  if (o.allowSymlinks) {
    args.push('--allow-symlinks');
  }
  if (o.trustExtensionUrls) {
    args.push('--trust-extension-urls');
  }
  if (o.trustIntegration) {
    args.push('--trust-integration');
  }
  args.push('--non-interactive');
  return args;
}

export class InitRunner {
  private handle: CliRunHandle | undefined;
  private cliChecked = false;
  private cliCmd: string | undefined;
  private cancelled = false;

  constructor(private readonly deps: RunnerDeps) {}

  /** 设置驱动的 CLI 路径 */
  private configuredPath(): string {
    return vscode.workspace.getConfiguration('speckitGui').get<string>('specifyCliPath', '');
  }

  /** contracts/cli.md §1 发现链；不可用时回报 cli-not-found（silent=true 时仅返回 undefined，用于被动快照）并返回 undefined */
  async ensureCli(opts: { silent?: boolean } = {}): Promise<string | undefined> {
    if (this.cliChecked && this.cliCmd) {
      return this.cliCmd;
    }
    const configured = this.configuredPath().trim();
    if (configured.length > 0) {
      if (fs.existsSync(configured)) {
        this.cliCmd = configured;
        this.cliChecked = true;
        return this.cliCmd;
      }
      if (!opts.silent) {
        this.deps.onError({
          code: 'cli-not-found',
          message: `未找到 specify CLI（设置路径无效：${configured}）`,
          suggestion: INSTALL_GUIDANCE,
          canRetry: true,
        });
      }
      return undefined;
    }
    const found = findSpecifyInPath(process.env.PATH ?? '', process.platform);
    if (!found) {
      if (!opts.silent) {
        this.deps.onError({
          code: 'cli-not-found',
          message: '未找到 specify CLI',
          suggestion: INSTALL_GUIDANCE,
          canRetry: true,
        });
      }
      return undefined;
    }
    this.cliCmd = found;
    this.cliChecked = true;
    return this.cliCmd;
  }

  /** 重新检测（设置变更或用户点击「重新检测」） */
  invalidateCli(): void {
    this.cliChecked = false;
    this.cliCmd = undefined;
  }

  get isRunning(): boolean {
    return this.handle !== undefined;
  }

  cancel(): void {
    this.cancelled = true;
    this.handle?.cancel();
  }

  /** T025 startInit 编排 */
  async startInit(options: InitOptions): Promise<void> {
    if (!this.deps.catalog.labelFor(options.integrationId)) {
      this.deps.onError({
        code: 'cli-failed',
        message: `所选工具不被支持：${options.integrationId}`,
        suggestion: '请从工具目录中重新选择',
        canRetry: true,
        context: { integrationId: options.integrationId },
      });
      return;
    }
    const args = buildInitArgs(options);
    await this.runCliOperation('init', options.integrationId, args, options.integrationId, {
      action: 'startInit',
      options,
    });
  }

  /** T025 switchIntegration 编排 */
  async switchIntegration(integrationId: string, force: boolean): Promise<void> {
    if (!this.deps.catalog.labelFor(integrationId)) {
      this.deps.onError({
        code: 'cli-failed',
        message: `所选工具不被支持：${integrationId}`,
        suggestion: '请从工具目录中重新选择',
        canRetry: true,
        context: { integrationId },
      });
      return;
    }
    const args = ['integration', 'install', integrationId];
    if (force) {
      args.push('--force');
    }
    await this.runCliOperation('integration-install', integrationId, args, integrationId, {
      action: 'switchIntegration',
      integrationId,
      force,
    });
  }

  private baseProgress(operation: Progress['operation'], label: string): Progress {
    const p = idleProgress();
    p.operation = operation;
    p.running = true;
    p.kind = 'indeterminate';
    p.label = label;
    p.cancellable = true;
    return p;
  }

  private async runCliOperation(
    operation: Progress['operation'],
    integrationId: string,
    args: string[],
    verifyIntegration: string,
    retry: { action: 'startInit'; options: InitOptions } | { action: 'switchIntegration'; integrationId: string; force: boolean },
  ): Promise<void> {
    if (this.handle) {
      this.deps.onError({
        code: 'io-error',
        message: '已有操作正在执行，请等待完成或取消',
        canRetry: false,
      });
      return;
    }
    const cli = await this.ensureCli();
    if (!cli) {
      return; // cli-not-found 已回报
    }

    this.cancelled = false;
    const ring: ProgressRing = {
      label:
        operation === 'init'
          ? `正在初始化 ${integrationId} 环境…`
          : `正在切换为 ${integrationId} 环境…`,
      logTail: [],
    };
    let progress = this.baseProgress(operation, ring.label);
    this.deps.onProgress(progress);

    const emitLine = (line: string) => {
      ring.logTail.push(line);
      if (ring.logTail.length > RING_MAX) {
        ring.logTail.shift();
      }
      this.deps.output.appendLine(`[${new Date().toISOString()}] ${line}`);
      progress = { ...progress, label: ring.label, logTail: [...ring.logTail] };
      this.deps.onProgress(progress);
    };

    this.deps.output.appendLine(`[speckit-gui] spawn: ${cli} ${args.join(' ')}`);
    const handle = runSpecify(this.deps.getRoot(), cli, args, emitLine);
    this.handle = handle;
    const result = await handle.promise;
    this.handle = undefined;

    if (this.cancelled || result.killed) {
      progress = {
        ...progress,
        running: false,
        cancellable: false,
        result: { outcome: 'cancelled', message: '操作已取消' },
      };
      this.deps.onProgress(progress);
      this.deps.onDone();
      return;
    }

    if (result.code !== 0) {
      progress = {
        ...progress,
        running: false,
        cancellable: false,
        result: { outcome: 'failure', message: '操作失败，可重试' },
      };
      this.deps.onProgress(progress);
      const mapped = this.mapCliFailure(result.stderrTail, operation, integrationId);
      this.deps.onError({
        ...mapped,
        // 上下文驱动重试：ErrorSurface 依据 action 重放原操作（contracts/webview-protocol.md）
        context: { ...mapped.context, action: retry.action, ...(retry as object) },
      });
      this.deps.onDone();
      return;
    }

    // 成功后回读 init-options.json 校验 ai 一致（contracts/cli.md §2）
    const verified = this.verifyIntegration(verifyIntegration);
    progress = {
      ...progress,
      running: false,
      cancellable: false,
      result: verified
        ? { outcome: 'success', message: `工具环境已更新：${integrationId}` }
        : { outcome: 'failure', message: '初始化完成但环境校验不一致' },
    };
    this.deps.onProgress(progress);
    if (!verified) {
      this.deps.onError({
        code: 'cli-failed',
        message: '初始化完成，但 init-options.json 与所选工具不一致',
        suggestion: '请查看日志并重试',
        canRetry: true,
        context: { integrationId },
      });
    }
    this.deps.onDone();
  }

  private verifyIntegration(expected: string): boolean {
    const p = path.join(this.deps.getRoot(), '.specify', 'init-options.json');
    try {
      const parsed = JSON.parse(fs.readFileSync(p, 'utf-8')) as { ai?: string };
      return parsed.ai === expected;
    } catch {
      return false;
    }
  }

  /** contracts/cli.md §3 错误映射表 */
  private mapCliFailure(
    stderrTail: string[],
    operation: Progress['operation'],
    integrationId: string,
  ): FriendlyError {
    const tail = stderrTail.join('\n');
    const opLabel = operation === 'init' ? '初始化' : '切换';
    if (/network|ECONN|ENOTFOUND|ETIMEDOUT|timeout|timed out/i.test(tail)) {
      return {
        code: 'cli-failed',
        message: `${opLabel}失败：网络错误，请检查网络连接`,
        suggestion: '检查网络后重试',
        canRetry: true,
        context: { integrationId },
      };
    }
    if (/directory conflict|--force|already exists|not empty/i.test(tail)) {
      return {
        code: 'cli-failed',
        message: `${opLabel}失败：当前目录已有冲突内容，需要覆盖确认`,
        suggestion: '勾选「强制覆盖」后重试',
        canRetry: true,
        context: { integrationId },
      };
    }
    if (/unknown integration|invalid integration|not a valid|unsupported|no such integration/i.test(tail)) {
      return {
        code: 'cli-failed',
        message: `${opLabel}失败：所选工具不被当前 CLI 支持（${integrationId}）`,
        suggestion: '升级 specify CLI 或换选其他工具',
        canRetry: true,
        context: { integrationId },
      };
    }
    const lastLine = stderrTail[stderrTail.length - 1] ?? `退出码非 0`;
    return {
      code: 'cli-failed',
      message: `${opLabel}失败：${lastLine}`,
      suggestion: '重试或查看日志（输出面板 Speckit GUI）',
      canRetry: true,
      context: { integrationId },
    };
  }
}