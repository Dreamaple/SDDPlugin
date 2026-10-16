// 项目配置（.specify/project-config.json）：宪法占位 tag 的可视化预填。
// 设计要点（v0.6）：
// - 字段目录内置常用 tag，可被 resources/project-fields.json 覆盖/扩展（无需改代码）
// - 配置文件 values 为开放 Record，目录之外的自定义字段可读写、可传递（字段扩展性）
// - 未填字段按 defaultFrom 策略计算缺省值（如 TAG_PREFIX ← 模块名大写）
import * as fs from 'node:fs';
import * as path from 'node:path';
import type { ProjectFieldDef } from '../../shared/protocol';

/** 项目配置文件（工作区相对路径） */
export const PROJECT_CONFIG_PATH = '.specify/project-config.json';

/** 内置字段目录（对齐宪法模板/常见规则文件的占位 tag；可扩展） */
export const DEFAULT_FIELD_CATALOG: ProjectFieldDef[] = [
  {
    id: 'PROJECT_NAME',
    label: '项目名',
    description: '项目显示名称（宪法标题等）',
    required: true,
    defaultFrom: 'workspace-name',
  },
  {
    id: 'APP_NAME',
    label: '模块名',
    description: '当前模块/子应用名',
    defaultFrom: 'workspace-name',
  },
  {
    id: 'APP_PACKAGE',
    label: '包根',
    description: '代码包根名',
    placeholder: 'com.example.app',
  },
  {
    id: 'FEATURE_SCOPE',
    label: '功能范围',
    description:
      '选填；导入的规范文档常为全量文档，填写本次工程要实现的功能边界后，specify 阶段只抽取该范围内的内容',
    placeholder: '如：仅后端接口服务模块；不包含移动端与运营后台',
  },
  {
    id: 'TECH_STACK',
    label: '技术栈',
    description:
      '选填；语言/版本与主要依赖（plan 阶段直接采用，不再调研）。例：C# / Unity 2022 LTS（依赖 UXML、UniTask）；Kotlin + Jetpack Compose',
    placeholder: '如：Kotlin 2.0 + Compose；C# / Unity 2022 LTS',
  },
  {
    id: 'TARGET_PLATFORM',
    label: '目标平台',
    description:
      '选填；目标平台/设备（plan 的 Target Platform 槽位）。例：MT8678 车机 Android 13；iOS 17+；Windows 桌面',
    placeholder: '如：MT8678 车机 Android 13 / iOS 17+',
  },
  {
    id: 'STORAGE',
    label: '存储方案',
    description:
      '选填；数据持久化方案——回答「数据存在哪、用什么技术存」（plan 的 Storage 槽位）。' +
      '常见选型：MMKV / DataStore / SharedPreferences（用户设置）；SQLite / Room（历史与离线数据）；本地 JSON（场景/资源配置）；服务端 API（数据在云端，无本地持久化）；不涉及 / N/A（纯展示、退出即丢）。拿不准可留空，plan 会标记 NEEDS CLARIFICATION 由 AI 调研建议',
    placeholder: '如：MMKV（用户设置）+ 本地 JSON（场景配置）；不涉及',
  },
  {
    id: 'PLAN_OUTPUT_STYLE',
    label: 'plan 输出物形态',
    description:
      '选填；声明 plan.md 的结构要求（如「详细设计说明书」），Agent 会在 speckit 模板基础上扩展对应章节。' +
      '例：详细设计说明书（概要设计+详细设计：模块划分/接口定义/数据模型/异常与日志/测试要点）',
    placeholder: '如：详细设计说明书（概要设计+详细设计）',
  },
  {
    id: 'TAG_PREFIX',
    label: '日志 TAG 前缀',
    description: '留空则按模块名大写自动生成',
    defaultFrom: 'app-name-upper',
  },
  {
    id: 'CLASS_PREFIX',
    label: '类名前缀',
    description: '留空则按模块名 PascalCase 自动生成',
    defaultFrom: 'app-name-pascal',
  },
  {
    id: 'OWNER_CONTACT',
    label: '负责人联系方式',
    description: '选填；可依托 git 记录追溯负责人',
  },
];

