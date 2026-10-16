// T033/T034/T044: 工作流视图——阶段时间线、下一步按钮、评审关卡、N/M 徽章
// 确认交互使用面板内联确认卡（VSCode webview 禁用 window.confirm/alert，原生弹窗不可用）
import { useEffect, useState } from 'react';
import { postToHost, onHostMessage } from '../vscode';
import type { GateId, StageId, StageState, WorkflowStage } from '../../../shared/protocol';

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

/** constitution 防误触：公共宪法目录为空时的后果说明（可随时补放规则并重跑） */
const CONSTITUTION_EMPTY_WARNING = [
  '公共宪法目录（.specify/constitution）下还没有规则文件。',
  '不主动输入规则就继续时，AI 只能依据内置模板生成通用宪法，无法体现你项目专属的工程规范与约束，后续阶段可能偏离项目实际要求。',
  '你可以随时把规则文件放入该目录，再运行 /speckit-constitution 增加或修改宪法。',
].join('\n');

/**
 * 触发前需要用户确认的场景与文案（null = 直接触发）：
 * - implement：任务清单未全部完成（contracts/dispatch.md §3）
 * - constitution：公共宪法目录为空
 */
function confirmMessageFor(stage: WorkflowStage, constitutionRules: string[] | undefined): string | null {
  if (stage.id === 'implement' && stage.taskStats && stage.taskStats.done < stage.taskStats.total) {
    return `任务清单尚未全部完成（${stage.taskStats.done}/${stage.taskStats.total}），确认运行 ${stage.commandToken}？`;
  }
  if (stage.id === 'constitution' && (constitutionRules?.length ?? 0) === 0) {
    return CONSTITUTION_EMPTY_WARNING;
  }
  return null;
}

/** 公共宪法目录引导横幅（宪法阶段未完成时显示） */
function ConstitutionBanner(props: { rules: string[] }) {
  const { rules } = props;
  return (
    <div className="spk-banner" style={{ marginTop: 10 }}>
      <strong>公共宪法目录（.specify/constitution）</strong>
      <div className="spk-implication" style={{ marginTop: 4 }}>
        把项目的公共规则、约束与原则放入该目录（一个或多个 .md/.txt 文件，支持子目录）。
        触发「宪法」命令时，这些文件的路径会自动附加到提示词中，由 AI 先阅读再生成宪法。
      </div>
      {rules.length > 0 ? (
        <div className="spk-context" style={{ marginTop: 6 }}>
          已发现 {rules.length} 个规则文件：{rules.join('、')}
        </div>
      ) : (
        <div className="spk-implication" style={{ marginTop: 6 }}>
          当前目录还没有规则文件（目录内 README.md 为使用说明）。
        </div>
      )}
      <div className="spk-row" style={{ marginTop: 6 }}>
        <button className="spk-btn secondary" onClick={() => postToHost({ type: 'openConstitutionDir' })}>
          打开目录
        </button>
        <button className="spk-btn secondary" onClick={() => postToHost({ type: 'loadProjectConfig' })}>
          填写项目配置
        </button>
        <span className="spk-muted">项目名/模块名/包根等占位 tag 可提前预填</span>
      </div>
    </div>
  );
}

/** 预处理卡片（规范文档导入 → specify 输入；位于阶段列表之前） */
const PREPROCESS_PREFIX = '.specify/preprocess/';

