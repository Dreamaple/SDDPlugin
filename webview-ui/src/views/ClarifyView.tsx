// T049: 澄清问题卡片视图（US4：上下文/问题/建议选项/自定义答案 → 由 Agent 整合写回）
// v0.7.6：选择状态上提，新增 全部按推荐选择（二次确认）/ 写回已选中 / 待澄清项导出
import { useState } from 'react';
import type { ClarificationItem } from '../../../shared/protocol';
import { pickRecommendedOption } from '../../../src/core/clarify';

/** 单项选择：选项标签或自定义文本 */
export type ClarifyPick = { kind: 'option'; label: string } | { kind: 'custom'; text: string };

function pickAnswer(pick: ClarifyPick | undefined): string | undefined {
  if (!pick) {
    return undefined;
  }
  if (pick.kind === 'custom') {
    return pick.text.trim().length > 0 ? pick.text.trim() : undefined;
  }
  return pick.label;
}

function ClarifyCard(props: {
  item: ClarificationItem;
  pick: ClarifyPick | undefined;
  onPick: (id: string, pick: ClarifyPick | undefined) => void;
  onSubmit: (id: string, answer: string) => void;
}) {
  const { item, pick, onPick, onSubmit } = props;
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

  const selectedLabel = pick?.kind === 'option' ? pick.label : undefined;
  const customText = pick?.kind === 'custom' ? pick.text : '';
  const answer = pickAnswer(pick);

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
              className={`spk-option${selectedLabel === opt.label ? ' selected' : ''}`}
            >
              <input
                type="radio"
                name={`clarify-${item.id}`}
                checked={selectedLabel === opt.label}
                onChange={() => onPick(item.id, { kind: 'option', label: opt.label })}
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
          placeholder="或输入自定义答案（写回时由 Agent 结合上下文整合进 spec）"
          value={customText}
          onChange={(e) =>
            onPick(item.id, e.target.value.length > 0 ? { kind: 'custom', text: e.target.value } : undefined)
          }
        />
      </div>
      <div className="spk-row" style={{ marginTop: 8 }}>
        <button
          className="spk-btn primary"
          disabled={!answer}
          onClick={() => {
            if (answer) {
              onSubmit(item.id, answer);
            }
          }}
          title="答案将派发给 Agent，由其结合上下文与选项影响说明整合进 spec 对应章节"
        >
          提交答案（Agent 整合写回）
        </button>
      </div>
    </div>
  );
}

export function ClarifyView(props: {
  items: ClarificationItem[];
  onAnswer: (id: string, answer: string) => void;
  onWriteBack: (answers: Array<{ id: string; answer: string }>) => void;
  onExport: () => void;
}) {
  const { items, onAnswer, onWriteBack, onExport } = props;
  // 选择状态上提：批量推荐选择/批量写回需要跨卡片汇总
  const [answers, setAnswers] = useState<Record<string, ClarifyPick>>({});
  const [confirmingRecommended, setConfirmingRecommended] = useState(false);

  const open = items.filter((i) => i.status === 'open');
  const unparseable = items.filter((i) => i.status === 'unparseable');

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

  const selectedEntries = open
    .map((item) => ({ item, answer: pickAnswer(answers[item.id]) }))
    .filter((e): e is { item: ClarificationItem; answer: string } => e.answer !== undefined);

  const recommendedPicks = open
    .map((item) => ({ item, label: pickRecommendedOption(item) }))
    .filter((p): p is { item: ClarificationItem; label: string } => p.label !== undefined);
  // 只补未作答的项（不覆盖用户已选/已输入）
  const pendingRecommended = recommendedPicks.filter((p) => !answers[p.item.id]);

  const applyRecommended = () => {
    const next: Record<string, ClarifyPick> = { ...answers };
    for (const p of pendingRecommended) {
      next[p.item.id] = { kind: 'option', label: p.label };
    }
    setAnswers(next);
    setConfirmingRecommended(false);
  };

  return (
    <div>
      {open.length > 0 ? (
        <div className="spk-row" style={{ flexWrap: 'wrap' }}>
          <button
            className="spk-btn secondary"
            disabled={pendingRecommended.length === 0}
            onClick={() => setConfirmingRecommended(true)}
            title="为所有未作答的项勾选推荐选项（显式标注「推荐」的优先，否则取首项）；填写后仍需点「写回已选中」派发给 Agent"
          >
            全部按推荐选择
          </button>
          <button
            className="spk-btn primary"
            disabled={selectedEntries.length === 0}
            onClick={() =>
              onWriteBack(selectedEntries.map((e) => ({ id: e.item.id, answer: e.answer })))
            }
            title={`把 ${selectedEntries.length} 条已选答案一次性派发给 Agent，由其整合进 spec 对应章节`}
          >
            写回已选中（{selectedEntries.length}）
          </button>
          <button className="spk-btn secondary" onClick={onExport} title="导出全部待澄清项为 Markdown 文件">
            待澄清项导出
          </button>
          <span className="spk-muted">
            已选 {selectedEntries.length}/{open.length} · 写回由 Agent 整合（自定义答案会结合上下文具体化）
          </span>
        </div>
      ) : null}

      {confirmingRecommended ? (
        <div className="spk-confirm" style={{ marginBottom: 10 }}>
          <strong>确认按推荐选择以下 {pendingRecommended.length} 项？</strong>
          <div style={{ marginTop: 4 }}>
            {pendingRecommended.map((p) => (
              <div key={p.item.id}>
                · {p.item.question.slice(0, 48)}
                {p.item.question.length > 48 ? '…' : ''} → <strong>{p.label}</strong>
              </div>
            ))}
            {open.length - pendingRecommended.length > 0 ? (
              <div className="spk-implication" style={{ marginTop: 4 }}>
                （其余 {open.length - pendingRecommended.length} 项已作答或无选项表，跳过）
              </div>
            ) : null}
          </div>
          <div className="spk-row" style={{ marginTop: 6 }}>
            <button className="spk-btn primary" onClick={applyRecommended}>
              确认选择
            </button>
            <button className="spk-btn secondary" onClick={() => setConfirmingRecommended(false)}>
              取消
            </button>
          </div>
        </div>
      ) : null}

      {open.map((item) => (
        <ClarifyCard
          key={item.id}
          item={item}
          pick={answers[item.id]}
          onPick={(id, pick) =>
            setAnswers((prev) => {
              const next = { ...prev };
              if (pick === undefined) {
                delete next[id];
              } else {
                next[id] = pick;
              }
              return next;
            })
          }
          onSubmit={onAnswer}
        />
      ))}
      {unparseable.map((item) => (
        <ClarifyCard
          key={item.id}
          item={item}
          pick={undefined}
          onPick={() => undefined}
          onSubmit={onAnswer}
        />
      ))}
    </div>
  );
}