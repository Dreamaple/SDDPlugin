// T025: 初始化/切换/内置源更新编排（contracts/cli.md §1/§2/§3）
// v0.4.0 架构：**内置 CLI 源码直跑**——插件自带 specify-cli 源码副本（resources/speckit-cli），
// 经 `uvx --from <内置源码> specify ...` 执行，不再依赖机器上的 specify CLI 版本。
// 调用来源解析链（contracts/cli.md §1）：
//   1. 设置 speckitGui.specifyCliPath（显式直跑，兼容旧流程/测试桩）
//   2. 内置源码 + uv（uvx --from；推荐路径，版本由插件内置/已下载副本决定）
//   3. PATH 上的 specify（兜底直跑）
// 「更新内置 Spec Kit」= 从 github/spec-kit 最新 Release 下载源码刷新内置副本（bundle.ts）。
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';
import type { FriendlyError, InitOptions, Progress } from '../../shared/protocol';
import { idleProgress } from '../../shared/protocol';
import type { ToolCatalog } from '../core/toolCatalog';
import {
  downloadLatestSpeckitBundle,
  resolveBundledSource,
} from './bundle';
import {
  findExeInPath,
  findSpecifyInPath,
  FULL_INIT_CAPS,
  parseInitCapabilities,
  parseVersionText,
  runSpecify,
  type CliRunHandle,
  type InitCapabilities,
} from './cli';

export const INSTALL_GUIDANCE =
  '初始化需要 uv（用于直跑插件内置的 Spec Kit 源码）：' +
  'powershell -c "irm https://astral.sh/uv/install.ps1 | iex" 或 pip install uv；' +
  '或安装独立 specify CLI：pipx install specify-cli / pip install specify-cli';

export interface RunnerDeps {
  getRoot(): string;
  catalog: ToolCatalog;
  output: vscode.OutputChannel;
  /** 插件自带的内置源码目录（resources/speckit-cli） */
  builtinSrcDir(): string;
  /** 已下载 release 副本存放目录（globalStorage/speckit-bundles） */
  bundleStorageDir(): string;
  /** PATH specify 兜底开关（默认 true；测试传 false 隔离真实 PATH） */
  allowPathFallback?: boolean;
  onProgress(progress: Progress): void;
  onDone(): void;
  onError(error: FriendlyError): void;
}

export type InvocationSource = 'bundled' | 'setting' | 'path' | 'none';

interface Invocation {
  source: 'bundled' | 'setting' | 'path';
  cmd: string;
  /** direct 模式：[]；bundled 模式：['--from', srcDir, 'specify'] */
  argvPrefix: string[];
  srcDir?: string;
  version?: string;
}

interface ProgressRing {
  label: string;
  logTail: string[];
  ratio?: number;
}

const RING_MAX = 10;

/**
 * 构建 `specify init` 参数（纯函数，可测试；contracts/cli.md §2）。
 * 值型选项统一使用 `--flag=value` 形式（避免以 "-" 开头的值被解析为新旗标）；
 * 每个旗标仅在该 CLI 能力（caps）支持时输出。
 */
export function buildInitArgs(o: InitOptions, caps: InitCapabilities = FULL_INIT_CAPS): string[] {
  const args = ['init', '--here', '--integration', o.integrationId, '--script', o.script];
  if (o.force && caps.force) {
    args.push('--force');
  }
  const preset = o.preset?.trim();
  if (preset && caps.preset) {
    args.push(`--preset=${preset}`);
  }
  if (caps.extension) {
    for (const ext of o.extensions ?? []) {
      const t = ext.trim();
      if (t) {
        args.push(`--extension=${t}`);
      }
    }
  }
  const io = o.integrationOptions?.trim();
  if (io && caps.integrationOptions) {
    args.push(`--integration-options=${io}`);
  }
  if (o.ignoreAgentTools && caps.ignoreAgentTools) {
    args.push('--ignore-agent-tools');
  }
  if (o.allowSymlinks && caps.allowSymlinks) {
    args.push('--allow-symlinks');
  }
  if (o.trustExtensionUrls && caps.trustExtensionUrls) {
    args.push('--trust-extension-urls');
  }
  if (o.trustIntegration && caps.trustIntegration) {
    args.push('--trust-integration');
  }
  if (caps.nonInteractive) {
    args.push('--non-interactive');
  }
  return args;
}

