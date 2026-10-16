// T014: 澄清标记解析（contracts/artifacts.md §4）——纯函数，可单元测试
// 写回（vscode 依赖）在 src/core/specWriter.ts（T048）
import type { ClarificationItem, ClarificationOption } from '../../shared/protocol';

/** 标记语法：[NEEDS CLARIFICATION: <问题文本>] */
export const CLARIFICATION_PATTERN = /\[NEEDS CLARIFICATION:\s*([^\]]+)\]/g;
/** 未闭合/格式异常探测 */
const STRAY_MARKER = /\[\s*NEEDS CLARIFICATION[^\]]*\]?/g;

/** 在标记后 ≤30 行内寻找 Option/Answer 形态的建议选项表 */
function parseOptionsAfter(lines: string[], startLine: number): ClarificationOption[] | undefined {
  const maxScan = Math.min(lines.length, startLine + 30);
  for (let i = startLine; i < maxScan; i++) {
    const line = lines[i].trim();
    if (line.length === 0) {
      continue;
    }
    // 表头：| Option | Answer | Implications |（Answer/Implications 列可为任意组合）
    if (/^\|\s*Option\s*\|/.test(line) && /Answer|影响|Implication/i.test(line)) {
      const options: ClarificationOption[] = [];
      for (let j = i + 2; j < maxScan; j++) {
        const row = lines[j].trim();
        if (!/^\|/.test(row)) {
          break;
        }
        // 跳过分隔行
        if (/^\|[\s:|-]+\|$/.test(row)) {
          continue;
        }
        const cells = row
          .split('|')
          .slice(1, -1)
          .map((c) => c.trim());
        if (cells.length >= 1 && cells[0].length > 0) {
          options.push({
            label: cells[0],
            implication: cells.slice(1).join('；') || '',
          });
        }
      }
      return options.length > 0 ? options : undefined;
    }
  }
  return undefined;
}

/** 解析 spec 文本中的澄清标记为问题卡片列表 */
export function parseClarifications(content: string, fileId = 'spec.md'): ClarificationItem[] {
  const items: ClarificationItem[] = [];
  const lines = content.split(/\r?\n/);

  // 1. 正常匹配（含空问题 → unparseable）
  const consumed: Array<[number, number]> = [];
  let m: RegExpExecArray | null;
  CLARIFICATION_PATTERN.lastIndex = 0;
  while ((m = CLARIFICATION_PATTERN.exec(content)) !== null) {
    consumed.push([m.index, m.index + m[0].length]);
    const question = m[1].trim();
    const lineIndex = content.slice(0, m.index).split(/\r?\n/).length - 1;
    const contextLines = lines.slice(Math.max(0, lineIndex - 1), lineIndex + 2);
    const context = contextLines
      .map((l) => l.trim())
      .filter((l) => l.length > 0)
      .join('\n')
      .slice(0, 200);

    items.push({
      id: `${fileId}#${items.length + 1}`,
      question,
      context,
      options: parseOptionsAfter(lines, lineIndex + 1),
      status: question.length > 0 ? 'open' : 'unparseable',
      rawMarker: m[0],
    });
  }

  // 2. 探测未闭合/异常标记（[NEEDS CLARIFICATION ... 无 ] 或无冒号问题）
  STRAY_MARKER.lastIndex = 0;
  while ((m = STRAY_MARKER.exec(content)) !== null) {
    const start = m.index;
    const end = start + m[0].length;
    const isConsumed = consumed.some(([s, e]) => start >= s && end <= e);
    if (isConsumed) {
      continue;
    }
    const text = m[0].trim();
    const lineIndex = content.slice(0, start).split(/\r?\n/).length - 1;
    const contextLines = lines.slice(Math.max(0, lineIndex - 1), lineIndex + 2);
    items.push({
      id: `${fileId}#u${items.length + 1}`,
      question: text,
      context: contextLines
        .map((l) => l.trim())
        .join('\n')
        .slice(0, 200),
      status: 'unparseable',
      rawMarker: text,
    });
  }

  return items;
}

/** 当前特性是否仍有未答标记（unparseable 不阻塞 clarify 阶段完成，contracts/artifacts.md §3） */
export function hasOpenClarifications(items: ClarificationItem[]): boolean {
  return items.some((i) => i.status === 'open');
}

