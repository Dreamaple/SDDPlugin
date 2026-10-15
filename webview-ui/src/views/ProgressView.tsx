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
    <div className="spk-banner error" role="alert">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <strong style={{ flex: 1 }}>
          {icon} {progress.result.message}
        </strong>
        <button
          className="spk-btn secondary"
          style={{ padding: '1px 8px', flex: 'none' }}
          onClick={() => postToHost({ type: 'refresh' })}
          title="关闭此提示"
        >
          ×
        </button>
      </div>
      {progress.result.outcome === 'failure' && progress.logTail.length > 0 ? (
        <>
          <div className="spk-log" style={{ marginTop: 8 }}>
            {progress.logTail.slice(-3).map((line, i) => (
              <div key={i}>{line}</div>
            ))}
          </div>
          <div className="spk-row" style={{ marginTop: 8 }}>
            <button className="spk-btn secondary" onClick={() => postToHost({ type: 'openLogs' })}>
              查看日志
            </button>
          </div>
        </>
      ) : null}
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
      {progress.kind === 'determinate' && progress.ratio !== undefined ? (
        <div
          style={{
            height: 4,
            borderRadius: 2,
            marginTop: 6,
            background: 'var(--vscode-input-border, #444)',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              width: `${Math.round(Math.min(1, Math.max(0, progress.ratio)) * 100)}%`,
              height: '100%',
              background: 'var(--vscode-focusBorder, #3794ff)',
            }}
          />
        </div>
      ) : null}
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