/** 请求的高级选项中第一个不被 caps 支持的旗标名（无 → undefined） */
export function checkCapabilities(o: InitOptions, caps: InitCapabilities): string | undefined {
  if (o.preset?.trim() && !caps.preset) {
    return '--preset';
  }
  if ((o.extensions ?? []).some((e) => e.trim()) && !caps.extension) {
    return '--extension';
  }
  if (o.integrationOptions?.trim() && !caps.integrationOptions) {
    return '--integration-options';
  }
  if (o.ignoreAgentTools && !caps.ignoreAgentTools) {
    return '--ignore-agent-tools';
  }
  if (o.allowSymlinks && !caps.allowSymlinks) {
    return '--allow-symlinks';
  }
  if (o.trustExtensionUrls && !caps.trustExtensionUrls) {
    return '--trust-extension-urls';
  }
  if (o.trustIntegration && !caps.trustIntegration) {
    return '--trust-integration';
  }
  return undefined;
}

export class InitRunner {
  private handle: CliRunHandle | undefined;
  private invocation: Invocation | undefined;
  private invocationResolved = false;
  private versionChecked = false;
  private capsChecked = false;
  private caps: InitCapabilities | undefined;
  private cancelled = false;
  private downloadAbort: AbortController | undefined;

  constructor(private readonly deps: RunnerDeps) {}

  /** 设置驱动的 CLI 路径（直跑模式） */
  private configuredPath(): string {
    return vscode.workspace.getConfiguration('speckitGui').get<string>('specifyCliPath', '');
  }

  /**
   * 调用来源解析链（缓存；contracts/cli.md §1）：
   * 设置直跑 → 内置源码 + uvx → PATH specify → none（silent 时不回报错误）
   */
  async ensureInvocation(opts: { silent?: boolean } = {}): Promise<Invocation | undefined> {
    if (this.invocationResolved && this.invocation) {
      return this.invocation;
    }
    // 1. 设置显式路径 → 直跑
    const configured = this.configuredPath().trim();
    if (configured.length > 0 && fs.existsSync(configured)) {
      this.invocation = { source: 'setting', cmd: configured, argvPrefix: [] };
      this.invocationResolved = true;
      return this.invocation;
    }
    // 2. 内置源码 + uvx
    const bundled = resolveBundledSource(this.deps.builtinSrcDir(), this.deps.bundleStorageDir());
    const uvx = findExeInPath('uvx', process.env.PATH ?? '', process.platform);
    if (bundled && uvx) {
      this.invocation = {
        source: 'bundled',
        cmd: uvx,
        argvPrefix: ['--from', bundled.dir, 'specify'],
        srcDir: bundled.dir,
        version: bundled.version,
      };
      this.invocationResolved = true;
      return this.invocation;
    }
    // 3. PATH specify 兜底
    if (this.deps.allowPathFallback !== false) {
      const found = findSpecifyInPath(process.env.PATH ?? '', process.platform);
      if (found) {
        this.invocation = { source: 'path', cmd: found, argvPrefix: [] };
        this.invocationResolved = true;
        return this.invocation;
      }
    }
    // 4. 无来源
    if (!opts.silent) {
      const missingUv = bundled !== undefined; // 有内置源但缺 uv
      this.deps.onError({
        code: 'cli-not-found',
        message: missingUv
          ? '未找到 uv（直跑内置 Spec Kit 源码需要 uv）'
          : '未找到可用的 Spec Kit 初始化来源（uv 与 specify CLI 均不可用）',
        suggestion: INSTALL_GUIDANCE,
        canRetry: true,
      });
    }
    return undefined;
  }

  /** 当前调用来源（供面板显示；undefined = 无来源） */
  async currentSource(): Promise<InvocationSource> {
    const inv = await this.ensureInvocation({ silent: true });
    return inv ? inv.source : 'none';
  }

  /** CLI/内置源版本（bundled → pyproject 解析；direct → --version；缓存） */
  async getVersion(): Promise<string | undefined> {
    const inv = await this.ensureInvocation({ silent: true });
    if (!inv || inv.version) {
      return inv?.version;
    }
    if (this.versionChecked) {
      return inv.version;
    }
    const lines: string[] = [];
    const handle = runSpecify(this.deps.getRoot(), inv.cmd, ['--version'], (line) =>
      lines.push(line),
    );
    const result = await handle.promise;
    if (result.code === 0) {
      const version = parseVersionText(lines.join('\n'));
      if (version) {
        inv.version = version;
      }
    }
    this.versionChecked = true;
    return inv.version;
  }

  /** `specify init` 旗标能力：bundled 源为 1.2.x 全能力（免 --help 探测）；direct 探测（缓存） */
  async getInitCapabilities(): Promise<InitCapabilities> {
    const inv = await this.ensureInvocation({ silent: true });
    if (!inv) {
      return FULL_INIT_CAPS;
    }
    if (inv.source === 'bundled') {
      return FULL_INIT_CAPS;
    }
    if (this.capsChecked && this.caps) {
      return this.caps;
    }
    const lines: string[] = [];
    const handle = runSpecify(this.deps.getRoot(), inv.cmd, ['init', '--help'], (line) =>
      lines.push(line),
    );
    const result = await handle.promise;
    const caps = result.code === 0 ? parseInitCapabilities(lines.join('\n')) : FULL_INIT_CAPS;
    this.caps = caps;
    this.capsChecked = true;
    return caps;
  }

