// v0.3.1 能力探测测试：parseInitCapabilities / checkCapabilities / buildInitArgs(caps)
import { describe, expect, it } from 'vitest';
import {
  buildInitArgs,
  checkCapabilities,
} from '../../src/init/initRunner';
import { FULL_INIT_CAPS, parseInitCapabilities } from '../../src/init/cli';
import type { InitOptions } from '../../shared/protocol';

// 1.2.x 全能力 help 样例（含全部旗标）
const HELP_FULL = `
Usage: specify init [OPTIONS] [PROJECT_NAME]
│ --script TEXT
│ --force          Force merge/overwrite when using --here
│ --non-interactive  Never prompt
│ --preset TEXT
│ --extension TEXT
│ --integration TEXT
│ --integration-options TEXT
│ --ignore-agent-tools
│ --allow-symlinks
│ --trust-extension-urls
│ --trust-integration
`;

// 0.13.1.dev0 实测 help 样例（无 --non-interactive/--extension/--allow-symlinks/--trust-*）
const HELP_013 = `
Usage: specify init [OPTIONS] [PROJECT_NAME]
│ --script                     TEXT  Script type to use: sh or ps
│ --ignore-agent-tools               Skip checks for coding agent tools like
│ --here                             Initialize project in the current
│ --force                            Force merge/overwrite when using --here
│ --preset                     TEXT  Install a preset during initialization
│ --integration                TEXT  AI coding agent integration to use
│ --integration-options        TEXT  Options for the integration
│ --help                             Show this message and exit.
`;

const base: InitOptions = {
  integrationId: 'claude',
  script: 'ps',
  force: true,
};

describe('parseInitCapabilities', () => {
  it('1.2.x 全能力 help → 全部 true', () => {
    const caps = parseInitCapabilities(HELP_FULL);
    expect(caps).toEqual({
      force: true,
      nonInteractive: true,
      preset: true,
      extension: true,
      integrationOptions: true,
      ignoreAgentTools: true,
      allowSymlinks: true,
      trustExtensionUrls: true,
      trustIntegration: true,
    });
  });

  it('0.13.1 实测 help → nonInteractive/extension/allowSymlinks/trust-* 为 false', () => {
    const caps = parseInitCapabilities(HELP_013);
    expect(caps.force).toBe(true);
    expect(caps.preset).toBe(true);
    expect(caps.integrationOptions).toBe(true);
    expect(caps.ignoreAgentTools).toBe(true);
    expect(caps.nonInteractive).toBe(false);
    expect(caps.extension).toBe(false);
    expect(caps.allowSymlinks).toBe(false);
    expect(caps.trustExtensionUrls).toBe(false);
    expect(caps.trustIntegration).toBe(false);
  });
});

describe('buildInitArgs（能力感知）', () => {
  it('0.13 能力下：不输出 --non-interactive（修复用户实测报错 No such option）', () => {
    const caps = parseInitCapabilities(HELP_013);
    const args = buildInitArgs(base, caps);
    expect(args).toEqual([
      'init',
      '--here',
      '--integration',
      'claude',
      '--script',
      'ps',
      '--force',
    ]);
    expect(args).not.toContain('--non-interactive');
  });

  it('0.13 能力下：支持的 preset 正常输出，未请求的旗标不出现', () => {
    const caps = parseInitCapabilities(HELP_013);
    const args = buildInitArgs({ ...base, preset: 'lean' }, caps);
    expect(args).toContain('--preset=lean');
    expect(args).not.toContain('--non-interactive');
  });

  it('全能力下：行为与之前一致（--non-interactive 在列）', () => {
    const args = buildInitArgs(base, FULL_INIT_CAPS);
    expect(args).toContain('--non-interactive');
  });
});

describe('checkCapabilities（请求超出能力 → 升级指引输入）', () => {
  it('0.13 能力 + 请求 extensions → "--extension"', () => {
    const caps = parseInitCapabilities(HELP_013);
    expect(checkCapabilities({ ...base, extensions: ['git'] }, caps)).toBe('--extension');
  });

  it('0.13 能力 + 请求 preset → undefined（支持）', () => {
    const caps = parseInitCapabilities(HELP_013);
    expect(checkCapabilities({ ...base, preset: 'lean' }, caps)).toBeUndefined();
  });

  it('全能力 + 请求全部 → undefined', () => {
    expect(
      checkCapabilities(
        {
          ...base,
          preset: 'lean',
          extensions: ['git'],
          integrationOptions: '--skills',
          ignoreAgentTools: true,
          allowSymlinks: true,
          trustExtensionUrls: true,
          trustIntegration: true,
        },
        FULL_INIT_CAPS,
      ),
    ).toBeUndefined();
  });

  it('能力值缺省（未提供 caps）→ 默认全能力', () => {
    expect(buildInitArgs(base)).toContain('--non-interactive');
    expect(checkCapabilities({ ...base, extensions: ['git'] }, FULL_INIT_CAPS)).toBeUndefined();
  });
});