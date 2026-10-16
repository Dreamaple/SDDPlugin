// 低保真可交互原型（v0.7.7 可选流程）：基于当前 spec 生成单文件 HTML 线框图，
// 供用户在进入方案（plan）前点击走查需求。生成由 Agent 完成，插件负责派发与打开。
import * as fs from 'node:fs';
import * as path from 'node:path';

/** 原型文件名（与 spec 同目录，单文件自包含，浏览器直接打开） */
export const PROTOTYPE_FILE = 'prototype.html';

/** 原型文件绝对路径（spec 同目录） */
export function prototypePathFor(specPath: string): string {
  return path.join(path.dirname(specPath), PROTOTYPE_FILE);
}

/** 原型 mtime（未生成 → undefined） */
export function prototypeMtime(specPath: string): number | undefined {
  try {
    return fs.statSync(prototypePathFor(specPath)).mtimeMs;
  } catch {
    return undefined;
  }
}

/**
 * 原型生成派发指令（发给 Agent 执行）。
 * 关键约束：单文件自包含 / 低保真灰阶 / 可点击跳转 / 标注需求编号 / 未定义细节 [TBD] 占位
 * （禁止 Agent 自行发明需求——原型只用于理解 spec，不是需求来源）。
 */
export function buildPrototypeGenerateToken(specRelPath: string, outRelPath: string): string {
  return [
    '低保真可交互原型生成：请基于当前 spec 生成一份可点击浏览的 HTML 线框图原型。要求：',
    `1. 输出为单个自包含 HTML 文件（内联 CSS/JS，不依赖网络与外部资源），保存到 ${outRelPath}；`,
    `2. 内容依据 ${specRelPath}：覆盖其中的主要页面、入口与核心流程，页面间可点击跳转；`,
    '3. 低保真风格：灰阶线框 + 占位图形（矩形/圆/线条），不做高保真视觉与配色；',
    '4. 交互用原生 JS 即可（视图切换/弹层/Tab），无需真实数据与后端；',
    '5. 每个页面/区块以注释或角标标注对应需求编号（如 FR-001）；spec 未定义的细节用 [TBD] 占位，不要自行发明需求；',
    '6. 完成后不要修改 spec.md 其他内容。',
  ].join('\n');
}