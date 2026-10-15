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
  if (cmd === 'init' || cmd === 'integration') {
    const integration = cmd === 'init' ? findArg('--integration') : args[2];
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
  if (cmd === 'check') {
    await emit('[fake-specify] all tools ok');
    process.exit(exitCode);
  }
  await emit(`[fake-specify] unknown command: ${cmd ?? ''}`);
  process.exit(2);
}

main().catch((e) => {
  console.error(e);
  process.exit(3);
});