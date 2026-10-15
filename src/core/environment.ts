// T010: 环境检测（contracts/artifacts.md §1）——纯 Node 逻辑，可单元测试
import * as fs from 'node:fs';
import * as path from 'node:path';
import type { ScriptType, WorkspaceEnvironment } from '../../shared/protocol';

export interface DetectOptions {
  /** specify CLI 是否可发现（由调用方的发现链提供） */
  cliAvailable: boolean;
  /** 工具目录 label 查询（命中 → 已知集成；未命中 → 未知/自定义） */
  labelFor?: (integrationId: string) => string | undefined;
}

function normalizeScript(raw: unknown): ScriptType | undefined {
  return raw === 'sh' || raw === 'ps' || raw === 'py' ? raw : undefined;
}

/** 检测工作区根的 Speckit 环境状态（missing / incomplete / ready） */
export async function detectEnvironment(
  root: string,
  opts: DetectOptions,
): Promise<WorkspaceEnvironment> {
  const specifyDir = path.join(root, '.specify');
  const cliAvailable = opts.cliAvailable;

  if (!fs.existsSync(specifyDir) || !fs.statSync(specifyDir).isDirectory()) {
    return {
      state: 'missing',
      isKnownIntegration: false,
      cliAvailable,
      hints: [],
    };
  }

  const optionsPath = path.join(specifyDir, 'init-options.json');
  const hints: string[] = [];

  if (!fs.existsSync(optionsPath)) {
    hints.push('缺少 .specify/init-options.json（初始化可能被中断）');
  } else {
    let parsed: Record<string, unknown> | undefined;
    try {
      parsed = JSON.parse(fs.readFileSync(optionsPath, 'utf-8')) as Record<string, unknown>;
    } catch {
      hints.push('.specify/init-options.json 无法解析（损坏）');
    }
    if (parsed) {
      if (typeof parsed.ai !== 'string' || parsed.ai.length === 0) {
        hints.push('init-options.json 缺少有效的 ai 字段');
      } else {
        // ready
        const integrationId = parsed.ai;
        const label = opts.labelFor?.(integrationId);
        return {
          state: 'ready',
          integrationId,
          integrationLabel: label,
          isKnownIntegration: Boolean(label),
          script: normalizeScript(parsed.script),
          speckitVersion:
            typeof parsed.speckit_version === 'string' ? parsed.speckit_version : undefined,
          aiSkills: parsed.ai_skills === true,
          cliAvailable,
          hints: [],
        };
      }
    }
    // 辅证（仅用于 incomplete 提示）：.specify/integrations/*.manifest.json
    const integrationsDir = path.join(specifyDir, 'integrations');
    if (fs.existsSync(integrationsDir)) {
      const manifests = fs
        .readdirSync(integrationsDir)
        .filter((f) => f.endsWith('.manifest.json'))
        .map((f) => f.replace('.manifest.json', ''));
      if (manifests.length > 0) {
        hints.push(`检测到集成清单：${manifests.join(', ')}`);
      }
    }
  }

  return {
    state: 'incomplete',
    isKnownIntegration: false,
    cliAvailable,
    hints,
  };
}