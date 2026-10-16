// 低保真可交互原型：路径解析、mtime 探测、生成指令要素（v0.8.4 提示词重写）
import { describe, expect, it } from 'vitest';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import {
  buildPrototypeGenerateToken,
  PROTOTYPE_FILE,
  prototypeMtime,
  prototypePathFor,
} from '../../src/core/prototype';

describe('prototypePathFor / prototypeMtime', () => {
  it('原型与 spec 同目录、文件名固定', () => {
    const spec = path.join('root', 'specs', '001-demo', 'spec.md');
    expect(prototypePathFor(spec)).toBe(path.join('root', 'specs', '001-demo', PROTOTYPE_FILE));
  });

  it('prototypeMtime：存在 → mtime；缺失 → undefined', () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-proto-'));
    const spec = path.join(tmp, 'spec.md');
    fs.writeFileSync(spec, '# spec');
    expect(prototypeMtime(spec)).toBeUndefined();
    fs.writeFileSync(prototypePathFor(spec), '<html></html>');
    expect(prototypeMtime(spec)).toBeGreaterThan(0);
    fs.rmSync(tmp, { recursive: true, force: true });
  });
});

describe('buildPrototypeGenerateToken（v0.8.4 多文档 + 应用线框硬约束）', () => {
  const out = 'specs/001-demo/prototype.html';

  it('多文档输入：列出全部文档并给出合并指令（同模块统一术语/冲突 [TBD]/按用户任务组织）', () => {
    const token = buildPrototypeGenerateToken(
      ['specs/001-demo/spec.md', 'specs/001-demo/checklists/requirements.md'],
      out,
    );
    expect(token).toContain('specs/001-demo/spec.md');
    expect(token).toContain('specs/001-demo/checklists/requirements.md');
    expect(token).toContain('需求合并');
    expect(token).toContain('统一术语');
    expect(token).toContain('以"用户任务"为单位列出屏幕');
    expect(token).toContain('冲突处标 [TBD]');
  });

  it('产物形态硬约束：应用骨架/线框占位/屏幕切换', () => {
    const token = buildPrototypeGenerateToken(['specs/001-demo/spec.md'], out);
    expect(token).toContain('它是一个"应用"，不是文档');
    expect(token).toContain('原生 JS 切换');
    expect(token).toContain('信息架构');
    expect(token).toContain('灰阶线框');
  });

  it('禁止项：整段原文贴页 / 标题+段落复述 / 按来源文档分块——违反即返工', () => {
    const token = buildPrototypeGenerateToken(['specs/001-demo/spec.md'], out);
    expect(token).toContain('【禁止——违反任何一条即返工】');
    expect(token).toContain('整段贴进页面');
    expect(token).toContain('文档阅读式排版');
    expect(token).toContain('绝不按"来源文档 A 一组屏、文档 B 一组屏"分块');
  });

  it('交互硬指标与自检清单', () => {
    const token = buildPrototypeGenerateToken(['specs/001-demo/spec.md'], out);
    expect(token).toContain('屏间跳转 ≥ 2 条可点击');
    expect(token).toContain('自检（生成后逐条核对，任一不满足则重做）');
    expect(token).toContain('屏幕数 ≥ 2 且均可点击切换');
  });

  it('输出/标注/禁改：单文件自包含、FR/US 角标、[TBD] 禁发明需求、不改输入文档', () => {
    const token = buildPrototypeGenerateToken(['specs/001-demo/spec.md'], out);
    expect(token).toContain(`保存到 ${out}`);
    expect(token).toContain('内联 CSS/JS');
    expect(token).toContain('FR-xxx / US-x');
    expect(token).toContain('[TBD] 占位，不要自行发明需求');
    expect(token).toContain('完成后不要修改输入文档（含 spec）的任何内容');
  });
});