/** 构造写回替换文本：answerPrefix + answer（contracts/artifacts.md §2；纯函数） */
export function buildReplacement(answerPrefix: string, answer: string): string {
  return `${answerPrefix}${answer}`;
}

/**
 * 澄清派发协议后缀（v0.7.5）：附加在 /speckit.clarify 令牌后，约束 Agent 的提问方式。
 * 背景：Agent 默认会用交互式提问工具逐条提问，问题不落盘 → 插件「澄清」面板解析不到。
 * 协议要求：一次性输出全部问题（最多 5 个）并以 [NEEDS CLARIFICATION: ...] 标记写入
 * spec.md，附建议选项表（Answer 列留空），由插件面板统一作答并自动写回。
 */
export function buildClarifyProtocolSuffix(): string {
  return (
    '（澄清协议：一次性输出全部澄清问题（最多 5 个），禁止使用交互式提问工具逐条询问；' +
    '每个问题以 [NEEDS CLARIFICATION: 问题文本] 标记写入 spec.md，' +
    '并在标记后紧跟建议选项表：| Option | Answer | Implications |（Answer 列留空）；' +
    '用户将在插件「澄清」面板统一作答，答案会自动写回 spec，无需在聊天中等待逐题确认。）'
  );
}

// ---------- 澄清答案应用（v0.7.6：写回走 Agent） ----------

export interface ClarifyApplyEntry {
  question: string;
  answer: string;
}

/**
 * 构建「澄清答案应用」派发指令（多行，发给 Agent 执行）。
 * 自定义答案可能笼统、选项影响说明较长 → 由 Agent 结合上下文具体化后整合进 spec，
 * 插件不再直接替换标记文本。
 */
export function buildClarifyApplyToken(entries: ClarifyApplyEntry[]): string {
  const lines = [
    '澄清答案应用：请将下列已确认的澄清结论整合进 spec.md。要求：',
    '1. 逐条删除对应的 [NEEDS CLARIFICATION: ...] 标记，把结论改写为该章节的正式描述（需求/决策/约束）；',
    '2. 结论较笼统时，结合该章节上下文与选项 Implications 说明具体化后再落笔，不要原样照抄；',
    '3. 除这些标记区域外不要改动 spec 其他内容；改写完成后无需再次提问。',
    '逐条结论：',
    ...entries.map((e, i) => `${i + 1}. 问题：${e.question}\n   答案：${e.answer}`),
  ];
  return lines.join('\n');
}

/**
 * 挑选推荐选项：显式标注「推荐/Recommended」的优先；否则取第一个选项
 * （speckit 澄清惯例：选项按推荐度排序，首项为基线）。无选项表 → undefined。
 */
export function pickRecommendedOption(item: ClarificationItem): string | undefined {
  if (!item.options || item.options.length === 0) {
    return undefined;
  }
  const marked = item.options.find(
    (o) => /推荐|recommended/i.test(o.label) || /推荐|recommended/i.test(o.implication),
  );
  return marked?.label ?? item.options[0]?.label;
}

/** 导出待澄清项为 Markdown（交给 Agent 或人工评审） */
export function buildClarifyExport(featureName: string, items: ClarificationItem[]): string {
  const lines = [
    `# 待澄清项导出：${featureName}`,
    '',
    `> 导出时间：${new Date().toISOString()} · 共 ${items.length} 条待澄清项`,
    '> 用法：可直接把本文件交给 AI Agent 逐条澄清；或人工评审后把结论写回 spec.md 对应标记处。',
    '',
  ];
  items.forEach((item, i) => {
    lines.push(`## ${i + 1}. ${item.question}`, '');
    lines.push(`- 原始标记：\`${item.rawMarker}\``);
    if (item.context) {
      lines.push(`- 上下文：${item.context.replace(/\n/g, ' / ')}`);
    }
    if (item.options && item.options.length > 0) {
      lines.push('- 建议选项：');
      for (const opt of item.options) {
        lines.push(`  - ${opt.label}：${opt.implication || '（无影响说明）'}`);
      }
    }
    lines.push('');
  });
  return lines.join('\n');
}