// v0.6: 项目配置视图——宪法占位 tag 的可视化填表（读/写 .specify/project-config.json）
// 扩展性：内置字段来自宿主字段目录；目录外自定义字段可增/改/删；配置文件 values 为开放 Record
import { useEffect, useMemo, useState } from 'react';
import { postToHost } from '../vscode';
import type { ProjectFieldDef } from '../../../shared/protocol';

export interface ProjectConfigPayload {
  fields: ProjectFieldDef[];
  values: Record<string, string>;
  defaults: Record<string, string>;
  workspaceName: string;
  updatedAt?: string;
}

/** 归一化自定义字段 id：非字母数字 → 下划线，转大写（对齐占位 tag 风格） */
function normalizeCustomId(raw: string): string {
  return raw
    .trim()
    .replace(/[^A-Za-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toUpperCase();
}

interface CustomRow {
  key: number; // 行 key（仅用于 React 渲染稳定）
  id: string; // 编辑中的 id（未归一化）
  value: string;
}

let customRowSeq = 0;

export function ProjectConfigView(props: { config: ProjectConfigPayload; onBack: () => void }) {
  const { config, onBack } = props;

  // —— 内置字段草稿（目录驱动，id 固定）——
  const [draft, setDraft] = useState<Record<string, string>>({});
  // —— 自定义字段行（目录之外的扩展字段）——
  const [customRows, setCustomRows] = useState<CustomRow[]>([]);

  // 宿主回读（保存/打开）后以 updatedAt 感知并重置草稿
  useEffect(() => {
    const next: Record<string, string> = {};
    for (const f of config.fields) {
      next[f.id] = config.values[f.id] ?? '';
    }
    // 配置文件里目录之外的自定义字段 → 转为可编辑行
    const extras = Object.entries(config.values)
      .filter(([id]) => !config.fields.some((f) => f.id === id))
      .map(([id, value]) => ({ key: ++customRowSeq, id, value }));
    setDraft(next);
    setCustomRows(extras);
  }, [config]);

  const filledCount = useMemo(() => {
    const saved = Object.values(config.values).filter((v) => v.trim().length > 0).length;
    return saved;
  }, [config.values]);

  const save = () => {
    const values: Record<string, string> = {};
    for (const [id, v] of Object.entries(draft)) {
      const val = v.trim();
      if (val.length > 0) {
        values[id] = val;
      }
    }
    for (const row of customRows) {
      const id = normalizeCustomId(row.id);
      const val = row.value.trim();
      if (id.length > 0 && val.length > 0) {
        values[id] = val;
      }
    }
    postToHost({ type: 'saveProjectConfig', values });
  };

  return (
    <div className="spk-col">
      <div className="spk-row">
        <button className="spk-btn secondary" onClick={onBack}>
          ← 返回
        </button>
        <strong>项目配置</strong>
        <span className="spk-muted">
          {filledCount > 0 ? `已填 ${filledCount} 项` : '尚未填写'} · 存于 .specify/project-config.json
        </span>
      </div>

      <div className="spk-implication">
        触发「宪法」命令时，已填字段会以 [TAG]=值 的形式附加到提示词，由 AI 填入宪法/规则中的对应占位符；
        留空且带默认规则的字段按规则自动生成。字段可随插件版本扩展，也可在下方添加自定义字段。
      </div>

      {config.fields.map((f) => {
        const def = config.defaults[f.id] ?? '';
        const hasDefault = def.length > 0;
        return (
          <div key={f.id} className="spk-col" style={{ gap: 2 }}>
            <span>
              {f.label}
              {f.required ? <span style={{ color: 'var(--vscode-testing-iconFailed, #f66)' }}> *</span> : null}
              <span className="spk-muted" style={{ marginLeft: 6 }}>
                [{f.id}]
              </span>
            </span>
            <input
              className="spk-input"
              value={draft[f.id] ?? ''}
              placeholder={f.placeholder ?? (hasDefault ? `留空则使用默认：${def}` : '未填写')}
              onChange={(e) => setDraft((prev) => ({ ...prev, [f.id]: e.target.value }))}
            />
            {f.description ? <span className="spk-implication">{f.description}</span> : null}
          </div>
        );
      })}

      {customRows.length > 0 ? (
        <div className="spk-muted">自定义字段（配置文件扩展；[TAG] 形式传给 AI）</div>
      ) : null}
      {customRows.map((row) => (
        <div key={row.key} className="spk-row" style={{ margin: 0 }}>
          <input
            className="spk-input"
            style={{ width: 160, flex: 'none', fontFamily: 'var(--vscode-editor-font-family, monospace)' }}
            placeholder="TAG_ID"
            value={row.id}
            onChange={(e) =>
              setCustomRows((prev) =>
                prev.map((r) => (r.key === row.key ? { ...r, id: e.target.value } : r)),
              )
            }
          />
          <input
            className="spk-input"
            style={{ flex: 1 }}
            placeholder="值"
            value={row.value}
            onChange={(e) =>
              setCustomRows((prev) =>
                prev.map((r) => (r.key === row.key ? { ...r, value: e.target.value } : r)),
              )
            }
          />
          <button
            className="spk-btn secondary"
            style={{ flex: 'none' }}
            title="删除该字段"
            onClick={() => setCustomRows((prev) => prev.filter((r) => r.key !== row.key))}
          >
            ×
          </button>
        </div>
      ))}
      <div>
        <button
          className="spk-btn secondary"
          onClick={() => setCustomRows((prev) => [...prev, { key: ++customRowSeq, id: '', value: '' }])}
        >
          + 添加自定义字段
        </button>
      </div>

      <div className="spk-row">
        <button className="spk-btn primary" onClick={save}>
          保存配置
        </button>
        <span className="spk-muted">保存后触发宪法命令即可生效；随时可改。</span>
      </div>
    </div>
  );
}