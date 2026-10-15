// T024: specify CLI 进程封装（contracts/cli.md 调用契约）
// - spawn 永不使用 shell；UTF-8；逐行 stdout/stderr 回调
// - 取消 → 进程树终止（Windows taskkill /T /F；POSIX 进程组 SIGTERM）
// - 120s 无输出告警（不自动杀进程）
import { spawn, type ChildProcess } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';

export interface CliRunResult {
  /** 进程退出码；被终止时为 null */
  code: number | null;
  /** 是否被取消终止 */
  killed: boolean;
  /** stderr 尾行（错误映射输入） */
  stderrTail: string[];
}

export interface CliRunHandle {
  promise: Promise<CliRunResult>;
  cancel(): void;
}

const NO_OUTPUT_WARN_MS = 120_000;

/**
 * PATH 语义查找 specify 可执行文件（纯函数，可测试）。
 * win32：specify.cmd / specify.exe / specify.bat / specify；posix：specify
 */
export function findSpecifyInPath(pathEnv: string, platform: string): string | undefined {
  const dirs = pathEnv.split(path.delimiter).filter((d) => d.length > 0);
  const exts = platform === 'win32' ? ['.cmd', '.exe', '.bat', ''] : [''];
  for (const dir of dirs) {
    for (const ext of exts) {
      const candidate = path.join(dir, `specify${ext}`);
      try {
        if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
          return candidate;
        }
      } catch {
        // ignore
      }
    }
  }
  return undefined;
}

function killTree(child: ChildProcess): void {
  if (child.pid === undefined) {
    return;
  }
  if (process.platform === 'win32') {
    try {
      spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true });
    } catch {
      child.kill();
    }
  } else {
    try {
      // detached: true → 负 pid 表示进程组
      process.kill(-child.pid, 'SIGTERM');
    } catch {
      child.kill('SIGTERM');
    }
  }
}

/** 从 `specify --version` 输出解析版本号（纯函数，可测试；版本必须以数字开头，跳过 "version"/"v" 字样） */
export function parseVersionText(output: string): string | undefined {
  const m = /specify(?:\s+(?:version|v))?\s+v?([0-9][0-9A-Za-z.\-+]*)/i.exec(output);
  return m ? m[1] : undefined;
}

/**
 * 探测 CLI 是否支持 `specify upgrade` 自升级（旧版 0.x 无此命令）。
 * 运行 `specify upgrade --help`：exit 0 → 支持；否则（如 "No such command"）→ 不支持。
 */
export function detectUpgradeSupportViaRun(
  run: (args: string[], onLine: (line: string, source: 'stdout' | 'stderr') => void) => CliRunHandle,
): Promise<boolean> {
  return new Promise((resolve) => {
    const collected: string[] = [];
    const handle = run(['upgrade', '--help'], (line, source) => {
      if (source === 'stdout' || source === 'stderr') {
        collected.push(line);
      }
    });
    void handle.promise.then((result) => {
      const text = collected.join('\n');
      if (/No such command/i.test(text)) {
        resolve(false);
        return;
      }
      resolve(result.code === 0);
    });
  });
}

/** 运行 specify CLI 子命令；返回可取消句柄（onLine 逐行回调 stdout/stderr） */
export function runSpecify(
  root: string,
  cmd: string,
  args: string[],
  onLine: (line: string, source: 'stdout' | 'stderr') => void,
): CliRunHandle {
  // Windows：.cmd/.bat 无法被无 shell 的 spawn 直接执行（Node EINVAL 安全策略），
  // 以 cmd.exe /d /s /c + windowsVerbatimArguments 执行手工引号化的命令行——
  // 参数均来自本项目常量与经工具目录校验的 id（无空格、无注入面）。
  let file = cmd;
  let argv = args;
  if (process.platform === 'win32' && /\.(cmd|bat)$/i.test(cmd)) {
    file = process.env.ComSpec ?? 'cmd.exe';
    const commandLine = `"${cmd}" ${args.join(' ')}`;
    argv = ['/d', '/s', '/c', commandLine];
    const child = spawn(file, argv, {
      cwd: root,
      windowsHide: true,
      shell: false,
      windowsVerbatimArguments: true,
      detached: false,
    });
    return wireChild(child, onLine);
  }
  const child = spawn(file, argv, {
    cwd: root,
    windowsHide: true,
    shell: false,
    detached: process.platform !== 'win32',
  });
  return wireChild(child, onLine);
}

function wireChild(
  child: ChildProcess,
  onLine: (line: string, source: 'stdout' | 'stderr') => void,
): CliRunHandle {
  let killed = false;
  let lastOutput = Date.now();
  let warned = false;
  const stderrTail: string[] = [];
  const pushTail = (line: string) => {
    stderrTail.push(line);
    if (stderrTail.length > 10) {
      stderrTail.shift();
    }
  };

  const attach = (stream: NodeJS.ReadableStream | null, source: 'stdout' | 'stderr') => {
    if (!stream) {
      return;
    }
    let buffer = '';
    stream.setEncoding('utf-8');
    stream.on('data', (chunk: string) => {
      lastOutput = Date.now();
      warned = false;
      buffer += chunk;
      const parts = buffer.split(/\r?\n/);
      buffer = parts.pop() ?? '';
      for (const line of parts) {
        if (line.length > 0) {
          onLine(line, source);
          if (source === 'stderr') {
            pushTail(line);
          }
        }
      }
    });
    stream.on('end', () => {
      if (buffer.length > 0) {
        onLine(buffer, source);
        if (source === 'stderr') {
          pushTail(buffer);
        }
      }
    });
  };
  attach(child.stdout, 'stdout');
  attach(child.stderr, 'stderr');

  // 120s 无输出告警（contracts/cli.md §2，不自动杀进程）
  const watchdog = setInterval(() => {
    if (!killed && Date.now() - lastOutput > NO_OUTPUT_WARN_MS && !warned) {
      warned = true;
      onLine('[speckit-gui] CLI 超过 120 秒无输出，仍在等待（可取消）…', 'stderr');
    }
  }, 5_000);

  const promise = new Promise<CliRunResult>((resolve) => {
    child.on('error', (err) => {
      clearInterval(watchdog);
      onLine(`[speckit-gui] 进程错误：${err.message}`, 'stderr');
      pushTail(err.message);
      resolve({ code: null, killed, stderrTail });
    });
    child.on('exit', (code) => {
      clearInterval(watchdog);
      resolve({ code, killed, stderrTail });
    });
  });

  return {
    promise,
    cancel: () => {
      if (!killed) {
        killed = true;
        killTree(child);
      }
    },
  };
}