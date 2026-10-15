// T019: 文件监听（contracts/artifacts.md §4 时序与监听范围）
import * as vscode from 'vscode';

export class WorkspaceWatcher {
  private readonly watchers: vscode.FileSystemWatcher[] = [];
  private debounceTimer: NodeJS.Timeout | undefined;
  /** 自写忽略窗口：path → 生效截止时间（ms），避免澄清写回触发回环刷新 */
  private readonly ignoreWindows = new Map<string, number>();
  private readonly disposables: vscode.Disposable[] = [];

  constructor(
    rootUri: vscode.Uri,
    private readonly onChange: () => void,
    private readonly debounceMs = 300,
  ) {
    const relSpecify = new vscode.RelativePattern(rootUri, '.specify/**/*');
    const relSpecs = new vscode.RelativePattern(rootUri, 'specs/**/*');
    for (const pattern of [relSpecify, relSpecs]) {
      const watcher = vscode.workspace.createFileSystemWatcher(pattern);
      const handler = (uri: vscode.Uri) => this.handleEvent(uri);
      watcher.onDidCreate(handler, null, this.disposables);
      watcher.onDidChange(handler, null, this.disposables);
      watcher.onDidDelete(handler, null, this.disposables);
      this.watchers.push(watcher);
    }
  }

  private handleEvent(uri: vscode.Uri): void {
    const until = this.ignoreWindows.get(uri.fsPath);
    if (until !== undefined) {
      if (Date.now() < until) {
        return; // 自写忽略窗口内，跳过（防回环）
      }
      this.ignoreWindows.delete(uri.fsPath);
    }
    this.schedule();
  }

  private schedule(): void {
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
    }
    this.debounceTimer = setTimeout(() => {
      this.debounceTimer = undefined;
      this.onChange();
    }, this.debounceMs);
  }

  /** 写回后调用：1s 内忽略该文件的事件（contracts/artifacts.md §4） */
  setIgnoreWindow(fsPath: string, ms = 1000): void {
    this.ignoreWindows.set(fsPath, Date.now() + ms);
  }

  dispose(): void {
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
    }
    for (const d of this.disposables) {
      d.dispose();
    }
    for (const w of this.watchers) {
      w.dispose();
    }
  }
}