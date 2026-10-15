#!/usr/bin/env node
// T008: fake-specify CLI 桩（确定性测试：可控退出码/延迟/输出）
// 用法（经 .cmd/.sh 包装后）：
//   fake-specify init --here --integration claude --script ps --force --non-interactive
//   fake-specify integration install copilot --force
//   fake-specify check
// 环境变量：
//   FAKE_SPECIFY_DELAY      每行输出延迟 ms（默认 0）
//   FAKE_SPECIFY_EXIT       模拟退出码（默认 0）
//   FAKE_SPECIFY_LINES      额外输出的行数（默认 3，用于进度流测试）
//   FAKE_SPECIFY_NO_SETTLE  设为 1 时不写 init-options.json（模拟失败残留）
const args = process.argv.slice(2);
const delay = parseInt(process.env.FAKE_SPECIFY_DELAY || '0', 10);
const exitCode = parseInt(process.env.FAKE_SPECIFY_EXIT || '0', 10);
const lines = parseInt(process.env.FAKE_SPECIFY_LINES || '3', 10);
const settle = process.env.FAKE_SPECIFY_NO_SETTLE !== '1';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function emit(text) {
  if (delay > 0) await sleep(delay);
  process.stdout.write(text + '\n');
}

function findArg(name) {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : undefined;
}

async function main() {
  const cmd = args[0];
  await emit(`[fake-specify] running: ${args.join(' ')}`);
  if (cmd === 'init') {
    if (args.includes('--help')) {
      // 模拟 1.x 全能力 CLI 的 help（供能力探测测试）——立即输出，不受 FAKE_SPECIFY_DELAY 影响
      const usage = [
        '[fake-specify] Usage: specify init [OPTIONS] [PROJECT_NAME]',
        '[fake-specify] --script TEXT  Script type to use: sh or ps',
        '[fake-specify] --force          Force merge/overwrite when using --here',
        '[fake-specify] --non-interactive  Never prompt',
        '[fake-specify] --preset TEXT    Install a preset during initialization',
        '[fake-specify] --extension TEXT Install an extension during initialization',
        '[fake-specify] --integration-options TEXT Options for the integration',
        '[fake-specify] --ignore-agent-tools  Skip checks for coding agent tools',
        '[fake-specify] --allow-symlinks  Persist permission for contained symlinks',
        '[fake-specify] --trust-extension-urls  Pre-authorize external URLs',
        '[fake-specify] --trust-integration  Authorize external integration package',
      ];
      for (const line of usage) {
        process.stdout.write(line + '\n');
      }
      process.exit(0);
    }
    const integration = findArg('--integration');
    const script = findArg('--script') || 'ps';
    for (let i = 1; i <= lines; i++) {
      await emit(`[fake-specify] step ${i}/${lines}: preparing ${integration ?? '?'}`);
    }
    if (exitCode === 0 && settle && integration) {
      const fs = require('fs');
      const path = require('path');
      const specDir = path.join(process.cwd(), '.specify');
      fs.mkdirSync(specDir, { recursive: true });
      fs.writeFileSync(
        path.join(specDir, 'init-options.json'),
        JSON.stringify(
          {
            ai: integration,
            ai_skills: true,
            feature_numbering: 'sequential',
            here: true,
            integration,
            script,
            speckit_version: '1.0.0-fake',
          },
          null,
          2,
        ),
      );
      await emit(`[fake-specify] wrote .specify/init-options.json (ai=${integration})`);
    }
    await emit(`[fake-specify] done`);
    process.exit(exitCode);
  }
  if (cmd === 'integration') {
    // specify integration install <id> [--force]
    const integration = args[2];
    const script = findArg('--script') || 'ps';
    for (let i = 1; i <= lines; i++) {
      await emit(`[fake-specify] install step ${i}/${lines}: installing ${integration ?? '?'}`);
    }
    if (exitCode === 0 && settle && integration) {
      const fs = require('fs');
      const path = require('path');
      const specDir = path.join(process.cwd(), '.specify');
      fs.mkdirSync(specDir, { recursive: true });
      fs.writeFileSync(
        path.join(specDir, 'init-options.json'),
        JSON.stringify(
          {
            ai: integration,
            ai_skills: false,
            feature_numbering: 'sequential',
            here: true,
            integration,
            script,
            speckit_version: '1.0.0-fake',
          },
          null,
          2,
        ),
      );
      await emit(`[fake-specify] wrote .specify/init-options.json (ai=${integration})`);
    }
    await emit(`[fake-specify] done`);
    process.exit(exitCode);
  }
  if (cmd === 'check') {
    await emit('[fake-specify] all tools ok');
    process.exit(exitCode);
  }
  if (cmd === 'upgrade') {
    if (args.includes('--help')) {
      // 模拟 typer help 行为：--help 恒定 exit 0（用于升级支持探测）——立即输出
      process.stdout.write('[fake-specify] usage: specify upgrade [--tag vX.Y.Z]\n');
      process.exit(0);
    }
    for (let i = 1; i <= lines; i++) {
      await emit(`[fake-specify] upgrade step ${i}/${lines}: resolving latest release`);
    }
    if (exitCode === 0) {
      await emit('[fake-specify] Upgraded specify-cli: 0.0.0-fake -> 1.0.0-fake');
    }
    await emit('[fake-specify] done');
    process.exit(exitCode);
  }
  await emit(`[fake-specify] unknown command: ${cmd ?? ''}`);
  process.exit(2);
}

main().catch((e) => {
  console.error(e);
  process.exit(3);
});