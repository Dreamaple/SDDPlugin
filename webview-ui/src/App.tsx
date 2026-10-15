// T020: Webview 外壳——消息总线、环境横幅、视图路由、进度浮层与命令回执提示
import { useEffect, useState } from 'react';
import type {
  FriendlyError,
  HostToWebview,
  Progress,
  Snapshot,
} from '../../shared/protocol';
import { idleProgress } from '../../shared/protocol';
import { onHostMessage, postToHost } from './vscode';
import { ErrorSurface } from './components/ErrorSurface';
import { FeatureSwitcher } from './components/FeatureSwitcher';
import { WizardView } from './views/WizardView';
import { CliMissingView } from './views/CliMissingView';
import { WorkflowView } from './views/WorkflowView';
import { ProgressView } from './views/ProgressView';
import { ClarifyView } from './views/ClarifyView';

type Tab = 'workflow' | 'clarify';

export function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | undefined>(undefined);
  const [progress, setProgress] = useState<Progress>(idleProgress());
  const [error, setError] = useState<FriendlyError | null>(null);
  const [tab, setTab] = useState<Tab>('workflow');
  const [notice, setNotice] = useState<string | undefined>(undefined);

  useEffect(() => {
    const off = onHostMessage((msg: HostToWebview) => {
      switch (msg.type) {
        case 'stateUpdated':
          setSnapshot(msg.snapshot);
          // 注意：不在 stateUpdated 时清除错误——失败详情必须保持可见直到用户处置或新操作开始
          break;
        case 'progressUpdated':
          setProgress(msg.progress);
          // 新操作开始（running）或成功/取消终态 → 清除旧错误
          if (msg.progress.running || msg.progress.result?.outcome !== 'failure') {
            setError(null);
          }
          break;
        case 'errorRaised':
          setError(msg.error);
          break;
        case 'commandResult':
          setNotice(
            msg.outcome === 'failed'
              ? `命令触发失败：${msg.token}`
              : msg.outcome === 'fallback-clipboard'
                ? `已复制 ${msg.token}，请粘贴到 AI 聊天发送`
                : `已触发 ${msg.token}（阶段转进行中）`,
          );
          break;
      }
    });
    postToHost({ type: 'ready' });
    return off;
  }, []);

  if (!snapshot) {
    return <div className="spk-muted">Speckit 面板加载中…</div>;
  }

  const { environment, features, stages, clarifications, nextStep, reviewPending } = snapshot;
  const tools = snapshot.tools ?? [];

  const envChip = snapshot.multiRootBlocked
    ? { text: '多根工作区（不支持）', cls: 'warn' }
    : environment.state === 'missing'
      ? { text: '未初始化', cls: 'warn' }
      : environment.state === 'incomplete'
        ? { text: '环境不完整', cls: 'warn' }
        : {
            text: environment.isKnownIntegration
              ? (environment.integrationLabel ?? environment.integrationId ?? '')
              : '未知/自定义环境',
            cls: 'ok',
          };

  const upgradeButton = !snapshot.multiRootBlocked && environment.cliAvailable ? (
    <button
      className="spk-btn secondary"
      title={
        environment.cliUpgradeSupported
          ? `升级 specify CLI（当前 ${environment.cliVersion ?? '未知版本'}；需访问 GitHub Releases）`
          : `当前 CLI ${environment.cliVersion ?? ''} 较旧、不支持自升级，点击查看手动升级指引`
      }
      onClick={() => postToHost({ type: 'upgradeSpeckit' })}
    >
      升级 Spec Kit{environment.cliVersion ? `（${environment.cliVersion}）` : ''}
    </button>
  ) : null;

  const showWizard = !snapshot.multiRootBlocked && environment.state !== 'ready';

  const envSummary =
    environment.state === 'ready'
      ? [
          environment.script ? `脚本 ${environment.script}` : undefined,
          environment.speckitVersion ? `Spec Kit ${environment.speckitVersion}` : undefined,
          environment.aiSkills ? 'skills 模式' : undefined,
        ]
          .filter(Boolean)
          .join(' · ')
      : '';

  return (
    <div>
      <div className="spk-header">
        <strong>Speckit 面板</strong>
        <span className={`spk-chip ${envChip.cls}`}>{envChip.text}</span>
        {envSummary ? <span className="spk-muted">{envSummary}</span> : null}
        <span style={{ flex: 1 }} />
        <FeatureSwitcher features={features} disabled={snapshot.multiRootBlocked} />
        {upgradeButton}
        <button className="spk-btn secondary" onClick={() => postToHost({ type: 'refresh' })}>
          刷新
        </button>
      </div>

      <ErrorSurface error={error} onDismiss={() => setError(null)} />
      <ProgressView progress={progress} />

      {snapshot.multiRootBlocked ? (
        <div className="spk-banner error">
          <strong>v1 仅支持单根工作区</strong>
          <div className="spk-implication" style={{ marginTop: 4 }}>
            请打开单个项目文件夹后重试。
          </div>
        </div>
      ) : showWizard ? (
        environment.state !== 'missing' || environment.cliAvailable ? (
          <WizardView
            tools={tools}
            environment={environment}
            onStart={(options) => postToHost({ type: 'startInit', options })}
          />
        ) : (
          <CliMissingView />
        )
      ) : (
        <>
          <div className="spk-tabs">
            <button className={`spk-tab${tab === 'workflow' ? ' active' : ''}`} onClick={() => setTab('workflow')}>
              工作流
            </button>
            <button className={`spk-tab${tab === 'clarify' ? ' active' : ''}`} onClick={() => setTab('clarify')}>
              澄清
              {clarifications.some((c) => c.status === 'open') ? ' ●' : ''}
            </button>
          </div>
          {tab === 'workflow' ? (
            <WorkflowView stages={stages} nextStep={nextStep} reviewPending={reviewPending} />
          ) : (
            <ClarifyView
              items={clarifications}
              onAnswer={(id, answer) => postToHost({ type: 'answerClarification', id, answer })}
            />
          )}
        </>
      )}

      {notice ? (
        <div className="spk-toast" onClick={() => setNotice(undefined)}>
          {notice}
        </div>
      ) : null}
    </div>
  );
}