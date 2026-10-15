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