function PreprocessCard(props: {
  files: string[];
  selected: string[];
}) {
  const { files, selected } = props;
  const selectedSet = new Set(selected);

  const toggleFile = (file: string) => {
    const next = selectedSet.has(file)
      ? selected.filter((s) => s !== file)
      : [...selected, file];
    postToHost({ type: 'setPreprocessSelection', selected: next });
  };

  // 按顶层目录分组；目录勾选框批量开关组内全部文件（"选择文件夹"）
  const groups = new Map<string, string[]>();
  for (const f of files) {
    const rel = f.startsWith(PREPROCESS_PREFIX) ? f.slice(PREPROCESS_PREFIX.length) : f;
    const dir = rel.includes('/') ? rel.slice(0, rel.indexOf('/')) : '(根目录)';
    const list = groups.get(dir);
    if (list) {
      list.push(f);
    } else {
      groups.set(dir, [f]);
    }
  }

  const toggleFolder = (groupFiles: string[]) => {
    const allOn = groupFiles.every((f) => selectedSet.has(f));
    const next = allOn
      ? selected.filter((s) => !groupFiles.includes(s))
      : [...selected, ...groupFiles.filter((f) => !selectedSet.has(f))];
    postToHost({ type: 'setPreprocessSelection', selected: next });
  };

  return (
    <div className="spk-card">
      <div className="spk-row" style={{ marginTop: 0 }}>
        <strong>预处理（导入规范文档）</strong>
        <span className={`spk-chip${selected.length > 0 ? '' : ' warn'}`}>
          规范输入：{selected.length > 0 ? `已选 ${selected.length} 项` : '未选择（必选）'}
        </span>
        <span style={{ flex: 1 }} />
        <button className="spk-btn primary" onClick={() => postToHost({ type: 'runPreprocess' })}>
          预处理
        </button>
        <button className="spk-btn secondary" onClick={() => postToHost({ type: 'openPreprocessDir' })}>
          打开目录
        </button>
      </div>
      <div className="spk-implication">
        点击「预处理」选择一个或多个规范文档（PDF/DOCX/PPTX 等，可多选），AI
        将其转换为 Markdown 输出到 .specify/preprocess；在下方勾选要加载的文件或文件夹，作为「规范」阶段的输入（必选）。
      </div>
      {files.length === 0 ? (
        <div className="spk-muted" style={{ marginTop: 6 }}>
          暂无预处理输出。点击「预处理」选择文档目录开始导入。
        </div>
      ) : (
        <div className="spk-col" style={{ marginTop: 6 }}>
          {Array.from(groups.entries()).map(([dir, groupFiles]) => {
            const allOn = groupFiles.every((f) => selectedSet.has(f));
            return (
              <div key={dir}>
                <label className="spk-row" style={{ margin: '2px 0' }}>
                  <input
                    type="checkbox"
                    checked={allOn}
                    onChange={() => toggleFolder(groupFiles)}
                  />
                  <strong>📁 {dir}</strong>
                  <span className="spk-muted">（{groupFiles.length} 个文件）</span>
                </label>
                <div style={{ paddingLeft: 22 }}>
                  {groupFiles.map((f) => (
                    <label key={f} className="spk-row" style={{ margin: '2px 0' }}>
                      <input type="checkbox" checked={selectedSet.has(f)} onChange={() => toggleFile(f)} />
                      <span style={{ fontFamily: 'var(--vscode-editor-font-family, monospace)', fontSize: 11 }}>
                        {f.slice(PREPROCESS_PREFIX.length)}
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            );
          })}
          <div className="spk-row">
            <button
              className="spk-btn secondary"
              onClick={() =>
                postToHost({ type: 'setPreprocessSelection', selected: files.filter((f) => !selectedSet.has(f)) })
              }
            >
              全选
            </button>
            <button
              className="spk-btn secondary"
              onClick={() => postToHost({ type: 'setPreprocessSelection', selected: [] })}
            >
              清空
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** 低保真可交互原型卡片（可选流程：spec → HTML 线框图 → 浏览器点击走查） */
function PrototypeCard(props: { prototype: { mtimeMs: number } | undefined; specReady: boolean }) {
  const { prototype, specReady } = props;
  return (
    <div className="spk-card">
      <div className="spk-row" style={{ marginTop: 0 }}>
        <strong>低保真原型（可选）</strong>
        {prototype ? (
          <span className="spk-muted">已生成 · {new Date(prototype.mtimeMs).toLocaleString()}</span>
        ) : (
          <span className={`spk-chip${specReady ? '' : ' warn'}`}>
            {specReady ? '未生成' : '需先完成规范'}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {prototype ? (
          <button className="spk-btn primary" onClick={() => postToHost({ type: 'openPrototype' })}>
            打开原型
          </button>
        ) : null}
        <button
          className="spk-btn secondary"
          disabled={!specReady}
          onClick={() => postToHost({ type: 'generatePrototype' })}
          title="派发指令给 Agent：基于当前 spec 生成单文件 HTML 线框图（灰阶占位、可点击跳转、标注需求编号）"
        >
          {prototype ? '重新生成' : '生成原型'}
        </button>
      </div>
      <div className="spk-implication">
        基于当前 spec 生成可交互 HTML 线框图（灰阶占位、页面间可点击跳转、标注需求编号，
        spec 未定义的细节以 [TBD] 占位），用于在进入方案（plan）前直观走查需求。
        生成由 AI 完成，完成后浏览器打开即可点击浏览；澄清更新后可随时重新生成。
      </div>
    </div>
  );
}

/** 高保真可交互原型卡片（plan 评审通过后的 UI 1:1 落地；输入源可选） */
const HIFI_SOURCE_OPTIONS: Array<{ id: string; label: string }> = [
  { id: 'mastergo-bridge', label: 'MasterGo 网页桥（无 MCP）' },
  { id: 'mastergo', label: 'MasterGo MCP/令牌' },
  { id: 'playwright', label: 'Playwright MCP' },
  { id: 'local', label: '本地目录' },
  { id: 'svn', label: '远程（SVN 等）' },
];

const HIFI_INPUT_PLACEHOLDER: Record<string, string> = {
  mastergo: 'MasterGo 设计稿页面 ID / 分享链接（无 MCP 坐席时填网页链接）',
  'mastergo-bridge': 'MasterGo 设计稿页面 ID / 分享链接 / 帧名',
  playwright: '在线设计平台 URL（需登录）',
  local: '本地设计稿/切图目录路径（可用「浏览」选择）',
  svn: 'SVN 仓库 URL（设计稿/切图目录）',
};

function HiFiPrototypeCard(props: {
  hifi: { mtimeMs: number } | undefined;
  config: { source: string; input: string; downloadAssets: boolean } | undefined;
  tokenSaved?: boolean;
  planReady: boolean;
}) {
  const { hifi, config, tokenSaved, planReady } = props;
  const [source, setSource] = useState<string>(config?.source ?? 'mastergo');
  const [input, setInput] = useState<string>(config?.input ?? '');
  const [downloadAssets, setDownloadAssets] = useState<boolean>(config?.downloadAssets ?? true);
  const [authToken, setAuthToken] = useState<string>('');

  // 本地目录选择器结果（宿主通过 folderPicked 回传）
  useEffect(() => {
    return onHostMessage((msg) => {
      if (msg.type === 'folderPicked' && msg.path) {
        setInput(msg.path);
      }
    });
  }, []);

  const generate = () => {
    postToHost({
      type: 'generateHiFiPrototype',
      source: source as 'local' | 'svn' | 'mastergo' | 'mastergo-bridge' | 'playwright',
      input,
      downloadAssets,
      authToken: authToken.trim().length > 0 ? authToken.trim() : undefined,
    });
  };

  return (
    <div className="spk-card">
      <div className="spk-row" style={{ marginTop: 0 }}>
        <strong>高保真原型（UI 1:1 还原）</strong>
        {hifi ? (
          <span className="spk-muted">已生成 · {new Date(hifi.mtimeMs).toLocaleString()}</span>
        ) : (
          <span className={`spk-chip${planReady ? '' : ' warn'}`}>
            {planReady ? '未生成' : '需先通过方案评审'}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {hifi ? (
          <button className="spk-btn primary" onClick={() => postToHost({ type: 'openHiFiPrototype' })}>
            打开高保真原型
          </button>
        ) : null}
        <button className="spk-btn secondary" disabled={!planReady} onClick={generate}>
          {hifi ? '重新生成' : '生成高保真原型'}
        </button>
      </div>
      <div className="spk-implication">
        plan 评审通过后，Agent 会先读取 spec/plan/data-model/contracts/constitution 输出 UE 需求清单，
        再按所选 UI 输入源 1:1 还原为可交互 HTML（登录等行为用 Playwright MCP 打通），
        全量覆盖 UE 需求并输出完成度清单（README）。
      </div>
      <div className="spk-row" style={{ flexWrap: 'wrap' }}>
        <span className="spk-muted" style={{ flex: 'none' }}>UI 输入</span>
        <select
          className="spk-select"
          style={{ width: 'auto', flex: 'none' }}
          value={source}
          onChange={(e) => setSource(e.target.value)}
        >
          {HIFI_SOURCE_OPTIONS.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
        <input
          className="spk-input"
          style={{ flex: 1, minWidth: 200 }}
          placeholder={HIFI_INPUT_PLACEHOLDER[source] ?? 'UI 输入'}
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        {source === 'local' ? (
          <button
            className="spk-btn secondary"
            style={{ flex: 'none' }}
            onClick={() => postToHost({ type: 'pickHiFiFolder' })}
          >
            浏览…
          </button>
        ) : null}
        <label className="spk-row" style={{ margin: 0, flex: 'none' }}>
          <input type="checkbox" checked={downloadAssets} onChange={(e) => setDownloadAssets(e.target.checked)} />
          先下载全部切图
        </label>
      </div>
      {source === 'mastergo-bridge' ? (
        <div className="spk-implication">
          无需 MCP 坐席、无需认证令牌——通过已登录 MasterGo 的调试 Chrome（--remote-debugging-port）CDP
          连接，在页面内用插件 API（window.mg）读取设计原始数据（几何/DSL/矢量 SVG/位图），
          经插件 ui.html + 本地桥（127.0.0.1）落盘后 1:1 还原。前置：能加载开发者插件的已登录编辑器会话
          （codegen 需研发模式，不可用时自动退化为 getNodeById 遍历）。
        </div>
      ) : null}
      {source === 'mastergo' ? (
        <div className="spk-col" style={{ marginTop: 6 }}>
          <span className="spk-muted">
            个人认证令牌（选填）：用于免登录直调 MasterGo 数据 API；保存于 VSCode Secrets 加密存储，不会出现在聊天记录里
          </span>
          <input
            className="spk-input"
            type="password"
            placeholder={
              tokenSaved
                ? '已保存令牌（留空沿用；输入新值则覆盖）'
                : '粘贴 MasterGo 个人访问令牌（选填）'
            }
            value={authToken}
            onChange={(e) => setAuthToken(e.target.value)}
          />
        </div>
      ) : null}
      {source === 'mastergo' || source === 'playwright' ? (
        <div className="spk-implication">
          {source === 'mastergo'
            ? '取材自动回退：有 MasterGo MCP 坐席走 MCP → 无坐席但填了令牌则免登录直调数据 API → 都没有则 Playwright MCP 登录网页端读数据 API。切图先行建议勾选。'
            : '需当前会话已接入 Playwright MCP（用于登录与在线页面遍历）。'}
        </div>
      ) : null}
    </div>
  );
}

export function WorkflowView(props: {
  stages: WorkflowStage[];
  nextStep: { stageId: StageId; token: string } | null;
  reviewPending: GateId | null;
  constitutionRules?: string[];
  preprocessFiles?: string[];
  preprocessSelected?: string[];
  clarifyRounds?: number;
  prototype?: { mtimeMs: number };
  hifi?: { mtimeMs: number } | undefined;
  hifiConfig?: { source: string; input: string; downloadAssets: boolean } | undefined;
  tokenSaved?: boolean;
}) {
  const {
    stages,
    nextStep,
    reviewPending,
    constitutionRules,
    preprocessFiles,
    preprocessSelected,
    clarifyRounds,
    prototype,
    hifi,
    hifiConfig,
    tokenSaved,
  } = props;
  // 面板内联确认：待确认的阶段 id（同一时刻至多一个；确认卡展示于对应行下方）
  const [pendingConfirm, setPendingConfirm] = useState<StageId | undefined>(undefined);
  const constitutionStage = stages.find((s) => s.id === 'constitution');
  const showConstitutionGuide =
    constitutionStage !== undefined && constitutionStage.state !== 'completed';
  return (
    <div>
      {showConstitutionGuide && constitutionRules !== undefined ? (
        <ConstitutionBanner rules={constitutionRules} />
      ) : null}
      {preprocessFiles !== undefined && preprocessSelected !== undefined ? (
        <PreprocessCard files={preprocessFiles} selected={preprocessSelected} />
      ) : null}
      <PrototypeCard
        prototype={prototype}
        specReady={stages.find((s) => s.id === 'specify')?.state === 'completed'}
      />
      <HiFiPrototypeCard
        hifi={hifi}
        config={hifiConfig}
        tokenSaved={tokenSaved}
        planReady={stages.find((s) => s.id === 'plan')?.state === 'completed'}
      />
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
          const confirmMessage = canDispatch ? confirmMessageFor(stage, constitutionRules) : null;
          const confirming = canDispatch && pendingConfirm === stage.id;
          // 澄清多轮：specify 完成后澄清可随时再发起，不受"已完成"状态机限制
          // （AI 可能把澄清问题写在聊天里而未写标记进 spec，状态判定会误显示"已完成"）
          const reclarifyAvailable =
            stage.id === 'clarify' &&
            !canDispatch &&
            stages.find((s) => s.id === 'specify')?.state === 'completed';
          const roundLabel =
            (clarifyRounds ?? 0) > 0 ? `（第 ${(clarifyRounds ?? 0) + 1} 轮）` : '';
          return (
            <li
              key={stage.id}
              className={`spk-step${isCurrent ? ' current' : ''}`}
              style={confirming ? { flexWrap: 'wrap' } : undefined}
            >
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
              {stage.id === 'specify' && preprocessSelected !== undefined ? (
                <span className={`spk-chip${preprocessSelected.length > 0 ? '' : ' warn'}`}>
                  {preprocessSelected.length > 0
                    ? `规范输入 ${preprocessSelected.length} 项`
                    : '规范输入未选（必选）'}
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
                confirming ? (
                  <span className="spk-row" style={{ margin: 0 }}>
                    <button
                      className="spk-btn primary"
                      onClick={() => {
                        setPendingConfirm(undefined);
                        postToHost({ type: 'dispatchStage', stageId: stage.id });
                      }}
                    >
                      确认运行 {stage.commandToken}
                    </button>
                    <button className="spk-btn secondary" onClick={() => setPendingConfirm(undefined)}>
                      取消
                    </button>
                  </span>
                ) : (
                  <button
                    className="spk-btn primary"
                    onClick={() => {
                      if (confirmMessage) {
                        setPendingConfirm(stage.id); // 需确认 → 展示内联确认卡
                        return;
                      }
                      postToHost({ type: 'dispatchStage', stageId: stage.id });
                    }}
                    title={`触发 ${stage.commandToken}`}
                  >
                    下一步：运行 {stage.commandToken}
                  </button>
                )
              ) : null}
              {reclarifyAvailable ? (
                <button
                  className="spk-btn secondary"
                  onClick={() => postToHost({ type: 'dispatchStage', stageId: 'clarify' })}
                  title={`随时可再发起一轮澄清，不受状态判定限制；触发 ${stage.commandToken}`}
                >
                  继续澄清{roundLabel}
                </button>
              ) : null}
              {confirming && confirmMessage ? (
                <div style={{ flexBasis: '100%' }}>
                  <div className="spk-confirm" style={{ marginTop: 6, whiteSpace: 'pre-line' }}>
                    {confirmMessage}
                  </div>
                </div>
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