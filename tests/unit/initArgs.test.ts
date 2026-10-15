// 初始化向导高级选项 → specify init 参数构建测试（contracts/cli.md §2）
import { describe, expect, it } from 'vitest';
import { buildInitArgs } from '../../src/init/initRunner';
import type { InitOptions } from '../../shared/protocol';

const base: InitOptions = {
  integrationId: 'claude',
  script: 'ps',
  force: true,
};

describe('buildInitArgs（GUI 高级初始化选项）', () => {
  it('基础选项 → init --here --integration/--script/--force --non-interactive', () => {
    expect(buildInitArgs(base)).toEqual([
      'init',
      '--here',
      '--integration',
      'claude',
      '--script',
      'ps',
      '--force',
      '--non-interactive',
    ]);
  });

  it('force=false 不追加 --force', () => {
    expect(buildInitArgs({ ...base, force: false })).not.toContain('--force');
  });

  it('preset → --preset=<id>（值形式，规避 "-" 开头歧义）', () => {
    expect(buildInitArgs({ ...base, preset: ' lean ' })).toContain('--preset=lean');
  });

  it('extensions → 每项一个 --extension=<name>，过滤空白项', () => {
    const args = buildInitArgs({ ...base, extensions: ['git', ' bug', '  ', 'agent-context'] });
    expect(args.filter((a) => a.startsWith('--extension='))).toEqual([
      '--extension=git',
      '--extension=bug',
      '--extension=agent-context',
    ]);
  });

  it('integrationOptions → 单个 --integration-options=<text> token（含空格不打散）', () => {
    const args = buildInitArgs({ ...base, integrationOptions: ' --commands-dir .myagent/cmds ' });
    expect(args).toContain('--integration-options=--commands-dir .myagent/cmds');
  });

  it('布尔开关：ignoreAgentTools/allowSymlinks/trustExtensionUrls/trustIntegration', () => {
    const args = buildInitArgs({
      ...base,
      ignoreAgentTools: true,
      allowSymlinks: true,
      trustExtensionUrls: true,
      trustIntegration: true,
    });
    expect(args).toEqual(
      expect.arrayContaining([
        '--ignore-agent-tools',
        '--allow-symlinks',
        '--trust-extension-urls',
        '--trust-integration',
      ]),
    );
  });

  it('默认关闭：布尔开关与可选值缺省时不出现', () => {
    const args = buildInitArgs({ ...base });
    expect(args.filter((a) => a.startsWith('--preset') || a.startsWith('--extension'))).toEqual([]);
    expect(args).not.toContain('--ignore-agent-tools');
    expect(args).not.toContain('--allow-symlinks');
    expect(args).not.toContain('--trust-extension-urls');
    expect(args).not.toContain('--trust-integration');
    expect(args).not.toContain('--integration-options');
  });
});