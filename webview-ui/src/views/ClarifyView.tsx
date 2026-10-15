// T049: 澄清问题卡片视图（US4：上下文/问题/建议选项/自定义答案 → 写回）
import { useState } from 'react';
import type { ClarificationItem } from '../../../shared/protocol';

function ClarifyCard(props: { item: ClarificationItem; onAnswer: (id: string, answer: string) => void }) {
  const { item, onAnswer } = props;
  const [selected, setSelected] = useState<string | undefined>(undefined);
  const [custom, setCustom] = useState('');

  if (item.status === 'unparseable') {
    return (
      <div className="spk-card">
        <div>
          <strong>⚠ 无法解析的待澄清标记</strong>
        </div>
        <div className="spk-context" style={{ marginTop: 6 }}>
          {item.question}
        </div>
        <div className="spk-implication" style={{ marginTop: 4 }}>
          标记格式异常（未闭合或问题为空）。请手工修正 spec 文档；本项不阻塞工作流。
        </div>
      </div>
    );
  }

  const answer = custom.trim().length > 0 ? custom.trim() : selected;
  const submit = () => {
    if (answer) {
      onAnswer(item.id, answer);
    }
  };

  return (
    <div className="spk-card">
      <div>
        <strong>❓ {item.question}</strong>
      </div>
      {item.context ? (
        <div className="spk-context" style={{ marginTop: 6 }}>
          {item.context}
        </div>
      ) : null}
      {item.options && item.options.length > 0 ? (
        <div className="spk-col" style={{ marginTop: 8 }}>
          {item.options.map((opt) => (
            <label
              key={opt.label}
              className={`spk-option${selected === opt.label ? ' selected' : ''}`}
            >
              <input
                type="radio"
                name={`clarify-${item.id}`}
                checked={selected === opt.label}
                onChange={() => {
                  setSelected(opt.label);
                  setCustom('');
                }}
              />
              <span>
                <strong>{opt.label}</strong>
                {opt.implication ? <div className="spk-implication">{opt.implication}</div> : null}
              </span>
            </label>
          ))}
        </div>
      ) : null}
      <div style={{ marginTop: 8 }}>
        <input
          className="spk-input"
          placeholder="或输入自定义答案（将替换文档中的标记）"
          value={custom}
          onChange={(e) => {
            setCustom(e.target.value);
            setSelected(undefined);
          }}
        />
      </div>
      <div className="spk-row" style={{ marginTop: 8 }}>
        <button className="spk-btn primary" disabled={!answer} onClick={submit}>
          提交答案并写回 spec
        </button>
      </div>
    </div>
  );
}

export function ClarifyView(props: {
  items: ClarificationItem[];
  onAnswer: (id: string, answer: string) => void;
}) {
  const { items, onAnswer } = props;
  if (items.length === 0) {
    return (
      <div className="spk-banner info">
        <strong>✅ 无待澄清项</strong>
        <div className="spk-implication" style={{ marginTop: 4 }}>
          当前特性 spec 无 [NEEDS CLARIFICATION] 标记，可进入下一阶段。
        </div>
      </div>
    );
  }
  const open = items.filter((i) => i.status === 'open');
  const unparseable = items.filter((i) => i.status === 'unparseable');
  return (
    <div>
      {open.map((item) => (
        <ClarifyCard key={item.id} item={item} onAnswer={onAnswer} />
      ))}
      {unparseable.map((item) => (
        <ClarifyCard key={item.id} item={item} onAnswer={onAnswer} />
      ))}
    </div>
  );
}