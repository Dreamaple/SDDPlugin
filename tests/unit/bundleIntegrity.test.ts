// v0.4.1 回归防护：内置源码副本必须满足 pyproject 全部 force-include 引用
// （漏拷任一目录会让 uvx/hatchling 构建失败：Forced include not found）
import { describe, expect, it } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { parsePyprojectVersion } from '../../src/init/bundle';

const BUNDLE_ROOT = path.join(process.cwd(), 'resources', 'speckit-cli');

function readForceIncludes(pyproject: string): string[] {
  const sectionStart = pyproject.indexOf('[tool.hatch.build.targets.wheel.force-include]');
  if (sectionStart < 0) {
    return [];
  }
  const lines = pyproject.slice(sectionStart).split(/\r?\n/).slice(1);
  const keep: string[] = [];
  for (const line of lines) {
    const t = line.trim();
    if (t.length === 0 || t.startsWith('[')) {
      break; // 到下一个 section / 空行为止
    }
    keep.push(line);
  }
  const sources: string[] = [];
  for (const m of keep.join('\n').matchAll(/"([^"]+)"\s*=/g)) {
    sources.push(m[1]);
  }
  return sources;
}

describe('内置源码副本完整性（resources/speckit-cli）', () => {
  const pyprojectPath = path.join(BUNDLE_ROOT, 'pyproject.toml');

  it('pyproject 存在且可解析版本', () => {
    expect(fs.existsSync(pyprojectPath)).toBe(true);
    expect(parsePyprojectVersion(fs.readFileSync(pyprojectPath, 'utf-8'))).toBeDefined();
  });

  it('全部 force-include 源存在（回归：presets/ 曾漏拷导致 hatchling 构建失败）', () => {
    const sources = readForceIncludes(fs.readFileSync(pyprojectPath, 'utf-8'));
    expect(sources.length).toBeGreaterThan(10); // 模板/命令/脚本×3/扩展×5/工作流×3/预设×2/ bundles…
    for (const rel of sources) {
      const abs = path.join(BUNDLE_ROOT, rel);
      expect({ rel, exists: fs.existsSync(abs) }).toEqual({ rel, exists: true });
    }
  });

  it('打包集（wheel packages）src/specify_cli 存在', () => {
    expect(fs.existsSync(path.join(BUNDLE_ROOT, 'src', 'specify_cli'))).toBe(true);
  });

  it('readme 引用文件存在（hatchling readme）', () => {
    const pyproject = fs.readFileSync(pyprojectPath, 'utf-8');
    const m = /^readme\s*=\s*"([^"]+)"/m.exec(pyproject);
    expect(m).not.toBeNull();
    expect(fs.existsSync(path.join(BUNDLE_ROOT, m![1]))).toBe(true);
  });
});