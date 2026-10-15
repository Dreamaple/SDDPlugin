// T011: 受支持工具目录（resources/tool-catalog.json 静态快照）
import * as fs from 'node:fs';
import type { ToolCatalogEntry } from '../../shared/protocol';

export type { ToolCatalogEntry };

export interface ToolCatalog {
  entries: ToolCatalogEntry[];
  labelFor: (id: string) => string | undefined;
}

export function parseToolCatalog(jsonText: string): ToolCatalog {
  const parsed = JSON.parse(jsonText) as { tools: ToolCatalogEntry[] };
  const map = new Map<string, string>();
  for (const entry of parsed.tools ?? []) {
    if (typeof entry.id === 'string' && typeof entry.label === 'string') {
      map.set(entry.id, entry.label);
    }
  }
  return {
    entries: [...map.entries()].map(([id, label]) => ({ id, label })),
    labelFor: (id) => map.get(id),
  };
}

/** 从文件加载工具目录（扩展宿主传 context.asAbsolutePath('resources/tool-catalog.json')） */
export async function loadToolCatalog(filePath: string): Promise<ToolCatalog> {
  return parseToolCatalog(fs.readFileSync(filePath, 'utf-8'));
}