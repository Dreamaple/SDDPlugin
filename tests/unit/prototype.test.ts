// 低保真可交互原型：路径解析、mtime 探测、生成指令要素
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

describe('buildPrototypeGenerateToken', () => {
  it('指令包含：单文件自包含、输入输出路径、灰阶线框、可点击跳转、需求编号、[TBD] 占位、禁改 spec', () => {
    const token = buildPrototypeGenerateToken('specs/001-demo/spec.md', 'specs/001-demo/prototype.html');
    expect(token).toContain('单个自包含 HTML 文件');
    expect(token).toContain('specs/001-demo/prototype.html');
    expect(token).toContain('specs/001-demo/spec.md');
    expect(token).toContain('灰阶线框');
    expect(token).toContain('可点击跳转');
    expect(token).toContain('FR-001');
    expect(token).toContain('[TBD]');
    expect(token).toContain('不要自行发明需求');
    expect(token).toContain('不要修改 spec.md 其他内容');
  });
});