/** PascalCase：按非字母数字切分后各段首字母大写拼接 */
export function pascalCase(input: string): string {
  return input
    .split(/[^A-Za-z0-9]+/)
    .filter(Boolean)
    .map((seg) => seg.charAt(0).toUpperCase() + seg.slice(1))
    .join('');
}

/**
 * 加载字段目录：resourceFile 存在且为合法数组 → 覆盖内置；否则回退内置目录。
 * 目录文件格式：ProjectFieldDef[]（字段扩展无需改插件代码）。
 */
export function loadFieldCatalog(resourceFile?: string): ProjectFieldDef[] {
  if (!resourceFile || !fs.existsSync(resourceFile)) {
    return DEFAULT_FIELD_CATALOG;
  }
  try {
    const parsed = JSON.parse(fs.readFileSync(resourceFile, 'utf-8')) as unknown;
    if (!Array.isArray(parsed)) {
      return DEFAULT_FIELD_CATALOG;
    }
    const fields = parsed
      .filter((f): f is ProjectFieldDef => {
        const def = f as ProjectFieldDef;
        return typeof def?.id === 'string' && def.id.length > 0 && typeof def?.label === 'string';
      })
      .map((f) => ({ ...f, id: f.id.trim(), label: f.label.trim() }));
    return fields.length > 0 ? fields : DEFAULT_FIELD_CATALOG;
  } catch {
    return DEFAULT_FIELD_CATALOG;
  }
}

/** 读取配置值（容错：文件缺失/损坏/字段非法 → 空值集） */
export function readProjectConfig(root: string): { values: Record<string, string>; updatedAt?: string } {
  const p = path.join(root, PROJECT_CONFIG_PATH);
  if (!fs.existsSync(p)) {
    return { values: {} };
  }
  try {
    const parsed = JSON.parse(fs.readFileSync(p, 'utf-8')) as {
      values?: Record<string, unknown>;
      updatedAt?: unknown;
    };
    const values: Record<string, string> = {};
    if (parsed.values && typeof parsed.values === 'object') {
      for (const [k, v] of Object.entries(parsed.values)) {
        const key = k.trim();
        if (key.length > 0 && typeof v === 'string' && v.trim().length > 0) {
          values[key] = v.trim();
        }
      }
    }
    const updatedAt = typeof parsed.updatedAt === 'string' ? parsed.updatedAt : undefined;
    return { values, updatedAt };
  } catch {
    return { values: {} };
  }
}

/** 写入配置（空串值剔除；.specify 不存在时自动创建）。返回 updatedAt。 */
export function writeProjectConfig(root: string, values: Record<string, string>): string {
  const dir = path.dirname(path.join(root, PROJECT_CONFIG_PATH));
  fs.mkdirSync(dir, { recursive: true });
  const cleaned: Record<string, string> = {};
  for (const [k, v] of Object.entries(values)) {
    const key = k.trim();
    const val = typeof v === 'string' ? v.trim() : '';
    if (key.length > 0 && val.length > 0) {
      cleaned[key] = val;
    }
  }
  const updatedAt = new Date().toISOString();
  fs.writeFileSync(
    path.join(root, PROJECT_CONFIG_PATH),
    `${JSON.stringify({ version: 1, updatedAt, values: cleaned }, null, 2)}\n`,
    'utf-8',
  );
  return updatedAt;
}

/** 按 defaultFrom 策略计算各字段缺省值（用户未填该字段时生效） */
export function computeDefaults(
  fields: ProjectFieldDef[],
  values: Record<string, string>,
  workspaceName: string,
): Record<string, string> {
  const appName = values['APP_NAME']?.trim() || workspaceName;
  const defaults: Record<string, string> = {};
  for (const f of fields) {
    switch (f.defaultFrom) {
      case 'workspace-name':
        defaults[f.id] = workspaceName;
        break;
      case 'app-name-upper':
        defaults[f.id] = appName.toUpperCase();
        break;
      case 'app-name-pascal':
        defaults[f.id] = pascalCase(appName);
        break;
      default:
        break;
    }
  }
  return defaults;
}

