// T033/T034/T044: 工作流视图——阶段时间线、下一步按钮、评审关卡、N/M 徽章
import { postToHost } from '../vscode';
import type { GateId, StageState, WorkflowStage } from '../../../shared/protocol';

const STATE_LABELS: Record<StageState, string> = {
  not_started: '未开始',
  in_progress: '进行中',
  completed: '已完成',
  blocked_review: '待评审',
  error: '出错',
};

function StateChip(props: { state: StageState }) {
  return <span className={`spk-state ${props.state}`}>{STATE_LABELS[props.state]}</span>;
}

export function WorkflowView(props: {
  stages: WorkflowStage[];
  nextStep: { stageId: import('../../../shared/protocol').StageId; token: string } | null;
  reviewPending: GateId | null;
}) {
  const { stages, nextStep, reviewPending } = props;
  return (
    <div>
      <ul className="spk-steps">
        {stages.map((stage) => {
          const isCurrent = nextStep?.stageId === stage.id;
          const canDispatch =
            isCurrent &&
            reviewPending === null &&
            stage.available &&
            (stage.state === 'not_started' ||
              stage.state === 'in_progress' ||
              stage.state === 'error');
          return (
            <li key={stage.id} className={`spk-step${isCurrent ? ' current' : ''}`}>
              <span className={`spk-dot ${stage.state}`} />
              <span style={{ minWidth: 64 }}>
                {stage.order}. {stage.label}
              </span>
              {stage.optional ? <span className="spk-muted">（可选）</span> : null}
              <StateChip state={stage.state} />
              {stage.taskStats ? (
                <span className="spk-chip">
                  {stage.taskStats.done}/{stage.taskStats.total} 已完成
                </span>
              ) : null}
              {!stage.available ? <span className="spk-muted">（命令不可用）</span> : null}
              <span style={{ flex: 1 }} />
              {stage.state === 'blocked_review' && reviewPending !== null ? (
                <button className="spk-btn" onClick={() => postToHost({ type: 'confirmReview', gateId: reviewPending })}>
                  评审通过，进入下一阶段
                </button>
              ) : null}
              {canDispatch ? (
                <button
                  className="spk-btn primary"
                  onClick={() => postToHost({ type: 'dispatchStage', stageId: stage.id })}
                  title={`触发 ${stage.commandToken}`}
                >
                  下一步：运行 {stage.commandToken}
                </button>
              ) : null}
            </li>
          );
        })}
      </ul>

      {reviewPending !== null ? (
        <div className="spk-banner" style={{ marginTop: 10 }}>
          <strong>人工评审关卡</strong>
          <div className="spk-implication" style={{ marginTop: 4 }}>
            {reviewPending === 'spec-review'
              ? 'spec 已生成，请评审确认后再进入方案（plan）阶段。'
              : 'plan 已生成，请评审确认后再进入任务（tasks）阶段。'}
          </div>
        </div>
      ) : null}

      {nextStep && reviewPending === null ? (
        <div className="spk-muted" style={{ marginTop: 8 }}>
          建议下一步：{nextStep.token}（点击上方按钮触发，由 AI 代理执行实际内容生成）
        </div>
      ) : null}
      {nextStep === null ? (
        <div className="spk-banner info" style={{ marginTop: 10 }}>
          🎉 工作流全部阶段已完成。
        </div>
      ) : null}
    </div>
  );
}