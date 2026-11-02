// 逆向范围与提示词：每个选定目录只生成一份 spec，不按模块拆分
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import {
  buildReversePromptSuffix,
  normalizeReverseTarget,
  parseReverseTargetInput,
  toWorkspaceRelativeDir,
} from '../../src/core/reverse';

const temps: string[] = [];

function makeRepo(): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-reverse-'));
  temps.push(root);
  fs.mkdirSync(path.join(root, 'src', 'pkg'), { recursive: true });
  fs.writeFileSync(path.join(root, 'src', 'pkg', 'main.ts'), 'export const n = 1;\n');
  return root;
}

afterEach(() => {
  for (const dir of temps.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

describe('逆向范围（一个目录一份 spec）', () => {
  it('工作区模式忽略路径', () => {
    const root = makeRepo();
    expect(parseReverseTargetInput(root, 'workspace', 'src/pkg')).toEqual({
      ok: true,
      target: { mode: 'workspace', path: '' },
    });
  });

  it('指定目录解析为工作区相对路径', () => {
    const root = makeRepo();
    const parsed = parseReverseTargetInput(root, 'directory', 'src/pkg');
    expect(parsed).toEqual({ ok: true, target: { mode: 'directory', path: 'src/pkg' } });
    expect(toWorkspaceRelativeDir(root, path.join(root, 'src', 'pkg'))).toBe('src/pkg');
    expect(toWorkspaceRelativeDir(root, root)).toBe('');
  });

  it('拒绝工作区外、路径穿越和不存在的目录', () => {
    const root = makeRepo();
    expect(parseReverseTargetInput(root, 'directory', '../outside').ok).toBe(false);
    expect(parseReverseTargetInput(root, 'directory', path.join(root, 'src')).ok).toBe(false);
    expect(parseReverseTargetInput(root, 'directory', 'missing/dir').ok).toBe(false);
    const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-outside-'));
    temps.push(outside);
    expect(toWorkspaceRelativeDir(root, outside)).toBeUndefined();
  });

  it('已消失的指定目录回退到工作区根', () => {
    const root = makeRepo();
    expect(normalizeReverseTarget(root, { mode: 'directory', path: 'src/gone' })).toEqual({
      mode: 'workspace',
      path: '',
    });
    expect(normalizeReverseTarget(root, { mode: 'directory', path: 'src/pkg' })).toEqual({
      mode: 'directory',
      path: 'src/pkg',
    });
  });

  it('提示词要求所选目录只一份 spec，禁止按模块拆分和根索引规格', () => {
    const workspace = buildReversePromptSuffix({ mode: 'workspace', path: '' });
    expect(workspace).toContain('当前工作区根目录');
    expect(workspace).toContain('只生成一份 spec.md');
    expect(workspace).toContain('禁止按模块、包或子目录拆成多份 spec');
    expect(workspace).toContain('禁止 root index spec 再加每模块一份 spec');
    expect(workspace).toContain('跨模块依赖若在代码中可见，记在这一份 spec 内即可');
    expect(workspace).toContain('.specify/memory/constitution.md');
    expect(workspace).not.toMatch(/请为每个模块/);

    const picked = buildReversePromptSuffix({ mode: 'directory', path: 'src/pkg' });
    expect(picked).toContain('选定目录「src/pkg」');
    expect(picked).toContain('只覆盖这个目录');
    expect(picked).toContain('只生成一份 spec.md');
  });
});
