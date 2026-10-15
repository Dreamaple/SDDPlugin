// T026: 初始化向导视图（US1：工具选择/脚本类型/覆盖二次确认；FR-002/FR-004）
// 增强：高级选项区对齐 specify init 完整旗标（preset/extensions/integration-options/开关）
import { useMemo, useState } from 'react';
import type { InitOptions, ScriptType, ToolCatalogEntry, WorkspaceEnvironment } from '../../../shared/protocol';

const BUNDLED_PRESETS = ['lean', 'constitution-sync'];
const BUNDLED_EXTENSIONS = ['git', 'agent-context', 'assess', 'bug', 'github'];

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

  // —— 高级选项（默认收起，全部可留空/关闭）——
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [presetChoice, setPresetChoice] = useState(''); // '' | bundled id | 'custom'
  const [presetCustom, setPresetCustom] = useState('');
  const [extensions, setExtensions] = useState<Record<string, boolean>>({});
  const [integrationOptions, setIntegrationOptions] = useState('');
  const [ignoreAgentTools, setIgnoreAgentTools] = useState(false);
  const [allowSymlinks, setAllowSymlinks] = useState(false);
  const [trustExtensionUrls, setTrustExtensionUrls] = useState(false);
  const [trustIntegration, setTrustIntegration] = useState(false);

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
  const selectedExtensionNames = BUNDLED_EXTENSIONS.filter((e) => extensions[e]);

  const buildOptions = (): InitOptions => ({
    integrationId: selectedTool!,
    script,
    force: forceAck,
    preset: presetChoice === 'custom' ? presetCustom.trim() : presetChoice || undefined,
    extensions: selectedExtensionNames.length > 0 ? selectedExtensionNames : undefined,
    integrationOptions: integrationOptions.trim() || undefined,
    ignoreAgentTools: ignoreAgentTools || undefined,
    allowSymlinks: allowSymlinks || undefined,
    trustExtensionUrls: trustExtensionUrls || undefined,
    trustIntegration: trustIntegration || undefined,
  });

  const submit = () => {
    if (!selectedTool) {
      return;
    }
    onStart(buildOptions());
    setConfirming(false);
    setForceAck(false);
  };

  // 高级选项摘要（确认卡与按钮副标题展示）
  const advancedSummary: string[] = [];
  const presetValue = presetChoice === 'custom' ? presetCustom.trim() : presetChoice;
  if (presetValue) {
    advancedSummary.push(`preset:${presetValue}`);
  }
  if (selectedExtensionNames.length > 0) {
    advancedSummary.push(`扩展:${selectedExtensionNames.join(',')}`);
  }
  if (integrationOptions.trim()) {
    advancedSummary.push('自定义集成选项');
  }
  if (ignoreAgentTools) {
    advancedSummary.push('跳过工具检查');
  }
  if (allowSymlinks) {
    advancedSummary.push('符号链接');
  }

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

      {/* —— 高级选项（对齐 specify init 完整旗标）—— */}
      <details
        open={showAdvanced}
        onToggle={(e) => setShowAdvanced((e.target as HTMLDetailsElement).open)}
      >
        <summary style={{ cursor: 'pointer', marginTop: 6 }}>
          高级选项
          {advancedSummary.length > 0 ? (
            <span className="spk-chip" style={{ marginLeft: 8 }}>
              {advancedSummary.length} 项已配置
            </span>
          ) : null}
        </summary>
        <div className="spk-card" style={{ marginTop: 8 }}>
          <div className="spk-row">
            <span className="spk-muted" style={{ minWidth: 84 }}>
              预设（preset）
            </span>
            <select
              className="spk-select"
              style={{ width: 'auto' }}
              value={presetChoice}
              onChange={(e) => setPresetChoice(e.target.value)}
            >
              <option value="">（不安装预设）</option>
              {BUNDLED_PRESETS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
              <option value="custom">自定义 id…</option>
            </select>
            {presetChoice === 'custom' ? (
              <input
                className="spk-input"
                style={{ width: 'auto', flex: 1 }}
                placeholder="输入预设 id"
                value={presetCustom}
                onChange={(e) => setPresetCustom(e.target.value)}
              />
            ) : null}
          </div>

          <div className="spk-row" style={{ alignItems: 'flex-start' }}>
            <span className="spk-muted" style={{ minWidth: 84, paddingTop: 3 }}>
              扩展（extension）
            </span>
            <div className="spk-row" style={{ flexWrap: 'wrap', margin: 0 }}>
              {BUNDLED_EXTENSIONS.map((name) => (
                <label key={name} className="spk-row" style={{ margin: 0 }}>
                  <input
                    type="checkbox"
                    checked={!!extensions[name]}
                    onChange={(e) =>
                      setExtensions((prev) => ({ ...prev, [name]: e.target.checked }))
                    }
                  />
                  {name}
                </label>
              ))}
            </div>
          </div>

          <div className="spk-col">
            <span className="spk-muted">集成选项（--integration-options，如 --commands-dir .myagent/cmds）</span>
            <input
              className="spk-input"
              value={integrationOptions}
              onChange={(e) => setIntegrationOptions(e.target.value)}
            />
          </div>

          <div className="spk-row" style={{ flexWrap: 'wrap' }}>
            <label className="spk-row" style={{ margin: 0 }}>
              <input
                type="checkbox"
                checked={ignoreAgentTools}
                onChange={(e) => setIgnoreAgentTools(e.target.checked)}
              />
              跳过 agent 工具检查
            </label>
            <label className="spk-row" style={{ margin: 0 }}>
              <input
                type="checkbox"
                checked={allowSymlinks}
                onChange={(e) => setAllowSymlinks(e.target.checked)}
              />
              允许符号链接
            </label>
          </div>

          <div className="spk-banner" style={{ margin: 0 }}>
            <div className="spk-implication">
              信任选项（仅外部内容需要；内置预设/扩展无需开启）
            </div>
            <div className="spk-row" style={{ flexWrap: 'wrap' }}>
              <label className="spk-row" style={{ margin: 0 }}>
                <input
                  type="checkbox"
                  checked={trustExtensionUrls}
                  onChange={(e) => setTrustExtensionUrls(e.target.checked)}
                />
                信任外部扩展 URL（--trust-extension-urls）
              </label>
              <label className="spk-row" style={{ margin: 0 }}>
                <input
                  type="checkbox"
                  checked={trustIntegration}
                  onChange={(e) => setTrustIntegration(e.target.checked)}
                />
                信任外部集成包（--trust-integration）
              </label>
            </div>
          </div>
        </div>
      </details>

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
          {advancedSummary.length > 0 ? (
            <div className="spk-context">高级选项：{advancedSummary.join(' · ')}</div>
          ) : null}
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
          {advancedSummary.length > 0 ? `（含 ${advancedSummary.length} 项高级选项）` : ''}
        </button>
      )}
    </div>
  );
}