// T047: 澄清解析与写回（纯函数部分）测试
import { describe, expect, it } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { hasOpenClarifications, parseClarifications, buildReplacement, buildClarifyProtocolSuffix, buildClarifyApplyToken, buildClarifyExport, pickRecommendedOption } from '../../src/core/clarify';
import type { ClarificationItem } from '../../shared/protocol';
// 写回的 vscode 事务路径（src/core/specWriter.ts）由集成测试覆盖；本文件测试其纯文本构造与替换模拟

const FIX = (...p: string[]) => path.join(process.cwd(), 'tests', 'fixtures', ...p);

describe('T047 parseClarifications', () => {
  it('clarify fixture：2 个 open 标记，#1 含选项表', () => {
    const spec = fs.readFileSync(FIX('clarify', 'specs', '003-clarify', 'spec.md'), 'utf-8');
    const items = parseClarifications(spec);
    expect(items).toHaveLength(2);
    expect(items[0].options?.length).toBe(3);
    expect(hasOpenClarifications(items)).toBe(true);
  });

  it('未闭合标记 → unparseable', () => {
    const items = parseClarifications('some [NEEDS CLARIFICATION: broken marker without close');
    expect(items).toHaveLength(1);
    expect(items[0].status).toBe('unparseable');
  });

  it('空问题 → unparseable', () => {
    const items = parseClarifications('[NEEDS CLARIFICATION: ] 后续');
    expect(items).toHaveLength(1);
    expect(items[0].status).toBe('unparseable');
  });

  it('无冒号问题 → unparseable', () => {
    const items = parseClarifications('前文 [NEEDS CLARIFICATION] 后文');
    expect(items).toHaveLength(1);
    expect(items[0].status).toBe('unparseable');
  });

  it('正常标记无选项 → options undefined', () => {
    const items = parseClarifications('MUST 记录日志 [NEEDS CLARIFICATION: 保留期限未指定]');
    expect(items).toHaveLength(1);
    expect(items[0].status).toBe('open');
    expect(items[0].options).toBeUndefined();
    expect(items[0].rawMarker).toBe('[NEEDS CLARIFICATION: 保留期限未指定]');
  });

  it('全部回答后 → hasOpenClarifications=false', () => {
    // 标记已被替换为答案 → 不再存在 open 标记
    const items = parseClarifications('已完成：**答案**: x');
    expect(hasOpenClarifications(items)).toBe(false);
  });
});

describe('T047 写回纯函数（替换模拟 → 残留 0）', () => {
  it('buildReplacement 生成前缀 + 答案', () => {
    expect(buildReplacement('**答案**: ', 'OAuth2')).toBe('**答案**: OAuth2');
    expect(buildReplacement('', 'SSO')).toBe('SSO');
  });

  it('模拟替换：rawMarker → 替换后重扫，open 残留 0（SC-005）', () => {
    const spec = fs.readFileSync(FIX('clarify', 'specs', '003-clarify', 'spec.md'), 'utf-8');
    let text = spec;
    for (const item of parseClarifications(text)) {
      if (item.status !== 'open') {
        continue;
      }
      text = text.replace(item.rawMarker, buildReplacement('**答案**: ', '模拟答案'));
    }
    const after = parseClarifications(text);
    expect(after.filter((i) => i.status === 'open')).toHaveLength(0);
    expect(hasOpenClarifications(after)).toBe(false);
    expect(text).toContain('**答案**: 模拟答案');
  });
});

describe('buildClarifyProtocolSuffix（澄清派发协议）', () => {
  it('协议包含：一次性全量、禁止交互式提问、标记格式、选项表、面板作答', () => {
    const suffix = buildClarifyProtocolSuffix();
    expect(suffix).toContain('一次性输出全部澄清问题');
    expect(suffix).toContain('最多 5 个');
    expect(suffix).toContain('禁止使用交互式提问工具');
    expect(suffix).toContain('[NEEDS CLARIFICATION: 问题文本]');
    expect(suffix).toContain('| Option | Answer | Implications |');
    expect(suffix).toContain('「澄清」面板');
  });

  it('协议中的标记语法与解析器兼容（写入 spec 后可被解析）', () => {
    const suffix = buildClarifyProtocolSuffix();
    const markerMatch = /\[NEEDS CLARIFICATION: ([^\]]+)\]/.exec(suffix);
    expect(markerMatch).not.toBeNull();
    const items = parseClarifications(`正文\n\n${markerMatch![0]}\n`);
    expect(items).toHaveLength(1);
    expect(items[0].status).toBe('open');
  });
});

describe('pickRecommendedOption / buildClarifyApplyToken / buildClarifyExport（v0.7.6）', () => {
  const baseItem = (overrides: Partial<ClarificationItem>): ClarificationItem => ({
    id: 'spec.md#1',
    question: 'Q?',
    context: 'ctx',
    status: 'open',
    rawMarker: '[NEEDS CLARIFICATION: Q?]',
    ...overrides,
  });

  it('pickRecommendedOption：显式推荐优先，否则首项，无选项表 undefined', () => {
    const options = [
      { label: 'A', implication: '实现简单' },
      { label: 'B', implication: '企业场景推荐' },
      { label: 'C', implication: '接入第三方' },
    ];
    expect(pickRecommendedOption(baseItem({ options }))).toBe('B'); // Implication 含「推荐」
    expect(
      pickRecommendedOption(
        baseItem({ options: [{ label: 'A（推荐）', implication: 'x' }, { label: 'B', implication: 'y' }] }),
      ),
    ).toBe('A（推荐）'); // Label 含「推荐」
    expect(pickRecommendedOption(baseItem({ options }))).toBe('B');
    expect(pickRecommendedOption(baseItem({ options: [{ label: 'A', implication: 'x' }] }))).toBe('A');
    expect(pickRecommendedOption(baseItem({}))).toBeUndefined();
  });

  it('buildClarifyApplyToken：多行指令含删标记/具体化/不改动其他内容/逐条结论', () => {
    const token = buildClarifyApplyToken([
      { question: '认证方式？', answer: 'A（邮箱密码；实现简单）' },
      { question: '保留期限？', answer: '保留 180 天' },
    ]);
    expect(token).toContain('[NEEDS CLARIFICATION: ...] 标记');
    expect(token).toContain('具体化');
    expect(token).toContain('不要改动 spec 其他内容');
    expect(token).toContain('1. 问题：认证方式？');
    expect(token).toContain('答案：A（邮箱密码；实现简单）');
    expect(token).toContain('2. 问题：保留期限？');
    expect(token.split('\n').length).toBeGreaterThan(5);
  });

  it('buildClarifyExport：标题、计数、标记反引号、选项列表', () => {
    const item = baseItem({
      question: '认证方式未指定？',
      options: [
        { label: 'A', implication: '邮箱密码' },
        { label: 'B', implication: 'OAuth2' },
      ],
    });
    const md = buildClarifyExport('003-clarify', [item]);
    expect(md).toContain('# 待澄清项导出：003-clarify');
    expect(md).toContain('共 1 条待澄清项');
    expect(md).toContain('`[NEEDS CLARIFICATION: Q?]`');
    expect(md).toContain('- A：邮箱密码');
    expect(md).toContain('- B：OAuth2');
  });
});