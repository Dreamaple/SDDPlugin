// 低保真可交互原型（v0.7.7 可选流程；v0.8.4 提示词重写）：基于当前特性的全部需求文档
// （spec + checklist 等，可为多份同模块文档）生成单文件 HTML 应用线框原型，
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
 * v0.8.4 重写要点（针对"生成成了文档展示"的失败模式）：
 *  - 产物形态硬约束：多屏"应用"线框（屏幕切换 + 导航 + 控件占位块），不是文档阅读页
 *  - 显式禁止：整段需求原文贴页面 / 标题+段落复述 spec / 按来源文档分组铺屏
 *  - 多文档合并：多份同模块输入先合并需求（统一术语/清单），屏幕按用户任务组织
 *  - 自检清单：不满足任一条即重做
 */
export function buildPrototypeGenerateToken(docRelPaths: string[], outRelPath: string): string {
  const docs = docRelPaths.length > 0 ? docRelPaths : ['当前特性 spec.md'];
  const n = { i: 0 };
  const step = (text: string): string => `${++n.i}. ${text}`;
  return [
    '低保真可交互原型生成：请生成一份可点击浏览的 HTML 应用线框原型。它是一个"应用"，不是文档——先读全部输入文档，再按以下步骤执行：',
    step(
      `需求合并：输入文档为同一模块的多份资料（${docs.join('、')}）。先做需求合并——统一术语与实体命名、合并页面/任务/数据清单、两份文档表述冲突处标 [TBD]；后续所有屏幕以合并后的需求为准，绝不按"来源文档 A 一组屏、文档 B 一组屏"分块；`,
    ),
    step(
      '屏幕清单：以"用户任务"为单位列出屏幕（如 浏览列表 → 查看详情 → 新建/编辑 → 确认/审批），每屏标注对应需求编号（FR-xxx / US-x）；',
    ),
    step(
      '应用骨架：单屏应用结构——顶部/侧边导航 + 内容区，屏幕间用原生 JS 切换（如 data-screen 显隐路由）；首屏是应用主界面；',
    ),
    step(
      '线框表达：每屏用 UI 容器与控件的占位块表达信息架构——列表/表格/卡片/表单/按钮/标签页/弹层/抽屉；控件文字用 2-6 字短标签（如「提交」「详情」）；灰阶线框风格，无配色无图片；',
    ),
    '【禁止——违反任何一条即返工】把需求或规格原文整段贴进页面（控件标签之外的成段文字都是错误）；用"标题+段落"复述 spec 的文档阅读式排版；把输入文档的章节目录当作屏幕清单照搬；',
    step(
      '交互硬指标：屏间跳转 ≥ 2 条可点击；至少 1 个标签页切换 + 1 个弹层/抽屉；表单控件可输入（本地 mock，无后端）；',
    ),
    step(
      `自检（生成后逐条核对，任一不满足则重做）：① 页面中最长连续文本不超过控件标签长度（无整段需求原文）；② 屏幕数 ≥ 2 且均可点击切换；③ 屏幕按用户任务组织、与来源文档分组无关；④ 灰阶线框风格；`,
    ),
    step(
      `输出：单个自包含 HTML 文件（内联 CSS/JS，零网络依赖），保存到 ${outRelPath}；输入文档中未定义的细节一律 [TBD] 占位，不要自行发明需求；`,
    ),
    step('完成后不要修改输入文档（含 spec）的任何内容。'),
  ].join('\n');
}