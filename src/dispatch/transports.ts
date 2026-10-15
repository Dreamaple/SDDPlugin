// T036: 传输层（contracts/dispatch.md §2）
// - Transport A chat-open：workbench.action.chat.open 预填令牌
// - Transport B clipboard：复制令牌 + 通知（含「打开聊天」重试）
import * as vscode from 'vscode';

export type DispatchTransport = 'chat-open' | 'clipboard';
export type DispatchOutcome = 'dispatched' | 'fallback-clipboard' | 'failed';

async function openChatWithToken(token: string): Promise<void> {
  await vscode.commands.executeCommand('workbench.action.chat.open', `${token} `);
}

/** 发送调用令牌；返回命令回执 outcome（SC-004 的 2s 以令牌送达计） */
export async function dispatchToken(
  token: string,
  transport: DispatchTransport,
): Promise<DispatchOutcome> {
  if (transport === 'chat-open') {
    try {
      await openChatWithToken(token);
      return 'dispatched';
    } catch {
      // fallthrough → clipboard 回退
    }
  }
  try {
    await vscode.env.clipboard.writeText(token);
    const choice = await vscode.window.showInformationMessage(
      `已复制 ${token}，请粘贴到 AI 聊天发送`,
      '打开聊天',
    );
    if (choice === '打开聊天') {
      try {
        await openChatWithToken(token);
      } catch {
        // 打开失败也视为剪贴板回退成功
      }
    }
    return 'fallback-clipboard';
  } catch {
    return 'failed';
  }
}