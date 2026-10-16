// 预处理（规范文档导入，v0.7）：markfiledown 技能调度 + 输出目录管理 + specify 输入选择。
// 流程：预处理按钮 → （技能缺失则自动安装）→ 选择文档目录 → dispatch /markfiledown.pipeline
//      → 输出固定写入 .specify/preprocess → 用户勾选输出文件 → specify 必选校验并拼接提示词。
import * as fs from 'node:fs';
import * as path from 'node:path';

/** 预处理输出目录（指定文件夹；specify 的输入源） */
export const PREPROCESS_DIR = '.specify/preprocess';

/** 技能安装目标（Cursor skills 目录；与 workflow.ts SKILLS_DIRS 首选一致） */
export const SKILL_TARGET_DIR = '.cursor/skills/markfiledown-0509';

/** 技能探测目录（对齐 workflow.ts 的 SKILLS_DIRS；任一存在即视为已安装） */
const SKILL_DETECT_DIRS = ['.cursor/skills', '.claude/skills', '.agents/skills', '.github/skills'];
const SKILL_PREFIX = 'markfiledown';

/** 预处理输出目录绝对路径 */
export function preprocessDir(root: string): string {
  return path.join(root, PREPROCESS_DIR);
}

/** 确保输出目录存在（幂等） */
export function ensurePreprocessDir(root: string): void {
  const dir = preprocessDir(root);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

/**
 * 列出预处理输出：workspace 相对 posix 路径的 .md 文件（final.md 为主交付物），
 * 排除 `_`/`.` 开头文件，字典序稳定输出。目录不存在 → 空数组。
 */
export function listPreprocessOutputs(root: string): string[] {
  const dir = preprocessDir(root);
  if (!fs.existsSync(dir)) {
    return [];
  }
  const out: string[] = [];
  const walk = (abs: string, rel: string): void => {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(abs, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      if (e.name.startsWith('_') || e.name.startsWith('.')) {
        continue; // 状态文件/隐藏文件
      }
      const childAbs = path.join(abs, e.name);
      const childRel = rel === '' ? e.name : `${rel}/${e.name}`;
      if (e.isDirectory()) {
        walk(childAbs, childRel);
      } else if (e.isFile() && /\.md$/i.test(e.name)) {
        out.push(`${PREPROCESS_DIR}/${childRel}`);
      }
    }
  };
  walk(dir, '');
  return out.sort((a, b) => a.localeCompare(b));
}

/** 工作区是否已安装 markfiledown 技能（任一技能目录下存在同名前缀目录） */
export function isPreprocessSkillInstalled(root: string): boolean {
  for (const dir of SKILL_DETECT_DIRS) {
    const abs = path.join(root, dir);
    try {
      const entries = fs.readdirSync(abs, { withFileTypes: true });
      if (entries.some((e) => e.isDirectory() && e.name.toLowerCase().startsWith(SKILL_PREFIX))) {
        return true;
      }
    } catch {
      // 目录不存在 → 继续探测
    }
  }
  return false;
}

export type SkillInstallResult = 'installed' | 'refreshed' | 'already' | 'failed';

/** 读取 bundle-manifest.json 的 version（缺失/损坏 → undefined） */
function readManifestVersion(dir: string): string | undefined {
  try {
    const parsed = JSON.parse(fs.readFileSync(path.join(dir, 'bundle-manifest.json'), 'utf-8')) as {
      version?: unknown;
    };
    return typeof parsed.version === 'string' && parsed.version.length > 0 ? parsed.version : undefined;
  } catch {
    return undefined;
  }
}

/**
 * 安装内置技能包（resources/markfiledown）到工作区 .cursor/skills/markfiledown-0509。
 * - 目标未安装且其他技能目录有同名技能（用户自装）→ 'already'（不覆盖用户安装）
 * - 目标已安装且 manifest 版本一致 → 'already'
 * - 目标已安装但版本不同 → 覆盖升级 → 'refreshed'（插件更新后旧工作区自动拿到新技能）
 * - 目标缺失 → 全新安装 → 'installed'
 */
export function installPreprocessSkill(root: string, bundledDir: string): SkillInstallResult {
  if (!fs.existsSync(path.join(bundledDir, 'SKILL.md'))) {
    return 'failed';
  }
  const target = path.join(root, SKILL_TARGET_DIR);
  const targetExists = fs.existsSync(path.join(target, 'SKILL.md'));
  const bundledVersion = readManifestVersion(bundledDir);
  const installedVersion = targetExists ? readManifestVersion(target) : undefined;

  if (targetExists) {
    if (bundledVersion === undefined || installedVersion === bundledVersion) {
      return 'already'; // 无法比较或版本一致 → 不动
    }
  } else if (isPreprocessSkillInstalled(root)) {
    return 'already'; // 用户自装在别的技能目录 → 不覆盖
  }

  try {
    fs.rmSync(target, { recursive: true, force: true });
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.cpSync(bundledDir, target, {
      recursive: true,
      filter: (src) => !src.includes('__pycache__') && !src.endsWith('.bak'),
    });
    if (!fs.existsSync(path.join(target, 'SKILL.md'))) {
      return 'failed';
    }
    return targetExists ? 'refreshed' : 'installed';
  } catch {
    return 'failed';
  }
}

/** specify 规范输入后缀：（规范输入：.specify/preprocess/a/final.md、…）；空选择 → 空串 */
export function buildSpecifyInputSuffix(selected: string[]): string {
  const items = selected.filter((s) => s.trim().length > 0);
  if (items.length === 0) {
    return '';
  }
  return `（规范输入：${items.join('、')}）`;
}

/** 持久化选择 ∩ 当前存在的文件（剔除过期项），按可用列表顺序稳定输出 */
export function normalizeSelection(
  selected: string[] | undefined,
  available: string[],
): string[] {
  const availableIdx = new Map(available.map((p, i) => [p, i]));
  const seen = new Set<string>();
  const out: Array<{ p: string; i: number }> = [];
  for (const s of selected ?? []) {
    const i = availableIdx.get(s);
    if (i !== undefined && !seen.has(s)) {
      seen.add(s);
      out.push({ p: s, i });
    }
  }
  return out.sort((a, b) => a.i - b.i).map((x) => x.p);
}