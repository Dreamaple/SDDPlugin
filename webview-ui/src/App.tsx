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
import { ProjectConfigView, type ProjectConfigPayload } from './views/ProjectConfigView';

type Tab = 'workflow' | 'clarify';

export function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | undefined>(undefined);
  const [progress, setProgress] = useState<Progress>(idleProgress());
  const [error, setError] = useState<FriendlyError | null>(null);
  const [tab, setTab] = useState<Tab>('workflow');
  const [notice, setNotice] = useState<string | undefined>(undefined);
  // 项目配置视图（宪法占位 tag 预填）；undefined = 关闭
  const [projectConfig, setProjectConfig] = useState<ProjectConfigPayload | undefined>(undefined);

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
        case 'projectConfigLoaded':
          setProjectConfig({
            fields: msg.fields,
            values: msg.values,
            defaults: msg.defaults,
            workspaceName: msg.workspaceName,
            updatedAt: msg.updatedAt,
          });
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
        environment.cliSource === 'bundled'
          ? `从 github/spec-kit 最新 Release 下载源码刷新内置副本（当前内置 v${environment.cliVersion ?? '?'}）`
          : '更新内置 Spec Kit 源码（更新后初始化不再依赖机器上的 CLI 版本）'
      }
      onClick={() => postToHost({ type: 'updateBundledSpeckit' })}
    >
      更新内置 Spec Kit{environment.cliSource === 'bundled' && environment.cliVersion ? `（${environment.cliVersion}）` : ''}
    </button>
  ) : null;

  const showWizard = !snapshot.multiRootBlocked && environment.state !== 'ready';

  const envSummary =
    environment.state === 'ready'
      ? [
          environment.script ? `脚本 ${environment.script}` : undefined,
          environment.speckitVersion ? `Spec Kit ${environment.speckitVersion}` : undefined,
          environment.aiSkills ? 'skills 模式' : undefined,
          environment.cliVersion
            ? `${environment.cliSource === 'bundled' ? '内置' : 'CLI'} ${environment.cliVersion}`
            : undefined,
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
        {!snapshot.multiRootBlocked ? (
          <button
            className="spk-btn secondary"
            title="预填宪法占位 tag（项目名/模块名/包根等），存于 .specify/project-config.json"
            onClick={() => postToHost({ type: 'loadProjectConfig' })}
          >
            项目配置
          </button>
        ) : null}
        {upgradeButton}
        <button className="spk-btn secondary" onClick={() => postToHost({ type: 'refresh' })}>
          刷新
        </button>
      </div>

      <ErrorSurface error={error} onDismiss={() => setError(null)} />
      <ProgressView progress={progress} />

      {projectConfig ? (
        <ProjectConfigView config={projectConfig} onBack={() => setProjectConfig(undefined)} />
      ) : snapshot.multiRootBlocked ? (
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
            running={progress.running}
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
            <WorkflowView
              stages={stages}
              nextStep={nextStep}
              reviewPending={reviewPending}
              constitutionRules={snapshot.constitutionRules}
              preprocessFiles={snapshot.preprocessFiles}
              preprocessSelected={snapshot.preprocessSelected}
              clarifyRounds={snapshot.clarifyRounds}
              prototype={snapshot.prototype}
              hifi={snapshot.hifiPrototype}
              hifiConfig={snapshot.hifiConfig}
              tokenSaved={snapshot.hifiTokenSaved}
            />
          ) : (
            <ClarifyView
              items={clarifications}
              onAnswer={(id, answer) => postToHost({ type: 'answerClarification', id, answer })}
              onWriteBack={(answers) => postToHost({ type: 'applyClarificationBatch', answers })}
              onExport={() => postToHost({ type: 'exportClarifications' })}
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