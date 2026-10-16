// 高保真可交互原型（v0.8.0，plan 评审通过后的 UI 落地）：
// 基于全部前置产物（spec/plan/data-model/contracts/constitution）做 1:1 可交互 UI 还原，
// UI 输入支持 本地目录 / 远程（SVN 等）/ MasterGo MCP / Playwright MCP，支持"切图先行"。
// 产物：specs/<dir>/prototype-hifi/（index.html 入口 + 各页面 + assets/ + README 完成度清单）。
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

export type HiFiSource = 'local' | 'svn' | 'mastergo' | 'mastergo-bridge' | 'playwright';

export const HIFI_DIR = 'prototype-hifi';

export const HIFI_SOURCES: Array<{ id: HiFiSource; label: string }> = [
  { id: 'mastergo-bridge', label: 'MasterGo 网页桥（无 MCP）' },
  { id: 'mastergo', label: 'MasterGo MCP/令牌' },
  { id: 'playwright', label: 'Playwright MCP' },
  { id: 'local', label: '本地目录' },
  { id: 'svn', label: '远程（SVN 等）' },
];

/** 高保真原型入口（index.html）绝对路径 */
export function hiFiIndexPathFor(specPath: string): string {
  return path.join(path.dirname(specPath), HIFI_DIR, 'index.html');
}

/** 高保真原型目录的 mtime（未生成 → undefined；以 index.html 为准） */
export function hiFiMtime(specPath: string): number | undefined {
  try {
    return fs.statSync(hiFiIndexPathFor(specPath)).mtimeMs;
  } catch {
    return undefined;
  }
}

/** 认证令牌临时文件（用户级 tmp 目录，固定文件名便于 Agent 读取） */
export const AUTH_TOKEN_FILE = 'speckit-mastergo-token.txt';

/** 把认证令牌写入临时文件并返回路径（令牌经临时文件传递，避免出现在聊天记录中） */
export function writeAuthTokenFile(token: string): string {
  const file = path.join(os.tmpdir(), AUTH_TOKEN_FILE);
  fs.writeFileSync(file, token.trim(), 'utf-8');
  return file;
}

/** 各输入源的取材指引（拼进 Agent 指令） */
const SOURCE_GUIDE: Record<HiFiSource, (input: string) => string> = {
  local: (input) =>
    `本地设计稿目录「${input}」——直接读取其中的设计稿图片与切图，按文件名对应页面；`,
  svn: (input) =>
    `远程设计稿（SVN）「${input}」——用 svn 命令行 checkout/export 该目录到本地临时目录后读取（含全部切图），用完清理临时目录；`,
  mastergo: (input) =>
    `设计稿（MasterGo）「${input}」——取材按优先级自动回退：` +
    `① 若会话已接入 MasterGo MCP：通过 MCP 读取页面结构、样式与图层信息，并通过 MCP 导出/下载切图；` +
    `② 若无 MCP 坐席但提供了认证令牌：直接调用 MasterGo 开放/数据 API 读取页面树、图层与样式（按 API 文档要求携带认证头）；` +
    `③ 两者都不可用时：用 Playwright MCP 登录 MasterGo 网页端并读取其数据 API 响应；` +
    `任一路径都先完成全部切图下载，再用设计数据渲染 1:1 还原为 HTML（结构复杂可临时导入 OpenPencil 核对，最终交付以 HTML 为准）；`,
  playwright: (input) =>
    `在线设计平台「${input}」——用 Playwright MCP 打开该地址并完成登录与页面遍历，按页截图并下载切图资源；`,
  'mastergo-bridge': (input) =>
    `设计稿（MasterGo 网页桥，无 MCP 坐席）「${input}」——通过 MasterGo 页面内插件 API（window.mg）读取设计原始数据（不是截图、不是 DOM 解析），步骤：` +
    `（前置）用 chromium.connectOverCDP 连接一个已登录 MasterGo 的调试 Chrome（以 --remote-debugging-port 启动），继承登录态；无需 MCP 坐席、无需认证令牌；` +
    `（定位）在 mastergo.com 文件页先确认页面上下文中 window.mg 可用（不可用或用户无法加载插件 → 报告阻塞，不得伪造视觉）；按帧名从图层清单定位帧 ID；` +
    `（取数，在页面上下文 page.evaluate 内执行）` +
    `a) mg.getNodeById(id) 递归读类型化属性：位置取 relativeTransform 第三列（m[0][2], m[1][2]），旋转用 atan2(m[1][0], m[0][0]) 反推，宽高/透明度/isMask/clipsContent 直读，填充/描边/效果/文本逐项归一化，数字 round 到 3-4 位；` +
    `b) mg.codegen.getDSL(id) 取结构 DSL（节点树/真实元素判定/样式 token）——该 API 仅研发模式（devMode）可用，不可用时退化为纯 getNodeById 遍历；` +
    `c) mg.codegen.getCode(id) 取代码包 statics 中的内联 SVG（矢量几何）：被渲染为 SVG 的节点吞掉整棵子树（SVG 已含子路径，勿重复创建子节点）；even-odd 路径需重写为 non-zero（如 CanvasKit makeAsWinding）；` +
    `d) mg.getImageByHref(url) 取位图字节（走 MasterGo 自身图片缓存，免额外鉴权；MIME 按魔数判断而非扩展名；大数组按 32KB 分块转 base64 防爆栈）；` +
    `e) node.exportAsync({format:'PNG'}) 仅产出参考图用于对比校验，不参与构建；` +
    `（落盘）抽取产物写入 <out>/_extract/（spec.json / dsl.json / code.json / images/）；` +
    `插件沙箱不能联网/写盘——三件套插件（manifest.json/main.js/ui.html）由本任务生成到 <out>/_extract/plugin/，mg.* 数据经 mg.showUI 的 iframe postMessage 到仅监听 127.0.0.1 的本地桥落盘（本地桥由本任务启动）；` +
    `请提示用户在已登录编辑器中加载该开发者插件（画布右键→插件→开发者模式，或顶栏菜单），数据落盘后继续；` +
    `（渲染）按抽取数据 1:1 还原为 HTML（可先用 OpenPencil 回放核对布局再还原，最终交付以 HTML 为准）；`,
};

