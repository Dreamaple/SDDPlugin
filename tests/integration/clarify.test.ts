// T051: 集成测试——澄清写回（US4）
// 经 vscode 桩（真实文件系统落地）验证 specWriter 写回事务路径：
// rawMarker 精确替换 → 重扫残留 0（SC-005）
import { afterAll, describe, expect, it } from 'vitest';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { buildReplacement, parseClarifications } from '../../src/core/clarify';
import { writeBackMarker } from '../../src/core/specWriter';
import { Uri } from '../helpers/vscode-stub';

const FIX = (...p: string[]) => path.join(process.cwd(), 'tests', 'fixtures', ...p);
const tempRoots: string[] = [];

afterAll(() => {
  for (const dir of tempRoots) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

describe('T051 澄清写回（US4 集成）', () => {
  it('clarify fixture → 逐题写回 → spec.md 残留 open 标记 0（场景 4b，SC-005）', async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-clarify-'));
    tempRoots.push(root);
    fs.cpSync(FIX('clarify'), root, { recursive: true });
    const specPath = path.join(root, 'specs', '003-clarify', 'spec.md');

    // 第 1 题：点选选项 A（含上下文与建议选项）
    let items = parseClarifications(fs.readFileSync(specPath, 'utf-8'));
    expect(items).toHaveLength(2);
    expect(items[0].options?.[0].label).toBe('A');
    await writeBackMarker(
      Uri.file(specPath),
      items[0].rawMarker,
      buildReplacement('**答案**: ', 'A（邮箱密码）'),
    );

    // 第 2 题：自定义答案
    items = parseClarifications(fs.readFileSync(specPath, 'utf-8'));
    expect(items.filter((i) => i.status === 'open')).toHaveLength(1);
    await writeBackMarker(
      Uri.file(specPath),
      items[0].rawMarker,
      buildReplacement('**答案**: ', '保留 180 天'),
    );

    // 重扫：open 残留 0；文件包含两处答案
    const finalText = fs.readFileSync(specPath, 'utf-8');
    const finalItems = parseClarifications(finalText);
    expect(finalItems.filter((i) => i.status === 'open')).toHaveLength(0);
    expect(finalText).toContain('**答案**: A（邮箱密码）');
    expect(finalText).toContain('**答案**: 保留 180 天');
  });

  it('标记已被替换时抛错（幂等防护）', async () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'spk-clarify2-'));
    tempRoots.push(tmp);
    const specPath = path.join(tmp, 'spec.md');
    fs.writeFileSync(specPath, '[NEEDS CLARIFICATION: 问题一]\n', 'utf-8');
    await writeBackMarker(Uri.file(specPath), '[NEEDS CLARIFICATION: 问题一]', '答案一');
    // 重复写回同一标记 → 抛错（调用方映射为 write-back-failed）
    await expect(
      writeBackMarker(Uri.file(specPath), '[NEEDS CLARIFICATION: 问题一]', '答案一'),
    ).rejects.toThrow(/标记未找到/);
  });
});