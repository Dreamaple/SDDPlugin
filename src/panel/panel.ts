// T018/T027/T037/T043/T050: 面板宿主——WebviewView 生命周期、消息路由与快照组装
// 消息协议：contracts/webview-protocol.md；快照派生：data-model.md
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';
import type {
  ClarificationItem,
  Feature,
  GateId,
  Snapshot,
  StageId,
  WebviewToHost,
  WorkspaceEnvironment,
} from '../../shared/protocol';
import { idleProgress } from '../../shared/protocol';
import {
  detectStageAvailability,
  buildStages,
  deriveNextStep,
} from '../core/workflow';
import { countTaskCheckboxes, type TaskStats } from '../core/taskProgress';
import {
  buildReplacement,
  hasOpenClarifications,
  parseClarifications,
} from '../core/clarify';
import { writeBackMarker } from '../core/specWriter';
import {
  isConstitutionReady,
  resolveCurrentFeatureDir,
  scanFeatures,
} from '../core/featureCatalog';
import { detectEnvironment } from '../core/environment';
import { loadToolCatalog, type ToolCatalog } from '../core/toolCatalog';
import type { UiStateStore } from '../state/store';
import { InitRunner } from '../init/initRunner';
import { dispatchToken, type DispatchTransport } from '../dispatch/transports';
import { WorkspaceWatcher } from './watcher';

interface ProviderDeps {
  rootUri: vscode.Uri | undefined;
  catalogPath: string;
  store: UiStateStore;
  output: vscode.OutputChannel;
  extensionUri: vscode.Uri;
  onSnapshot?: (snapshot: Snapshot) => void;
}

const WEBVIEW_DIST = 'webview-ui/dist';

export class SpeckitPanelProvider implements vscode.WebviewViewProvider {
  static readonly viewId = 'speckitGui.panel';

  private view: vscode.WebviewView | undefined;
  private catalog: ToolCatalog | undefined;
  private watcher: WorkspaceWatcher | undefined;
  private runner: InitRunner | undefined;
  /** 运行时最近触发失败记录（不持久化；data-model §4 error 判定输入） */
  private lastFailure: Partial<Record<StageId, boolean>> = {};
  /** 最近一次快照的澄清列表（answerClarification 定位用） */
  private currentClarifications: ClarificationItem[] = [];
  private currentSpecPath: string | undefined;
  private latestStages: import('../../shared/protocol').WorkflowStage[] = [];
  private latestEnv: WorkspaceEnvironment | undefined;
  private disposed = false;

  constructor(private readonly deps: ProviderDeps) {}

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.deps.extensionUri, WEBVIEW_DIST)],
    };
    view.webview.html = this.buildHtml(view.webview);
    view.webview.onDidReceiveMessage((msg: WebviewToHost) => {
      void this.handleMessage(msg);
    });
    // 面板重新可见时推送最新快照（retainContextWhenHidden 下状态可能过期）
    view.onDidChangeVisibility(() => {
      if (view.visible) {
        void this.refresh();
      }
    });
    view.onDidDispose(() => {
      this.view = undefined;
    });

    // 首帧
    void this.refresh();

    // watcher（rootUri 存在时）
    if (this.deps.rootUri && !this.watcher) {
      this.watcher = new WorkspaceWatcher(this.deps.rootUri, () => {
        void this.refresh();
      });
    }
  }

  dispose(): void {
    this.disposed = true;
    this.watcher?.dispose();
    this.runner?.cancel();
  }

  /** 命令 speckitGui.refresh / 设置变更后调用 */
  invalidateCliAndRefresh(): void {
    this.runner?.invalidateCli();
    void this.refresh();
  }

  private async ensureRunner(): Promise<InitRunner> {
    if (!this.runner) {
      const catalog = await this.ensureCatalog();
      this.runner = new InitRunner({
        getRoot: () => this.deps.rootUri?.fsPath ?? '',
        catalog,
        output: this.deps.output,
        onProgress: (p) => {
          void this.post({ type: 'progressUpdated', progress: p });
          if (p.result) {
            // 终态后刷新快照（init/install 会写盘；watcher 也会触发，这里兜底）
            void this.refresh();
          }
        },
        onDone: () => {
          void this.refresh();
        },
        onError: (e) => {
          void this.post({ type: 'errorRaised', error: e });
        },
      });
    }
    return this.runner;
  }

  private async ensureCatalog(): Promise<ToolCatalog> {
    if (!this.catalog) {
      this.catalog = await loadToolCatalog(this.deps.catalogPath);
    }
    return this.catalog;
  }

  private buildHtml(webview: vscode.Webview): string {
    const base = vscode.Uri.joinPath(this.deps.extensionUri, WEBVIEW_DIST);
    const jsUri = webview.asWebviewUri(vscode.Uri.joinPath(base, 'assets', 'index.js'));
    const nonce = Array.from({ length: 24 }, () => Math.random().toString(36)[2] ?? '0').join('');
    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource} data:; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';">
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Speckit</title>
</head>
<body>
  <div id="root"></div>
  <script nonce="${nonce}" src="${jsUri}"></script>
