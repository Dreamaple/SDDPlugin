// T021: 全局错误呈现组件（FR-011：友好文案 + 建议操作 + 上下文驱动重试 + 查看日志）
import { postToHost } from '../vscode';
import type { FriendlyError } from '../../../shared/protocol';

interface RetryContext {
  action?: 'startInit' | 'switchIntegration';
  options?: { integrationId: string; script: 'sh' | 'ps' | 'py'; force: boolean };
  integrationId?: string;
  force?: boolean;
}

export function ErrorSurface(props: { error: FriendlyError | null }) {
  const { error } = props;
  if (!error) {
    return null;
  }
  const retry = (error.context ?? {}) as RetryContext;

  const retryAction = () => {
    if (retry.action === 'startInit' && retry.options) {
      postToHost({ type: 'startInit', options: retry.options });
    } else if (retry.action === 'switchIntegration' && retry.integrationId) {
      postToHost({
        type: 'switchIntegration',
        integrationId: retry.integrationId,
        force: retry.force ?? true,
      });
    } else {
      postToHost({ type: 'refresh' });
    }
  };

  const retryLabel =
    retry.action === 'startInit'
      ? '重试初始化'
      : retry.action === 'switchIntegration'
        ? '重试切换'
        : '重试';

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
          <button className="spk-btn" onClick={retryAction}>
            {retryLabel}
          </button>
        ) : null}
        <button className="spk-btn secondary" onClick={() => postToHost({ type: 'openLogs' })}>
          查看日志
        </button>
      </div>
    </div>
  );
}