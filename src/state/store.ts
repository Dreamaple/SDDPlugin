// T016: workspaceState 最小 UI 状态（data-model.md §7：仅三键）
import * as vscode from 'vscode';
import type { GateId, StageId } from '../../shared/protocol';

const KEY_ACTIVE_FEATURE = 'speckitGui.activeFeatureDir';
const KEY_REVIEW_CONFIRMATIONS = 'speckitGui.reviewConfirmations';
const KEY_LAST_STAGE_TRIGGER = 'speckitGui.lastStageTrigger';
const KEY_PREPROCESS_SELECTION = 'speckitGui.preprocessSelection';
const KEY_CLARIFY_ROUNDS = 'speckitGui.clarifyRounds';
const KEY_HIFI_CONFIG = 'speckitGui.hifiPrototypeConfig';

export class UiStateStore {
  constructor(private readonly context: vscode.ExtensionContext) {}

  getActiveFeature(): string | undefined {
    return this.context.workspaceState.get<string>(KEY_ACTIVE_FEATURE);
  }

  setActiveFeature(dirName: string | undefined): void {
    if (dirName === undefined) {
      void this.context.workspaceState.update(KEY_ACTIVE_FEATURE, undefined);
    } else {
      void this.context.workspaceState.update(KEY_ACTIVE_FEATURE, dirName);
    }
  }

  getReviewConfirmations(): Partial<Record<GateId, string>> {
    return this.context.workspaceState.get<Partial<Record<GateId, string>>>(
      KEY_REVIEW_CONFIRMATIONS,
      {},
    );
  }

  confirmReview(gateId: GateId): void {
    const current = this.getReviewConfirmations();
    current[gateId] = new Date().toISOString();
    void this.context.workspaceState.update(KEY_REVIEW_CONFIRMATIONS, current);
  }

  getLastStageTrigger(): Record<string, string> {
    return this.context.workspaceState.get<Record<string, string>>(KEY_LAST_STAGE_TRIGGER, {});
  }

  recordStageTrigger(stageId: StageId): void {
    const current = this.getLastStageTrigger();
    current[stageId] = new Date().toISOString();
    void this.context.workspaceState.update(KEY_LAST_STAGE_TRIGGER, current);
  }

  /** 预处理输出中勾选的 specify 规范输入（工作区相对路径；v0.7） */
  getPreprocessSelection(): string[] {
    return this.context.workspaceState.get<string[]>(KEY_PREPROCESS_SELECTION, []);
  }

  setPreprocessSelection(selected: string[]): void {
    void this.context.workspaceState.update(KEY_PREPROCESS_SELECTION, selected);
  }

  /** 澄清已触发的轮数（多轮澄清支持；v0.7.4） */
  getClarifyRounds(): number {
    return this.context.workspaceState.get<number>(KEY_CLARIFY_ROUNDS, 0);
  }

  recordClarifyRound(): number {
    const next = this.getClarifyRounds() + 1;
    void this.context.workspaceState.update(KEY_CLARIFY_ROUNDS, next);
    return next;
  }

  /** 高保真原型上次的输入配置（面板预填；v0.8.0） */
  getHiFiConfig(): { source: string; input: string; downloadAssets: boolean } | undefined {
    return this.context.workspaceState.get<
      { source: string; input: string; downloadAssets: boolean } | undefined
    >(KEY_HIFI_CONFIG, undefined);
  }

  setHiFiConfig(config: { source: string; input: string; downloadAssets: boolean }): void {
    void this.context.workspaceState.update(KEY_HIFI_CONFIG, config);
  }

  /** MasterGo 个人认证令牌（Secrets 加密存储；不进快照/聊天记录） */
  async getMastergoToken(): Promise<string | undefined> {
    return this.context.secrets.get('speckit.mastergoToken');
  }

  async setMastergoToken(token: string | undefined): Promise<void> {
    if (token === undefined) {
      await this.context.secrets.delete('speckit.mastergoToken');
    } else {
      await this.context.secrets.store('speckit.mastergoToken', token);
    }
  }
}