// CLI 版本解析测试（parseVersionText；v0.4.0 后升级改为内置源更新，编排测试见 bundle.test.ts）
import { describe, expect, it } from 'vitest';
import { parseVersionText } from '../../src/init/cli';

describe('CLI 版本解析（parseVersionText）', () => {
  it('"specify 0.13.1.dev0" → 0.13.1.dev0', () => {
    expect(parseVersionText('specify 0.13.1.dev0')).toBe('0.13.1.dev0');
  });
  it('"specify v1.2.3" → 1.2.3（v 前缀剥离）', () => {
    expect(parseVersionText('specify v1.2.3')).toBe('1.2.3');
  });
  it('多行输出取首个匹配（含 "version" 字样）', () => {
    expect(parseVersionText('banner...\nspecify version 1.0.0\nmore')).toBe('1.0.0');
  });
  it('无版本信息 → undefined', () => {
    expect(parseVersionText('nothing here')).toBeUndefined();
  });
});