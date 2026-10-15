// T047: 澄清解析与写回（纯函数部分）测试
import { describe, expect, it } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { hasOpenClarifications, parseClarifications, buildReplacement } from '../../src/core/clarify';
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