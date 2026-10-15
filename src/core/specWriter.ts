// T048: 澄清答案写回（contracts/artifacts.md §2 写回工件）
// - 单次事务替换（WorkspaceEdit）；未打开则以不可见编辑器打开
// - 写回前 mtime 校验由调用方（panel）负责；本模块只负责精确替换与保存
// - buildReplacement（纯函数）定义于 src/core/clarify.ts
import * as vscode from 'vscode';

/**
 * 将 spec 文档中第一个出现的 markerText 原地替换为 replacement（单次事务）。
 * 抛错时由调用方映射为 write-back-failed。
 */
export async function writeBackMarker(
  specUri: vscode.Uri,
  markerText: string,
  replacement: string,
): Promise<void> {
  const doc = await vscode.workspace.openTextDocument(specUri);
  const text = doc.getText();
  const idx = text.indexOf(markerText);
  if (idx < 0) {
    throw new Error(`标记未找到（可能已被替换）：${markerText.slice(0, 60)}`);
  }
  const startPos = doc.positionAt(idx);
  const endPos = doc.positionAt(idx + markerText.length);

  const edit = new vscode.WorkspaceEdit();
  edit.replace(specUri, new vscode.Range(startPos, endPos), replacement);
  const applied = await vscode.workspace.applyEdit(edit);
  if (!applied) {
    throw new Error('编辑应用失败');
  }
  // 若文档此前未被打开（不可见编辑器），保存以落盘
  if (doc.isDirty) {
    await doc.save();
  }
}