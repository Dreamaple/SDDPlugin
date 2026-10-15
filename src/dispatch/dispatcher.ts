// T035: 触发器——阶段→命令基名映射 + 调用令牌推导（contracts/dispatch.md §1）
// 令牌规则实现复用 src/core/workflow.ts（单一实现，避免漂移）
import type { StageId } from '../../shared/protocol';
import { STAGE_ORDER, deriveCommandToken, stageCommandBase } from '../core/workflow';

export { STAGE_ORDER, stageCommandBase, deriveCommandToken };

/** 阶段 → 调用令牌（skills 模式 /speckit-<name>；命令模式 /speckit.<name>） */
export function tokenForStage(stage: StageId, aiSkills: boolean): string {
  return deriveCommandToken(stage, aiSkills);
}