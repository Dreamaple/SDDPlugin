// 测试辅助：vscode 模块轻量桩（供 vitest alias 使用）
// 仅实现本项目用到的 API 面；openTextDocument/applyEdit 以真实文件系统落地，
// 使 specWriter 写回路径可获得真实集成验证。
import * as fs from 'node:fs';

export interface StubPosition {
  offset: number;
  line: number;
  character: number;
}

export interface StubRange {
  start: StubPosition;
  end: StubPosition;
}

const recordedCommands: Array<{ command: string; args: unknown[] }> = [];
const clipboardTexts: string[] = [];

export function getRecordedCommands(): Array<{ command: string; args: unknown[] }> {
  return recordedCommands;
}
export function getClipboardTexts(): string[] {
  return clipboardTexts;
}
export function resetStubs(): void {
  recordedCommands.length = 0;
  clipboardTexts.length = 0;
}

export namespace workspace {
  export const workspaceFolders = [{ uri: { fsPath: process.cwd() }, name: 'root', index: 0 }];

  export function getConfiguration(section: string) {
    void section;
    const values = new Map<string, unknown>();
    const overrides =
      (globalThis as Record<string, unknown>).__SPK_CONFIG as Record<string, unknown> | undefined;
    return {
      get<T>(key: string, fallback: T): T {
        if (overrides && key in overrides) {
          return overrides[key] as T;
        }
        return (values.get(key) as T) ?? fallback;
      },
      update(key: string, value: unknown): void {
        values.set(key, value);
      },
    };
  }

  export function createFileSystemWatcher(): { dispose(): void } {
    return { dispose: () => undefined };
  }

  export function onDidChangeConfiguration(): { dispose(): void } {
    return { dispose: () => undefined };
  }

  export async function openTextDocument(uriLike: { fsPath: string }) {
    const fsPath = uriLike.fsPath;
    const text = fs.readFileSync(fsPath, 'utf-8');
    return {
      uri: { fsPath },
      getText: () => fs.readFileSync(fsPath, 'utf-8'),
      get isDirty(): boolean {
        return fs.readFileSync(fsPath, 'utf-8') !== text;
      },
      positionAt(offset: number): StubPosition {
        const before = text.slice(0, offset);
        const line = (before.match(/\r?\n/g) ?? []).length;
        const lastBreak = Math.max(before.lastIndexOf('\n'), before.lastIndexOf('\r'));
        return { offset, line, character: offset - (lastBreak + 1) };
      },
      save: async () => {
        // 由 applyEdit 落盘；此处幂等
        return true;
      },
    };
  }

  export async function applyEdit(edit: StubWorkspaceEdit): Promise<boolean> {
    for (const op of edit.operations) {
      const current = fs.readFileSync(op.uri.fsPath, 'utf-8');
      const next =
        current.slice(0, op.range.start.offset) +
        op.text +
        current.slice(op.range.end.offset);
      fs.writeFileSync(op.uri.fsPath, next, 'utf-8');
    }
    return true;
  }
}

export class StubWorkspaceEdit {
  readonly operations: Array<{ uri: { fsPath: string }; range: StubRange; text: string }> = [];
  replace(uri: { fsPath: string }, range: StubRange, text: string): void {
    this.operations.push({ uri, range, text });
  }
}
export const WorkspaceEdit = StubWorkspaceEdit;

export class Range {
  constructor(
    public start: StubPosition,
    public end: StubPosition,
  ) {}
}
export type Uri = { fsPath: string; scheme?: string };
export const Uri = {
  file(fsPath: string): Uri {
    return { fsPath, scheme: 'file' };
  },
  joinPath(base: Uri | { fsPath: string }, ...parts: string[]): Uri {
    return { fsPath: require('node:path').join(base.fsPath, ...parts), scheme: 'file' };
  },
};

export namespace window {
  export function createOutputChannel(name: string) {
    void name;
    const lines: string[] = [];
    return {
      appendLine(line: string): void {
        lines.push(line);
      },
      show(): void {
        /* noop */
      },
      dispose(): void {
        /* noop */
      },
      getLines(): string[] {
        return lines;
      },
    };
  }
  export type StatusBarAlignment = number;
  export const StatusBarAlignment = { Left: 1, Right: 2 };
  export function createStatusBarItem() {
    let text = '';
    return {
      get text(): string {
        return text;
      },
      set text(v: string) {
        text = v;
      },
      command: undefined as string | undefined,
      tooltip: undefined as string | undefined,
      show(): void {
        /* noop */
      },
      dispose(): void {
        /* noop */
      },
    };
  }
  export async function showInformationMessage(
    message: string,
    ...items: string[]
  ): Promise<string | undefined> {
    recordedCommands.push({ command: 'showInformationMessage', args: [message, ...items] });
    return items[0];
  }
  export async function showWarningMessage(message: string): Promise<string | undefined> {
    recordedCommands.push({ command: 'showWarningMessage', args: [message] });
    return undefined;
  }
}

export namespace commands {
  export async function executeCommand(command: string, ...args: unknown[]): Promise<void> {
    if (command === 'workbench.action.chat.open' && (args[0] ?? '').toString().trim() === '') {
      throw new Error('chat unavailable in stub');
    }
    recordedCommands.push({ command, args });
  }
}

export namespace env {
  export const clipboard = {
    async writeText(text: string): Promise<void> {
      clipboardTexts.push(text);
    },
  };
}

export type CancellationToken = { isCancellationRequested: boolean };
export class CancellationTokenSource {
  private cancelled = false;
  get token(): CancellationToken {
    const self = this;
    return {
      get isCancellationRequested() {
        return self.cancelled;
      },
    };
  }
  cancel(): void {
    this.cancelled = true;
  }
  dispose(): void {
    /* noop */
  }
}

export type WebviewView = unknown;
export type WebviewViewProvider = unknown;
export const windowShowWarningMessageCompat = window.showWarningMessage;

const vscodeStub = {
  workspace,
  window,
  commands,
  env,
  Uri,
  Range,
  WorkspaceEdit,
  StatusBarAlignment: window.StatusBarAlignment,
};
export default vscodeStub;