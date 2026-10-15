// T016: workspaceState 最小 UI 状态（data-model.md §7：仅三键）
import * as vscode from 'vscode';
import type { GateId, StageId } from '../../shared/protocol';

const KEY_ACTIVE_FEATURE = 'speckitGui.activeFeatureDir';
const KEY_REVIEW_CONFIRMATIONS = 'speckitGui.reviewConfirmations';
const KEY_LAST_STAGE_TRIGGER = 'speckitGui.lastStageTrigger';

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
}