// 公共宪法目录（.specify/constitution）：初始化后自动创建，引导用户放置规则文件；
// 触发 constitution 命令时将规则文件相对路径列表拼接为提示词向下传递。
import * as fs from 'node:fs';
import * as path from 'node:path';

/** 公共宪法目录（工作区相对路径） */
export const CONSTITUTION_DIR = '.specify/constitution';

/** 引导说明文件（不入规则列表、不参与提示词） */
const GUIDE_FILE = 'README.md';

/** 识别为规则文件的扩展名 */
const RULE_EXTENSIONS = new Set(['.md', '.markdown', '.txt']);

const GUIDE_CONTENT = [
  '# 公共宪法（Constitution）目录',
  '',
  '将项目的公共规则、约束与原则放在本目录（一个或多个文件），例如：',
  '',
  '- `engineering.md` —— 工程规范（命名、目录结构、代码风格）',
  '- `quality.md` —— 质量红线（测试覆盖、禁用模式）',
  '- `arch.md` —— 架构决策与边界',
  '',
  '规则：',
  '',
  '- 支持 `.md` / `.markdown` / `.txt` 文件；支持子目录组织',
  '- 本 README 与下划线 `_` 开头的文件不会被当作规则传递',
  '',
  '在面板触发「宪法」阶段（/speckit-constitution）时，插件会自动把这些文件的',
  '路径作为提示词一并传给 AI，AI 会先阅读它们再生成/更新 `.specify/memory/constitution.md`。',
  '',
].join('\n');

/** 公共宪法目录的绝对路径 */
export function constitutionDir(root: string): string {
  return path.join(root, CONSTITUTION_DIR);
}

/**
 * 确保目录与引导文件存在（幂等；初始化成功后由宿主调用）。
 * 返回 true 表示本次发生了创建动作（目录或 README 首次落盘）。
 */
export function ensureConstitutionDir(root: string): boolean {
  const dir = constitutionDir(root);
  const readme = path.join(dir, GUIDE_FILE);
  let changed = false;
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
    changed = true;
  }
  if (!fs.existsSync(readme)) {
    fs.writeFileSync(readme, GUIDE_CONTENT, 'utf-8');
    changed = true;
  }
  return changed;
}

function isRuleFile(name: string): boolean {
  if (name === GUIDE_FILE || name.startsWith('_') || name.startsWith('.')) {
    return false; // 引导文件/隐藏文件不是规则
  }
  return RULE_EXTENSIONS.has(path.extname(name).toLowerCase());
}

/**
 * 扫描公共宪法目录，返回规则文件的工作区相对路径（正斜杠，按字典序稳定输出）。
 * 目录不存在 → 空数组。
 */
export function listConstitutionRules(root: string): string[] {
  const dir = constitutionDir(root);
  if (!fs.existsSync(dir)) {
    return [];
  }
  const out: string[] = [];
  const walk = (abs: string, rel: string): void => {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(abs, { withFileTypes: true });
    } catch {
      return; // 不可读 → 跳过
    }
    for (const e of entries) {
      const childAbs = path.join(abs, e.name);
      const childRel = rel === '' ? e.name : `${rel}/${e.name}`;
      if (e.isDirectory()) {
        walk(childAbs, childRel);
      } else if (e.isFile() && isRuleFile(e.name)) {
        out.push(childRel);
      }
    }
  };
  walk(dir, '');
  return out.sort((a, b) => a.localeCompare(b));
}

/**
 * constitution 命令的提示词后缀（拼接在调用令牌之后）。
 * 无规则文件 → 空串（保持原令牌不变）。
 */
export function buildConstitutionSuffix(root: string): string {
  const rules = listConstitutionRules(root);
  if (rules.length === 0) {
    return '';
  }
  return `（公共规则输入：${rules.join('、')}）`;
}