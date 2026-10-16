// 公共宪法目录：目录创建/引导文件、规则文件扫描、提示词后缀拼接
import { afterAll, describe, expect, it } from 'vitest';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import {
  buildConstitutionSuffix,
  CONSTITUTION_DIR,
  constitutionDir,
  ensureConstitutionDir,
  listConstitutionRules,
} from '../../src/core/constitutionDir';

const tempRoots: string[] = [];

function makeRoot(): string {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-constitution-'));
  tempRoots.push(tmp);
  return tmp;
}

afterAll(() => {
  for (const dir of tempRoots) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

describe('公共宪法目录', () => {
  it('ensureConstitutionDir 创建目录 + README（幂等，二次调用不报错）', () => {
    const root = makeRoot();
    expect(ensureConstitutionDir(root)).toBe(true);
    const dir = constitutionDir(root);
    expect(fs.existsSync(dir)).toBe(true);
    expect(fs.readFileSync(path.join(dir, 'README.md'), 'utf-8')).toContain('公共宪法');
    expect(ensureConstitutionDir(root)).toBe(false); // 已存在 → 无创建动作
  });

  it('listConstitutionRules：扫描 md/txt、支持子目录、排除 README/_开头/隐藏文件', () => {
    const root = makeRoot();
    const dir = path.join(root, CONSTITUTION_DIR);
    fs.mkdirSync(path.join(dir, 'rules'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'README.md'), 'guide');
    fs.writeFileSync(path.join(dir, '_draft.md'), 'x');
    fs.writeFileSync(path.join(dir, '.hidden.md'), 'x');
    fs.writeFileSync(path.join(dir, 'quality.md'), 'rule');
    fs.writeFileSync(path.join(dir, 'notes.bin'), 'binary'); // 非 md/txt → 不识别
    fs.writeFileSync(path.join(dir, 'rules', 'arch.md'), 'rule');
    expect(listConstitutionRules(root)).toEqual([
      'quality.md',
      'rules/arch.md',
    ]);
  });

  it('目录不存在 → 空规则列表、空后缀', () => {
    const root = makeRoot();
    expect(listConstitutionRules(root)).toEqual([]);
    expect(buildConstitutionSuffix(root)).toBe('');
  });

  it('buildConstitutionSuffix：有规则 → 中文提示 + 工作区相对路径', () => {
    const root = makeRoot();
    const dir = path.join(root, CONSTITUTION_DIR);
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'a.md'), 'x');
    fs.writeFileSync(path.join(dir, 'b.txt'), 'x');
    const suffix = buildConstitutionSuffix(root);
    expect(suffix).toContain('公共规则输入');
    expect(suffix).toContain('a.md');
    expect(suffix).toContain('b.txt');
  });
});