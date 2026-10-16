// 高保真可交互原型：路径解析、mtime、四种输入源的派发指令要素
import { describe, expect, it } from 'vitest';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import {
  AUTH_TOKEN_FILE,
  buildHiFiPrototypeGenerateToken,
  HIFI_DIR,
  hiFiIndexPathFor,
  hiFiMtime,
  writeAuthTokenFile,
} from '../../src/core/hiFiPrototype';

const baseOpts = {
  specRel: 'specs/001-demo/spec.md',
  planRel: 'specs/001-demo/plan.md',
  outRel: 'specs/001-demo/prototype-hifi',
  input: 'design/wb-7.3',
  downloadAssets: true,
};

describe('hiFiIndexPathFor / hiFiMtime', () => {
  it('入口为 prototype-hifi/index.html（spec 同目录）', () => {
    const spec = path.join('root', 'specs', '001-demo', 'spec.md');
    expect(hiFiIndexPathFor(spec)).toBe(path.join('root', 'specs', '001-demo', HIFI_DIR, 'index.html'));
  });

  it('hiFiMtime：未生成 → undefined；生成后有值', () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-hifi-'));
    const spec = path.join(tmp, 'spec.md');
    fs.writeFileSync(spec, '# spec');
    expect(hiFiMtime(spec)).toBeUndefined();
    fs.mkdirSync(path.join(tmp, HIFI_DIR), { recursive: true });
    fs.writeFileSync(hiFiIndexPathFor(spec), '<html></html>');
    expect(hiFiMtime(spec)).toBeGreaterThan(0);
    fs.rmSync(tmp, { recursive: true, force: true });
  });
});

describe('buildHiFiPrototypeGenerateToken', () => {
  it('公共要素：需求清单先行、1:1 禁改视觉、全交互、全量覆盖、README 清单、[TBD]、输出路径、禁改 spec/plan', () => {
    const token = buildHiFiPrototypeGenerateToken({ ...baseOpts, source: 'mastergo' });
    expect(token).toContain('需求梳理');
    expect(token).toContain('specs/001-demo/spec.md');
    expect(token).toContain('data-model.md');
    expect(token).toContain('constitution.md');
    expect(token).toContain('1:1 还原');
    expect(token).toContain('不得自行调整视觉');
    expect(token).toContain('可交互');
    expect(token).toContain('Playwright MCP');
    expect(token).toContain('缺任何一条都视为未完成');
    expect(token).toContain('specs/001-demo/prototype-hifi');
    expect(token).toContain('README.md');
    expect(token).toContain('[TBD]');
    expect(token).toContain('不要发明需求');
    expect(token).toContain('不要修改 spec.md / plan.md');
  });

  it('四种输入源各自的取材指引', () => {
    const mastergo = buildHiFiPrototypeGenerateToken({ ...baseOpts, source: 'mastergo' });
    expect(mastergo).toContain('若无 MCP 坐席但提供了认证令牌');
    expect(mastergo).toContain('Playwright MCP 登录 MasterGo 网页端');
    expect(mastergo).toContain('数据 API');
    expect(mastergo).toContain('OpenPencil');
    const svn = buildHiFiPrototypeGenerateToken({ ...baseOpts, source: 'svn' });
    expect(svn).toContain('svn 命令行 checkout/export');
    const local = buildHiFiPrototypeGenerateToken({ ...baseOpts, source: 'local' });
    expect(local).toContain('本地设计稿目录「design/wb-7.3」');
    const playwright = buildHiFiPrototypeGenerateToken({ ...baseOpts, source: 'playwright' });
    expect(playwright).toContain('完成登录与页面遍历');
  });

  it('mastergo-bridge：window.mg 插件 API 取数链（无 MCP 坐席）', () => {
    const bridge = buildHiFiPrototypeGenerateToken({ ...baseOpts, source: 'mastergo-bridge' });
    expect(bridge).toContain('chromium.connectOverCDP');
    expect(bridge).toContain('--remote-debugging-port');
    expect(bridge).toContain('无需 MCP 坐席、无需认证令牌');
    expect(bridge).toContain('window.mg');
    expect(bridge).toContain('mg.getNodeById');
    expect(bridge).toContain('relativeTransform');
    expect(bridge).toContain('atan2');
    expect(bridge).toContain('mg.codegen.getDSL');
    expect(bridge).toContain('mg.codegen.getCode');
    expect(bridge).toContain('吞掉整棵子树');
    expect(bridge).toContain('even-odd');
    expect(bridge).toContain('mg.getImageByHref');
    expect(bridge).toContain('32KB 分块');
    expect(bridge).toContain('exportAsync');
    expect(bridge).toContain('_extract/');
    expect(bridge).toContain('mg.showUI');
    expect(bridge).toContain('127.0.0.1');
    expect(bridge).toContain('OpenPencil');
    expect(bridge).toContain('报告阻塞，不得伪造视觉');
  });

  it('认证令牌：提供文件路径 → 指令含读取文件与保密要求；未提供 → 不出现认证段', () => {
    const withToken = buildHiFiPrototypeGenerateToken({
      ...baseOpts,
      source: 'mastergo',
      authTokenFile: 'C:\\Temp\\speckit-mastergo-token.txt',
    });
    expect(withToken).toContain('认证令牌');
    expect(withToken).toContain('C:\\Temp\\speckit-mastergo-token.txt');
    expect(withToken).toContain('不得写入交付文件、日志或回复正文');
    const without = buildHiFiPrototypeGenerateToken({ ...baseOpts, source: 'mastergo' });
    expect(without).not.toContain('认证令牌：已写入文件');
  });

  it('writeAuthTokenFile：写入用户临时目录并返回路径（内容可回读）', () => {
    const file = writeAuthTokenFile('  mg-token-123  ');
    expect(file).toContain(AUTH_TOKEN_FILE);
    expect(fs.readFileSync(file, 'utf-8')).toBe('mg-token-123'); // trim 处理
  });

  it('切图先行：勾选 → 下载步骤 + assets 索引；不勾选 → 无该步骤', () => {
    const withAssets = buildHiFiPrototypeGenerateToken({ ...baseOpts, source: 'local', downloadAssets: true });
    expect(withAssets).toContain('切图先行');
    expect(withAssets).toContain('specs/001-demo/prototype-hifi/assets/');
    const without = buildHiFiPrototypeGenerateToken({ ...baseOpts, source: 'local', downloadAssets: false });
    expect(without).not.toContain('切图先行');
  });
});