</body>
</html>`;
  }

  // ---------- 快照组装（纯派生：磁盘产物 → 状态） ----------

  async assembleSnapshot(): Promise<Snapshot> {
    const rootUri = this.deps.rootUri;
    const multiRootBlocked = rootUri === undefined;
    const root = rootUri?.fsPath ?? '';
    const catalog = await this.ensureCatalog();

    const runner = await this.ensureRunner();
    const cli = await runner.ensureCli({ silent: true }).catch(() => undefined);
    const cliAvailable = !multiRootBlocked && cli !== undefined;
    const [cliVersion, cliUpgradeSupported] = multiRootBlocked
      ? [undefined, undefined]
      : await Promise.all([runner.getVersion().catch(() => undefined), runner.detectUpgradeSupport().catch(() => false)]);

    const environment = multiRootBlocked
      ? {
          state: 'missing' as const,
          isKnownIntegration: false,
          cliAvailable: false,
          hints: ['工作区非单根，v1 不支持 multi-root'],
        }
      : await detectEnvironment(root, {
          cliAvailable,
          labelFor: catalog.labelFor,
          cliVersion,
          cliUpgradeSupported,
        });

    const features = multiRootBlocked ? [] : await scanFeatures(root);
    const preferred = this.deps.store.getActiveFeature();
    const currentDir = multiRootBlocked
      ? undefined
      : resolveCurrentFeatureDir(root, features, preferred);
    const marked: Feature[] = features.map((f) => ({
      ...f,
      isCurrent: f.dirName === currentDir,
    }));
    const feature = marked.find((f) => f.dirName === currentDir);

    // 当前特性产物读取
    let specContent: string | undefined;
    let clarifications: ClarificationItem[] = [];
    let taskStats: TaskStats | undefined;
    this.currentSpecPath = undefined;
    if (feature) {
      const featureDir = path.join(root, 'specs', feature.dirName);
      const specPath = path.join(featureDir, 'spec.md');
      if (fs.existsSync(specPath)) {
        this.currentSpecPath = specPath;
        specContent = fs.readFileSync(specPath, 'utf-8');
        clarifications = parseClarifications(specContent, feature.dirName);
      }
      const tasksPath = path.join(featureDir, 'tasks.md');
      if (fs.existsSync(tasksPath)) {
        taskStats = countTaskCheckboxes(fs.readFileSync(tasksPath, 'utf-8'));
      }
    }
    this.currentClarifications = clarifications;

    const availableCommands = multiRootBlocked
      ? ({} as Record<StageId, boolean>)
      : detectStageAvailability(root, environment);

    const stages = buildStages({
      env: environment,
      feature,
      specContent,
      taskStats,
      constitutionReady: multiRootBlocked ? false : isConstitutionReady(root),
      hasOpenClarifications: hasOpenClarifications(clarifications),
      availableCommands,
      lastTrigger: this.deps.store.getLastStageTrigger(),
      lastFailure: this.lastFailure,
      reviewConfirmations: this.deps.store.getReviewConfirmations(),
    });
    this.latestStages = stages;
    this.latestEnv = environment;

    const { nextStep, reviewPending } = deriveNextStep(stages);

    return {
      workspaceRootLabel: rootUri ? path.basename(rootUri.fsPath) : '',
      multiRootBlocked,
      environment,
      tools: catalog.entries,
      features: marked,
      stages,
      clarifications,
      nextStep,
      reviewPending,
    };
  }

  async refresh(): Promise<void> {
    if (this.disposed || !this.view) {
      return;
    }
    try {
      const snapshot = await this.assembleSnapshot();
      this.deps.onSnapshot?.(snapshot);
      await this.post({ type: 'stateUpdated', snapshot });
    } catch (err) {
      this.deps.output.appendLine(`[speckit-gui] 快照组装失败：${String(err)}`);
      await this.post({
        type: 'errorRaised',
        error: {
          code: 'io-error',
          message: '读取工作区状态失败',
          suggestion: '点击重试刷新',
          canRetry: true,
        },
      });
    }
  }

  private async post(message: import('../../shared/protocol').HostToWebview): Promise<void> {
    await this.view?.webview.postMessage(message);
  }

  // ---------- 上行消息路由 ----------

  private async handleMessage(msg: WebviewToHost): Promise<void> {
    switch (msg.type) {
      case 'ready':
      case 'refresh':
        await this.refresh();
        break;
      case 'startInit':
        await this.handleStartInit(msg.options);
        break;
      case 'switchIntegration':
        await this.handleSwitchIntegration(msg.integrationId, msg.force);
        break;
      case 'selectFeature':
        await this.handleSelectFeature(msg.dirName);
        break;
      case 'dispatchStage':
        await this.handleDispatch(msg.stageId);
        break;
      case 'confirmReview':
        this.deps.store.confirmReview(msg.gateId as GateId);
        await this.refresh();
        break;
      case 'answerClarification':
        await this.handleAnswer(msg.id, msg.answer);
        break;
      case 'cancelOperation':
        this.runner?.cancel();
        break;
      case 'upgradeSpeckit':
        await this.handleUpgrade();
        break;
      case 'openLogs':
        this.deps.output.show();
        break;
    }
  }

  // ---------- init / switch（US1，T027 接线） ----------

  private async handleStartInit(options: import('../../shared/protocol').InitOptions): Promise<void> {
    if (this.deps.rootUri === undefined) {
      await this.postWorkspaceMissing();
      return;
    }
    const runner = await this.ensureRunner();
    await runner.startInit(options);
    await this.refresh();
  }

  private async handleSwitchIntegration(integrationId: string, force: boolean): Promise<void> {
    if (this.deps.rootUri === undefined) {
      await this.postWorkspaceMissing();
      return;
    }
    const runner = await this.ensureRunner();
    await runner.switchIntegration(integrationId, force);
    await this.refresh();
  }

  // ---------- dispatch（US2，T037 接线） ----------

  private async handleDispatch(stageId: StageId): Promise<void> {
    if (this.deps.rootUri === undefined) {
      await this.postWorkspaceMissing();
      return;
    }
    if (this.latestEnv?.state !== 'ready') {
      await this.post({
        type: 'errorRaised',
        error: {
          code: 'io-error',
          message: '工作区尚未初始化 Speckit 环境，无法触发命令',
          suggestion: '请先完成初始化向导',
          canRetry: false,
        },
      });
      return;
    }
    const stage = this.latestStages.find((s) => s.id === stageId);
    if (!stage || !stage.available) {
      await this.post({
        type: 'errorRaised',
        error: {
          code: 'io-error',
          message: `阶段 ${stageId} 当前不可用`,
          canRetry: false,
        },
      });
      return;
    }
    if (this.latestEnv.aiSkills === undefined) {
      // 未知环境：按命令模式令牌（dispatcher 已在快照中推导，此处直接用快照令牌）
    }
    const transport = vscode.workspace
      .getConfiguration('speckitGui')
      .get<DispatchTransport>('dispatchTransport', 'chat-open');
    const outcome = await dispatchToken(stage.commandToken, transport);
    await this.post({
      type: 'commandResult',
      stageId,
      outcome,
      token: stage.commandToken,
    });
    if (outcome === 'failed') {
      this.lastFailure[stageId] = true;
      await this.post({
        type: 'errorRaised',
        error: {
          code: 'io-error',
          message: `命令触发失败：${stage.commandToken}`,
          suggestion: '检查剪贴板权限或改用设置 speckitGui.dispatchTransport=clipboard',
          canRetry: true,
        },
      });
    } else {
      delete this.lastFailure[stageId];
      this.deps.store.recordStageTrigger(stageId);
    }
    await this.refresh();
  }

  // ---------- selectFeature（US2） ----------

  /** 升级 Spec Kit CLI（v0.3.0：版本感知——旧版 CLI 无 upgrade 命令时给出手动指引） */
  private async handleUpgrade(): Promise<void> {
    if (this.deps.rootUri === undefined) {
      await this.postWorkspaceMissing();
      return;
    }
    const runner = await this.ensureRunner();
    const cli = await runner.ensureCli({ silent: true }).catch(() => undefined);
    if (!cli) {
      await this.post({
        type: 'errorRaised',
        error: {
          code: 'cli-not-found',
          message: '未找到 specify CLI，无法升级',
          suggestion: '请先安装 specify CLI（见安装指引）',
          canRetry: true,
        },
      });
      return;
    }
    await runner.upgradeSpeckit();
    await this.refresh();
  }

  private async handleSelectFeature(dirName: string): Promise<void> {
    const features = await scanFeatures(this.deps.rootUri?.fsPath ?? '');
    if (!features.some((f) => f.dirName === dirName)) {
      await this.post({
        type: 'errorRaised',
        error: { code: 'io-error', message: `特性目录不存在：${dirName}`, canRetry: false },
      });
      return;
    }
    this.deps.store.setActiveFeature(dirName);
    await this.refresh();
  }

  // ---------- answer（US4，T050 接线；mtime 冲突重试一次） ----------

  private async handleAnswer(id: string, answer: string): Promise<void> {
    const specPath = this.currentSpecPath;
    if (!specPath) {
      await this.post({
        type: 'errorRaised',
        error: { code: 'write-back-failed', message: '当前特性没有 spec 文档', canRetry: false },
      });
      return;
    }
    const item = this.currentClarifications.find((c) => c.id === id && c.status === 'open');
    if (!item) {
      await this.post({
        type: 'errorRaised',
        error: {
          code: 'write-back-failed',
          message: '澄清问题不存在或已回答',
          suggestion: '请刷新面板',
          canRetry: true,
        },
      });
      return;
    }
    const answerPrefix = vscode.workspace
      .getConfiguration('speckitGui')
      .get<string>('answerPrefix', '**答案**: ');
    const replacement = buildReplacement(answerPrefix, answer);

    // mtime 校验：解析后写回前文件被外部修改 → 重解析重试一次（contracts/artifacts.md §2）
    const attempt = async (): Promise<void> => {
      const uri = vscode.Uri.file(specPath);
      await writeBackMarker(uri, item.rawMarker, replacement);
      this.watcher?.setIgnoreWindow(specPath);
    };
    try {
      const mtimeBefore = fs.statSync(specPath).mtimeMs;
      try {
        await attempt();
      } catch (firstErr) {
        const mtimeNow = fs.statSync(specPath).mtimeMs;
        if (mtimeNow !== mtimeBefore) {
          // 外部修改：重解析定位后重试一次
          const text = fs.readFileSync(specPath, 'utf-8');
          const reparsed = parseClarifications(text);
          const again = reparsed.find((c) => c.id === id && c.status === 'open');
          if (!again) {
            throw firstErr;
          }
          const uri = vscode.Uri.file(specPath);
          await writeBackMarker(uri, again.rawMarker, buildReplacement(answerPrefix, answer));
          this.watcher?.setIgnoreWindow(specPath);
        } else {
          throw firstErr;
        }
      }
      const progress = idleProgress();
      progress.result = { outcome: 'success', message: '澄清答案已写回 spec' };
      await this.post({ type: 'progressUpdated', progress });
      await this.refresh();
    } catch (err) {
      this.deps.output.appendLine(`[speckit-gui] 写回失败：${String(err)}`);
      await this.post({
        type: 'errorRaised',
        error: {
          code: 'write-back-failed',
          message: '澄清答案写回失败',
          suggestion: '文件可能被外部修改，请刷新后重试',
          canRetry: true,
        },
      });
    }
  }

  private async postWorkspaceMissing(): Promise<void> {
    await this.post({
      type: 'errorRaised',
      error: {
        code: 'workspace-missing',
        message: 'v1 仅支持单根工作区，请打开单个项目文件夹',
        canRetry: false,
      },
    });
  }
}