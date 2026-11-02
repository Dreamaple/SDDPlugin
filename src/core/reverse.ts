// 逆向生成（代码 → 规格）：选定目录只对应一份 spec，产物仍走本地 .specify / specs 布局。
import * as fs from 'node:fs';
import * as path from 'node:path';

/** 逆向范围：整个工作区根，或用户在「指定目录」模式下选中的一个目录。 */
export interface ReverseTarget {
  mode: 'workspace' | 'directory';
  /** 工作区相对路径。workspace 模式为空串；directory 模式在尚未选择时也为空串。 */
  path: string;
}

export function workspaceReverseTarget(): ReverseTarget {
  return { mode: 'workspace', path: '' };
}

export type ReverseTargetParse =
  | { ok: true; target: ReverseTarget }
  | { ok: false; message: string };

/** 绝对路径 → 工作区相对目录。工作区根本身为 ''；越界、非目录或不存在返回 undefined。 */
export function toWorkspaceRelativeDir(root: string, absPath: string): string | undefined {
  const rootResolved = path.resolve(root);
  const abs = path.resolve(absPath);
  let dirStat: fs.Stats;
  try {
    dirStat = fs.statSync(abs);
  } catch {
    return undefined;
  }
  if (!dirStat.isDirectory()) {
    return undefined;
  }
  if (abs === rootResolved) {
    return '';
  }
  const rel = path.relative(rootResolved, abs);
  if (rel === '' || rel.startsWith(`..${path.sep}`) || rel === '..' || path.isAbsolute(rel)) {
    return undefined;
  }
  return rel.split(path.sep).join('/');
}

/**
 * 校验面板提交的逆向范围。
 * directory 模式允许空路径（尚未点选）；真正派发前由宿主拒绝空路径。
 */
export function parseReverseTargetInput(
  root: string,
  mode: 'workspace' | 'directory',
  pathInput: string,
): ReverseTargetParse {
  if (mode === 'workspace') {
    return { ok: true, target: workspaceReverseTarget() };
  }
  const rel = pathInput.trim().replace(/\\/g, '/').replace(/^\.\//, '').replace(/\/+$/, '');
  if (!rel || rel === '.') {
    return { ok: true, target: { mode: 'directory', path: '' } };
  }
  const trimmed = pathInput.trim();
  if (path.isAbsolute(trimmed) || path.win32.isAbsolute(rel) || rel.startsWith('/')) {
    return { ok: false, message: '请选择当前工作区内的目录' };
  }
  const parts = rel.split('/');
  if (parts.some((part) => part === '' || part === '.' || part === '..')) {
    return { ok: false, message: '请使用工作区内的相对目录' };
  }
  const normalized = toWorkspaceRelativeDir(root, path.resolve(root, ...parts));
  if (normalized === undefined) {
    return { ok: false, message: '目录不存在，或不在当前工作区内' };
  }
  if (normalized === '') {
    return { ok: true, target: workspaceReverseTarget() };
  }
  return { ok: true, target: { mode: 'directory', path: normalized } };
}

/** 读出持久化范围；非法或已消失的目录回退到工作区根，避免派发到工作区外。 */
export function normalizeReverseTarget(
  root: string,
  raw: Partial<ReverseTarget> | undefined,
): ReverseTarget {
  if (raw?.mode !== 'directory') {
    return workspaceReverseTarget();
  }
  const parsed = parseReverseTargetInput(root, 'directory', raw.path ?? '');
  if (!parsed.ok) {
    return workspaceReverseTarget();
  }
  return parsed.target;
}

/**
 * 拼在 /speckit.reverse（或 /speckit-reverse）之后的提示词。
 * 约束：所选目录恰好一份 spec，不按模块拆分，也不做根索引规格 + 每模块规格。
 */
export function buildReversePromptSuffix(target: ReverseTarget): string {
  const scope =
    target.mode === 'directory' && target.path
      ? `选定目录「${target.path}」（相对工作区根；只覆盖这个目录）`
      : '当前工作区根目录（整个已打开的文件夹）';
  return (
    `（逆向生成：阅读${scope}中的现有代码，反推为 Spec Kit 规格，并写入本地产物：` +
    `.specify/memory/constitution.md，以及当前特性目录 specs/<NNN-name>/ 下的 spec.md、plan.md、tasks.md。` +
    `硬约束：所选目录只生成一份 spec.md，把该目录的全部代码作为单一单元写入这一份规格；` +
    `禁止按模块、包或子目录拆成多份 spec；禁止 root index spec 再加每模块一份 spec。` +
    `跨模块依赖若在代码中可见，记在这一份 spec 内即可。` +
    `不要调用云服务或远程 API，只读写工作区本地文件。）`
  );
}