  /** 重新检测（设置变更或用户点击「重新检测」） */
  invalidateCli(): void {
    this.invocationResolved = false;
    this.invocation = undefined;
    this.versionChecked = false;
    this.capsChecked = false;
    this.caps = undefined;
  }

  get isRunning(): boolean {
    return this.handle !== undefined || this.downloadAbort !== undefined;
  }

  cancel(): void {
    this.cancelled = true;
    this.handle?.cancel();
    this.downloadAbort?.abort();
  }

  /** T025 startInit 编排（能力感知：不支持的高级选项 → 升级指引而非裸错误） */
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
    const caps = await this.getInitCapabilities();
    const unsupported = checkCapabilities(options, caps);
    if (unsupported) {
      const version = this.invocation?.version ? `（当前 ${this.invocation.version}）` : '';
      this.deps.onError({
        code: 'cli-failed',
        message: `当前 CLI${version} 不支持选项 ${unsupported}，已跳过本次初始化`,
        suggestion: '点击「更新内置 Spec Kit」升级内置源码后重试',
        canRetry: true,
        context: { integrationId: options.integrationId },
      });
      return;
    }
    const args = buildInitArgs(options, caps);
    await this.runCliOperation('init', options.integrationId, args, {
      verifyIntegration: options.integrationId,
      retry: { action: 'startInit', options },
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
    await this.runCliOperation('integration-install', integrationId, args, {
      verifyIntegration: integrationId,
      retry: { action: 'switchIntegration', integrationId, force },
    });
  }

  /**
   * 更新内置 Spec Kit（v0.4.0）：从 github/spec-kit 最新 Release 下载源码刷新内置副本。
   * 下载可取消；解压阶段不可取消。成功后 invalidateCli → 下次 init 使用新版本。
   */
  async updateBundledSpeckit(): Promise<void> {
    if (this.isRunning) {
      this.deps.onError({
        code: 'io-error',
        message: '已有操作正在执行，请等待完成或取消',
        canRetry: false,
      });
      return;
    }
    const label = '正在更新内置 Spec Kit';
    const ring: ProgressRing = { label: `${label}…`, logTail: [] };
    const emit = (p: Progress) => {
      this.deps.onProgress(p);
    };
    const base = (): Progress => ({
      ...idleProgress(),
      operation: 'upgrade',
      running: true,
      kind: 'indeterminate',
      label: ring.label,
      logTail: [...ring.logTail],
      cancellable: true,
    });

    this.cancelled = false;
    emit(base());
    this.downloadAbort = new AbortController();
    try {
      const result = await downloadLatestSpeckitBundle(this.deps.bundleStorageDir(), {
        signal: this.downloadAbort.signal,
        onStage: (stage, detail) => {
          ring.label =
            stage === 'resolve-tag'
              ? '正在解析最新版本…'
              : stage === 'download'
                ? `正在下载 ${detail ?? ''}…`
                : stage === 'extract'
                  ? '正在解压内置源码…'
                  : '更新完成';
          this.deps.output.appendLine(`[speckit-gui] bundle ${stage} ${detail ?? ''}`);
        },
        onProgress: (ratio, received) => {
          ring.ratio = ratio;
          ring.logTail.push(
            ratio !== undefined
              ? `下载进度 ${(ratio * 100).toFixed(0)}%（${(received / 1024 / 1024).toFixed(1)} MB）`
              : `已接收 ${(received / 1024 / 1024).toFixed(1)} MB`,
          );
          if (ring.logTail.length > RING_MAX) {
            ring.logTail.shift();
          }
          emit({
            ...base(),
            kind: ratio !== undefined ? 'determinate' : 'indeterminate',
            ratio,
            label: ring.label,
            logTail: [...ring.logTail],
          });
        },
      });
      if (this.cancelled) {
        emit({
          ...idleProgress(),
          operation: 'upgrade',
          running: false,
          result: { outcome: 'cancelled', message: '更新已取消' },
        });
        return;
      }
      this.invalidateCli();
      emit({
        ...idleProgress(),
        operation: 'upgrade',
        running: false,
        result: { outcome: 'success', message: `内置 Spec Kit 已更新至 ${result.tag}（v${result.version}）` },
      });
      this.deps.onDone();
    } catch (err) {
      if (this.cancelled) {
        emit({
          ...idleProgress(),
          operation: 'upgrade',
          running: false,
          result: { outcome: 'cancelled', message: '更新已取消' },
        });
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      this.deps.output.appendLine(`[speckit-gui] 更新失败：${message}`);
      emit({
        ...idleProgress(),
        operation: 'upgrade',
        running: false,
        result: { outcome: 'failure', message: `更新失败：${message}` },
      });
      this.deps.onError({
        code: 'cli-failed',
        message: `更新内置 Spec Kit 失败：${message}`,
        suggestion: '检查网络/代理后重试；GitHub API 限流时请稍后再试',
        canRetry: true,
      });
      this.deps.onDone();
    } finally {
      this.downloadAbort = undefined;
    }
  }

  private async runCliOperation(
    operation: Progress['operation'],
    integrationId: string,
    specifyArgs: string[],
    opts: {
      verifyIntegration?: string;
      retry?:
        | { action: 'startInit'; options: InitOptions }
        | { action: 'switchIntegration'; integrationId: string; force: boolean };
      cancellable?: boolean;
    } = {},
  ): Promise<void> {
    if (this.handle) {
      this.deps.onError({
        code: 'io-error',
        message: '已有操作正在执行，请等待完成或取消',
        canRetry: false,
      });
      return;
    }
    const inv = await this.ensureInvocation();
    if (!inv) {
      return; // 来源错误已回报
    }
    // bundled 模式首次构建 uv 环境可能较慢（下载依赖并缓存），日志行会持续输出
    const sourceLabel = inv.source === 'bundled' ? '内置源码' : inv.source === 'setting' ? '指定 CLI' : 'PATH CLI';
    this.deps.output.appendLine(
      `[speckit-gui] spawn(${inv.source}): ${inv.cmd} ${[...inv.argvPrefix, ...specifyArgs].join(' ')}`,
    );

    this.cancelled = false;
    const cancellable = opts.cancellable ?? true;
    const opLabel =
      operation === 'init'
        ? `正在初始化 ${integrationId} 环境`
        : operation === 'upgrade'
          ? '正在升级 Spec Kit'
          : `正在切换为 ${integrationId} 环境`;
    const ring: ProgressRing = { label: `${opLabel}…`, logTail: [] };
    const initial: Progress = {
      ...idleProgress(),
      operation,
      running: true,
      kind: 'indeterminate',
      label: ring.label,
      logTail: [],
      cancellable,
    };
    let progress = initial;
    this.deps.onProgress(progress);

    const emitLine = (line: string) => {
      ring.logTail.push(line);
      if (ring.logTail.length > RING_MAX) {
        ring.logTail.shift();
      }
      this.deps.output.appendLine(`[${new Date().toISOString()}] ${line}`);
      progress = {
        ...progress,
        label: ring.label,
        logTail: [...ring.logTail],
      };
      this.deps.onProgress(progress);
    };

    const handle = runSpecify(this.deps.getRoot(), inv.cmd, [...inv.argvPrefix, ...specifyArgs], emitLine);
    this.handle = handle;
    const result = await handle.promise;
    this.handle = undefined;
    void sourceLabel;

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
      const lastLine = result.stderrTail[result.stderrTail.length - 1] ?? '退出码非 0';
      progress = {
        ...progress,
        running: false,
        cancellable: false,
        result: { outcome: 'failure', message: `${opLabel}失败：${lastLine}` },
      };
      this.deps.onProgress(progress);
      const mapped = this.mapCliFailure(result.stderrTail, operation, integrationId);
      this.deps.onError({
        ...mapped,
        // 上下文驱动重试：ErrorSurface 依据 action 重放原操作（contracts/webview-protocol.md）
        context: {
          ...mapped.context,
          ...(opts.retry as object),
        },
      });
      this.deps.onDone();
      return;
    }

    // 成功后回读 init-options.json 校验 ai 一致（contracts/cli.md §2；upgrade 无需校验）
    const verified = opts.verifyIntegration ? this.verifyIntegration(opts.verifyIntegration) : true;
    const successMessage = verified
      ? `工具环境已更新：${integrationId}`
      : '初始化完成但环境校验不一致';
    progress = {
      ...progress,
      running: false,
      cancellable: false,
      result: { outcome: verified ? 'success' : 'failure', message: successMessage },
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
    const opLabel = operation === 'init' ? '初始化' : operation === 'upgrade' ? '升级' : '切换';
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
        suggestion: '更新内置 Spec Kit 或换选其他工具',
        canRetry: true,
        context: { integrationId },
      };
    }
    if (/No such option/i.test(tail)) {
      // 版本能力不匹配（如旧 CLI 无 --non-interactive）——能力探测本应规避，兜底提示更新内置源
      return {
        code: 'cli-failed',
        message: `${opLabel}失败：CLI 版本能力不匹配（${lastSafeLine(stderrTail)}）`,
        suggestion: '点击「更新内置 Spec Kit」后重试',
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

function lastSafeLine(stderrTail: string[]): string {
  return stderrTail[stderrTail.length - 1] ?? '退出码非 0';
}