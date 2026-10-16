// 预处理：输出列表、技能安装、规范输入后缀、选择归一化
import { afterAll, describe, expect, it } from 'vitest';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import {
  buildSpecifyInputSuffix,
  installPreprocessSkill,
  listPreprocessOutputs,
  normalizeSelection,
  PREPROCESS_DIR,
  preprocessDir,
  SKILL_TARGET_DIR,
} from '../../src/core/preprocess';

const tempRoots: string[] = [];

function makeRoot(): string {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-preprocess-'));
  tempRoots.push(tmp);
  return tmp;
}

afterAll(() => {
  for (const dir of tempRoots) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

describe('listPreprocessOutputs', () => {
  it('目录缺失 → 空', () => {
    expect(listPreprocessOutputs(makeRoot())).toEqual([]);
  });

  it('递归收集 md、排除 _/隐藏/非 md、workspace 相对 posix 路径、字典序', () => {
    const root = makeRoot();
    const dir = preprocessDir(root);
    fs.mkdirSync(path.join(dir, 'doc-a', 'sub'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'doc-a', 'final.md'), 'x');
    fs.writeFileSync(path.join(dir, 'doc-a', 'sub', 'note.md'), 'x');
    fs.writeFileSync(path.join(dir, '_pipeline-state.json'), '{}');
    fs.writeFileSync(path.join(dir, 'raw.txt'), 'x');
    fs.writeFileSync(path.join(dir, '.hidden.md'), 'x');
    fs.mkdirSync(path.join(dir, 'doc-b'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'doc-b', 'FINAL.MD'), 'x');
    expect(listPreprocessOutputs(root)).toEqual([
      `${PREPROCESS_DIR}/doc-a/final.md`,
      `${PREPROCESS_DIR}/doc-a/sub/note.md`,
      `${PREPROCESS_DIR}/doc-b/FINAL.MD`,
    ]);
  });
});

describe('技能安装', () => {
  function makeBundled(): string {
    const bundled = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-skill-src-'));
    tempRoots.push(bundled);
    fs.writeFileSync(path.join(bundled, 'SKILL.md'), 'skill');
    fs.writeFileSync(path.join(bundled, 'bundle-manifest.json'), '{"version": "2.0.0"}');
    fs.mkdirSync(path.join(bundled, 'engines', '__pycache__'), { recursive: true });
    fs.writeFileSync(path.join(bundled, 'engines', 'x.py'), 'x');
    fs.writeFileSync(path.join(bundled, 'engines', '__pycache__', 'x.pyc'), 'x');
    fs.writeFileSync(path.join(bundled, 'y.bak'), 'x');
    return bundled;
  }

  it('未安装 → 从内置包复制到 .cursor/skills/markfiledown-0509', () => {
    const root = makeRoot();
    const bundled = makeBundled();

    expect(installPreprocessSkill(root, bundled)).toBe('installed');
    const target = path.join(root, SKILL_TARGET_DIR);
    expect(fs.readFileSync(path.join(target, 'SKILL.md'), 'utf-8')).toBe('skill');
    expect(fs.existsSync(path.join(target, 'engines', 'x.py'))).toBe(true);
    expect(fs.existsSync(path.join(target, 'engines', '__pycache__'))).toBe(false);
    expect(fs.existsSync(path.join(target, 'y.bak'))).toBe(false);
    // 同版本再次安装 → already
    expect(installPreprocessSkill(root, bundled)).toBe('already');
  });

  it('已装旧版本 → 覆盖升级（refreshed）', () => {
    const root = makeRoot();
    const bundled = makeBundled();
    const target = path.join(root, SKILL_TARGET_DIR);
    fs.mkdirSync(target, { recursive: true });
    fs.writeFileSync(path.join(target, 'SKILL.md'), 'old');
    fs.writeFileSync(path.join(target, 'bundle-manifest.json'), '{"version": "1.0.0"}');
    expect(installPreprocessSkill(root, bundled)).toBe('refreshed');
    expect(fs.readFileSync(path.join(target, 'SKILL.md'), 'utf-8')).toBe('skill');
    expect(installPreprocessSkill(root, bundled)).toBe('already');
  });

  it('技能目录已存在（.github/skills，用户自装）→ already（不覆盖）', () => {
    const root = makeRoot();
    fs.mkdirSync(path.join(root, '.github', 'skills', 'markfiledown-0509'), { recursive: true });
    const bundled = makeBundled();
    expect(installPreprocessSkill(root, bundled)).toBe('already');
    expect(fs.existsSync(path.join(root, SKILL_TARGET_DIR))).toBe(false);
  });

  it('内置包缺 SKILL.md → failed', () => {
    const root = makeRoot();
    const bundled = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-skill-empty-'));
    tempRoots.push(bundled);
    expect(installPreprocessSkill(root, bundled)).toBe('failed');
  });
});

describe('规范输入后缀与选择归一化', () => {
  it('buildSpecifyInputSuffix：空 → 空串；非空 → 中文提示 + 顿号连接', () => {
    expect(buildSpecifyInputSuffix([])).toBe('');
    const s = buildSpecifyInputSuffix([`${PREPROCESS_DIR}/a/final.md`, `${PREPROCESS_DIR}/b.md`]);
    expect(s).toBe(`（规范输入：${PREPROCESS_DIR}/a/final.md、${PREPROCESS_DIR}/b.md）`);
  });

  it('normalizeSelection：剔除过期/去重，按可用列表顺序', () => {
    const available = ['a.md', 'b.md', 'c.md'];
    expect(normalizeSelection(['c.md', 'a.md', 'gone.md', 'c.md'], available)).toEqual(['a.md', 'c.md']);
    expect(normalizeSelection(undefined, available)).toEqual([]);
  });
});