/** 字段有效值：用户已填 → 用户值；否则 → 缺省值（无则空） */
export function effectiveValue(
  id: string,
  values: Record<string, string>,
  defaults: Record<string, string>,
): string {
  return values[id]?.trim() || defaults[id]?.trim() || '';
}

/**
 * constitution 命令的项目配置后缀（拼接在调用令牌后）：
 * 输出所有「有效值非空」的字段（含按缺省策略生成的），格式：
 * （项目配置：[PROJECT_NAME]=X、[TAG_PREFIX]=Y）
 * 无可传字段 → 空串。
 */
export function buildProjectConfigSuffix(
  root: string,
  fields: ProjectFieldDef[] = DEFAULT_FIELD_CATALOG,
): string {
  const { values } = readProjectConfig(root);
  const filled = Object.values(values).some((v) => v.trim().length > 0);
  if (!filled) {
    return ''; // 从未填过配置 → 不附加（保持令牌简洁，由 AI 用模板默认）
  }
  const workspaceName = path.basename(root);
  const defaults = computeDefaults(fields, values, workspaceName);
  const parts = fields
    .map((f) => ({ id: f.id, value: effectiveValue(f.id, values, defaults) }))
    .filter((p) => p.value.length > 0)
    .map((p) => `[${p.id}]=${p.value}`);
  if (parts.length === 0) {
    return '';
  }
  return `（项目配置：${parts.join('、')}）`;
}

/**
 * specify 阶段的功能范围提示词后缀：导入文档常为全量文档，需指示 AI 只抽取当前工程要做的部分。
 * 「功能范围」（FEATURE_SCOPE）未填 → 空串（不做额外约束）。
 */
export function buildFeatureScopeSuffix(root: string): string {
  const { values } = readProjectConfig(root);
  const scope = values['FEATURE_SCOPE']?.trim();
  if (!scope) {
    return '';
  }
  return `（功能范围：${scope}。注意：规范输入可能是全量文档，仅提取上述范围内当前工程要实现的内容，范围外内容一律忽略）`;
}

/**
 * plan 阶段的技术事实后缀（v0.7.8）：把项目配置中的既定技术事实（技术栈/目标平台/存储）
 * 传递给 Agent，并禁止对已确认事实再进入 NEEDS CLARIFICATION 调研——
 * 事实由项目拍板，设计性工作（架构/模块/数据模型/契约）仍由 Agent 按 speckit 模板自主完成。
 * PLAN_OUTPUT_STYLE 已填时附加输出物形态要求（如「详细设计说明书」章节结构）。
 * 相关字段全部未填 → 空串（保持 speckit 默认流程）。
 */
export function buildPlanConfigSuffix(root: string, fields: ProjectFieldDef[] = DEFAULT_FIELD_CATALOG): string {
  const { values } = readProjectConfig(root);
  if (Object.keys(values).length === 0) {
    return '';
  }
  const workspaceName = path.basename(root);
  const defaults = computeDefaults(fields, values, workspaceName);
  const fact = (id: string, label: string): string | undefined => {
    const v = effectiveValue(id, values, defaults);
    return v.length > 0 ? `${label}=${v}` : undefined;
  };
  const facts = [
    fact('TECH_STACK', '技术栈'),
    fact('TARGET_PLATFORM', '目标平台'),
    fact('STORAGE', '存储'),
  ].filter((s): s is string => s !== undefined);
  const parts: string[] = [];
  if (facts.length > 0) {
    parts.push(
      `技术上下文既定事实（直接采用，不要再进入 NEEDS CLARIFICATION 调研）：${facts.join('；')}`,
    );
  }
  const style = values['PLAN_OUTPUT_STYLE']?.trim();
  if (style) {
    parts.push(`输出物形态：${style}——plan.md 按此结构组织章节，在 speckit plan 模板基础上扩展对应章节`);
  }
  if (parts.length === 0) {
    return '';
  }
  return `（plan 约定：${parts.join('；')}）`;
}