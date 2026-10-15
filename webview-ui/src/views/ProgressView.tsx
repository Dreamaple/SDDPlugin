// T042: 进度视图（US3：活动指示/日志尾/N-M/取消/终态摘要）
import { postToHost } from '../vscode';
import type { Progress } from '../../../shared/protocol';

export function ProgressView(props: { progress: Progress }) {
  const { progress } = props;

  if (!progress.running && !progress.result) {
    return null;
  }

  if (progress.result) {
    const icon =
      progress.result.outcome === 'success' ? '✅' : progress.result.outcome === 'cancelled' ? '🟡' : '❌';
    return (
      <div className={`spk-banner ${progress.result.outcome === 'success' ? 'info' : 'error'}`}>
        <strong>
          {icon} {progress.result.message}
        </strong>
      </div>
    );
  }

  return (
    <div className="spk-card">
      <div className="spk-row">
        <span className="spk-spin" />
        <strong>{progress.label || '操作进行中…'}</strong>
        <span style={{ flex: 1 }} />
        {progress.taskStats ? (
          <span className="spk-chip">
            {progress.taskStats.done}/{progress.taskStats.total} 已完成
          </span>
        ) : null}
        {progress.cancellable ? (
          <button className="spk-btn secondary" onClick={() => postToHost({ type: 'cancelOperation' })}>
            取消
          </button>
        ) : null}
      </div>
      {progress.logTail.length > 0 ? (
        <div className="spk-log">
          {progress.logTail.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      ) : null}
    </div>
  );
}