export interface HiFiGenerateOptions {
  specRel: string;
  planRel: string;
  outRel: string;
  source: HiFiSource;
  input: string;
  downloadAssets: boolean;
  /** MasterGo 个人认证令牌文件路径（已写入磁盘；Agent 读取该文件取令牌） */
  authTokenFile?: string;
}

/**
 * 高保真 1:1 UI 还原派发指令（发给 Agent 执行）。
 * 关键约束：需求清单先行（验收依据）/ 按源取材 / 切图先行（可选）/ 1:1 不得改视觉 /
 * 全交互（登录用 Playwright MCP）/ UE 全量覆盖 / README 完成度清单 / [TBD] 占位禁发明需求。
 */
export function buildHiFiPrototypeGenerateToken(opts: HiFiGenerateOptions): string {
  let n = 0;
  const step = (text: string): string => `${++n}. ${text}`;
  const lines: string[] = [];
  lines.push('高保真可交互原型（UI 1:1 还原）：先梳理需求清单，再完成还原实现。按以下步骤执行：');
  lines.push(
    step(
      `需求梳理：读取 ${opts.specRel}、${opts.planRel}（含 data-model.md 与 contracts/）以及 .specify/memory/constitution.md，输出全部 UE 需求清单（页面/状态/交互/异常路径）——这是还原完成度的验收依据；`,
    ),
  );
  lines.push(step(`UI 输入：${SOURCE_GUIDE[opts.source](opts.input)}`));
  if (opts.authTokenFile) {
    lines.push(
      step(
        `认证令牌：已写入文件 ${opts.authTokenFile}——需要直接调用 MasterGo 数据 API 时，读取该文件内容作为认证令牌，` +
          '按 API 文档要求的认证头携带（如 X-Auth-Token / Authorization）；令牌内容不得写入交付文件、日志或回复正文；',
      ),
    );
  }
  if (opts.downloadAssets) {
    lines.push(
      step(`切图先行：先把设计稿的全部切图下载到 ${opts.outRel}/assets/，按图层/资源原名建立索引清单，再开始页面还原；`),
    );
  }
  lines.push(step('1:1 还原：布局、间距、配色、字体、图标、切图与设计稿完全一致，不得自行调整视觉或重绘；'));
  lines.push(
    step('可交互：按钮/输入/页面跳转/状态切换/弹层全部可用，数据用本地 mock；涉及登录或在线设计平台时用 Playwright MCP 打通登录与遍历；'),
  );
  lines.push(step('全量覆盖：对照需求清单逐条实现，缺任何一条都视为未完成；'));
  lines.push(
    step(`输出：${opts.outRel}/（index.html 入口 + 各页面 HTML + assets/），浏览器直接打开 index.html 即可完整交互；`),
  );
  lines.push(
    step(
      `完成度清单：在 ${opts.outRel}/README.md 逐条标注 UE 需求实现状态（已完成/部分完成/[TBD]）；设计中未定义的细节一律标 [TBD]，不要发明需求；`,
    ),
  );
  lines.push(step('不要修改 spec.md / plan.md 的任何内容。'));
  return lines.join('\n');
}