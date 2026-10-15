// T026: 初始化向导视图（US1：工具选择/脚本类型/覆盖二次确认；FR-002/FR-004）
import { useMemo, useState } from 'react';
import type { InitOptions, ScriptType, ToolCatalogEntry, WorkspaceEnvironment } from '../../../shared/protocol';

function defaultScript(): ScriptType {
  // 平台默认：Windows → ps，其他 → sh（contracts/cli.md §2）
  if (typeof navigator !== 'undefined' && /win/i.test(navigator.platform)) {
    return 'ps';
  }
  return 'sh';
}

export function WizardView(props: {
  tools: ToolCatalogEntry[];
  environment: WorkspaceEnvironment;
  onStart: (options: InitOptions) => void;
}) {
  const { tools, environment, onStart } = props;
  const [search, setSearch] = useState('');
  const [selectedTool, setSelectedTool] = useState<string | undefined>(undefined);
  const [script, setScript] = useState<ScriptType>(defaultScript());
  const [confirming, setConfirming] = useState(false);
  const [forceAck, setForceAck] = useState(false);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) {
      return tools;
    }
    return tools.filter(
      (t) => t.id.toLowerCase().includes(q) || t.label.toLowerCase().includes(q),
    );
  }, [tools, search]);

  const isSwitch = environment.state === 'ready';
  const currentLabel = isSwitch
    ? environment.isKnownIntegration
      ? (environment.integrationLabel ?? environment.integrationId)
      : '未知/自定义环境'
    : undefined;
  const targetLabel = tools.find((t) => t.id === selectedTool)?.label ?? selectedTool;

  const submit = () => {
    if (!selectedTool) {
      return;
    }
    onStart({ integrationId: selectedTool, script, force: forceAck });
    setConfirming(false);
    setForceAck(false);
  };

  return (
    <div className="spk-col">
      {isSwitch ? (
        <div className="spk-banner info">
          当前工具环境：<strong>{currentLabel}</strong>
          {environment.script ? `（脚本 ${environment.script}）` : ''}
          {environment.speckitVersion ? ` · Spec Kit ${environment.speckitVersion}` : ''}
          <div className="spk-implication" style={{ marginTop: 4 }}>
            下方选择将安装/切换为新的工具环境（specify integration install）。覆盖前需二次确认。
          </div>
        </div>
      ) : environment.state === 'incomplete' ? (
        <div className="spk-banner">
          <strong>环境不完整</strong>
          <ul style={{ margin: '6px 0 0 16px' }}>
            {environment.hints.map((h, i) => (
              <li key={i} className="spk-implication">
                {h}
              </li>
            ))}
          </ul>
          <div className="spk-implication" style={{ marginTop: 4 }}>
            可通过下方向导修复或重新初始化（可能合并/覆盖现有 .specify 内容）。
          </div>
        </div>
      ) : (
        <div className="spk-banner info">
          当前项目尚未初始化 Speckit 环境。选择 AI 工具与脚本类型，一键完成初始化。
        </div>
      )}

      <input
        className="spk-input"
        placeholder="搜索工具（如 claude / copilot / cursor）"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      <div className="spk-tools">
        {filtered.map((tool) => (
          <div
            key={tool.id}
            className={`spk-tool${tool.id === selectedTool ? ' selected' : ''}`}
            onClick={() => setSelectedTool(tool.id)}
          >
            <span>{tool.label}</span>
            <span className="spk-muted">{tool.id}</span>
          </div>
        ))}
        {filtered.length === 0 ? <div className="spk-tool">无匹配工具</div> : null}
      </div>

      <div className="spk-row">
        <span className="spk-muted">脚本类型</span>
        {(['sh', 'ps', 'py'] as ScriptType[]).map((s) => (
          <label key={s} className="spk-row" style={{ margin: 0 }}>
            <input
              type="radio"
              name="script"
              checked={script === s}
              onChange={() => setScript(s)}
            />
            {s}
          </label>
        ))}
      </div>

      {confirming ? (
        <div className="spk-card">
          <div>
            <strong>确认{isSwitch ? '切换' : '初始化'}</strong>
          </div>
          <div className="spk-implication" style={{ margin: '6px 0' }}>
            {isSwitch
              ? `将在当前工作区根目录执行 specify integration install ${selectedTool}（当前：${currentLabel}）`
              : `将在当前工作区根目录执行 specify init --here --integration ${selectedTool} --script ${script}`}
            。此操作会写入/合并 .specify 目录与所选工具的命令文件。
          </div>
          <label className="spk-row">
            <input type="checkbox" checked={forceAck} onChange={(e) => setForceAck(e.target.checked)} />
            我确认覆盖/合并现有配置（force）
          </label>
          <div className="spk-row">
            <button className="spk-btn primary" disabled={!forceAck} onClick={submit}>
              确认执行（{targetLabel}）
            </button>
            <button className="spk-btn secondary" onClick={() => setConfirming(false)}>
              取消
            </button>
          </div>
        </div>
      ) : (
        <button className="spk-btn primary" disabled={!selectedTool} onClick={() => setConfirming(true)}>
          {isSwitch ? `切换为 ${targetLabel ?? '所选工具'}` : '开始初始化'}
        </button>
      )}
    </div>
  );
}