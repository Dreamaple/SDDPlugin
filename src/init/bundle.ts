// v0.4.0: 内置 Spec Kit CLI 源码管理（bundle）
// - 内置副本：resources/speckit-cli（specify-cli 源码，uvx --from <dir> specify 直跑）
// - 版本更新：从 github/spec-kit 最新 Release 下载源码 zip，解压到 globalStorage 后作为优先源
// - 全部纯函数与 I/O 分离，核心逻辑可单元测试
import * as fs from 'node:fs';
import * as path from 'node:path';
import AdmZip from 'adm-zip';

/** 从 pyproject.toml 解析 version 字段（纯函数） */
export function parsePyprojectVersion(text: string): string | undefined {
  const m = /^version\s*=\s*"([^"]+)"/m.exec(text);
  return m ? m[1] : undefined;
}

/** 版本比较：点分数字逐段比较，段数不足补 0；相等时更长者视为更新（1.2.1.dev0 > 1.2.1） */
export function compareVersions(a: string, b: string): number {
  const norm = (v: string) => v.split(/[.\-+]/).map((seg) => (/^\d+$/.test(seg) ? parseInt(seg, 10) : seg));
  const pa = norm(a);
  const pb = norm(b);
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i++) {
    const x = pa[i] ?? 0;
    const y = pb[i] ?? 0;
    if (x === y) {
      continue;
    }
    if (typeof x === 'number' && typeof y === 'number') {
      return x - y;
    }
    return String(x) < String(y) ? -1 : 1;
  }
  // 前缀相同：更长（多段，如 1.2.1.dev0 vs 1.2.1）视为更新
  return pa.length - pb.length;
}

export interface BundleCandidate {
  dir: string;
  version: string;
}

/** 从候选内置源中选最新版本（纯函数） */
export function resolveNewestBundle(candidates: BundleCandidate[]): BundleCandidate | undefined {
  if (candidates.length === 0) {
    return undefined;
  }
  return candidates.reduce((best, cur) => (compareVersions(cur.version, best.version) > 0 ? cur : best));
}

/** uvx 直跑内置源码的命令参数（纯函数） */
export function buildUvxArgs(srcDir: string, specifyArgs: string[]): string[] {
  return ['--from', srcDir, 'specify', ...specifyArgs];
}

/** zip 条目防 zip-slip：解析后必须仍位于目标目录内（纯函数） */
export function isSafeZipEntry(entryName: string, targetRoot: string): boolean {
  const resolved = path.resolve(targetRoot, entryName);
  const root = path.resolve(targetRoot);
  return resolved === root || resolved.startsWith(root + path.sep);
}

export interface BundleDownloadEvents {
  /** 下载进度：0..1（content-length 已知时）；未知为 undefined */
  onProgress?: (ratio: number | undefined, receivedBytes: number) => void;
  onStage?: (stage: 'resolve-tag' | 'download' | 'extract' | 'done', detail?: string) => void;
  /** 取消下载（AbortController） */
  signal?: AbortSignal;
}

export interface BundleDownloadResult {
  tag: string;
  dir: string;
  version: string;
}

const SPEC_KIT_REPO = 'github/spec-kit';

/**
 * 下载 github/spec-kit 最新 Release 源码 zip 并解压到 storageDir/<tag>/。
 * 目录布局 = 整仓快照（pyproject 在根，force-include 路径齐备），可直接作为 uvx --from 的项目根。
 */
