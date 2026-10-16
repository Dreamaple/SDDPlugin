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
  buildClarifyApplyToken,
  buildClarifyExport,
  buildClarifyProtocolSuffix,
  hasOpenClarifications,
  parseClarifications,
  type ClarifyApplyEntry,
} from '../core/clarify';
import {
  isConstitutionReady,
  resolveCurrentFeatureDir,
  scanFeatures,
} from '../core/featureCatalog';
import { detectEnvironment } from '../core/environment';
import { loadToolCatalog, type ToolCatalog } from '../core/toolCatalog';
import {
  buildConstitutionSuffix,
  constitutionDir,
  ensureConstitutionDir,
  listConstitutionRules,
} from '../core/constitutionDir';
import {
  buildFeatureScopeSuffix,
  buildPlanConfigSuffix,
  buildProjectConfigSuffix,
  computeDefaults,
  loadFieldCatalog,
  readProjectConfig,
  writeProjectConfig,
} from '../core/projectConfig';
import {
  buildSpecifyInputSuffix,
  ensurePreprocessDir,
  installPreprocessSkill,
  listPreprocessOutputs,
  normalizeSelection,
  preprocessDir,
} from '../core/preprocess';
import type { ProjectFieldDef } from '../../shared/protocol';
import {
  buildPrototypeGenerateToken,
  prototypeMtime,
  prototypePathFor,
} from '../core/prototype';
import {
  buildHiFiPrototypeGenerateToken,
  hiFiIndexPathFor,
  hiFiMtime,
  writeAuthTokenFile,
  type HiFiSource,
} from '../core/hiFiPrototype';
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
  globalStorageUri: vscode.Uri;
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
        builtinSrcDir: () =>
          vscode.Uri.joinPath(this.deps.extensionUri, 'resources', 'speckit-cli').fsPath,
        bundleStorageDir: () =>
          vscode.Uri.joinPath(this.deps.globalStorageUri, 'speckit-bundles').fsPath,
        onProgress: (p) => {
          void this.post({ type: 'progressUpdated', progress: p });
          if (p.result) {
            // 终态后刷新快照（init/install 会写盘；watcher 也会触发，这里兜底）
            void this.refresh();
            // 初始化/切换成功 → 确保公共宪法目录与引导文件存在（幂等）
            if (
              p.result.outcome === 'success' &&
              (p.operation === 'init' || p.operation === 'integration-install')
            ) {
              try {
                ensureConstitutionDir(this.deps.rootUri?.fsPath ?? '');
              } catch (err) {
                this.deps.output.appendLine(
                  `[speckit-gui] 创建公共宪法目录失败：${String(err)}`,
                );
              }
            }
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
    const [invSource, cliVersion] = multiRootBlocked
      ? ['none' as const, undefined]
      : await Promise.all([
          runner.currentSource(),
          runner.getVersion().catch(() => undefined),
        ]);
    const cliAvailable = invSource !== 'none';

    const environment = multiRootBlocked
      ? {
          state: 'missing' as const,
          isKnownIntegration: false,
          cliAvailable: false,
          cliSource: 'none' as const,
          hints: ['工作区非单根，v1 不支持 multi-root'],
        }
      : await detectEnvironment(root, {
          cliAvailable,
          cliVersion,
          cliSource: invSource,
          labelFor: catalog.labelFor,
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
      constitutionRules: multiRootBlocked ? [] : listConstitutionRules(root),
      preprocessFiles: multiRootBlocked ? [] : listPreprocessOutputs(root),
      preprocessSelected: multiRootBlocked
        ? []
        : normalizeSelection(this.deps.store.getPreprocessSelection(), listPreprocessOutputs(root)),
      clarifyRounds: this.deps.store.getClarifyRounds(),
      prototype:
        !multiRootBlocked && this.currentSpecPath
          ? (() => {
              const mtimeMs = prototypeMtime(this.currentSpecPath);
              return mtimeMs !== undefined ? { mtimeMs } : undefined;
            })()
          : undefined,
      hifiPrototype:
        !multiRootBlocked && this.currentSpecPath
          ? (() => {
              const mtimeMs = hiFiMtime(this.currentSpecPath);
              return mtimeMs !== undefined ? { mtimeMs } : undefined;
            })()
          : undefined,
      hifiConfig: multiRootBlocked ? undefined : this.deps.store.getHiFiConfig(),
      hifiTokenSaved: multiRootBlocked
        ? false
        : (await this.deps.store.getMastergoToken()) !== undefined,
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
      case 'applyClarificationBatch':
        await this.handleApplyClarificationBatch(msg.answers);
        break;
      case 'exportClarifications':
        await this.handleExportClarifications();
        break;
      case 'generatePrototype':
        await this.handleGeneratePrototype();
        break;
      case 'openPrototype':
        await this.handleOpenPrototype();
        break;
      case 'generateHiFiPrototype':
        await this.handleGenerateHiFiPrototype(msg.source, msg.input, msg.downloadAssets, msg.authToken);
        break;
      case 'openHiFiPrototype':
        await this.handleOpenHiFiPrototype();
        break;
      case 'pickHiFiFolder':
        await this.handlePickHiFiFolder();
        break;
      case 'cancelOperation':
        this.runner?.cancel();
        break;
      case 'dismissResult':
        await this.post({ type: 'progressUpdated', progress: idleProgress() });
        break;
      case 'openConstitutionDir':
        await this.handleOpenConstitutionDir();
        break;
      case 'loadProjectConfig':
        await this.handleLoadProjectConfig();
        break;
      case 'saveProjectConfig':
        await this.handleSaveProjectConfig(msg.values);
        break;
      case 'runPreprocess':
        await this.handleRunPreprocess();
        break;
      case 'setPreprocessSelection':
        this.deps.store.setPreprocessSelection(msg.selected ?? []);
        await this.refresh();
        break;
      case 'openPreprocessDir':
        await this.handleOpenPreprocessDir();
        break;
      case 'updateBundledSpeckit':
        await this.handleUpdateBundled();
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
    // constitution 阶段：公共规则文件路径 + 项目配置（占位 tag 预填）拼接为提示词向下传递
    // specify 阶段：规范输入必选（预处理输出勾选），并拼接所选文件路径
    let token = stage.commandToken;
    if (stageId === 'constitution') {
      const suffix = [
        buildConstitutionSuffix(this.deps.rootUri.fsPath),
        buildProjectConfigSuffix(this.deps.rootUri.fsPath, this.loadFieldCatalog()),
      ]
        .filter(Boolean)
        .join('；');
      if (suffix) {
        token = `${token} ${suffix}`;
      }
    }
    if (stageId === 'clarify') {
      // 澄清协议：一次性输出全部问题并写入标记，供插件「澄清」面板解析作答
      const suffix = buildClarifyProtocolSuffix();
      if (suffix) {
        token = `${token} ${suffix}`;
      }
    }
    if (stageId === 'plan') {
      // plan 约定：技术事实（技术栈/平台/存储）由项目配置传递并禁止再调研；输出物形态可声明
      const suffix = buildPlanConfigSuffix(this.deps.rootUri.fsPath, this.loadFieldCatalog());
      if (suffix) {
        token = `${token} ${suffix}`;
      }
    }
    if (stageId === 'specify') {
      const selected = normalizeSelection(
        this.deps.store.getPreprocessSelection(),
        listPreprocessOutputs(this.deps.rootUri.fsPath),
      );
      if (selected.length === 0) {
        await this.post({
          type: 'errorRaised',
          error: {
            code: 'io-error',
            message: '「规范」阶段必须先选择规范输入',
            suggestion: '请使用「预处理」导入规范文档，并在输出列表中勾选要加载的文件',
            canRetry: false,
          },
        });
        return;
      }
      const suffix = [
        buildSpecifyInputSuffix(selected),
        buildFeatureScopeSuffix(this.deps.rootUri.fsPath),
      ]
        .filter(Boolean)
        .join('；');
      if (suffix) {
        token = `${token} ${suffix}`;
      }
    }
    const outcome = await dispatchToken(token, transport);
    await this.post({
      type: 'commandResult',
      stageId,
      outcome,
      token,
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
      if (stageId === 'clarify') {
        this.deps.store.recordClarifyRound(); // 多轮澄清：每次触发计一轮
      }
    }
    await this.refresh();
  }

  // ---------- selectFeature（US2） ----------

  /** 更新内置 Spec Kit（v0.4.0：GitHub Release 刷新内置源码；版本感知降级已由 runner 处理） */
  private async handleUpdateBundled(): Promise<void> {
    const runner = await this.ensureRunner();
    await runner.updateBundledSpeckit();
    await this.refresh();
  }

  // ---------- openConstitutionDir（公共宪法目录引导） ----------

  private async handleOpenConstitutionDir(): Promise<void> {
    const root = this.deps.rootUri?.fsPath;
    if (!root) {
      await this.postWorkspaceMissing();
      return;
    }
    try {
      ensureConstitutionDir(root); // 幂等：目录/README 不存在则先创建
    } catch (err) {
      this.deps.output.appendLine(`[speckit-gui] 创建公共宪法目录失败：${String(err)}`);
      await this.post({
        type: 'errorRaised',
        error: { code: 'io-error', message: '创建公共宪法目录失败', canRetry: true },
      });
      return;
    }
    await vscode.commands.executeCommand('workbench.view.explorer');
    await vscode.commands.executeCommand('revealInExplorer', vscode.Uri.file(constitutionDir(root)));
  }

  // ---------- 项目配置（宪法占位 tag 预填表） ----------

  /** 字段目录：resources/project-fields.json 可覆盖内置目录（字段扩展无需改代码） */
  private loadFieldCatalog(): ProjectFieldDef[] {
    try {
      return loadFieldCatalog(
        vscode.Uri.joinPath(this.deps.extensionUri, 'resources', 'project-fields.json').fsPath,
      );
    } catch {
      return loadFieldCatalog(undefined);
    }
  }

  private async handleLoadProjectConfig(): Promise<void> {
    const root = this.deps.rootUri?.fsPath;
    if (!root) {
      await this.postWorkspaceMissing();
      return;
    }
    const fields = this.loadFieldCatalog();
    const { values, updatedAt } = readProjectConfig(root);
    const workspaceName = path.basename(root);
    await this.post({
      type: 'projectConfigLoaded',
      fields,
      values,
      defaults: computeDefaults(fields, values, workspaceName),
      workspaceName,
      updatedAt,
    });
  }

  private async handleSaveProjectConfig(values: Record<string, string>): Promise<void> {
    const root = this.deps.rootUri?.fsPath;
    if (!root) {
      await this.postWorkspaceMissing();
      return;
    }
    try {
      writeProjectConfig(root, values ?? {});
    } catch (err) {
      this.deps.output.appendLine(`[speckit-gui] 项目配置保存失败：${String(err)}`);
      await this.post({
        type: 'errorRaised',
        error: { code: 'io-error', message: '项目配置保存失败', canRetry: true },
      });
      return;
    }
    // 保存后回读并重发（前端据此刷新表单与 updatedAt）
    await this.handleLoadProjectConfig();
    const progress = idleProgress();
    progress.result = { outcome: 'success', message: '项目配置已保存（触发宪法命令时自动传递）' };
    await this.post({ type: 'progressUpdated', progress });
  }

  // ---------- 预处理（规范文档导入，v0.7） ----------

  /** 内置技能包目录（resources/markfiledown） */
  private bundledSkillDir(): string {
    return vscode.Uri.joinPath(this.deps.extensionUri, 'resources', 'markfiledown').fsPath;
  }

  private async handleRunPreprocess(): Promise<void> {
    const root = this.deps.rootUri?.fsPath;
    if (!root) {
      await this.postWorkspaceMissing();
      return;
    }
    // 1. 技能缺失 → 从插件内置包自动安装（幂等；已装过则跳过）
    const installState = installPreprocessSkill(root, this.bundledSkillDir());
    if (installState === 'failed') {
      await this.post({
        type: 'errorRaised',
        error: {
          code: 'io-error',
          message: 'markfiledown 技能安装失败（无法复制内置技能包到工作区）',
          suggestion: '请检查工作区 .cursor/skills 目录写权限，或手动安装技能后重试',
          canRetry: true,
        },
      });
      return;
    }
    // 2. 选择规范文档输入（可多选文件）
    const picked = await vscode.window.showOpenDialog({
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: true,
      openLabel: '选择规范文档（可多选）',
      title: '预处理：选择规范文档输入（输出到 .specify/preprocess）',
    });
    if (!picked || picked.length === 0) {
      return; // 用户取消
    }
    const inputRefs = picked
      .map((u) => {
        const rel = path.relative(root, u.fsPath).split(path.sep).join('/');
        return rel.length > 0 && !rel.startsWith('..') ? rel : u.fsPath; // 工作区内用相对路径
      })
      .map((p) => `@${p}`)
      .join('; ');
    // 3. dispatch 技能令牌（输出固定到 .specify/preprocess）
    const transport = vscode.workspace
      .getConfiguration('speckitGui')
      .get<DispatchTransport>('dispatchTransport', 'chat-open');
    const token = `/markfiledown.pipeline Input files: ${inputRefs} Output root: .specify/preprocess`;
    const outcome = await dispatchToken(token, transport);
    const installNote =
      installState === 'installed'
        ? '已自动安装 markfiledown 技能；'
        : installState === 'refreshed'
          ? '已升级 markfiledown 技能包；'
          : '';
    const progress = idleProgress();
    progress.result =
      outcome === 'failed'
        ? { outcome: 'failure', message: '预处理命令触发失败' }
        : {
            outcome: 'success',
            message: `${installNote}预处理命令已触发（输出 .specify/preprocess）；请在 AI 聊天中执行，完成后回来勾选规范输入`,
          };
    await this.post({ type: 'progressUpdated', progress });
  }

  private async handleOpenPreprocessDir(): Promise<void> {
    const root = this.deps.rootUri?.fsPath;
    if (!root) {
      await this.postWorkspaceMissing();
      return;
    }
    ensurePreprocessDir(root);
    await vscode.commands.executeCommand('workbench.view.explorer');
    await vscode.commands.executeCommand('revealInExplorer', vscode.Uri.file(preprocessDir(root)));
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

  // ---------- answer（US4，v0.7.6：写回走 Agent——自定义答案需结合上下文具体化） ----------

  private async handleAnswer(id: string, answer: string): Promise<void> {
    await this.applyClarificationEntries([{ id, answer }]);
  }

  private async handleApplyClarificationBatch(
    answers: Array<{ id: string; answer: string }>,
  ): Promise<void> {
    await this.applyClarificationEntries(answers);
  }

  /** 把澄清结论组装为 Agent 指令并派发；Agent 改写 spec 后由 watcher 触发面板刷新 */
  private async applyClarificationEntries(
    answers: Array<{ id: string; answer: string }>,
  ): Promise<void> {
    if (this.deps.rootUri === undefined) {
      await this.postWorkspaceMissing();
      return;
    }
    if (!this.currentSpecPath) {
      await this.post({
        type: 'errorRaised',
        error: { code: 'write-back-failed', message: '当前特性没有 spec 文档', canRetry: false },
      });
      return;
    }
    const entries: ClarifyApplyEntry[] = [];
    const seen = new Set<string>();
    for (const a of answers) {
      if (seen.has(a.id)) {
        continue;
      }
      const item = this.currentClarifications.find((c) => c.id === a.id && c.status === 'open');
      if (!item) {
        continue; // 已回答/不存在 → 跳过（不阻塞其余条目）
      }
      seen.add(a.id);
      // 选项作答时把选项含义（Answer 列 + Implications）一并带上，Agent 无需回查表格
      const option = item.options?.find((o) => o.label === a.answer);
      entries.push({
        question: item.question,
        answer: option ? `${option.label}（${option.implication || '无补充说明'}）` : a.answer,
      });
    }
    if (entries.length === 0) {
      await this.post({
        type: 'errorRaised',
        error: {
          code: 'write-back-failed',
          message: '没有可应用的澄清答案（不存在或已回答）',
          suggestion: '请刷新面板后重试',
          canRetry: true,
        },
      });
      return;
    }
    const transport = vscode.workspace
      .getConfiguration('speckitGui')
      .get<DispatchTransport>('dispatchTransport', 'chat-open');
    const token = buildClarifyApplyToken(entries);
    const outcome = await dispatchToken(token, transport);
    if (outcome === 'failed') {
      await this.post({
        type: 'errorRaised',
        error: {
          code: 'io-error',
          message: '澄清答案应用指令触发失败',
          suggestion: '检查剪贴板权限或改用设置 speckitGui.dispatchTransport=clipboard',
          canRetry: true,
        },
      });
      return;
    }
    const progress = idleProgress();
    progress.result = {
      outcome: 'success',
      message: `已把 ${entries.length} 条澄清结论交给 Agent 整合进 spec；Agent 改写后澄清面板会自动更新`,
    };
    await this.post({ type: 'progressUpdated', progress });
    await this.refresh();
  }

  private async handleExportClarifications(): Promise<void> {
    if (!this.currentSpecPath) {
      await this.post({
        type: 'errorRaised',
        error: { code: 'write-back-failed', message: '当前特性没有 spec 文档', canRetry: false },
      });
      return;
    }
    const open = this.currentClarifications.filter((c) => c.status === 'open');
    if (open.length === 0) {
      const progress = idleProgress();
      progress.result = { outcome: 'success', message: '当前没有待澄清项，无需导出' };
      await this.post({ type: 'progressUpdated', progress });
      return;
    }
    const featureDir = path.basename(path.dirname(this.currentSpecPath));
    const exportPath = path.join(path.dirname(this.currentSpecPath), 'clarifications.md');
    try {
      fs.writeFileSync(exportPath, buildClarifyExport(featureDir, open), 'utf-8');
    } catch (err) {
      this.deps.output.appendLine(`[speckit-gui] 澄清导出失败：${String(err)}`);
      await this.post({
        type: 'errorRaised',
        error: { code: 'io-error', message: '待澄清项导出失败', canRetry: true },
      });
      return;
    }
    await vscode.window.showTextDocument(vscode.Uri.file(exportPath));
    const progress = idleProgress();
    progress.result = {
      outcome: 'success',
      message: `已导出 ${open.length} 条待澄清项 → specs/${featureDir}/clarifications.md`,
    };
    await this.post({ type: 'progressUpdated', progress });
  }

  // ---------- 低保真可交互原型（v0.7.7 可选流程） ----------

  private async handleGeneratePrototype(): Promise<void> {
    const root = this.deps.rootUri?.fsPath;
    if (!root) {
      await this.postWorkspaceMissing();
      return;
    }
    const specPath = this.currentSpecPath;
    if (!specPath) {
      await this.post({
        type: 'errorRaised',
        error: {
          code: 'io-error',
          message: '当前特性还没有 spec，无法生成原型',
          suggestion: '请先完成规范（specify）阶段',
          canRetry: false,
        },
      });
      return;
    }
    const rel = (p: string) => path.relative(root, p).split(path.sep).join('/');
    const transport = vscode.workspace
      .getConfiguration('speckitGui')
      .get<DispatchTransport>('dispatchTransport', 'chat-open');
    // v0.8.4 多文档输入：spec + 同目录 checklists/requirements.md（存在即纳入，Agent 端做需求合并）
    const docs: string[] = [rel(specPath)];
    const checklistPath = path.join(path.dirname(specPath), 'checklists', 'requirements.md');
    if (fs.existsSync(checklistPath)) {
      docs.push(rel(checklistPath));
    }
    const token = buildPrototypeGenerateToken(docs, rel(prototypePathFor(specPath)));
    const outcome = await dispatchToken(token, transport);
    if (outcome === 'failed') {
      await this.post({
        type: 'errorRaised',
        error: {
          code: 'io-error',
          message: '原型生成指令触发失败',
          suggestion: '检查剪贴板权限或改用设置 speckitGui.dispatchTransport=clipboard',
          canRetry: true,
        },
      });
      return;
    }
    const progress = idleProgress();
    progress.result = {
      outcome: 'success',
      message: '原型生成指令已触发；AI 完成后此处会出现「打开原型」按钮',
    };
    await this.post({ type: 'progressUpdated', progress });
    await this.refresh();
  }

  private async handleOpenPrototype(): Promise<void> {
    const specPath = this.currentSpecPath;
    if (!specPath) {
      await this.post({
        type: 'errorRaised',
        error: { code: 'io-error', message: '当前特性没有 spec，也没有原型', canRetry: false },
      });
      return;
    }
    const protoPath = prototypePathFor(specPath);
    if (!fs.existsSync(protoPath)) {
      await this.post({
        type: 'errorRaised',
        error: {
          code: 'io-error',
          message: '原型尚未生成，请先点击「生成原型」',
          canRetry: false,
        },
      });
      return;
    }
    await vscode.env.openExternal(vscode.Uri.file(protoPath));
  }

  // ---------- 高保真可交互原型（v0.8.0，plan 评审通过后的 UI 1:1 落地） ----------

  private async handleGenerateHiFiPrototype(
    source: HiFiSource,
    input: string,
    downloadAssets: boolean,
    authToken?: string,
  ): Promise<void> {
    const root = this.deps.rootUri?.fsPath;
    if (!root) {
      await this.postWorkspaceMissing();
      return;
    }
    const specPath = this.currentSpecPath;
    if (!specPath) {
      await this.post({
        type: 'errorRaised',
        error: {
          code: 'io-error',
          message: '当前特性还没有 spec，无法做高保真还原',
          suggestion: '请先完成规范（specify）与方案（plan）阶段',
          canRetry: false,
        },
      });
      return;
    }
    const planStage = this.latestStages.find((s) => s.id === 'plan');
    if (!planStage || planStage.state !== 'completed') {
      await this.post({
        type: 'errorRaised',
        error: {
          code: 'io-error',
          message: '方案（plan）阶段评审尚未通过，暂不能进入高保真 UI 还原',
          suggestion: '先完成 plan 并在面板确认评审通过',
          canRetry: false,
        },
      });
      return;
    }
    const trimmedInput = input.trim();
    if (!trimmedInput) {
      await this.post({
        type: 'errorRaised',
        error: { code: 'io-error', message: '请先填写 UI 输入（路径/URL/设计稿标识）', canRetry: false },
      });
      return;
    }
    if (source === 'local' && !fs.existsSync(trimmedInput)) {
      await this.post({
        type: 'errorRaised',
        error: { code: 'io-error', message: `本地目录不存在：${trimmedInput}`, canRetry: true },
      });
      return;
    }
    const rel = (p: string) => path.relative(root, p).split(path.sep).join('/');
    const outAbs = path.join(path.dirname(specPath), 'prototype-hifi');
    // 认证令牌：webview 新输入 → 存 Secrets；留空 → 沿用已保存令牌；经临时文件传给 Agent
    const savedToken = await this.deps.store.getMastergoToken();
    const trimmedToken = authToken?.trim();
    if (trimmedToken && source === 'mastergo') {
      await this.deps.store.setMastergoToken(trimmedToken);
    }
    const effectiveToken =
      source === 'mastergo' ? trimmedToken || savedToken || undefined : undefined;
    const authTokenFile = effectiveToken ? writeAuthTokenFile(effectiveToken) : undefined;
    const transport = vscode.workspace
      .getConfiguration('speckitGui')
      .get<DispatchTransport>('dispatchTransport', 'chat-open');
    const token = buildHiFiPrototypeGenerateToken({
      specRel: rel(specPath),
      planRel: rel(path.join(path.dirname(specPath), 'plan.md')),
      outRel: rel(outAbs),
      source,
      input: trimmedInput,
      downloadAssets,
      authTokenFile,
    });
    this.deps.store.setHiFiConfig({ source, input: trimmedInput, downloadAssets });
    const outcome = await dispatchToken(token, transport);
    if (outcome === 'failed') {
      await this.post({
        type: 'errorRaised',
        error: {
          code: 'io-error',
          message: '高保真还原指令触发失败',
          suggestion: '检查剪贴板权限或改用设置 speckitGui.dispatchTransport=clipboard',
          canRetry: true,
        },
      });
      return;
    }
    const progress = idleProgress();
    progress.result = {
      outcome: 'success',
      message: `高保真还原指令已触发（${source}${downloadAssets ? ' · 切图先行' : ''}）；完成后卡片会出现「打开高保真原型」`,
    };
    await this.post({ type: 'progressUpdated', progress });
    await this.refresh();
  }

  private async handleOpenHiFiPrototype(): Promise<void> {
    const specPath = this.currentSpecPath;
    if (!specPath) {
      await this.post({
        type: 'errorRaised',
        error: { code: 'io-error', message: '当前特性没有 spec，也没有高保真原型', canRetry: false },
      });
      return;
    }
    const indexHtml = hiFiIndexPathFor(specPath);
    if (!fs.existsSync(indexHtml)) {
      await this.post({
        type: 'errorRaised',
        error: { code: 'io-error', message: '高保真原型尚未生成，请先点击「生成高保真原型」', canRetry: false },
      });
      return;
    }
    await vscode.env.openExternal(vscode.Uri.file(indexHtml));
  }

  private async handlePickHiFiFolder(): Promise<void> {
    const picked = await vscode.window.showOpenDialog({
      canSelectFiles: false,
      canSelectFolders: true,
      canSelectMany: false,
      openLabel: '选择本地设计稿目录',
      title: '高保真原型：选择本地设计稿/切图目录',
    });
    await this.post({
      type: 'folderPicked',
      path: picked && picked.length > 0 ? picked[0].fsPath : undefined,
    });
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