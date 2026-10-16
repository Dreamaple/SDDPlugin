// 项目配置：读写容错、缺省值策略、字段目录扩展、dispatch 后缀拼接
import { afterAll, describe, expect, it } from 'vitest';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import {
  DEFAULT_FIELD_CATALOG,
  PROJECT_CONFIG_PATH,
  buildFeatureScopeSuffix,
  buildPlanConfigSuffix,
  buildProjectConfigSuffix,
  computeDefaults,
  effectiveValue,
  loadFieldCatalog,
  pascalCase,
  readProjectConfig,
  writeProjectConfig,
} from '../../src/core/projectConfig';

const tempRoots: string[] = [];

function makeRoot(): string {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-projcfg-'));
  tempRoots.push(tmp);
  return tmp;
}

afterAll(() => {
  for (const dir of tempRoots) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

describe('pascalCase', () => {
  it('按非字母数字切分并 PascalCase', () => {
    expect(pascalCase('my-app_core')).toBe('MyAppCore');
    expect(pascalCase('sdd plugin')).toBe('SddPlugin');
  });
});

describe('项目配置读写', () => {
  it('写入后回读一致；空串值剔除；updatedAt 生成', () => {
    const root = makeRoot();
    const at = writeProjectConfig(root, { PROJECT_NAME: '示例项目', TAG_PREFIX: '', APP_NAME: 'core' });
    expect(at.length).toBeGreaterThan(0);
    const { values, updatedAt } = readProjectConfig(root);
    expect(values).toEqual({ PROJECT_NAME: '示例项目', APP_NAME: 'core' });
    expect(updatedAt).toBe(at);
    // .specify 目录被自动创建
    expect(fs.existsSync(path.join(root, '.specify'))).toBe(true);
  });

  it('文件缺失/损坏 → 容错为空值集', () => {
    const root = makeRoot();
    expect(readProjectConfig(root).values).toEqual({});
    fs.mkdirSync(path.join(root, '.specify'), { recursive: true });
    fs.writeFileSync(path.join(root, PROJECT_CONFIG_PATH), '{broken');
    expect(readProjectConfig(root).values).toEqual({});
  });

  it('自定义字段（目录外）可读写往返', () => {
    const root = makeRoot();
    writeProjectConfig(root, { PROJECT_NAME: 'p', CUSTOM_TAG: 'v1' });
    const { values } = readProjectConfig(root);
    expect(values['CUSTOM_TAG']).toBe('v1');
  });
});

describe('缺省值策略', () => {
  it('workspace-name / app-name-upper / app-name-pascal', () => {
    const defaults = computeDefaults(DEFAULT_FIELD_CATALOG, { APP_NAME: 'my-app' }, 'demo');
    expect(defaults['PROJECT_NAME']).toBe('demo');
    expect(defaults['APP_NAME']).toBe('demo'); // APP_NAME 无 defaultFrom
    expect(defaults['TAG_PREFIX']).toBe('MY-APP');
    expect(defaults['CLASS_PREFIX']).toBe('MyApp');
    // APP_PACKAGE 无策略 → 不出现在 defaults
    expect(defaults['APP_PACKAGE']).toBeUndefined();
  });

  it('APP_NAME 未填时回退工作区名', () => {
    const defaults = computeDefaults(DEFAULT_FIELD_CATALOG, {}, 'demo');
    expect(defaults['TAG_PREFIX']).toBe('DEMO');
    expect(defaults['CLASS_PREFIX']).toBe('Demo');
  });

  it('effectiveValue：用户值优先，其次缺省', () => {
    expect(effectiveValue('TAG_PREFIX', { TAG_PREFIX: 'x' }, { TAG_PREFIX: 'Y' })).toBe('x');
    expect(effectiveValue('TAG_PREFIX', {}, { TAG_PREFIX: 'Y' })).toBe('Y');
    expect(effectiveValue('APP_PACKAGE', {}, {})).toBe('');
  });
});

describe('字段目录扩展', () => {
  it('resources/project-fields.json 合法数组 → 覆盖内置', () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-fields-'));
    tempRoots.push(tmp);
    const file = path.join(tmp, 'project-fields.json');
    fs.writeFileSync(
      file,
      JSON.stringify([{ id: 'PROJECT_NAME', label: '项目名' }, { id: 'EXTRA_FIELD', label: '扩展字段' }]),
    );
    const fields = loadFieldCatalog(file);
    expect(fields.map((f) => f.id)).toEqual(['PROJECT_NAME', 'EXTRA_FIELD']);
  });

  it('文件缺失/损坏/非法 → 回退内置目录', () => {
    expect(loadFieldCatalog(undefined)).toEqual(DEFAULT_FIELD_CATALOG);
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-fields-'));
    tempRoots.push(tmp);
    const file = path.join(tmp, 'bad.json');
    fs.writeFileSync(file, '{oops');
    expect(loadFieldCatalog(file)).toEqual(DEFAULT_FIELD_CATALOG);
    fs.writeFileSync(file, '{"not":"array"}');
    expect(loadFieldCatalog(file)).toEqual(DEFAULT_FIELD_CATALOG);
  });
});

describe('buildProjectConfigSuffix', () => {
  it('未配置 → 空后缀', () => {
    expect(buildProjectConfigSuffix(makeRoot())).toBe('');
  });

  it('已配置 → 含用户值 + 缺省值，按目录序输出 [TAG]=值', () => {
    const root = makeRoot();
    writeProjectConfig(root, { PROJECT_NAME: '示例', APP_PACKAGE: 'com.demo.app' });
    const suffix = buildProjectConfigSuffix(root);
    expect(suffix).toContain('（项目配置：');
    expect(suffix).toContain('[PROJECT_NAME]=示例');
    expect(suffix).toContain('[APP_PACKAGE]=com.demo.app');
    expect(suffix).toContain('[TAG_PREFIX]='); // 缺省生成
  });

  it('自定义字段参与后缀（目录扩展）', () => {
    const root = makeRoot();
    writeProjectConfig(root, { CUSTOM_TAG: 'hello' });
    const fields = [{ id: 'CUSTOM_TAG', label: '自定义' }];
    const suffix = buildProjectConfigSuffix(root, fields);
    expect(suffix).toBe('（项目配置：[CUSTOM_TAG]=hello）');
  });
});

describe('buildPlanConfigSuffix（plan 约定）', () => {
  it('技术字段全未填 → 空后缀（其他字段有值也不拼）', () => {
    const root = makeRoot();
    expect(buildPlanConfigSuffix(root)).toBe('');
    writeProjectConfig(root, { PROJECT_NAME: '示例', TAG_PREFIX: 'X' });
    expect(buildPlanConfigSuffix(root)).toBe('');
  });

  it('已填技术事实 → 中文标签拼接 + 禁止再调研', () => {
    const root = makeRoot();
    writeProjectConfig(root, {
      PROJECT_NAME: '示例',
      TECH_STACK: 'Unity 2022 LTS + UXML',
      TARGET_PLATFORM: 'MT8678 车机 Android 13',
    });
    const suffix = buildPlanConfigSuffix(root);
    expect(suffix).toContain('（plan 约定：');
    expect(suffix).toContain('技术栈=Unity 2022 LTS + UXML');
    expect(suffix).toContain('目标平台=MT8678 车机 Android 13');
    expect(suffix).not.toContain('存储='); // STORAGE 未填不出现
    expect(suffix).toContain('不要再进入 NEEDS CLARIFICATION');
    expect(suffix).not.toContain('输出物形态');
  });

  it('PLAN_OUTPUT_STYLE 已填 → 附加输出物形态（详细设计说明书）', () => {
    const root = makeRoot();
    writeProjectConfig(root, {
      TECH_STACK: 'Unity 2022 LTS',
      PLAN_OUTPUT_STYLE: '详细设计说明书（概要设计+详细设计：模块划分/接口定义/数据模型/异常与日志/测试要点）',
    });
    const suffix = buildPlanConfigSuffix(root);
    expect(suffix).toContain('输出物形态：详细设计说明书');
    expect(suffix).toContain('speckit plan 模板基础上扩展');
  });
});

describe('buildFeatureScopeSuffix', () => {
  it('未填功能范围 → 空串', () => {
    const root = makeRoot();
    expect(buildFeatureScopeSuffix(root)).toBe('');
    writeProjectConfig(root, { PROJECT_NAME: 'p' });
    expect(buildFeatureScopeSuffix(root)).toBe('');
  });

  it('已填 → 含范围值与全量文档抽取约束', () => {
    const root = makeRoot();
    writeProjectConfig(root, { FEATURE_SCOPE: '仅后端接口服务模块' });
    const suffix = buildFeatureScopeSuffix(root);
    expect(suffix).toContain('（功能范围：仅后端接口服务模块');
    expect(suffix).toContain('全量文档');
    expect(suffix).toContain('忽略');
  });
});