export async function downloadLatestSpeckitBundle(
  storageDir: string,
  events: BundleDownloadEvents = {},
): Promise<BundleDownloadResult> {
  events.onStage?.('resolve-tag');
  // 1. 最新 release tag（GitHub API，公开仓库无需 token）
  const apiRes = await fetch(`https://api.github.com/repos/${SPEC_KIT_REPO}/releases/latest`, {
    headers: { 'User-Agent': 'speckit-gui-extension', Accept: 'application/vnd.github+json' },
    signal: events.signal,
  });
  if (!apiRes.ok) {
    throw new Error(
      apiRes.status === 403
        ? 'GitHub API 限流（403），请稍后重试'
        : `GitHub API 请求失败：HTTP ${apiRes.status}`,
    );
  }
  const release = (await apiRes.json()) as { tag_name?: string };
  const tag = release.tag_name;
  if (!tag) {
    throw new Error('未能解析最新 Release 标签');
  }

  // 2. 下载源码 zip（codeload 跟随重定向）
  events.onStage?.('download', tag);
  const zipRes = await fetch(`https://codeload.github.com/${SPEC_KIT_REPO}/zip/refs/tags/${tag}`, {
    headers: { 'User-Agent': 'speckit-gui-extension' },
    signal: events.signal,
  });
  if (!zipRes.ok) {
    throw new Error(`源码包下载失败：HTTP ${zipRes.status}`);
  }
  const total = Number(zipRes.headers.get('content-length') ?? 0);
  const reader = zipRes.body?.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  if (reader) {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      if (value) {
        chunks.push(value);
        received += value.byteLength;
        events.onProgress?.(total > 0 ? received / total : undefined, received);
      }
    }
  }
  const zipBuf = Buffer.concat(chunks.map((c) => Buffer.from(c)));

  // 3. 解压（zip-slip 防护；目标目录先清空同名 tag）
  events.onStage?.('extract', tag);
  const targetDir = path.join(storageDir, tag);
  fs.rmSync(targetDir, { recursive: true, force: true });
  fs.mkdirSync(targetDir, { recursive: true });
  const zip = new AdmZip(zipBuf);
  for (const entry of zip.getEntries()) {
    if (entry.isDirectory) {
      continue;
    }
    // zip 内根目录形如 spec-kit-<tag>/…，剥掉第一段后写入 targetDir
    const parts = entry.entryName.split(/[\\/]/);
    parts.shift();
    const rel = parts.join('/');
    if (!isSafeZipEntry(rel, targetDir)) {
      throw new Error(`zip 条目路径非法（疑似 zip-slip）：${entry.entryName}`);
    }
    const outFile = path.resolve(targetDir, rel);
    fs.mkdirSync(path.dirname(outFile), { recursive: true });
    fs.writeFileSync(outFile, entry.getData());
  }

  // 4. 校验：pyproject 存在且可解析版本
  const pyproject = path.join(targetDir, 'pyproject.toml');
  if (!fs.existsSync(pyproject)) {
    throw new Error('下载的源码包缺少 pyproject.toml，内容不完整');
  }
  const version = parsePyprojectVersion(fs.readFileSync(pyproject, 'utf-8'));
  if (!version) {
    throw new Error('pyproject.toml 中未找到 version 字段');
  }
  events.onStage?.('done', tag);
  return { tag, dir: targetDir, version };
}

/**
 * 内置源解析：在候选中选最新——
 *  1. 已下载的 release 副本（globalStorage/speckit-bundles/<tag>/pyproject.toml）
 *  2. 插件自带副本（resources/speckit-cli）
 */
export function resolveBundledSource(
  builtinDir: string,
  storageDir: string,
): BundleCandidate | undefined {
  const candidates: BundleCandidate[] = [];
  const scan = (dir: string) => {
    const p = path.join(dir, 'pyproject.toml');
    if (fs.existsSync(p)) {
      try {
        const version = parsePyprojectVersion(fs.readFileSync(p, 'utf-8'));
        if (version) {
          candidates.push({ dir, version });
        }
      } catch {
        /* ignore malformed */
      }
    }
  };
  scan(builtinDir);
  if (fs.existsSync(storageDir)) {
    for (const entry of fs.readdirSync(storageDir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        scan(path.join(storageDir, entry.name));
      }
    }
  }
  return resolveNewestBundle(candidates);
}