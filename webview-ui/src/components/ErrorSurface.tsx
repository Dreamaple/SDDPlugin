// T021: 全局错误呈现组件（FR-011：友好文案 + 建议操作 + 重试 + 查看日志）
import { postToHost } from '../vscode';
import type { FriendlyError } from '../../../shared/protocol';

export function ErrorSurface(props: { error: FriendlyError | null }) {
  const { error } = props;
  if (!error) {
    return null;
  }
  return (
    <div className="spk-banner error" role="alert">
      <div>
        <strong>⚠ {error.message}</strong>
      </div>
      {error.suggestion ? (
        <div className="spk-implication" style={{ marginTop: 4 }}>
          建议：{error.suggestion}
        </div>
      ) : null}
      <div className="spk-row" style={{ marginTop: 8 }}>
        {error.canRetry ? (
          <button
            className="spk-btn"
            onClick={() => {
              // 重试动作：刷新状态（向导/按钮可再次点击触发原操作）
              postToHost({ type: 'refresh' });
            }}
          >
            重试
          </button>
        ) : null}
        <button className="spk-btn secondary" onClick={() => postToHost({ type: 'openLogs' })}>
          查看日志
        </button>
      </div>
    </div>
  );
}