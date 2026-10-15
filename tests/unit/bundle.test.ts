// v0.4.0 内置源管理纯函数测试：pyproject 版本解析 / 版本比较 / 最新副本解析 / uvx 参数 / zip-slip 防护
import { describe, expect, it } from 'vitest';
import {
  buildUvxArgs,
  compareVersions,
  isSafeZipEntry,
  parsePyprojectVersion,
  resolveNewestBundle,
} from '../../src/init/bundle';
import * as os from 'node:os';
import * as path from 'node:path';

describe('parsePyprojectVersion', () => {
  it('解析 version 字段', () => {
    expect(parsePyprojectVersion('[project]\nname = "specify-cli"\nversion = "1.2.1.dev0"\n')).toBe(
      '1.2.1.dev0',
    );
  });
  it('无 version → undefined', () => {
    expect(parsePyprojectVersion('[project]\nname = "x"\n')).toBeUndefined();
  });
});

describe('compareVersions', () => {
  it('数字逐段比较', () => {
    expect(compareVersions('1.2.1', '1.2.0')).toBeGreaterThan(0);
    expect(compareVersions('1.2.1', '1.10.0')).toBeLessThan(0);
    expect(compareVersions('1.2.1', '1.2.1')).toBe(0);
  });
  it('前缀相同时更长（带后缀段）视为更新', () => {
    expect(compareVersions('1.2.1.dev0', '1.2.1')).toBeGreaterThan(0);
  });
  it('混合段（数字 vs 字符串）字符串比较兜底', () => {
    expect(compareVersions('1.0.0.dev1', '1.0.0.dev0')).toBeGreaterThan(0);
  });
});

describe('resolveNewestBundle', () => {
  it('内置 1.2.1.dev0 vs 已下载 1.3.0 → 选已下载', () => {
    const best = resolveNewestBundle([
      { dir: 'builtin', version: '1.2.1.dev0' },
      { dir: 'downloaded', version: '1.3.0' },
    ]);
    expect(best?.dir).toBe('downloaded');
  });
  it('无候选 → undefined', () => {
    expect(resolveNewestBundle([])).toBeUndefined();
  });
});

describe('buildUvxArgs', () => {
  it('uvx --from <src> specify <args>', () => {
    expect(buildUvxArgs('C:/ext/resources/speckit-cli', ['init', '--here'])).toEqual([
      '--from',
      'C:/ext/resources/speckit-cli',
      'specify',
      'init',
      '--here',
    ]);
  });
});

describe('isSafeZipEntry（zip-slip 防护）', () => {
  const root = path.join(os.tmpdir(), 'spk-zip-root');
  it('正常相对路径 → true', () => {
    expect(isSafeZipEntry('src/specify_cli/x.py', root)).toBe(true);
    expect(isSafeZipEntry('pyproject.toml', root)).toBe(true);
  });
  it('../ 穿越 → false', () => {
    expect(isSafeZipEntry('../evil.py', root)).toBe(false);
    expect(isSafeZipEntry('a/../../evil.py', root)).toBe(false);
  });
  it('绝对路径/盘符 → false', () => {
    expect(isSafeZipEntry('C:\\Windows\\evil.py', root)).toBe(false);
  });
});