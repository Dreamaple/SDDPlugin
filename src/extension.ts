// T017/T028: 激活入口——命令注册、OutputChannel、状态栏、面板 Provider、multi-root 守卫
import * as path from 'node:path';
import * as vscode from 'vscode';
import type { Snapshot } from '../shared/protocol';
import { SpeckitPanelProvider } from './panel/panel';
import { UiStateStore } from './state/store';

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel('Speckit GUI');
  const store = new UiStateStore(context);

  const folders = vscode.workspace.workspaceFolders ?? [];
  const rootUri = folders.length === 1 ? folders[0].uri : undefined;

  // 状态栏项（US1：环境摘要快速可见，SC-002）
  const statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusItem.command = 'speckitGui.openPanel';
  statusItem.text = 'Speckit';
  statusItem.tooltip = 'Spec Kit 可视化面板';
  statusItem.show();

  const provider = new SpeckitPanelProvider({
    rootUri,
    catalogPath: context.asAbsolutePath(path.join('resources', 'tool-catalog.json')),
    store,
    output,
    extensionUri: context.extensionUri,
    onSnapshot: (snapshot: Snapshot) => {
      updateStatusBar(statusItem, snapshot);
    },
  });

  context.subscriptions.push(
    output,
    statusItem,
    vscode.window.registerWebviewViewProvider(SpeckitPanelProvider.viewId, provider, {
      webviewOptions: { retainContextWhenHidden: true },
    }),
    vscode.commands.registerCommand('speckitGui.openPanel', async () => {
      if (rootUri === undefined) {
        void vscode.window.showWarningMessage(
          'Speckit GUI：v1 仅支持单根工作区，请打开单个项目文件夹',
        );
        return;
      }
      await vscode.commands.executeCommand(`${SpeckitPanelProvider.viewId}.focus`);
    }),
    vscode.commands.registerCommand('speckitGui.refresh', () => {
      provider.invalidateCliAndRefresh();
    }),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration('speckitGui.')) {
        provider.invalidateCliAndRefresh();
      }
    }),
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      void vscode.window
        .showInformationMessage('工作区文件夹已变化，建议重新加载窗口以刷新 Speckit 面板', '重新加载')
        .then((choice) => {
          if (choice === '重新加载') {
            void vscode.commands.executeCommand('workbench.action.reloadWindow');
          }
        });
    }),
  );

  if (rootUri === undefined) {
    // multi-root 守卫：提示但不崩溃（面板内也会显示 blocked 态）
    void vscode.window.showWarningMessage(
      'Speckit GUI：v1 仅支持单根工作区，当前打开 ' +
        (folders.length === 0 ? '0' : String(folders.length)) +
        ' 个根目录',
    );
  }
}

function updateStatusBar(item: vscode.StatusBarItem, snapshot: Snapshot): void {
  const env = snapshot.environment;
  if (snapshot.multiRootBlocked) {
    item.text = '$(warning) Speckit: 多根工作区';
    return;
  }
  switch (env.state) {
    case 'missing':
      item.text = '$(circle-slash) Speckit: 未初始化';
      break;
    case 'incomplete':
      item.text = '$(warning) Speckit: 环境不完整';
      break;
    case 'ready': {
      const label = env.isKnownIntegration ? (env.integrationLabel ?? env.integrationId) : '未知/自定义环境';
      item.text = `$(check) Speckit: ${label}`;
      break;
    }
  }
}

export function deactivate(): void {
  // 无需清理：subscription 均已注册到 context
}