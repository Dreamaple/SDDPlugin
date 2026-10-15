// T012: 特性扫描与当前特性解析（contracts/artifacts.md §1/§2）
import * as fs from 'node:fs';
import * as path from 'node:path';
import type { Feature } from '../../shared/protocol';

export const FEATURE_DIR_PATTERN = /^(\d{3})-(.+)$/;

/** 宪法就绪判定：存在且不含未填充占位符（contracts/artifacts.md §1） */
export function isConstitutionReady(root: string): boolean {
  const constitutionPath = path.join(root, '.specify', 'memory', 'constitution.md');
  if (!fs.existsSync(constitutionPath)) {
    return false;
  }
  try {
    const content = fs.readFileSync(constitutionPath, 'utf-8');
    const hasPlaceholder =
      content.includes('PRINCIPLE_1_NAME') || content.includes('[PROJECT_NAME]');
    return !hasPlaceholder;
  } catch {
    return false;
  }
}

function safeMtime(p: string): number | undefined {
  try {
    return fs.statSync(p).mtimeMs;
  } catch {
    return undefined;
  }
}

/** 扫描 specs/ 下形如 NNN-name 的特性目录，返回按序号排序的列表 */
export async function scanFeatures(root: string): Promise<Feature[]> {
  const specsDir = path.join(root, 'specs');
  if (!fs.existsSync(specsDir)) {
    return [];
  }

  let dirNames: string[];
  try {
    dirNames = fs
      .readdirSync(specsDir, { withFileTypes: true })
      .filter((e) => e.isDirectory())
      .map((e) => e.name);
  } catch {
    return [];
  }

  const features: Feature[] = [];
  for (const dirName of dirNames) {
    const m = FEATURE_DIR_PATTERN.exec(dirName);
    if (!m) {
      continue; // 不匹配的目录忽略（contracts/artifacts.md）
    }
    const featureDir = path.join(specsDir, dirName);
    const artifacts = {
      constitution: isConstitutionReady(root)
        ? safeMtime(path.join(root, '.specify', 'memory', 'constitution.md'))
        : undefined,
      spec: safeMtime(path.join(featureDir, 'spec.md')),
      plan: safeMtime(path.join(featureDir, 'plan.md')),
      tasks: safeMtime(path.join(featureDir, 'tasks.md')),
    };
    features.push({
      dirName,
      number: parseInt(m[1], 10),
      name: m[2],
      artifacts,
      isCurrent: false, // 由 resolveCurrentFeatureDir 标记
    });
  }

  features.sort((a, b) => (a.number ?? 999) - (b.number ?? 999));
  return features;
}

/** 读取 .specify/feature.json 的 feature_directory 候选 */
export function readFeatureJsonCandidate(root: string): string | undefined {
  const p = path.join(root, '.specify', 'feature.json');
  if (!fs.existsSync(p)) {
    return undefined;
  }
  try {
    const parsed = JSON.parse(fs.readFileSync(p, 'utf-8')) as { feature_directory?: string };
    const dir = parsed.feature_directory;
    return typeof dir === 'string' ? dir.replace(/^specs\//, '') : undefined;
  } catch {
    return undefined;
  }
}

/**
 * 当前特性解析链：workspaceState.activeFeatureDir → .specify/feature.json → 最近修改（目录 mtime）
 * （FR-012 / FR-013 / Edge Case「多特性目录」）
 */
export function resolveCurrentFeatureDir(
  root: string,
  features: Feature[],
  statePreferred?: string,
): string | undefined {
  if (features.length === 0) {
    return undefined;
  }
  if (statePreferred && features.some((f) => f.dirName === statePreferred)) {
    return statePreferred;
  }
  const jsonCandidate = readFeatureJsonCandidate(root);
  if (jsonCandidate && features.some((f) => f.dirName === jsonCandidate)) {
    return jsonCandidate;
  }
  // 默认最近修改
  let latest = features[0];
  let latestMtime = -1;
  for (const f of features) {
    const m = safeMtime(path.join(root, 'specs', f.dirName)) ?? 0;
    if (m > latestMtime) {
      latestMtime = m;
      latest = f;
    }
  }
  return latest.dirName;
}